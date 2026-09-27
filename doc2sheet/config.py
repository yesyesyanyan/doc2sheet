"""Runtime settings, read from environment variables (and an optional .env file)."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

HF_ROUTER_URL = "https://router.huggingface.co/v1"

# Vision models served through Hugging Face Inference Providers. Availability
# changes over time — any image-capable chat model id works.
SUGGESTED_MODELS = [
    "google/gemma-4-31B-it",
    "Qwen/Qwen3.6-35B-A3B",
    "Qwen/Qwen3-VL-8B-Instruct",
]
DEFAULT_MODEL = SUGGESTED_MODELS[0]


@dataclass(frozen=True)
class Settings:
    base_url: str = HF_ROUTER_URL
    api_key: str | None = None
    model: str = DEFAULT_MODEL
    json_mode: str = "auto"  # auto | schema | object | off
    max_pages: int = 3
    timeout: float = 120.0
    max_image_side: int = 1600  # lower it (e.g. 1024) for small local models with short context
    reasoning_effort: str | None = None  # e.g. "none" to disable thinking on Ollama

    @classmethod
    def from_env(cls, env_file: str | Path | None = ".env") -> Settings:
        if env_file:
            load_dotenv(env_file)
        return cls(
            base_url=os.getenv("DOC2SHEET_BASE_URL", HF_ROUTER_URL),
            api_key=(os.getenv("DOC2SHEET_API_KEY") or os.getenv("HF_TOKEN") or os.getenv("OPENAI_API_KEY") or None),
            model=os.getenv("DOC2SHEET_MODEL", DEFAULT_MODEL),
            json_mode=os.getenv("DOC2SHEET_JSON_MODE", "auto"),
            max_pages=int(os.getenv("DOC2SHEET_MAX_PAGES", "3")),
            timeout=float(os.getenv("DOC2SHEET_TIMEOUT", "120")),
            max_image_side=int(os.getenv("DOC2SHEET_MAX_IMAGE_SIDE", "1600")),
            reasoning_effort=os.getenv("DOC2SHEET_REASONING_EFFORT") or None,
        )


def load_dotenv(path: str | Path) -> None:
    """Minimal .env loader: KEY=VALUE lines, never overrides real env vars."""
    path = Path(path)
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.removeprefix("export ").strip()
        value = value.strip()
        if value[:1] in ('"', "'"):
            value = value[1:].split(value[0], 1)[0]  # quoted: keep everything inside the quotes
        else:
            value = re.split(r"\s+#", value, maxsplit=1)[0].strip()  # drop inline comments
        if key and key not in os.environ:
            os.environ[key] = value
