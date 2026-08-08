"""Fail-closed subprocess boundary for hostile parser inputs in cloud."""

from __future__ import annotations

from dataclasses import asdict
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
from tempfile import TemporaryDirectory

from ..canonical import sha256_bytes, stable_id
from ..contracts import models as m
from .service import (
    PARSER_VERSION,
    ParseRejected,
    ParsedArtifact,
    SafeParserService,
    _DOCX_MEDIA_TYPE,
    _PDF_MEDIA_TYPE,
    _TEXT_MEDIA_TYPES,
    _magic_compatibility,
    _safe_read,
)


_SANDBOX_BOOTSTRAP = (
    "import sys; "
    "sys.path.insert(0, sys.argv.pop(1)); "
    "from comprehension_verification.parsers.sandbox_worker import main; "
    "raise SystemExit(main())"
)

# Only stable parser codes emitted by the trusted structural parser may cross
# the subprocess boundary.  Treat any other child-controlled value as a
# sandbox failure so malformed output cannot become a log/UI injection vector.
_CHILD_REJECTION_CODES = frozenset(
    {
        "INGEST_ENCRYPTED_FILE",
        "INGEST_INVALID_ENCODING",
        "INGEST_MIME_DETECTOR_UNAVAILABLE",
        "INGEST_MIME_MISMATCH",
        "INGEST_PARSER_SANDBOX_FAILURE",
        "INGEST_SIZE_LIMIT",
        "INGEST_UNSUPPORTED_MEDIA",
        "IR_PROVENANCE_GAP",
        "PARSER_UNAVAILABLE",
        "PARSE_CORRUPT_FILE",
        "PARSE_EMPTY_NATIVE",
        "REJECTED_SECURITY",
    }
)
_CHILD_MIME_DETECTORS = frozenset({"libmagic", "signature-fallback"})
_CHILD_MEDIA_TYPES = frozenset(
    {*_TEXT_MEDIA_TYPES, _PDF_MEDIA_TYPE, _DOCX_MEDIA_TYPE}
)
_MAX_CHILD_OUTPUT_BYTES = 32_000_000


def _terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    """Terminate the isolated session without leaving parser descendants."""

    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:  # pragma: no cover - the cloud runtime is Linux.
            process.kill()
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:  # pragma: no cover - defensive fallback.
        process.kill()
        process.wait()


def harden_parent_process() -> None:
    """Prevent same-UID children from inspecting the cloud parent's memory/env."""

    if sys.platform != "linux":
        return
    import ctypes

    libc = ctypes.CDLL(None, use_errno=True)
    # PR_SET_DUMPABLE = 4.  This also blocks /proc/<pid>/environ reads by a
    # compromised same-UID parser child under the normal Linux ptrace policy.
    if libc.prctl(4, 0, 0, 0, 0) != 0:
        error = ctypes.get_errno()
        raise RuntimeError(f"PARSER_PARENT_HARDENING_FAILED:{error}")


