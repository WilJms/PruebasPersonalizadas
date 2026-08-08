from __future__ import annotations

import errno
import json
from pathlib import Path
import subprocess

import pytest

from comprehension_verification.contracts import models as m
import comprehension_verification.parsers.sandbox as parser_sandbox
import comprehension_verification.parsers.sandbox_worker as sandbox_worker
from comprehension_verification.parsers.service import ParseRejected, SafeParserService


def _parse(
    path: Path,
    *,
    timeout_seconds: int = 10,
    require_libmagic: bool = False,
) -> object:
    return parser_sandbox.parse_in_subprocess(
        path,
        parser=SafeParserService(require_libmagic=require_libmagic),
        tenant_id="tnt_sandbox",
        source_role=m.ArtifactRole.SUBMISSION,
        submission_id="sub_sandbox",
        declared_media_type="text/plain",
        timeout_seconds=timeout_seconds,
        require_isolation=False,
    )


def _mock_child(
    monkeypatch: pytest.MonkeyPatch,
    *,
    payload: bytes,
    returncode: int,
) -> None:
    class FakeProcess:
        pid = 424242

        def wait(self, timeout: int | None = None) -> int:
            assert timeout is not None
            return returncode

    def launch(*_args: object, **kwargs: object) -> FakeProcess:
        assert kwargs["stderr"] is subprocess.DEVNULL
        assert kwargs["start_new_session"] is True
        assert kwargs["close_fds"] is True
        response_stream = kwargs["stdout"]
        response_stream.write(payload)
        response_stream.flush()
        return FakeProcess()

    monkeypatch.setattr(parser_sandbox.subprocess, "Popen", launch)


def test_parser_subprocess_roundtrip_preserves_structured_provenance(
    tmp_path: Path,
) -> None:
    source = tmp_path / "submission.txt"
    source.write_text(
        "Control estructural\nLa evidencia conserva procedencia reproducible.\n",
        encoding="utf-8",
    )

    parsed = _parse(source)

    assert parsed.artifact.filename == source.name
    assert parsed.artifact.role == m.ArtifactRole.SUBMISSION
    assert parsed.evidence_units
    assert {item.submission_id for item in parsed.evidence_units} == {"sub_sandbox"}
    assert {item.tenant_id for item in parsed.evidence_units} == {"tnt_sandbox"}
    assert {item.artifact_hash for item in parsed.evidence_units} == {
        parsed.artifact.sha256
    }
    assert parsed.mime_detector in {"libmagic", "signature-fallback"}


def test_parser_subprocess_does_not_resolve_a_final_symlink(tmp_path: Path) -> None:
    target = tmp_path / "target.txt"
    target.write_text("synthetic structural evidence", encoding="utf-8")
    symlink = tmp_path / "submission.txt"
    symlink.symlink_to(target)

    with pytest.raises(ParseRejected) as error:
        _parse(symlink)

    assert error.value.code == "INGEST_UNSUPPORTED_MEDIA"


