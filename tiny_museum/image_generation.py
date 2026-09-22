from __future__ import annotations

import base64
import binascii
import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Protocol

from .models import AppConfig


class ImageGenerator(Protocol):
    def generate(self, prompt: str, destination: Path) -> None: ...


class OllamaImageGenerator:
    def __init__(self, base_url: str, model: str, size: str, timeout_seconds: int):
        self.url = f"{base_url.rstrip('/')}/api/generate"
        self.model = model
        self.size = size
        self.timeout_seconds = timeout_seconds

    def generate(self, prompt: str, destination: Path) -> None:
        width, height = (int(value) for value in self.size.split("x", 1))
        payload = json.dumps(
            {
                "model": self.model,
                "prompt": prompt,
                "width": width,
                "height": height,
                "stream": False,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            self.url,
            data=payload,
            headers={"Content-Type": "application/json", "Authorization": "Bearer ollama"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                result = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Ollama image request failed: {exc}") from exc
        try:
            image = base64.b64decode(result["image"], validate=True)
        except (KeyError, TypeError, binascii.Error) as exc:
            raise RuntimeError("Ollama returned an invalid image response") from exc
        if len(image) > 50_000_000 or not image.startswith(b"\x89PNG\r\n\x1a\n"):
            raise RuntimeError("Ollama returned an invalid PNG image")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(image)


def create_image_generator(config: AppConfig) -> ImageGenerator | None:
    settings = config.image_generation
    if not settings.enabled:
        return None
    provider = config.providers[settings.provider]
    return OllamaImageGenerator(provider.base_url, settings.model, settings.size, settings.timeout_seconds)
