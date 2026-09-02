#!/usr/bin/env python3
"""Fail when tracked files contain likely credentials or generated artifacts."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]

SECRET_PATTERNS = {
    "private key": re.compile(r"BEGIN " + r"(?:RSA |EC |OPENSSH )?PRIVATE KEY"),
    "AWS access key": re.compile(r"AKIA" + r"[0-9A-Z]{16}"),
    "GitHub token": re.compile(r"gh[pousr]_" + r"[A-Za-z0-9]{30,}"),
    "Supabase secret key": re.compile(r"sb_" + r"secret_[A-Za-z0-9_-]{20,}"),
    "JWT": re.compile(
        r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"
    ),
}
DATABASE_CREDENTIAL = re.compile(
    r"postgres(?:ql)?(?:\+psycopg)?://[^:\s/]+:([^@\s]+)@", re.IGNORECASE
)
ALLOWED_DATABASE_PASSWORDS = {"procurement", "pass", "password", "...", "<password>"}


def tracked_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return [item.decode() for item in result.stdout.split(b"\0") if item]


def artifact_reason(relative: str) -> str | None:
    path = PurePosixPath(relative)
    parts = set(path.parts)
    if parts & {"__pycache__", ".venv", ".pytest_cache", ".ruff_cache", "node_modules"}:
        return "generated directory"
    if any(part.endswith(".egg-info") for part in path.parts):
        return "package build metadata"
    if path.suffix in {".pyc", ".pyo", ".log"}:
        return "runtime artifact"
    if relative == ".env" or (path.name.startswith(".env.") and path.name != ".env.example"):
        return "environment secret file"
    if path.parts and path.parts[0] == "logs":
        return "runtime log directory"
    return None


def secret_findings(relative: str) -> list[tuple[int, str]]:
    path = ROOT / relative
    try:
        text = path.read_text()
    except (UnicodeDecodeError, OSError):
        return []
    findings = []
    for line_number, line in enumerate(text.splitlines(), 1):
        for label, pattern in SECRET_PATTERNS.items():
            if pattern.search(line):
                findings.append((line_number, label))
        for match in DATABASE_CREDENTIAL.finditer(line):
            password = match.group(1).strip("'\"`")
            if "{" not in password and password not in ALLOWED_DATABASE_PASSWORDS:
                findings.append((line_number, "database URL credential"))
    return findings


def main() -> int:
    violations = []
    files = tracked_files()
    for relative in files:
        reason = artifact_reason(relative)
        if reason:
            violations.append(f"{relative}: {reason}")
        for line_number, label in secret_findings(relative):
            violations.append(f"{relative}:{line_number}: possible {label}")
    if violations:
        print("Repository audit failed:")
        for violation in violations:
            print(f"- {violation}")
        return 1
    print(f"Repository audit passed ({len(files)} tracked files checked).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
