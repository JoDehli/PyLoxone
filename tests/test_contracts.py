"""Source and metadata consistency checks (no Home Assistant runtime).

Each test pins one thing that is easy to break by editing a single file:
platform modules vs the platform list, manifest requirements vs imports,
translation parity, services vs translations, the version string.  A test
marked ``xfail(strict=True)`` documents a mismatch that exists today; once it
is fixed the test starts passing and the marker must be removed.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
INTEGRATION = ROOT / "custom_components" / "loxone"
TRANSLATIONS = INTEGRATION / "translations"

NOT_PLATFORMS = {
    "__init__",
    "config_flow",
    "const",
    "coordinator",
    "diagnostics",
    "helpers",
    "miniserver",
    "system_health",
}


def _platform_modules() -> set[str]:
    """Module names under the integration that define ``async_setup_entry``."""
    found = set()
    for path in INTEGRATION.glob("*.py"):
        if path.stem in NOT_PLATFORMS:
            continue
        tree = ast.parse(path.read_text())
        if any(isinstance(node, ast.AsyncFunctionDef) and node.name == "async_setup_entry" for node in tree.body):
            found.add(path.stem)
    return found


def _manifest() -> dict:
    return json.loads((INTEGRATION / "manifest.json").read_text())


def _translation(lang: str) -> dict:
    return json.loads((TRANSLATIONS / f"{lang}.json").read_text())


def _missing_keys(reference: dict, other: dict, path: str = "") -> list[str]:
    missing = []
    for key, value in reference.items():
        here = f"{path}.{key}" if path else key
        if key not in other:
            missing.append(here)
        elif isinstance(value, dict) and isinstance(other[key], dict):
            missing.extend(_missing_keys(value, other[key], here))
    return missing


@pytest.mark.xfail(
    strict=True,
    reason="text.py has async_setup_entry but Platform.TEXT is not in LOXONE_PLATFORMS: the platform never loads",
)
def test_platform_modules_match_loxone_platforms():
    from custom_components.loxone.const import LOXONE_PLATFORMS

    listed = {platform.value for platform in LOXONE_PLATFORMS}
    assert _platform_modules() == listed


def test_every_manifest_requirement_is_imported():
    """A requirement nobody imports is dead weight on every install."""
    import_names = {"pycryptodome": "Crypto"}
    source = "\n".join(path.read_text() for path in INTEGRATION.rglob("*.py"))
    for requirement in _manifest()["requirements"]:
        name = re.split(r"[<>=!~\[]", requirement, maxsplit=1)[0].strip()
        module = import_names.get(name, name)
        assert re.search(rf"^\s*(import|from)\s+{re.escape(module)}\b", source, re.MULTILINE), (
            f"manifest requires {requirement!r} but nothing imports {module!r}"
        )


def test_manifest_version_is_semver():
    assert re.fullmatch(r"\d+\.\d+\.\d+", _manifest()["version"])


@pytest.mark.xfail(strict=True, reason="de.json lacks services.sync_areas")
def test_de_translations_cover_en():
    assert _missing_keys(_translation("en"), _translation("de")) == []


def test_services_yaml_keys_have_en_translations():
    keys = [
        match.group(1)
        for line in (INTEGRATION / "services.yaml").read_text().splitlines()
        if (match := re.match(r"^([A-Za-z_]\w*):", line))
    ]
    assert keys, "services.yaml parsed to zero services"
    assert set(keys) <= set(_translation("en")["services"]), (
        f"services without an en.json entry: {set(keys) - set(_translation('en')['services'])}"
    )


@pytest.mark.parametrize("module", sorted(_platform_modules()))
def test_platform_module_imports(module, enable_custom_integrations, hass):
    """Every platform module imports cleanly (a SyntaxError or a bad import
    would otherwise only surface when Home Assistant loads that platform)."""
    import importlib

    importlib.import_module(f"custom_components.loxone.{module}")