def test_parser_subprocess_timeout_is_stable_and_content_free(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "private-student-content.txt"
    source.write_text("do not expose this marker", encoding="utf-8")

    class TimedOutProcess:
        pid = 424242

        def wait(self, timeout: int | None = None) -> int:
            raise subprocess.TimeoutExpired(cmd="isolated-parser", timeout=timeout)

    terminated: list[int] = []
    monkeypatch.setattr(
        parser_sandbox.subprocess,
        "Popen",
        lambda *_args, **_kwargs: TimedOutProcess(),
    )
    monkeypatch.setattr(
        parser_sandbox,
        "_terminate_process_group",
        lambda process: terminated.append(process.pid),
    )

    with pytest.raises(ParseRejected) as error:
        _parse(source, timeout_seconds=7)

    assert error.value.code == "INGEST_PARSER_TIMEOUT"
    assert terminated == [424242]
    assert "private-student-content" not in str(error.value)
    assert "do not expose" not in str(error.value)


@pytest.mark.parametrize(
    ("stdout", "returncode", "expected_code"),
    [
        (
            json.dumps({"ok": False, "code": "PARSE_CORRUPT_FILE"}).encode(),
            2,
            "PARSE_CORRUPT_FILE",
        ),
        (
            json.dumps(
                {"ok": False, "code": "INGEST_EXFILTRATE_TENANT_SECRET"}
            ).encode(),
            2,
            "INGEST_PARSER_SANDBOX_FAILURE",
        ),
        (
            json.dumps({"ok": False, "code": "BAD\nstudent-secret"}).encode(),
            2,
            "INGEST_PARSER_SANDBOX_FAILURE",
        ),
        (json.dumps(["student-secret"]).encode(), 3, "INGEST_PARSER_SANDBOX_FAILURE"),
    ],
)
def test_parser_subprocess_sanitizes_child_envelopes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stdout: bytes,
    returncode: int,
    expected_code: str,
) -> None:
    source = tmp_path / "submission.txt"
    source.write_text("student-secret", encoding="utf-8")
    _mock_child(monkeypatch, payload=stdout, returncode=returncode)

    with pytest.raises(ParseRejected) as error:
        _parse(source)

    assert error.value.code == expected_code
    assert "student-secret" not in str(error.value)
    assert "stderr" not in str(error.value)


def test_parser_subprocess_caps_child_output_before_loading_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "submission.txt"
    source.write_text("synthetic", encoding="utf-8")
    monkeypatch.setattr(parser_sandbox, "_MAX_CHILD_OUTPUT_BYTES", 32)
    _mock_child(monkeypatch, payload=b"x" * 33, returncode=0)

    with pytest.raises(ParseRejected) as error:
        _parse(source)

    assert error.value.code == "INGEST_SIZE_LIMIT"


@pytest.mark.parametrize(
    ("mime_detector", "libmagic_media_type"),
    [
        ("HOSTILE\nVALUE", None),
        ("libmagic", "text/plain\nstudent-secret"),
        ("libmagic", "application/pdf"),
        ("signature-fallback", "text/plain"),
        ("unknown", None),
    ],
)
def test_parser_subprocess_rejects_untrusted_success_attestations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mime_detector: str,
    libmagic_media_type: str | None,
) -> None:
    source = tmp_path / "submission.txt"
    source.write_text("student-secret", encoding="utf-8")
    direct = SafeParserService(require_libmagic=False).parse(
        source,
        tenant_id="tnt_sandbox",
        source_role=m.ArtifactRole.SUBMISSION,
        submission_id="sub_sandbox",
        declared_media_type="text/plain",
    )
    payload = json.dumps(
        {
            "ok": True,
            "artifact": direct.artifact.model_dump(mode="json"),
            "evidence_units": [
                item.model_dump(mode="json") for item in direct.evidence_units
            ],
            "mime_detector": mime_detector,
            "libmagic_media_type": libmagic_media_type,
        }
    ).encode()
    _mock_child(monkeypatch, payload=payload, returncode=0)

    with pytest.raises(ParseRejected) as error:
        _parse(source)

    assert error.value.code == "INGEST_PARSER_SANDBOX_FAILURE"
    assert "student-secret" not in str(error.value)


def test_parser_subprocess_requires_libmagic_attestation_when_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "submission.txt"
    source.write_text("synthetic structural evidence", encoding="utf-8")
    direct = SafeParserService(require_libmagic=False).parse(
        source,
        tenant_id="tnt_sandbox",
        source_role=m.ArtifactRole.SUBMISSION,
        submission_id="sub_sandbox",
        declared_media_type="text/plain",
    )
    payload = json.dumps(
        {
            "ok": True,
            "artifact": direct.artifact.model_dump(mode="json"),
            "evidence_units": [
                item.model_dump(mode="json") for item in direct.evidence_units
            ],
            "mime_detector": "signature-fallback",
            "libmagic_media_type": None,
        }
    ).encode()
    _mock_child(monkeypatch, payload=payload, returncode=0)

    with pytest.raises(ParseRejected) as error:
        _parse(source, require_libmagic=True)

    assert error.value.code == "INGEST_PARSER_SANDBOX_FAILURE"


