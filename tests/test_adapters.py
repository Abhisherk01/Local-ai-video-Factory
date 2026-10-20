"""Adapter probes and failure contracts (no real models needed)."""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import pytest

from laf.adapters import OllamaAdapter, PiperAdapter, KokoroAdapter
from laf.adapters.ollama import effective_prompt, strip_think
from laf.adapters.base import AdapterUnavailable


def test_ollama_probe_unreachable_reports_honestly(monkeypatch) -> None:
    monkeypatch.setenv("LAF_OLLAMA_URL", "http://127.0.0.1:1")  # nothing there
    status = OllamaAdapter().available()
    assert status.available is False
    assert "11434" not in status.detail or "no Ollama daemon" in status.detail


def test_piper_resolution_order_env_then_models_dir(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("LAF_PIPER", raising=False)
    monkeypatch.delenv("LAF_PIPER_VOICE", raising=False)

    missing = PiperAdapter(models_dir=tmp_path)
    assert missing.resolve_exe() is None
    assert missing.available().available is False

    exe = tmp_path / "piper" / "piper.exe" if sys.platform == "win32" \
        else tmp_path / "piper" / "piper"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"stub")
    voice = tmp_path / "piper" / "voices" / "en_US-amy-medium.onnx"
    voice.parent.mkdir(parents=True)
    voice.write_bytes(b"stub-onnx")

    found = PiperAdapter(models_dir=tmp_path)
    assert found.resolve_exe() == str(exe)
    assert found.resolve_voice() == voice
    status = found.available()
    assert status.available is True and "ready" in status.detail


def test_piper_env_overrides_win(tmp_path: Path, monkeypatch) -> None:
    exe = tmp_path / "custom-piper"
    exe.write_bytes(b"stub")
    monkeypatch.setenv("LAF_PIPER", str(exe))
    adapter = PiperAdapter(models_dir=tmp_path / "models")
    assert adapter.resolve_exe() == str(exe)


def test_piper_synthesize_runs_the_stub_cli(tmp_path: Path, monkeypatch) -> None:
    out = tmp_path / "out.wav"

    if sys.platform == "win32":
        stub = tmp_path / "fake_piper.cmd"
        stub.write_text(
            "@echo off\n"
            "setlocal enabledelayedexpansion\n"
            "set OUT=\n"
            ":loop\n"
            "if \"%1\"==\"\" goto run\n"
            "if \"%1\"==\"--output_file\" set OUT=%2\n"
            "shift\n"
            "goto loop\n"
            ":run\n"
            "powershell -Command \"$b=New-Object byte[] (44+320); [IO.File]::WriteAllBytes('%OUT%',$b)\"\n",
            encoding="utf-8",
        )
    else:
        stub = tmp_path / "fake_piper.sh"
        stub.write_text(
            "#!/bin/sh\n"
            "OUT=\"\"\n"
            "while [ $# -gt 0 ]; do\n"
            "  if [ \"$1\" = \"--output_file\" ]; then OUT=\"$2\"; fi\n"
            "  shift\n"
            "done\n"
            "python3 -c \"import sys; open(sys.argv[1],'wb').write(bytes(44+320))\" \"$OUT\"\n",
            encoding="utf-8",
        )
        stub.chmod(stub.stat().st_mode | stat.S_IEXEC)

    voice = tmp_path / "voice.onnx"
    voice.write_bytes(b"stub")
    monkeypatch.setenv("LAF_PIPER", str(stub))
    monkeypatch.setenv("LAF_PIPER_VOICE", str(voice))

    result = PiperAdapter(models_dir=tmp_path).synthesize("hello", out)
    assert result["method"] == "local_piper"
    assert out.exists() and result["bytes"] >= 44


def test_piper_synthesize_missing_exe_raises_with_fix_hint(tmp_path: Path) -> None:
    adapter = PiperAdapter(models_dir=tmp_path / "nowhere")
    with pytest.raises(AdapterUnavailable, match="not found"):
        adapter.synthesize("hello", tmp_path / "x.wav")


def test_kokoro_probe_is_honest_about_phase5() -> None:
    status = KokoroAdapter().available()
    assert status.available is False
    assert "Phase 5" in status.detail
    with pytest.raises(AdapterUnavailable, match="Phase 5"):
        KokoroAdapter().synthesize("text", "out.wav")


# ---------------------------------------------------------------------------
# Phase 6a.1: qwen3 think-leak hardening (strip_think + /no_think)
# ---------------------------------------------------------------------------


def test_strip_think_closed_block_removed() -> None:
    text, stripped, truncated = strip_think(
        "<think>plan the script first</think>Hook line. Body here."
    )
    assert text == "Hook line. Body here."
    assert stripped is True and truncated is False


def test_strip_think_unclosed_block_truncated() -> None:
    text, stripped, truncated = strip_think(
        "<think>rambling plan with no closing tag"
    )
    assert text == ""
    assert stripped is True and truncated is True


def test_strip_think_multiple_blocks_and_residue() -> None:
    text, stripped, truncated = strip_think(
        "<think>a</think>Keep <think>b</think>this. <think>tail without close"
    )
    assert text == "Keep this."
    assert stripped is True and truncated is True


def test_strip_think_clean_text_untouched() -> None:
    text, stripped, truncated = strip_think("A clean narration script.")
    assert text == "A clean narration script."
    assert stripped is False and truncated is False


def test_no_think_switch_only_for_qwen3() -> None:
    assert effective_prompt("Write it.", "qwen3:4b").endswith("/no_think")
    assert effective_prompt("Write it.", "llama3:8b") == "Write it."
