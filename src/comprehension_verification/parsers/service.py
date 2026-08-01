"""Deterministic parsers that never execute or dereference input content."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pdfplumber
from pdfminer.pdfparser import PDFSyntaxError
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from ..canonical import sha256_bytes, sha256_text, stable_id
from ..contracts import models as m


PARSER_VERSION = "stage0-parser/1.0.0"
_TEXT_MEDIA_TYPES = {"text/plain", "text/markdown"}
_PDF_MEDIA_TYPE = "application/pdf"
_ACTIVE_PDF_ACTIONS = {"/JavaScript", "/Launch", "/SubmitForm", "/ImportData"}


class ParseRejected(ValueError):
    """A stable fail-closed parser rejection with no raw content in the error."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ParseLimits:
    max_bytes: int = 5_000_000
    max_text_characters: int = 500_000
    max_pdf_pages: int = 50
    max_evidence_units: int = 2_000


@dataclass(frozen=True)
class ParsedArtifact:
    artifact: m.ArtifactRef
    evidence_units: tuple[m.EvidenceUnit, ...]


def _normalize_text(text: str) -> str:
    # Normalize transport differences only. Do not rewrite spelling or meaning.
    return text.replace("\r\n", "\n").replace("\r", "\n").strip()


def _sniff_media_type(data: bytes, path: Path) -> str:
    if data.startswith(b"%PDF-"):
        return _PDF_MEDIA_TYPE
    if b"\x00" in data[:8192]:
        raise ParseRejected("INGEST_UNSUPPORTED_MEDIA", "Binary content is not allowed")
    try:
        data.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ParseRejected("INGEST_INVALID_ENCODING", "Text must be UTF-8") from exc
    if path.suffix.lower() in {".md", ".markdown"}:
        return "text/markdown"
    return "text/plain"


def _pdf_has_active_content(reader: PdfReader) -> bool:
    root = reader.root_object
    names = root.get("/Names")
    if names and (names.get("/JavaScript") or names.get("/EmbeddedFiles")):
        return True
    if root.get("/OpenAction") or root.get("/AA"):
        return True
    for page in reader.pages:
        if page.get("/AA"):
            return True
        for annotation_ref in page.get("/Annots", []):
            annotation = annotation_ref.get_object()
            action = annotation.get("/A")
            if action and action.get("/S") in _ACTIVE_PDF_ACTIONS:
                return True
    return False


def _evidence_unit(
    *,
    tenant_id: str,
    submission_id: str | None,
    artifact_id: str,
    artifact_hash: str,
    source_role: m.ArtifactRole,
    modality: m.EvidenceModality,
    locator: m.SourceLocator,
    content_text: str,
    structured_content: dict[str, object] | None = None,
) -> m.EvidenceUnit:
    normalized = _normalize_text(content_text)
    if not normalized:
        raise ValueError("empty evidence unit")
    normalized_hash = sha256_text(normalized)
    evidence_id = stable_id(
        "ev",
        tenant_id,
        submission_id or source_role.value,
        artifact_id,
        artifact_hash,
        locator.model_dump(mode="json"),
        normalized_hash,
    )
    return m.EvidenceUnit(
        evidence_id=evidence_id,
        tenant_id=tenant_id,
        submission_id=submission_id,
        artifact_id=artifact_id,
        artifact_hash=artifact_hash,
        source_role=source_role,
        modality=modality,
        locator=locator,
        content_text=normalized,
        structured_content=structured_content,
        language="es",
        extraction_confidence=1.0,
        ocr_used=False,
        sensitive_labels=[],
        relations=[],
        normalized_hash=normalized_hash,
    )


def _parse_plain_text(
    text: str,
    *,
    tenant_id: str,
    submission_id: str | None,
    artifact_id: str,
    artifact_hash: str,
    source_role: m.ArtifactRole,
) -> list[m.EvidenceUnit]:
    lines = text.splitlines()
    units: list[m.EvidenceUnit] = []
    paragraph: list[str] = []
    paragraph_start = 0
    paragraph_index = 0

    def flush(end_line: int) -> None:
        nonlocal paragraph, paragraph_index
        content = "\n".join(paragraph).strip()
        if content:
            units.append(
                _evidence_unit(
                    tenant_id=tenant_id,
                    submission_id=submission_id,
                    artifact_id=artifact_id,
                    artifact_hash=artifact_hash,
                    source_role=source_role,
                    modality=m.EvidenceModality.PARAGRAPH,
                    locator=m.DocumentLocator(paragraph_index=paragraph_index),
                    content_text=content,
                    structured_content={
                        "line_start": paragraph_start + 1,
                        "line_end": end_line,
                    },
                )
            )
            paragraph_index += 1
        paragraph = []

    for index, line in enumerate(lines):
        if not line.strip():
            flush(index)
            continue
        if not paragraph:
            paragraph_start = index
        paragraph.append(line)
    flush(len(lines))
    return units


