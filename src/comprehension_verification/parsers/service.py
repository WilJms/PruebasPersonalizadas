"""Deterministic parsers that never execute or dereference input content."""

from __future__ import annotations

import io
import math
import os
import posixpath
import re
import stat
import struct
import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal
from xml.etree import ElementTree as ET

import pdfplumber
from pypdf import PdfReader

from ..canonical import sha256_bytes, sha256_text, stable_id
from ..contracts import models as m


PARSER_VERSION = "stage2-parser/2.0.0"
_TEXT_MEDIA_TYPES = {"text/plain", "text/markdown"}
_PDF_MEDIA_TYPE = "application/pdf"
_DOCX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)
DOCX_MEDIA_TYPE = _DOCX_MEDIA_TYPE
_ZIP_SIGNATURES = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
_OLE_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_ACTIVE_PDF_ACTIONS = {
    "/GoToR",
    "/ImportData",
    "/JavaScript",
    "/Launch",
    "/Movie",
    "/Rendition",
    "/SetOCGState",
    "/Sound",
    "/SubmitForm",
    "/Thread",
    "/URI",
}
_ACTIVE_PDF_KEYS = {
    "/AA",
    "/AcroForm",
    "/EmbeddedFiles",
    "/FS",
    "/JavaScript",
    "/JS",
    "/OpenAction",
    "/RichMediaContent",
    "/XFA",
}
_ACTIVE_PDF_SUBTYPES = {
    "/3D",
    "/FileAttachment",
    "/Movie",
    "/RichMedia",
    "/Screen",
    "/Sound",
}
_OOXML_MAIN_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument."
    "wordprocessingml.document.main+xml"
)
_OOXML_RELATIONSHIP_NS = (
    "http://schemas.openxmlformats.org/package/2006/relationships"
)
_OOXML_CONTENT_TYPES_NS = (
    "http://schemas.openxmlformats.org/package/2006/content-types"
)
_WORDPROCESSINGML_NS = (
    "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
)
_OFFICE_NS = "urn:schemas-microsoft-com:office:office"
_OOXML_OFFICE_DOCUMENT_RELATIONSHIP = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"
    "officeDocument"
)
_BLOCKED_OOXML_PART_FRAGMENTS = (
    "/activex/",
    "/embeddings/",
    "/oleobject",
    "/vbaproject",
    "/webextensions/",
)
_BLOCKED_OOXML_CONTENT_FRAGMENTS = (
    "activex",
    "html",
    "javascript",
    "macroenabled",
    "msdownload",
    "oleobject",
    "shockwave",
    "svg",
    "vbaproject",
)
_BLOCKED_OOXML_RELATIONSHIP_SUFFIXES = (
    "/attachedtemplate",
    "/control",
    "/externaldata",
    "/externallink",
    "/frame",
    "/oleobject",
    "/package",
    "/subdocument",
    "/vbaproject",
    "/webextension",
)
_BLOCKED_WORD_XML_ELEMENTS = {
    "altChunk",
    "control",
    "object",
    "oleObject",
    "subDoc",
}
_ACTIVE_WORD_FIELD_RE = re.compile(
    r"\b(?:DATABASE|DDE|DDEAUTO|HYPERLINK|INCLUDEPICTURE|INCLUDETEXT|LINK|MACROBUTTON)\b",
    re.IGNORECASE,
)


