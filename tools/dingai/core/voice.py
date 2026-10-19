"""Local speech-to-text through a whisper.cpp binary. No package and no network.

Set DINGAI_WHISPER to the whisper-cli executable and DINGAI_WHISPER_MODEL to a
ggml model. DINGAI_WHISPER_LANG is zh, en, or vi.
"""

import os
import shutil
import subprocess

LANGS = ("zh", "en", "vi")


def whisper_bin():
    env = os.environ.get("DINGAI_WHISPER", "").strip()
    if env:
        return env
    return shutil.which("whisper-cli") or shutil.which("whisper-cpp") or ""


def whisper_lang():
    lang = os.environ.get("DINGAI_WHISPER_LANG", "zh").strip().lower()
    return lang if lang in LANGS else "zh"


def transcribe(wav_path, lang=None):
    binary = whisper_bin()
    model = os.environ.get("DINGAI_WHISPER_MODEL", "").strip()
    chosen = lang or whisper_lang()
    if chosen not in LANGS:
        chosen = "zh"
    if not binary or not model or not wav_path or not os.path.isfile(wav_path):
        return ""
    proc = subprocess.run(
        [binary, "-m", model, "-f", wav_path, "-l", chosen, "-nt"],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        return ""
    return (proc.stdout or "").strip()
