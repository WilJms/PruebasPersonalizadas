#!/usr/bin/env python3
"""Generate the deterministic Stage 1 OpenAPI snapshot."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


os.environ.setdefault("CVA_ENVIRONMENT", "test")
os.environ.setdefault("CVA_DATABASE_URL", "sqlite+pysqlite://")
os.environ.setdefault("CVA_FRONTEND_DIST", "/tmp/cva-openapi-no-frontend")

from comprehension_verification.web.app import create_app  # noqa: E402
from comprehension_verification.web.settings import Settings  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "tests" / "fixtures" / "openapi" / "stage1-v1.json"


def build_schema() -> dict:
    app = create_app(
        Settings(
            environment="test",
            database_url="sqlite+pysqlite://",
            frontend_dist="/tmp/cva-openapi-no-frontend",
        )
    )
    return app.openapi()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(build_schema(), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
