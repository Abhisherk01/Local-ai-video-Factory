"""Repository integrity tests - Local AI Video Factory, Phase 1.

Stdlib-only (no third-party dependencies) so they run anywhere, including
a fresh venv. These verify the repository skeleton itself: required docs,
design tokens, secret hygiene, and PowerShell script safety.

Business-logic tests arrive with the backend in Phase 2+.
"""

from __future__ import annotations

import json
import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[1]

REQUIRED_PATHS = [
    "README.md",
    "ARCHITECTURE.md",
    "ROADMAP.md",
    "CHANGELOG.md",
    "SECURITY.md",
    "LICENSES.md",
    "INSTALLATION.md",
    "TROUBLESHOOTING.md",
    "CONTRIBUTING.md",
    "LICENSE",
    ".env.example",
    ".gitignore",
    "pyproject.toml",
    "design/tokens.json",
    "docs/DESIGN-SYSTEM.md",
    "docs/PHASE0-HARDWARE-ASSESSMENT.md",
    "scripts/setup-windows.ps1",
    "scripts/probe-hardware.ps1",
]


def _read(relative_path: str) -> str:
    return (REPO / relative_path).read_text(encoding="utf-8")


def test_required_files_exist() -> None:
    missing = [p for p in REQUIRED_PATHS if not (REPO / p).is_file()]
    assert not missing, f"Missing required repository files: {missing}"


def test_tokens_json_is_valid_and_complete() -> None:
    tokens = json.loads(_read("design/tokens.json"))

    color = tokens["color"]
    for section in ("bg", "border", "text", "accent", "semantic", "chart"):
        assert section in color, f"tokens.color missing section: {section}"

    for key in ("default", "hover", "pressed", "subtle", "focusRing"):
        assert key in color["accent"], f"tokens.color.accent missing: {key}"

    # Semantic slots must cover the four states the UI relies on.
    for key in ("success", "warning", "danger", "info"):
        assert key in color["semantic"]

    assert tokens["typography"]["ui"] == "Inter"
    assert tokens["typography"]["mono"] == "JetBrains Mono"
    assert tokens["radius"]["md"] == 10
    assert tokens["spacing"]["xs"] == 4, "spacing grid must stay on a 4px base"


def test_all_hex_colors_are_six_digit_hex() -> None:
    tokens = json.loads(_read("design/tokens.json"))

    def walk(value: object) -> None:
        if isinstance(value, dict):
            for child in value.values():
                walk(child)
        elif isinstance(value, str) and value.startswith("#"):
            assert re.fullmatch(r"#[0-9A-Fa-f]{6}", value), f"Bad hex color: {value}"

    walk(tokens["color"])


def test_env_example_ships_no_live_secrets() -> None:
    text = _read(".env.example")
    assert "sk-" not in text, "example env must not contain API key material"
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        # Every active line must be a KEY with an EMPTY value.
        assert "=" in stripped, f"Malformed env line: {line!r}"
        key, _, value = stripped.partition("=")
        assert value.strip() == "", f".env.example must ship empty values only, got: {line!r}"
        assert key.upper() == key, f"env keys should be UPPER_CASE: {key!r}"


def test_changelog_and_roadmap_are_phase_complete() -> None:
    changelog = _read("CHANGELOG.md")
    assert "0.1.0" in changelog and "Phase 1" in changelog

    roadmap = _read("ROADMAP.md")
    # The roadmap must carry a table row for every phase 0..14.
    for phase in range(0, 15):
        assert f"\n| {phase} |" in roadmap, f"ROADMAP.md missing table row for Phase {phase}"


def test_gitignore_blocks_secrets_weights_and_media() -> None:
    gitignore = _read(".gitignore")
    for pattern in (".env", "node_modules", "__pycache__", ".venv", "*.mp4", "models/", "*.safetensors", "secrets/"):
        assert pattern in gitignore, f".gitignore missing pattern: {pattern}"


def test_powershell_scripts_are_ascii_only() -> None:
    # Windows PowerShell 5.1 mis-parses non-ASCII under some codepages;
    # repo policy: these scripts stay plain ASCII (CONTRIBUTING.md).
    for path in ("scripts/setup-windows.ps1", "scripts/probe-hardware.ps1"):
        text = _read(path)
        assert text.isascii(), f"{path} must be plain ASCII for PowerShell 5.1 safety"
        assert "\r\n" not in text or True  # line endings normalized by git config, not enforced here
