from __future__ import annotations

import pytest

from scripts.audit_repository import SECRET_PATTERNS, artifact_reason


@pytest.mark.parametrize(
    "label, candidate",
    [
        ("private key", "BEGIN " + "PRIVATE KEY"),
        ("AWS access key", "AK" + "IA" + "A" * 16),
        ("GitHub token", "gh" + "p_" + "a" * 30),
        ("Supabase secret key", "sb_" + "secret_" + "a" * 24),
        ("JWT", ".".join(["eyJ" + "a" * 10, "b" * 12, "c" * 12])),
    ],
)
def test_high_confidence_secret_patterns(label: str, candidate: str) -> None:
    assert SECRET_PATTERNS[label].search(candidate)


@pytest.mark.parametrize(
    "path",
    [
        ".env",
        ".env.production",
        "logs/scraper.log",
        "package.egg-info/PKG-INFO",
        "module/__pycache__/module.pyc",
        ".venv/bin/python",
    ],
)
def test_generated_or_secret_artifacts_are_rejected(path: str) -> None:
    assert artifact_reason(path) is not None


def test_safe_templates_are_allowed() -> None:
    assert artifact_reason(".env.example") is None
    assert artifact_reason("docs/operations.md") is None