def test_parser_subprocess_rejects_cross_context_success_envelope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "submission.txt"
    source.write_text("synthetic structural evidence", encoding="utf-8")
    foreign = SafeParserService(require_libmagic=False).parse(
        source,
        tenant_id="tnt_other",
        source_role=m.ArtifactRole.SUBMISSION,
        submission_id="sub_other",
        declared_media_type="text/plain",
    )
    payload = json.dumps(
        {
            "ok": True,
            "artifact": foreign.artifact.model_dump(mode="json"),
            "evidence_units": [
                item.model_dump(mode="json") for item in foreign.evidence_units
            ],
            "mime_detector": foreign.mime_detector,
            "libmagic_media_type": foreign.libmagic_media_type,
        }
    ).encode()
    _mock_child(monkeypatch, payload=payload, returncode=0)

    with pytest.raises(ParseRejected) as error:
        _parse(source)

    assert error.value.code == "INGEST_PARSER_SANDBOX_FAILURE"


def test_network_self_test_accepts_seccomp_eperm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def denied(*_args: object, **_kwargs: object) -> object:
        raise OSError(errno.EPERM, "hostile detail must not escape")

    monkeypatch.setattr(sandbox_worker.socket, "socket", denied)

    sandbox_worker._assert_network_is_denied()


@pytest.mark.parametrize(
    ("timeout_seconds", "expected_cpu_limit"),
    [(7, (7, 8)), (120, (20, 21))],
)
def test_worker_cpu_limit_is_bounded_by_the_wall_timeout(
    monkeypatch: pytest.MonkeyPatch,
    timeout_seconds: int,
    expected_cpu_limit: tuple[int, int],
) -> None:
    applied: list[tuple[int, tuple[int, int]]] = []
    monkeypatch.setattr(
        sandbox_worker.resource,
        "setrlimit",
        lambda kind, limit: applied.append((kind, limit)),
    )
    monkeypatch.setattr(
        sandbox_worker.resource,
        "getrlimit",
        lambda _kind: (256, 256),
    )

    sandbox_worker._set_resource_limits(timeout_seconds=timeout_seconds)

    assert (
        sandbox_worker.resource.RLIMIT_CPU,
        expected_cpu_limit,
    ) in applied


def test_network_self_test_closes_socket_and_fails_if_network_is_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class UnexpectedSocket:
        closed = False

        def close(self) -> None:
            self.closed = True

    unexpected = UnexpectedSocket()
    monkeypatch.setattr(
        sandbox_worker.socket,
        "socket",
        lambda *_args, **_kwargs: unexpected,
    )

    with pytest.raises(RuntimeError, match="network isolation self-test failed"):
        sandbox_worker._assert_network_is_denied()

    assert unexpected.closed is True


def test_worker_fails_closed_before_parsing_when_network_self_test_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    request = tmp_path / "request.json"
    request.write_text(json.dumps({"require_isolation": True}), encoding="utf-8")
    monkeypatch.setattr(sandbox_worker.sys, "argv", ["sandbox-worker", str(request)])
    monkeypatch.setattr(
        sandbox_worker,
        "_set_resource_limits",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(sandbox_worker, "_deny_network_with_seccomp", lambda: None)

    def failed_self_test() -> None:
        raise RuntimeError("student-secret from failed isolation")

    monkeypatch.setattr(sandbox_worker, "_assert_network_is_denied", failed_self_test)

    assert sandbox_worker.main() == 3
    response = capsys.readouterr()
    assert json.loads(response.out) == {
        "ok": False,
        "code": "INGEST_PARSER_SANDBOX_FAILURE",
    }
    assert "student-secret" not in response.out
    assert response.err == ""
