"""Minimal child entrypoint for the cloud parser sandbox."""

from __future__ import annotations

import ctypes
import errno
import json
import os
from pathlib import Path
import resource
import socket
import sys

from ..contracts import models as m
from .service import ParseLimits, ParseRejected, SafeParserService


_MAX_CPU_SECONDS = 20


def _set_resource_limits(*, timeout_seconds: int) -> None:
    if isinstance(timeout_seconds, bool) or timeout_seconds <= 0:
        raise RuntimeError("invalid parser timeout")
    cpu_seconds = min(timeout_seconds, _MAX_CPU_SECONDS)
    limits = (
        (resource.RLIMIT_CORE, 0, 0),
        (resource.RLIMIT_CPU, cpu_seconds, cpu_seconds + 1),
        (resource.RLIMIT_FSIZE, 32 * 1024 * 1024, 32 * 1024 * 1024),
        (resource.RLIMIT_NOFILE, 32, 32),
    )
    if sys.platform == "linux":
        limits = (
            *limits,
            (resource.RLIMIT_AS, 512 * 1024 * 1024, 512 * 1024 * 1024),
        )
    if hasattr(resource, "RLIMIT_NPROC"):
        # RLIMIT_NPROC is accounted per UID.  The existing container user may
        # already own the parent process, so lowering the hard limit below the
        # current count is rejected by some kernels.  A soft limit of one still
        # prevents this child from forking; keep the inherited hard ceiling.
        _current_soft, current_hard = resource.getrlimit(resource.RLIMIT_NPROC)
        limits = (*limits, (resource.RLIMIT_NPROC, 1, current_hard))
    for kind, soft, hard in limits:
        resource.setrlimit(kind, (soft, hard))


def _deny_network_with_seccomp() -> None:
    if sys.platform != "linux":
        raise RuntimeError("seccomp is available only on Linux")
    library = ctypes.CDLL("libseccomp.so.2", use_errno=True)
    library.seccomp_init.argtypes = [ctypes.c_uint32]
    library.seccomp_init.restype = ctypes.c_void_p
    library.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    library.seccomp_syscall_resolve_name.restype = ctypes.c_int
    library.seccomp_rule_add.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_int,
        ctypes.c_uint,
    ]
    library.seccomp_rule_add.restype = ctypes.c_int
    library.seccomp_load.argtypes = [ctypes.c_void_p]
    library.seccomp_load.restype = ctypes.c_int
    library.seccomp_release.argtypes = [ctypes.c_void_p]
    allow = 0x7FFF0000
    errno_action = 0x00050000 | errno.EPERM
    context = library.seccomp_init(allow)
    if not context:
        raise RuntimeError("seccomp_init failed")
    try:
        for name in (
            b"socket",
            b"socketpair",
            b"connect",
            b"bind",
            b"listen",
            b"accept",
            b"accept4",
            b"sendto",
            b"sendmsg",
            b"sendmmsg",
        ):
            syscall = library.seccomp_syscall_resolve_name(name)
            if syscall >= 0 and library.seccomp_rule_add(
                context, errno_action, syscall, 0
            ) != 0:
                raise RuntimeError("seccomp_rule_add failed")
        if library.seccomp_load(context) != 0:
            raise RuntimeError("seccomp_load failed")
    finally:
        library.seccomp_release(context)


def _assert_network_is_denied() -> None:
    """Fail closed unless the installed filter rejects socket creation."""

    candidate: socket.socket | None = None
    try:
        candidate = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    except OSError as exc:
        if exc.errno == errno.EPERM:
            return
        raise RuntimeError(
            "network isolation self-test returned an unsafe error"
        ) from None
    finally:
        if candidate is not None:
            candidate.close()
    raise RuntimeError("network isolation self-test failed")


def main() -> int:
    os.umask(0o077)
    try:
        request = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
        _set_resource_limits(timeout_seconds=request["timeout_seconds"])
        if request.get("require_isolation") is True:
            _deny_network_with_seccomp()
            _assert_network_is_denied()
        parser = SafeParserService(
            ParseLimits(**request["limits"]),
            require_libmagic=bool(request.get("require_libmagic")),
        )
        parsed = parser.parse(
            Path(request["path"]),
            tenant_id=request["tenant_id"],
            source_role=m.ArtifactRole(request["source_role"]),
            submission_id=request.get("submission_id"),
            declared_media_type=request.get("declared_media_type"),
        )
        response = {
            "ok": True,
            "artifact": parsed.artifact.model_dump(mode="json"),
            "evidence_units": [
                item.model_dump(mode="json") for item in parsed.evidence_units
            ],
            "mime_detector": parsed.mime_detector,
            "libmagic_media_type": parsed.libmagic_media_type,
        }
        sys.stdout.write(
            json.dumps(response, ensure_ascii=True, separators=(",", ":"))
        )
        return 0
    except ParseRejected as exc:
        sys.stdout.write(json.dumps({"ok": False, "code": exc.code}))
        return 2
    except BaseException:
        # Never expose exception text or hostile content across the boundary.
        sys.stdout.write(
            json.dumps({"ok": False, "code": "INGEST_PARSER_SANDBOX_FAILURE"})
        )
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