def _parse_markdown(
    text: str,
    *,
    tenant_id: str,
    submission_id: str | None,
    artifact_id: str,
    artifact_hash: str,
    source_role: m.ArtifactRole,
) -> list[m.EvidenceUnit]:
    lines = text.splitlines()
    units: list[m.EvidenceUnit] = []
    heading_path: list[str] = []
    paragraph: list[str] = []
    paragraph_start = 0
    paragraph_index = 0

    def flush(end_line: int) -> None:
        nonlocal paragraph, paragraph_index
        content = "\n".join(paragraph).strip()
        if content:
            units.append(
                _evidence_unit(
                    tenant_id=tenant_id,
                    submission_id=submission_id,
                    artifact_id=artifact_id,
                    artifact_hash=artifact_hash,
                    source_role=source_role,
                    modality=m.EvidenceModality.PARAGRAPH,
                    locator=m.DocumentLocator(
                        paragraph_index=paragraph_index,
                        heading_path=list(heading_path),
                    ),
                    content_text=content,
                    structured_content={
                        "line_start": paragraph_start + 1,
                        "line_end": end_line,
                    },
                )
            )
            paragraph_index += 1
        paragraph = []

    for index, line in enumerate(lines):
        heading_match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if heading_match:
            flush(index)
            level = len(heading_match.group(1))
            title = heading_match.group(2).strip()
            heading_path = heading_path[: level - 1]
            heading_path.append(title)
            units.append(
                _evidence_unit(
                    tenant_id=tenant_id,
                    submission_id=submission_id,
                    artifact_id=artifact_id,
                    artifact_hash=artifact_hash,
                    source_role=source_role,
                    modality=m.EvidenceModality.HEADING,
                    locator=m.DocumentLocator(
                        paragraph_index=paragraph_index,
                        heading_path=list(heading_path),
                    ),
                    content_text=title,
                    structured_content={
                        "line_start": index + 1,
                        "line_end": index + 1,
                        "heading_level": level,
                    },
                )
            )
            paragraph_index += 1
            continue
        if not line.strip():
            flush(index)
            continue
        if not paragraph:
            paragraph_start = index
        paragraph.append(line)
    flush(len(lines))
    return units


def _parse_pdf(
    path: Path,
    *,
    limits: ParseLimits,
    tenant_id: str,
    submission_id: str | None,
    artifact_id: str,
    artifact_hash: str,
    source_role: m.ArtifactRole,
) -> list[m.EvidenceUnit]:
    try:
        reader = PdfReader(path, strict=True)
        if reader.is_encrypted:
            raise ParseRejected(
                "INGEST_ENCRYPTED_FILE", "Encrypted PDFs are not supported"
            )
        if len(reader.pages) > limits.max_pdf_pages:
            raise ParseRejected("INGEST_SIZE_LIMIT", "PDF page limit exceeded")
        if _pdf_has_active_content(reader):
            raise ParseRejected(
                "REJECTED_SECURITY", "Active PDF content is not supported"
            )

        units: list[m.EvidenceUnit] = []
        extracted_characters = 0
        with pdfplumber.open(path) as pdf:
            for page_number, page in enumerate(pdf.pages, start=1):
                lines = page.extract_text_lines(strip=True, return_chars=False) or []
                for block_index, line in enumerate(lines):
                    text = _normalize_text(str(line.get("text", "")))
                    if not text:
                        continue
                    extracted_characters += len(text)
                    if extracted_characters > limits.max_text_characters:
                        raise ParseRejected(
                            "INGEST_SIZE_LIMIT", "PDF text character limit exceeded"
                        )
                    if len(units) >= limits.max_evidence_units:
                        raise ParseRejected(
                            "INGEST_SIZE_LIMIT", "Evidence unit limit exceeded"
                        )
                    bbox = [
                        round(float(line["x0"]), 3),
                        round(float(line["top"]), 3),
                        round(float(line["x1"]), 3),
                        round(float(line["bottom"]), 3),
                    ]
                    units.append(
                        _evidence_unit(
                            tenant_id=tenant_id,
                            submission_id=submission_id,
                            artifact_id=artifact_id,
                            artifact_hash=artifact_hash,
                            source_role=source_role,
                            modality=m.EvidenceModality.PARAGRAPH,
                            locator=m.PageLocator(
                                page=page_number,
                                bbox=bbox,
                                block_index=block_index,
                            ),
                            content_text=text,
                            structured_content={"native_text": True},
                        )
                    )
    except ParseRejected:
        raise
    except (
        PdfReadError,
        PDFSyntaxError,
        EOFError,
        KeyError,
        OSError,
        TypeError,
        ValueError,
    ) as exc:
        raise ParseRejected(
            "PARSE_CORRUPT_FILE", "PDF structure is invalid"
        ) from exc
    if not units:
        raise ParseRejected("PARSE_EMPTY_NATIVE", "PDF contains no selectable text")
    return units


