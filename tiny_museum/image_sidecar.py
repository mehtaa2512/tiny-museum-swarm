from __future__ import annotations

import atexit
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from .models import AppConfig


ROOT = Path(__file__).resolve().parent.parent
SIDECAR_BINARY = ROOT / "work" / "ollama-0.32.5" / "ollama"
SIDECAR_LOG = ROOT / ".tiny-museum" / "image-ollama.log"
_process: subprocess.Popen[bytes] | None = None
_log = None


def ensure_image_service(config: AppConfig) -> None:
    global _process, _log
    settings = config.image_generation
    if not settings.enabled:
        return
    provider = config.providers[settings.provider]
    parsed = urlparse(provider.base_url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"} or not parsed.port:
        raise RuntimeError("The image service must use an explicit local HTTP port")
    if _service_version(provider.base_url) == "0.32.5":
        return
    if not SIDECAR_BINARY.is_file():
        raise RuntimeError(f"Missing image sidecar: {SIDECAR_BINARY}")
    SIDECAR_LOG.parent.mkdir(parents=True, exist_ok=True)
    _log = SIDECAR_LOG.open("ab")
    environment = os.environ.copy()
    environment.update(
        OLLAMA_HOST=parsed.netloc,
        OLLAMA_MAX_LOADED_MODELS="1",
        OLLAMA_NUM_PARALLEL="1",
    )
    _process = subprocess.Popen(
        [str(SIDECAR_BINARY), "serve"],
        cwd=SIDECAR_BINARY.parent,
        env=environment,
        stdout=_log,
        stderr=subprocess.STDOUT,
    )
    atexit.register(_stop_sidecar)
    for _ in range(40):
        if _service_version(provider.base_url) == "0.32.5":
            return
        if _process.poll() is not None:
            break
        time.sleep(0.25)
    raise RuntimeError(f"Image sidecar did not start; see {SIDECAR_LOG}")


def _service_version(base_url: str) -> str | None:
    try:
        with urllib.request.urlopen(f"{base_url.rstrip('/')}/api/version", timeout=0.5) as response:
            return str(json.loads(response.read().decode("utf-8")).get("version"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return None


def _stop_sidecar() -> None:
    if _process is not None and _process.poll() is None:
        _process.terminate()
    if _log is not None:
        _log.close()