class ParseRejected(ValueError):
    """A stable fail-closed parser rejection with no raw content in the error."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ParseLimits:
    max_bytes: int = 5_000_000
    max_text_characters: int = 500_000
    max_evidence_unit_characters: int = 100_000
    max_pdf_pages: int = 50
    max_pdf_objects: int = 100_000
    max_evidence_units: int = 2_000
    max_archive_entries: int = 1_024
    max_archive_entry_bytes: int = 10_000_000
    max_archive_uncompressed_bytes: int = 25_000_000
    max_archive_compression_ratio: float = 200.0
    max_archive_path_depth: int = 12
    max_xml_part_bytes: int = 8_000_000
    max_xml_depth: int = 128
    max_xml_elements: int = 100_000

    def __post_init__(self) -> None:
        for field_name, value in self.__dict__.items():
            if value <= 0:
                raise ValueError(f"{field_name} must be positive")
        if self.max_evidence_unit_characters > 100_000:
            raise ValueError(
                "max_evidence_unit_characters exceeds the canonical contract"
            )


@dataclass(frozen=True)
class ParsedArtifact:
    artifact: m.ArtifactRef
    evidence_units: tuple[m.EvidenceUnit, ...]
    mime_detector: Literal["libmagic", "signature-fallback", "unknown"] = "unknown"
    libmagic_media_type: str | None = None


@dataclass(frozen=True)
class _DocxPreflight:
    xml_parts: dict[str, bytes]
    part_names: frozenset[str]


def _normalize_text(text: str) -> str:
    # Normalize transport differences only. Do not rewrite spelling or meaning.
    return text.replace("\r\n", "\n").replace("\r", "\n").strip()


def _safe_read(path: Path, max_bytes: int) -> bytes:
    """Read a regular file once, without following a final-component symlink."""

    try:
        if path.is_symlink():
            raise ParseRejected(
                "INGEST_UNSUPPORTED_MEDIA", "Only regular files are accepted"
            )
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
    except ParseRejected:
        raise
    except (FileNotFoundError, NotADirectoryError, OSError) as exc:
        raise ParseRejected(
            "INGEST_UNSUPPORTED_MEDIA", "Only readable regular files are accepted"
        ) from exc

    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ParseRejected(
                "INGEST_UNSUPPORTED_MEDIA", "Only regular files are accepted"
            )
        if metadata.st_size > max_bytes:
            raise ParseRejected("INGEST_SIZE_LIMIT", "Artifact byte limit exceeded")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            data = stream.read(max_bytes + 1)
    except ParseRejected:
        raise
    except OSError as exc:
        raise ParseRejected(
            "INGEST_UNSUPPORTED_MEDIA", "Artifact could not be read safely"
        ) from exc
    finally:
        os.close(descriptor)

    if len(data) > max_bytes:
        raise ParseRejected("INGEST_SIZE_LIMIT", "Artifact byte limit exceeded")
    return data


def _xml_local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _xml_namespace(tag: str) -> str:
    return tag[1:].split("}", 1)[0] if tag.startswith("{") and "}" in tag else ""


def _safe_xml_root(data: bytes, *, limits: ParseLimits) -> ET.Element:
    if len(data) > limits.max_xml_part_bytes:
        raise ParseRejected("INGEST_SIZE_LIMIT", "OOXML XML part limit exceeded")
    if b"\x00" in data[:512] or data.startswith(
        (b"\xff\xfe", b"\xfe\xff", b"\x00\x00\xfe\xff", b"\xff\xfe\x00\x00")
    ):
        raise ParseRejected(
            "REJECTED_SECURITY", "Only UTF-8 OOXML XML parts are supported"
        )
    declaration = re.match(br"\s*<\?xml\s+([^?]+)\?>", data[:512], re.IGNORECASE)
    if declaration:
        encoding = re.search(
            br"\bencoding\s*=\s*['\"]([^'\"]+)['\"]",
            declaration.group(1),
            re.IGNORECASE,
        )
        if encoding and encoding.group(1).replace(b"-", b"").lower() != b"utf8":
            raise ParseRejected(
                "REJECTED_SECURITY", "Only UTF-8 OOXML XML parts are supported"
            )
    if re.search(br"<!\s*(?:DOCTYPE|ENTITY)\b", data, re.IGNORECASE):
        raise ParseRejected(
            "REJECTED_SECURITY", "OOXML document types and entities are forbidden"
        )
    if re.search(br"<\?xml-stylesheet\b", data, re.IGNORECASE):
        raise ParseRejected(
            "REJECTED_SECURITY", "OOXML external stylesheets are forbidden"
        )

    depth = 0
    elements = 0
    try:
        iterator = ET.iterparse(io.BytesIO(data), events=("start", "end"))
        for event, _element in iterator:
            if event == "start":
                depth += 1
                elements += 1
                if depth > limits.max_xml_depth:
                    raise ParseRejected(
                        "INGEST_SIZE_LIMIT", "OOXML XML depth limit exceeded"
                    )
                if elements > limits.max_xml_elements:
                    raise ParseRejected(
                        "INGEST_SIZE_LIMIT", "OOXML XML element limit exceeded"
                    )
            else:
                depth -= 1
        root = iterator.root
    except ParseRejected:
        raise
    except (ET.ParseError, LookupError, UnicodeError, ValueError) as exc:
        raise ParseRejected(
            "PARSE_CORRUPT_FILE", "OOXML contains invalid XML"
        ) from exc
    if root is None or depth != 0:
        raise ParseRejected("PARSE_CORRUPT_FILE", "OOXML contains invalid XML")
    return root


def _normalized_ooxml_name(name: str, *, limits: ParseLimits) -> str:
    if not name or "\x00" in name or "\\" in name:
        raise ParseRejected("REJECTED_SECURITY", "OOXML contains an unsafe part path")
    normalized = unicodedata.normalize("NFC", name)
    if normalized.startswith("/") or any(
        part in {"", ".", ".."} for part in normalized.split("/")
    ):
        raise ParseRejected("REJECTED_SECURITY", "OOXML contains an unsafe part path")
    path = PurePosixPath(normalized)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ParseRejected("REJECTED_SECURITY", "OOXML contains an unsafe part path")
    if len(path.parts) > limits.max_archive_path_depth:
        raise ParseRejected("INGEST_SIZE_LIMIT", "OOXML part path depth limit exceeded")
    return path.as_posix()


def _read_zip_entry(
    archive: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    *,
    limits: ParseLimits,
) -> bytes:
    read = 0
    chunks: list[bytes] = []
    try:
        with archive.open(info, "r") as stream:
            while True:
                chunk = stream.read(min(65_536, limits.max_archive_entry_bytes + 1 - read))
                if not chunk:
                    break
                read += len(chunk)
                if read > limits.max_archive_entry_bytes:
                    raise ParseRejected(
                        "INGEST_SIZE_LIMIT", "OOXML entry size limit exceeded"
                    )
                chunks.append(chunk)
    except ParseRejected:
        raise
    except RuntimeError as exc:
        # zipfile reports password-protected members as RuntimeError.
        raise ParseRejected(
            "INGEST_ENCRYPTED_FILE", "Encrypted OOXML packages are not supported"
        ) from exc
    except (EOFError, NotImplementedError, OSError, ValueError, zipfile.BadZipFile) as exc:
        raise ParseRejected(
            "PARSE_CORRUPT_FILE", "OOXML package structure is invalid"
        ) from exc
    if read != info.file_size:
        raise ParseRejected("PARSE_CORRUPT_FILE", "OOXML entry size is inconsistent")
    return b"".join(chunks)


def _relationship_source_part(relationship_part: str) -> str:
    if relationship_part == "_rels/.rels":
        return ""
    marker = "/_rels/"
    if marker not in relationship_part or not relationship_part.endswith(".rels"):
        raise ParseRejected(
            "PARSE_CORRUPT_FILE", "OOXML relationship part path is invalid"
        )
    parent, filename = relationship_part.split(marker, 1)
    return posixpath.join(parent, filename[: -len(".rels")])


def _target_is_external(target: str) -> bool:
    stripped = target.strip()
    if not stripped:
        return False
    if stripped.startswith(("//", "\\\\")):
        return True
    first_segment = stripped.replace("\\", "/").split("/", 1)[0]
    return ":" in first_segment


def _resolve_relationship_target(source_part: str, target: str) -> str | None:
    if target.startswith("#"):
        return None
    if "\\" in target or "\x00" in target:
        raise ParseRejected(
            "REJECTED_SECURITY", "OOXML relationship target is unsafe"
        )
    base = posixpath.dirname(source_part)
    resolved = posixpath.normpath(posixpath.join(base, target.lstrip("/")))
    if resolved == ".." or resolved.startswith("../") or resolved.startswith("/"):
        raise ParseRejected(
            "REJECTED_SECURITY", "OOXML relationship target escapes the package"
        )
    return unicodedata.normalize("NFC", resolved)


def _validate_ooxml_semantics(preflight: _DocxPreflight, *, limits: ParseLimits) -> None:
    content_types = _safe_xml_root(
        preflight.xml_parts["[Content_Types].xml"], limits=limits
    )
    if content_types.tag != f"{{{_OOXML_CONTENT_TYPES_NS}}}Types":
        raise ParseRejected(
            "PARSE_CORRUPT_FILE", "OOXML content types XML is invalid"
        )
    main_content_type: str | None = None
    for element in content_types.iter():
        content_type = element.attrib.get("ContentType", "")
        if any(
            fragment in content_type.casefold()
            for fragment in _BLOCKED_OOXML_CONTENT_FRAGMENTS
        ):
            raise ParseRejected(
                "REJECTED_SECURITY", "OOXML active content is not supported"
            )
        part_name = element.attrib.get("PartName")
        if part_name == "/word/document.xml":
            main_content_type = content_type
    if main_content_type != _OOXML_MAIN_CONTENT_TYPE:
        if main_content_type and "macroenabled" in main_content_type.casefold():
            raise ParseRejected(
                "REJECTED_SECURITY", "Macro-enabled OOXML is not supported"
            )
        raise ParseRejected(
            "PARSE_CORRUPT_FILE", "OOXML main document content type is invalid"
        )

    office_document_target_found = False
    for part_name, raw_xml in preflight.xml_parts.items():
        root = _safe_xml_root(raw_xml, limits=limits)
        if part_name.endswith(".rels"):
            source_part = _relationship_source_part(part_name)
            if root.tag != f"{{{_OOXML_RELATIONSHIP_NS}}}Relationships":
                raise ParseRejected(
                    "PARSE_CORRUPT_FILE", "OOXML relationship XML is invalid"
                )
            for relationship in root:
                if relationship.tag != f"{{{_OOXML_RELATIONSHIP_NS}}}Relationship":
                    continue
                target = relationship.attrib.get("Target", "")
                target_mode = relationship.attrib.get("TargetMode", "Internal")
                relationship_type = relationship.attrib.get("Type", "")
                if target_mode.casefold() == "external" or _target_is_external(target):
                    raise ParseRejected(
                        "REJECTED_SECURITY",
                        "External OOXML relationships are not supported",
                    )
                if target_mode.casefold() != "internal":
                    raise ParseRejected(
                        "PARSE_CORRUPT_FILE", "OOXML relationship mode is invalid"
                    )
                if any(
                    relationship_type.casefold().endswith(suffix)
                    for suffix in _BLOCKED_OOXML_RELATIONSHIP_SUFFIXES
                ):
                    raise ParseRejected(
                        "REJECTED_SECURITY", "OOXML active relationship is not supported"
                    )
                resolved_target = _resolve_relationship_target(source_part, target)
                if resolved_target is not None and resolved_target not in preflight.part_names:
                    raise ParseRejected(
                        "PARSE_CORRUPT_FILE", "OOXML relationship target is missing"
                    )
                if (
                    part_name == "_rels/.rels"
                    and relationship_type == _OOXML_OFFICE_DOCUMENT_RELATIONSHIP
                    and resolved_target == "word/document.xml"
                ):
                    office_document_target_found = True

        for element in root.iter():
            local_name = _xml_local_name(element.tag)
            namespace = _xml_namespace(element.tag)
            if local_name in _BLOCKED_WORD_XML_ELEMENTS and namespace in {
                _WORDPROCESSINGML_NS,
                _OFFICE_NS,
            }:
                raise ParseRejected(
                    "REJECTED_SECURITY", "OOXML active content is not supported"
                )
            if (
                namespace == _WORDPROCESSINGML_NS
                and local_name in {"fldSimple", "instrText"}
            ):
                field_text = " ".join(element.itertext())
                field_text += " " + " ".join(element.attrib.values())
                if _ACTIVE_WORD_FIELD_RE.search(field_text):
                    raise ParseRejected(
                        "REJECTED_SECURITY", "OOXML active fields are not supported"
                    )
    if not office_document_target_found:
        raise ParseRejected(
            "PARSE_CORRUPT_FILE", "OOXML office document relationship is missing"
        )


def _preflight_docx(data: bytes, *, limits: ParseLimits) -> _DocxPreflight:
    search_start = max(0, len(data) - 65_557)
    search_end = len(data)
    eocd_offset = -1
    saw_eocd = False
    while search_end > search_start:
        candidate = data.rfind(b"PK\x05\x06", search_start, search_end)
        if candidate < 0:
            break
        saw_eocd = True
        if candidate + 22 <= len(data):
            candidate_comment_size = struct.unpack_from("<H", data, candidate + 20)[0]
            if candidate + 22 + candidate_comment_size == len(data):
                eocd_offset = candidate
                break
        search_end = candidate
    if eocd_offset < 0:
        if saw_eocd:
            raise ParseRejected(
                "REJECTED_SECURITY", "OOXML contains data outside the ZIP package"
            )
        raise ParseRejected(
            "PARSE_CORRUPT_FILE", "OOXML ZIP directory is invalid"
        )
    try:
        (
            disk_number,
            directory_disk,
            entries_on_disk,
            entry_count,
            directory_size,
            directory_offset,
            comment_size,
        ) = struct.unpack_from("<HHHHIIH", data, eocd_offset + 4)
    except struct.error as exc:
        raise ParseRejected(
            "PARSE_CORRUPT_FILE", "OOXML ZIP directory is invalid"
        ) from exc
    if disk_number or directory_disk or entries_on_disk != entry_count:
        raise ParseRejected(
            "REJECTED_SECURITY", "Multi-disk OOXML packages are not supported"
        )
    if entry_count == 0xFFFF or entry_count > limits.max_archive_entries:
        raise ParseRejected("INGEST_SIZE_LIMIT", "OOXML entry count limit exceeded")
    if eocd_offset + 22 + comment_size != len(data):
        raise ParseRejected(
            "REJECTED_SECURITY", "OOXML contains data outside the ZIP package"
        )
    if directory_offset + directory_size > eocd_offset:
        raise ParseRejected(
            "PARSE_CORRUPT_FILE", "OOXML ZIP directory is invalid"
        )
    try:
        archive = zipfile.ZipFile(io.BytesIO(data), mode="r")
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        raise ParseRejected(
            "PARSE_CORRUPT_FILE", "OOXML package structure is invalid"
        ) from exc

    with archive:
        entries = archive.infolist()
        if len(entries) > limits.max_archive_entries:
            raise ParseRejected("INGEST_SIZE_LIMIT", "OOXML entry count limit exceeded")

        seen: set[str] = set()
        part_names: set[str] = set()
        xml_parts: dict[str, bytes] = {}
        declared_total = 0
        actual_total = 0
        for info in entries:
            name = _normalized_ooxml_name(info.filename.rstrip("/"), limits=limits)
            collision_key = unicodedata.normalize("NFC", name).casefold()
            if collision_key in seen:
                raise ParseRejected(
                    "REJECTED_SECURITY", "OOXML contains duplicate part names"
                )
            seen.add(collision_key)
            mode = (info.external_attr >> 16) & 0o170000
            if stat.S_ISLNK(mode):
                raise ParseRejected(
                    "REJECTED_SECURITY", "OOXML symbolic links are forbidden"
                )
            if info.is_dir():
                if mode and not stat.S_ISDIR(mode):
                    raise ParseRejected(
                        "REJECTED_SECURITY",
                        "OOXML special filesystem entries are forbidden",
                    )
                continue
            part_names.add(name)

            if mode and not stat.S_ISREG(mode):
                raise ParseRejected(
                    "REJECTED_SECURITY", "OOXML special filesystem entries are forbidden"
                )
            if info.flag_bits & 0x1:
                raise ParseRejected(
                    "INGEST_ENCRYPTED_FILE", "Encrypted OOXML packages are not supported"
                )
            if info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
                raise ParseRejected(
                    "REJECTED_SECURITY", "OOXML compression method is not supported"
                )
            if info.file_size > limits.max_archive_entry_bytes:
                raise ParseRejected(
                    "INGEST_SIZE_LIMIT", "OOXML entry size limit exceeded"
                )
            declared_total += info.file_size
            if declared_total > limits.max_archive_uncompressed_bytes:
                raise ParseRejected(
                    "INGEST_SIZE_LIMIT", "OOXML uncompressed size limit exceeded"
                )
            if info.file_size:
                if info.compress_size <= 0:
                    raise ParseRejected(
                        "REJECTED_SECURITY", "OOXML compression metadata is unsafe"
                    )
                if info.file_size / info.compress_size > limits.max_archive_compression_ratio:
                    raise ParseRejected(
                        "REJECTED_SECURITY", "OOXML compression ratio limit exceeded"
                    )

            lowered = f"/{name.casefold()}"
            if any(fragment in lowered for fragment in _BLOCKED_OOXML_PART_FRAGMENTS):
                raise ParseRejected(
                    "REJECTED_SECURITY", "OOXML active or embedded content is forbidden"
                )

            payload = _read_zip_entry(archive, info, limits=limits)
            actual_total += len(payload)
            if actual_total > limits.max_archive_uncompressed_bytes:
                raise ParseRejected(
                    "INGEST_SIZE_LIMIT", "OOXML uncompressed size limit exceeded"
                )
            if payload.startswith(_ZIP_SIGNATURES) or payload.startswith(_OLE_SIGNATURE):
                raise ParseRejected(
                    "REJECTED_SECURITY", "Nested archives are not supported in OOXML"
                )
            if name.endswith(".xml") or name.endswith(".rels") or name == "[Content_Types].xml":
                if len(payload) > limits.max_xml_part_bytes:
                    raise ParseRejected(
                        "INGEST_SIZE_LIMIT", "OOXML XML part limit exceeded"
                    )
                xml_parts[name] = payload

    required = {"[Content_Types].xml", "_rels/.rels", "word/document.xml"}
    if not required.issubset(part_names) or not required.issubset(xml_parts):
        raise ParseRejected(
            "PARSE_CORRUPT_FILE", "OOXML required document parts are missing"
        )
    preflight = _DocxPreflight(
        xml_parts=xml_parts,
        part_names=frozenset(part_names),
    )
    _validate_ooxml_semantics(preflight, limits=limits)
    return preflight


def _signature_media_type(
    data: bytes,
    path: Path,
    *,
    declared_media_type: str | None,
    limits: ParseLimits,
) -> tuple[str, _DocxPreflight | None]:
    if data.startswith(b"%PDF-"):
        return _PDF_MEDIA_TYPE, None
    if data.startswith(_OLE_SIGNATURE):
        if declared_media_type == _DOCX_MEDIA_TYPE or path.suffix.casefold() in {
            ".docx",
            ".docm",
        }:
            raise ParseRejected(
                "INGEST_ENCRYPTED_FILE",
                "Encrypted or legacy Office containers are not supported",
            )
        raise ParseRejected("INGEST_UNSUPPORTED_MEDIA", "OLE content is not allowed")
    if data.startswith(_ZIP_SIGNATURES):
        try:
            preflight = _preflight_docx(data, limits=limits)
        except ParseRejected as exc:
            expected_docx = declared_media_type == _DOCX_MEDIA_TYPE or (
                path.suffix.casefold() in {".docx", ".docm"}
            )
            if exc.code == "PARSE_CORRUPT_FILE" and not expected_docx:
                raise ParseRejected(
                    "INGEST_UNSUPPORTED_MEDIA", "ZIP content is not an approved DOCX"
                ) from exc
            raise
        return _DOCX_MEDIA_TYPE, preflight
    if b"\x00" in data[:8192]:
        raise ParseRejected("INGEST_UNSUPPORTED_MEDIA", "Binary content is not allowed")
    try:
        data.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ParseRejected("INGEST_INVALID_ENCODING", "Text must be UTF-8") from exc
    if path.suffix.lower() in {".md", ".markdown"}:
        return "text/markdown", None
    return "text/plain", None


def _libmagic_media_type(data: bytes) -> str | None:
    try:
        import magic  # type: ignore[import-not-found]

        detected = magic.from_buffer(data, mime=True)
    except (AttributeError, ImportError, OSError):
        return None
    except Exception as exc:  # python-magic exposes backend-specific exception types.
        if exc.__class__.__module__.startswith("magic"):
            return None
        raise
    if not isinstance(detected, str):
        return None
    normalized = detected.split(";", 1)[0].strip().casefold()
    return normalized or None


def _magic_compatibility(signature_type: str, magic_type: str) -> bool | None:
    if signature_type == _PDF_MEDIA_TYPE:
        return magic_type in {_PDF_MEDIA_TYPE, "application/x-pdf"}
    if signature_type == _DOCX_MEDIA_TYPE:
        return magic_type in {
            _DOCX_MEDIA_TYPE,
            "application/zip",
            "application/x-zip",
            "application/x-zip-compressed",
        }
    if signature_type in _TEXT_MEDIA_TYPES:
        if magic_type.startswith("text/"):
            return True
        if magic_type == "application/octet-stream":
            return None
        return False
    return False


def _detect_media_type(
    data: bytes,
    path: Path,
    *,
    declared_media_type: str | None,
    limits: ParseLimits,
    require_libmagic: bool,
) -> tuple[str, _DocxPreflight | None, Literal["libmagic", "signature-fallback"], str | None]:
    signature_type, preflight = _signature_media_type(
        data,
        path,
        declared_media_type=declared_media_type,
        limits=limits,
    )
    magic_type = _libmagic_media_type(data)
    if magic_type is None:
        if require_libmagic:
            raise ParseRejected(
                "INGEST_MIME_DETECTOR_UNAVAILABLE",
                "The required MIME detector is unavailable",
            )
        return signature_type, preflight, "signature-fallback", None

    compatibility = _magic_compatibility(signature_type, magic_type)
    if compatibility is False:
        raise ParseRejected(
            "INGEST_MIME_MISMATCH", "Signature and libmagic MIME differ"
        )
    if compatibility is None and require_libmagic:
        raise ParseRejected(
            "INGEST_MIME_MISMATCH",
            "libmagic did not identify an approved MIME type",
        )
    detector: Literal["libmagic", "signature-fallback"] = (
        "libmagic" if compatibility else "signature-fallback"
    )
    return signature_type, preflight, detector, magic_type


def _pdf_has_active_content(reader: PdfReader, *, limits: ParseLimits) -> bool:
    visited_indirect: set[tuple[int, int]] = set()
    visited_direct: set[int] = set()
    objects_seen = 0

    def visit(value: object, depth: int = 0) -> bool:
        nonlocal objects_seen
        if depth > 64:
            raise ParseRejected("INGEST_SIZE_LIMIT", "PDF object depth limit exceeded")

        get_object = getattr(value, "get_object", None)
        idnum = getattr(value, "idnum", None)
        generation = getattr(value, "generation", None)
        if callable(get_object) and isinstance(idnum, int):
            key = (idnum, int(generation or 0))
            if key in visited_indirect:
                return False
            visited_indirect.add(key)
            value = get_object()

        if isinstance(value, dict):
            identity = id(value)
            if identity in visited_direct:
                return False
            visited_direct.add(identity)
            objects_seen += 1
            if objects_seen > limits.max_pdf_objects:
                raise ParseRejected("INGEST_SIZE_LIMIT", "PDF object limit exceeded")
            for key, child in value.items():
                key_text = str(key)
                if key_text in _ACTIVE_PDF_KEYS:
                    return True
                if key_text == "/S" and str(child) in _ACTIVE_PDF_ACTIONS:
                    return True
                if key_text == "/Subtype" and str(child) in _ACTIVE_PDF_SUBTYPES:
                    return True
                if visit(child, depth + 1):
                    return True
            return False
        if isinstance(value, (list, tuple)):
            identity = id(value)
            if identity in visited_direct:
                return False
            visited_direct.add(identity)
            objects_seen += 1
            if objects_seen > limits.max_pdf_objects:
                raise ParseRejected("INGEST_SIZE_LIMIT", "PDF object limit exceeded")
            return any(visit(child, depth + 1) for child in value)
        return False

    return visit(reader.trailer)


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
    limits: ParseLimits,
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
            if len(content) > limits.max_evidence_unit_characters:
                raise ParseRejected(
                    "INGEST_SIZE_LIMIT", "Evidence unit character limit exceeded"
                )
            if len(units) >= limits.max_evidence_units:
                raise ParseRejected(
                    "INGEST_SIZE_LIMIT", "Evidence unit limit exceeded"
                )
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
    limits: ParseLimits,
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
            if len(content) > limits.max_evidence_unit_characters:
                raise ParseRejected(
                    "INGEST_SIZE_LIMIT", "Evidence unit character limit exceeded"
                )
            if len(units) >= limits.max_evidence_units:
                raise ParseRejected(
                    "INGEST_SIZE_LIMIT", "Evidence unit limit exceeded"
                )
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
            if len(title) > limits.max_evidence_unit_characters:
                raise ParseRejected(
                    "INGEST_SIZE_LIMIT", "Evidence unit character limit exceeded"
                )
            if len(units) >= limits.max_evidence_units:
                raise ParseRejected(
                    "INGEST_SIZE_LIMIT", "Evidence unit limit exceeded"
                )
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
    data: bytes,
    *,
    limits: ParseLimits,
    tenant_id: str,
    submission_id: str | None,
    artifact_id: str,
    artifact_hash: str,
    source_role: m.ArtifactRole,
) -> list[m.EvidenceUnit]:
    try:
        reader = PdfReader(io.BytesIO(data), strict=True)
        if reader.is_encrypted:
            raise ParseRejected(
                "INGEST_ENCRYPTED_FILE", "Encrypted PDFs are not supported"
            )
        if len(reader.pages) > limits.max_pdf_pages:
            raise ParseRejected("INGEST_SIZE_LIMIT", "PDF page limit exceeded")
        if _pdf_has_active_content(reader, limits=limits):
            raise ParseRejected(
                "REJECTED_SECURITY", "Active PDF content is not supported"
            )

        units: list[m.EvidenceUnit] = []
        extracted_characters = 0
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for page_number, page in enumerate(pdf.pages, start=1):
                lines = page.extract_text_lines(strip=True, return_chars=False) or []
                for block_index, line in enumerate(lines):
                    text = _normalize_text(str(line.get("text", "")))
                    if not text:
                        continue
                    if len(text) > limits.max_evidence_unit_characters:
                        raise ParseRejected(
                            "INGEST_SIZE_LIMIT",
                            "Evidence unit character limit exceeded",
                        )
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
                    if not all(math.isfinite(coordinate) for coordinate in bbox):
                        raise ParseRejected(
                            "PARSE_CORRUPT_FILE", "PDF contains invalid coordinates"
                        )
                    if bbox[2] < bbox[0] or bbox[3] < bbox[1]:
                        raise ParseRejected(
                            "PARSE_CORRUPT_FILE", "PDF contains invalid coordinates"
                        )
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
    except Exception as exc:
        raise ParseRejected(
            "PARSE_CORRUPT_FILE", "PDF structure is invalid"
        ) from exc
    if not units:
        raise ParseRejected("PARSE_EMPTY_NATIVE", "PDF contains no selectable text")
    return units


def _docx_heading_level(paragraph: object) -> int | None:
    style = getattr(paragraph, "style", None)
    candidates = [
        getattr(style, "style_id", "") or "",
        getattr(style, "name", "") or "",
    ]
    for candidate in candidates:
        match = re.search(r"(?:heading|t[ií]tulo)\s*([1-9])$", candidate, re.IGNORECASE)
        if match:
            return int(match.group(1))

    style_element = getattr(style, "element", None)
    paragraph_properties = getattr(style_element, "pPr", None)
    outline_level = getattr(paragraph_properties, "outlineLvl", None)
    value = getattr(outline_level, "val", None)
    try:
        numeric = int(value)
    except (TypeError, ValueError):
        return None
    return numeric + 1 if 0 <= numeric <= 8 else None


def _docx_paragraph_metadata(paragraph: object) -> dict[str, object]:
    style = getattr(paragraph, "style", None)
    style_name = getattr(style, "name", None)
    xml_paragraph = getattr(paragraph, "_p", None)
    paragraph_properties = getattr(xml_paragraph, "pPr", None)
    list_item = getattr(paragraph_properties, "numPr", None) is not None or bool(
        style_name
        and re.match(r"^(?:list|lista)\b", str(style_name), re.IGNORECASE)
    )
    image_count = 0
    xpath = getattr(xml_paragraph, "xpath", None)
    if callable(xpath):
        try:
            image_count = len(xpath(".//a:blip"))
        except (KeyError, TypeError, ValueError):
            image_count = 0
    metadata: dict[str, object] = {"native_text": True}
    if style_name:
        metadata["style"] = str(style_name)[:255]
    if list_item:
        metadata["list_item"] = True
    if image_count:
        metadata["inline_image_count"] = image_count
    return metadata


def _parse_docx(
    data: bytes,
    *,
    limits: ParseLimits,
    tenant_id: str,
    submission_id: str | None,
    artifact_id: str,
    artifact_hash: str,
    source_role: m.ArtifactRole,
) -> list[m.EvidenceUnit]:
    # Security checks over the raw OPC package must have completed before this
    # structural library sees any OOXML.
    try:
        from docx import Document
        from docx.table import Table
        from docx.text.paragraph import Paragraph
    except ImportError as exc:
        raise ParseRejected(
            "PARSER_UNAVAILABLE", "The approved DOCX parser is unavailable"
        ) from exc

    try:
        document = Document(io.BytesIO(data))
    except Exception as exc:
        raise ParseRejected(
            "PARSE_CORRUPT_FILE", "DOCX structure is invalid"
        ) from exc

    units: list[m.EvidenceUnit] = []
    heading_path: list[str] = []
    extracted_characters = 0
    paragraph_index = 0
    table_index = 0

    def append_unit(
        *,
        content: str,
        modality: m.EvidenceModality,
        locator: m.DocumentLocator,
        structured_content: dict[str, object],
    ) -> None:
        nonlocal extracted_characters
        normalized = _normalize_text(content)
        if not normalized:
            return
        if len(normalized) > limits.max_evidence_unit_characters:
            raise ParseRejected(
                "INGEST_SIZE_LIMIT", "Evidence unit character limit exceeded"
            )
        extracted_characters += len(normalized)
        if extracted_characters > limits.max_text_characters:
            raise ParseRejected(
                "INGEST_SIZE_LIMIT", "DOCX text character limit exceeded"
            )
        if len(units) >= limits.max_evidence_units:
            raise ParseRejected("INGEST_SIZE_LIMIT", "Evidence unit limit exceeded")
        units.append(
            _evidence_unit(
                tenant_id=tenant_id,
                submission_id=submission_id,
                artifact_id=artifact_id,
                artifact_hash=artifact_hash,
                source_role=source_role,
                modality=modality,
                locator=locator,
                content_text=normalized,
                structured_content=structured_content,
            )
        )

    try:
        body_items = document.iter_inner_content()
        for item in body_items:
            if isinstance(item, Paragraph):
                text = _normalize_text(item.text)
                level = _docx_heading_level(item)
                if text and level is not None:
                    heading_path = heading_path[: level - 1]
                    heading_path.append(text)
                    metadata = _docx_paragraph_metadata(item)
                    metadata["heading_level"] = level
                    append_unit(
                        content=text,
                        modality=m.EvidenceModality.HEADING,
                        locator=m.DocumentLocator(
                            paragraph_index=paragraph_index,
                            heading_path=list(heading_path),
                        ),
                        structured_content=metadata,
                    )
                elif text:
                    metadata = _docx_paragraph_metadata(item)
                    modality = (
                        m.EvidenceModality.LIST
                        if metadata.get("list_item")
                        else m.EvidenceModality.PARAGRAPH
                    )
                    append_unit(
                        content=text,
                        modality=modality,
                        locator=m.DocumentLocator(
                            paragraph_index=paragraph_index,
                            heading_path=list(heading_path),
                        ),
                        structured_content=metadata,
                    )
                paragraph_index += 1
                continue

            if isinstance(item, Table):
                seen_cells: set[object] = set()
                for row_index, row in enumerate(item.rows):
                    for column_index, cell in enumerate(row.cells):
                        cell_element = cell._tc
                        if cell_element in seen_cells:
                            continue
                        seen_cells.add(cell_element)
                        paragraphs = [
                            _normalize_text(paragraph.text)
                            for paragraph in cell.paragraphs
                            if _normalize_text(paragraph.text)
                        ]
                        append_unit(
                            content="\n".join(paragraphs),
                            modality=m.EvidenceModality.TABLE,
                            locator=m.DocumentLocator(
                                heading_path=list(heading_path),
                                table_index=table_index,
                                row=row_index,
                                column=column_index,
                            ),
                            structured_content={
                                "native_text": True,
                                "table_cell": True,
                                "paragraph_count": len(paragraphs),
                            },
                        )
                table_index += 1
    except ParseRejected:
        raise
    except Exception as exc:
        raise ParseRejected(
            "PARSE_CORRUPT_FILE", "DOCX structure is invalid"
        ) from exc

    if not units:
        raise ParseRejected("PARSE_EMPTY_NATIVE", "DOCX contains no structural text")
    return units


class SafeParserService:
    """Parser facade with byte/MIME/hash/security checks before extraction."""

    def __init__(
        self,
        limits: ParseLimits | None = None,
        *,
        require_libmagic: bool | None = None,
    ) -> None:
        self.limits = limits or ParseLimits()
        cloud_environment = (
            os.environ.get("CVA_ENVIRONMENT", "local").strip().casefold() == "cloud"
        )
        if cloud_environment:
            require_libmagic = True
        elif require_libmagic is None:
            explicit = os.environ.get("CVA_REQUIRE_LIBMAGIC")
            if explicit is not None:
                require_libmagic = explicit.strip().casefold() in {"1", "true", "yes"}
            else:
                require_libmagic = False
        self.require_libmagic = require_libmagic

    def parse(
        self,
        path: Path,
        *,
        tenant_id: str,
        source_role: m.ArtifactRole,
        submission_id: str | None = None,
        declared_media_type: str | None = None,
    ) -> ParsedArtifact:
        data = _safe_read(path, self.limits.max_bytes)
        if not data:
            raise ParseRejected("PARSE_EMPTY_NATIVE", "Empty artifacts are not usable")
        media_type, docx_preflight, mime_detector, libmagic_media_type = (
            _detect_media_type(
                data,
                path,
                declared_media_type=declared_media_type,
                limits=self.limits,
                require_libmagic=self.require_libmagic,
            )
        )
        if declared_media_type is not None and declared_media_type != media_type:
            raise ParseRejected("INGEST_MIME_MISMATCH", "Declared and detected MIME differ")
        if media_type not in _TEXT_MEDIA_TYPES | {_PDF_MEDIA_TYPE, _DOCX_MEDIA_TYPE}:
            raise ParseRejected("INGEST_UNSUPPORTED_MEDIA", "Media type is not enabled")
        if source_role == m.ArtifactRole.SUBMISSION and submission_id is None:
            raise ParseRejected("IR_PROVENANCE_GAP", "Submission evidence requires submission_id")
        if source_role != m.ArtifactRole.SUBMISSION and submission_id is not None:
            raise ParseRejected(
                "IR_PROVENANCE_GAP",
                "Only submission evidence carries submission_id",
            )

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
            _DOCX_MEDIA_TYPE: "stage2-docx-structural",
        }[media_type]
        artifact = m.ArtifactRef(
            artifact_id=artifact_id,
            role=source_role,
            filename=path.name,
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
                limits=self.limits,
                tenant_id=tenant_id,
                submission_id=submission_id,
                artifact_id=artifact_id,
                artifact_hash=artifact_hash,
                source_role=source_role,
            )
        elif media_type == _PDF_MEDIA_TYPE:
            units = _parse_pdf(
                data,
                limits=self.limits,
                tenant_id=tenant_id,
                submission_id=submission_id,
                artifact_id=artifact_id,
                artifact_hash=artifact_hash,
                source_role=source_role,
            )
        else:
            # Classification cannot return DOCX without completing preflight.
            if docx_preflight is None:
                raise ParseRejected(
                    "PARSE_CORRUPT_FILE", "DOCX package preflight was incomplete"
                )
            units = _parse_docx(
                data,
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
        return ParsedArtifact(
            artifact=artifact,
            evidence_units=tuple(units),
            mime_detector=mime_detector,
            libmagic_media_type=libmagic_media_type,
        )
