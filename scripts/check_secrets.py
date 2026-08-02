#!/usr/bin/env python3
"""Fail on high-confidence credentials without printing matched content."""

from __future__ import annotations

from pathlib import Path
import re
import subprocess


ALLOW_MARKERS = (
    "cva_ci_password",
    "do-not-log",
    "example.test",
    "fake",
    "not-a-secret",
    "not_a_secret",
    "replace-with",
    "scoped-",
    "test-secret",
    "${",
    "…",
)

PATTERNS = {
    "private-key": re.compile(rb"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"),
    "aws-access-key": re.compile(rb"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "github-token": re.compile(
        rb"\b(?:gh[pousr]_[A-Za-z0-9_]{30,}|github_pat_[A-Za-z0-9_]{40,})\b"
    ),
    "google-api-key": re.compile(rb"\bAIza[0-9A-Za-z_-]{35}\b"),
    "jwt": re.compile(
        rb"\beyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\b"
    ),
    "authenticated-url": re.compile(
        rb"\b(?:postgres(?:ql)?(?:\+psycopg)?|https?)://[^\s/:@]+:[^\s/@]+@[^\s]+"
    ),
    "magic-link-token": re.compile(
        rb"(?:token_hash|access_token|refresh_token)=[A-Za-z0-9._~-]{20,}"
    ),
    "named-secret-assignment": re.compile(
        rb"(?m)^\s*(?:CVA_(?:DATABASE_URL|R2_ACCESS_KEY_ID|R2_SECRET_ACCESS_KEY|SESSION_SECRET)|AWS_(?:ACCESS_KEY_ID|SECRET_ACCESS_KEY)|POSTGRES_PASSWORD|SUPABASE_SERVICE_ROLE_KEY|GITHUB_TOKEN)\s*[:=]\s*[^\s#]+"
    ),
}


def _versionable_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        check=True,
        stdout=subprocess.PIPE,
    )
    return [Path(item) for item in result.stdout.decode().split("\0") if item]


def _is_allowed(match: bytes) -> bool:
    normalized = match.decode("utf-8", errors="ignore").lower()
    return any(marker in normalized for marker in ALLOW_MARKERS)


def main() -> int:
    findings: set[tuple[str, str]] = set()
    files = _versionable_files()
    for path in files:
        name = path.name
        if (name == ".env" or name.startswith(".env.")) and name != ".env.example":
            findings.add((str(path), "tracked-env-file"))
        if name.endswith(".tfvars") and not name.endswith(".tfvars.example"):
            findings.add((str(path), "tracked-terraform-variables"))
        if name.endswith((".tfstate", ".tfplan")) or ".tfstate." in name:
            findings.add((str(path), "tracked-terraform-state"))

        try:
            data = path.read_bytes()
        except OSError:
            findings.add((str(path), "unreadable-tracked-file"))
            continue
        for category, pattern in PATTERNS.items():
            for match in pattern.finditer(data):
                if not _is_allowed(match.group(0)):
                    findings.add((str(path), category))

    if findings:
        for path, category in sorted(findings):
            print(f"{path}\t{category}\tremove from Git and rotate if real")
        return 1
    print(f"PASS: {len(files)} versionable files; no high-confidence secrets found")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
