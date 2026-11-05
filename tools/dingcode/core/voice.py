"""Local speech-to-text through a whisper.cpp binary. No package and no network.

Set DINGCODE_WHISPER to the whisper-cli executable and DINGCODE_WHISPER_MODEL to a
ggml model. DINGCODE_WHISPER_LANG is zh, en, or vi.
"""

import os
import shutil
import subprocess

from core.paths import env

LANGS = ("zh", "en", "vi")


def whisper_bin():
    binary = (env("DINGCODE_WHISPER", "DINGAI_WHISPER", default="") or "").strip()
    if binary:
        return binary
    return shutil.which("whisper-cli") or shutil.which("whisper-cpp") or ""


def whisper_lang():
    lang = (env("DINGCODE_WHISPER_LANG", "DINGAI_WHISPER_LANG", default="zh") or "zh").strip().lower()
    return lang if lang in LANGS else "zh"


def transcribe(wav_path, lang=None):
    binary = whisper_bin()
    model = (env("DINGCODE_WHISPER_MODEL", "DINGAI_WHISPER_MODEL", default="") or "").strip()
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