class SafeParserService:
    """Parser facade with byte/MIME/hash/security checks before extraction."""

    def __init__(self, limits: ParseLimits | None = None) -> None:
        self.limits = limits or ParseLimits()

    def parse(
        self,
        path: Path,
        *,
        tenant_id: str,
        source_role: m.ArtifactRole,
        submission_id: str | None = None,
        declared_media_type: str | None = None,
    ) -> ParsedArtifact:
        resolved = path.resolve(strict=True)
        if path.is_symlink() or not resolved.is_file():
            raise ParseRejected("INGEST_UNSUPPORTED_MEDIA", "Only regular files are accepted")
        data = resolved.read_bytes()
        if not data:
            raise ParseRejected("PARSE_EMPTY_NATIVE", "Empty artifacts are not usable")
        if len(data) > self.limits.max_bytes:
            raise ParseRejected("INGEST_SIZE_LIMIT", "Artifact byte limit exceeded")
        media_type = _sniff_media_type(data, resolved)
        if declared_media_type is not None and declared_media_type != media_type:
            raise ParseRejected("INGEST_MIME_MISMATCH", "Declared and detected MIME differ")
        if media_type not in _TEXT_MEDIA_TYPES | {_PDF_MEDIA_TYPE}:
            raise ParseRejected("INGEST_UNSUPPORTED_MEDIA", "Media type is not enabled")
        if source_role == m.ArtifactRole.SUBMISSION and submission_id is None:
            raise ParseRejected("IR_PROVENANCE_GAP", "Submission evidence requires submission_id")
        if source_role != m.ArtifactRole.SUBMISSION and submission_id is not None:
            raise ParseRejected("IR_PROVENANCE_GAP", "Only submission evidence carries submission_id")

        artifact_hash = sha256_bytes(data)
        artifact_id = stable_id(
            "art",
            tenant_id,
            source_role.value,
            submission_id or source_role.value,
            artifact_hash,
        )
        parser_id = {
            "text/plain": "stage0-txt",
            "text/markdown": "stage0-markdown",
            "application/pdf": "stage0-pdf-digital",
        }[media_type]
        artifact = m.ArtifactRef(
            artifact_id=artifact_id,
            role=source_role,
            filename=resolved.name,
            media_type=media_type,
            sha256=artifact_hash,
            byte_size=len(data),
            parser_id=parser_id,
            parser_version=PARSER_VERSION,
        )
        if media_type in _TEXT_MEDIA_TYPES:
            text = data.decode("utf-8", errors="strict")
            if len(text) > self.limits.max_text_characters:
                raise ParseRejected("INGEST_SIZE_LIMIT", "Text character limit exceeded")
            parser = _parse_markdown if media_type == "text/markdown" else _parse_plain_text
            units = parser(
                text,
                tenant_id=tenant_id,
                submission_id=submission_id,
                artifact_id=artifact_id,
                artifact_hash=artifact_hash,
                source_role=source_role,
            )
        else:
            units = _parse_pdf(
                resolved,
                limits=self.limits,
                tenant_id=tenant_id,
                submission_id=submission_id,
                artifact_id=artifact_id,
                artifact_hash=artifact_hash,
                source_role=source_role,
            )
        if not units:
            raise ParseRejected("PARSE_EMPTY_NATIVE", "No evidence units were extracted")
        if len(units) > self.limits.max_evidence_units:
            raise ParseRejected("INGEST_SIZE_LIMIT", "Evidence unit limit exceeded")
        return ParsedArtifact(artifact=artifact, evidence_units=tuple(units))
