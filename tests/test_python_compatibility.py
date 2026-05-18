"""Source-level compatibility checks for modern Python versions."""

from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
LEGACY_EXCEPT_PATTERN = re.compile(
    r"except\s+[^\(\n:][^:\n]*,\s*[A-Za-z_][A-Za-z0-9_\.]*\s*:"
)


def test_no_legacy_comma_except_handlers_remain() -> None:
    """Modern Python rejects ``except A, B:`` syntax."""
    source_paths = ROOT.glob("custom_components/**/*.py")
    offenders = [
        str(path.relative_to(ROOT))
        for path in source_paths
        if LEGACY_EXCEPT_PATTERN.search(path.read_text(encoding="utf-8"))
    ]

    assert offenders == []


def test_ruff_targets_python_314() -> None:
    """Keep lint parsing aligned with the latest supported Python line."""
    ruff_config = (ROOT / "ruff.toml").read_text(encoding="utf-8")

    assert 'target-version = "py314"' in ruff_config
