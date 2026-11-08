"""Read optional server credentials without returning them to the browser."""

import os
from pathlib import Path


def openrouter_key() -> str:
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if key:
        return key
    filename = os.environ.get("OPENROUTER_API_KEY_FILE", "").strip()
    if filename:
        try:
            return Path(filename).read_text(encoding="utf-8").strip()
        except OSError:
            return ""
    return ""