def parse_in_subprocess(
    path: Path,
    *,
    parser: SafeParserService,
    tenant_id: str,
    source_role: m.ArtifactRole,
    submission_id: str | None,
    declared_media_type: str | None,
    timeout_seconds: int,
    require_isolation: bool,
) -> ParsedArtifact:
    """Parse in a fresh interpreter with a minimal environment and hard limits."""

    lexical_path = path.absolute()
    expected_data = _safe_read(lexical_path, parser.limits.max_bytes)
    expected_size = len(expected_data)
    expected_hash = sha256_bytes(expected_data)
    del expected_data
    expected_artifact_id = stable_id(
        "art",
        tenant_id,
        source_role.value,
        submission_id or source_role.value,
        expected_hash,
    )
    source_root = str(Path(__file__).resolve().parents[2])
    with TemporaryDirectory(prefix="cva-parser-control-") as control_dir:
        control_path = Path(control_dir)
        payload_path = control_path / "request.json"
        payload_path.write_text(
            json.dumps(
                {
                    # Keep the absolute lexical path so the child's lstat-based
                    # regular-file check still sees and rejects a final symlink.
                    "path": str(lexical_path),
                    "tenant_id": tenant_id,
                    "source_role": source_role.value,
                    "submission_id": submission_id,
                    "declared_media_type": declared_media_type,
                    "limits": asdict(parser.limits),
                    "require_libmagic": parser.require_libmagic,
                    "require_isolation": require_isolation,
                    "timeout_seconds": timeout_seconds,
                },
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        response_path = control_path / "response.json"
        environment = {
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            "PYTHONUTF8": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "TMPDIR": str(control_path),
        }
        try:
            with response_path.open("w+b") as response_stream:
                process = subprocess.Popen(
                    [
                        sys.executable,
                        "-I",
                        "-c",
                        _SANDBOX_BOOTSTRAP,
                        source_root,
                        str(payload_path),
                    ],
                    cwd=control_path,
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    stdout=response_stream,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                    close_fds=True,
                )
                try:
                    returncode = process.wait(timeout=timeout_seconds)
                except subprocess.TimeoutExpired as exc:
                    _terminate_process_group(process)
                    raise ParseRejected(
                        "INGEST_PARSER_TIMEOUT",
                        "The isolated parser exceeded its execution deadline",
                    ) from exc
                output_size = os.fstat(response_stream.fileno()).st_size
                if output_size > _MAX_CHILD_OUTPUT_BYTES:
                    raise ParseRejected(
                        "INGEST_SIZE_LIMIT",
                        "The isolated parser output exceeded its limit",
                    )
                response_stream.seek(0)
                raw_response = response_stream.read(_MAX_CHILD_OUTPUT_BYTES + 1)
        except ParseRejected:
            raise
        except OSError as exc:
            raise ParseRejected(
                "INGEST_PARSER_SANDBOX_FAILURE",
                "The isolated parser could not be started safely",
            ) from exc
        try:
            response = json.loads(raw_response.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
            raise ParseRejected(
                "INGEST_PARSER_SANDBOX_FAILURE",
                "The isolated parser returned an invalid envelope",
            ) from exc
        if not isinstance(response, dict):
            raise ParseRejected(
                "INGEST_PARSER_SANDBOX_FAILURE",
                "The isolated parser returned an invalid envelope",
            )
        if returncode != 0 or response.get("ok") is not True:
            code = response.get("code")
            if not isinstance(code, str) or code not in _CHILD_REJECTION_CODES:
                code = "INGEST_PARSER_SANDBOX_FAILURE"
            raise ParseRejected(code, "The isolated parser rejected the artifact")
        try:
            artifact = m.ArtifactRef.model_validate(response["artifact"])
            evidence_units = tuple(
                m.EvidenceUnit.model_validate(item)
                for item in response["evidence_units"]
            )
            mime_detector = response.get("mime_detector")
            libmagic_media_type = response.get("libmagic_media_type")
            if mime_detector not in _CHILD_MIME_DETECTORS:
                raise ValueError("invalid MIME detector attestation")
            if artifact.media_type not in _CHILD_MEDIA_TYPES:
                raise ValueError("artifact MIME is not enabled")
            if parser.require_libmagic and mime_detector != "libmagic":
                raise ValueError("required libmagic attestation is missing")
            if mime_detector == "libmagic":
                if not isinstance(libmagic_media_type, str) or not (
                    3 <= len(libmagic_media_type) <= 255
                ):
                    raise ValueError("invalid libmagic MIME attestation")
                if any(
                    ord(character) < 0x21 or ord(character) > 0x7E
                    for character in libmagic_media_type
                ):
                    raise ValueError("invalid libmagic MIME attestation")
                if _magic_compatibility(
                    artifact.media_type, libmagic_media_type
                ) is not True:
                    raise ValueError("incompatible libmagic MIME attestation")
            elif libmagic_media_type is not None:
                if not isinstance(libmagic_media_type, str) or not (
                    3 <= len(libmagic_media_type) <= 255
                ):
                    raise ValueError("invalid fallback MIME attestation")
                if _magic_compatibility(
                    artifact.media_type, libmagic_media_type
                ) is not None:
                    raise ValueError("incompatible fallback MIME attestation")
            if artifact.artifact_id != expected_artifact_id:
                raise ValueError("artifact ID does not match the request")
            if (
                artifact.role != source_role
                or artifact.filename != lexical_path.name
            ):
                raise ValueError("artifact identity does not match the request")
            if (
                artifact.sha256 != expected_hash
                or artifact.byte_size != expected_size
            ):
                raise ValueError("artifact fingerprint does not match the request")
            if (
                declared_media_type is not None
                and artifact.media_type != declared_media_type
            ):
                raise ValueError("artifact MIME does not match the request")
            if artifact.parser_version != PARSER_VERSION or not artifact.parser_id:
                raise ValueError("parser identity is invalid")
            if (
                not evidence_units
                or len(evidence_units) > parser.limits.max_evidence_units
            ):
                raise ValueError("evidence count is invalid")
            if len({item.evidence_id for item in evidence_units}) != len(
                evidence_units
            ):
                raise ValueError("evidence IDs are not unique")
            total_text_characters = 0
            for item in evidence_units:
                if (
                    item.tenant_id != tenant_id
                    or item.submission_id != submission_id
                    or item.source_role != source_role
                    or item.artifact_id != artifact.artifact_id
                    or item.artifact_hash != artifact.sha256
                ):
                    raise ValueError("evidence provenance does not match the request")
                content_length = len(item.content_text or "")
                if content_length > parser.limits.max_evidence_unit_characters:
                    raise ValueError("evidence text exceeds its request limit")
                total_text_characters += content_length
            if total_text_characters > parser.limits.max_text_characters:
                raise ValueError("evidence text exceeds the request limit")
            return ParsedArtifact(
                artifact=artifact,
                evidence_units=evidence_units,
                mime_detector=mime_detector,
                libmagic_media_type=libmagic_media_type,
            )
        except (KeyError, ValueError, TypeError) as exc:
            raise ParseRejected(
                "INGEST_PARSER_SANDBOX_FAILURE",
                "The isolated parser output failed contract validation",
            ) from exc
