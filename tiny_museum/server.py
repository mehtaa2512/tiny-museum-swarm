from __future__ import annotations

import json
import mimetypes
import urllib.error
import urllib.request
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .config import apply_runtime_agent_config, public_config
from .models import AppConfig
from .run import RunRegistry


STATIC_DIR = Path(__file__).resolve().parent / "static"
RUNS_DIR = Path(__file__).resolve().parent.parent / ".tiny-museum" / "runs"


class MuseumServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], config: AppConfig):
        super().__init__(address, MuseumHandler)
        self.config = config
        self.registry = RunRegistry(config, RUNS_DIR)


class MuseumHandler(BaseHTTPRequestHandler):
    server: MuseumServer
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/":
            self._serve_file("index.html")
            return
        if path.startswith("/static/"):
            self._serve_file(path.removeprefix("/static/"))
            return
        if path == "/api/config":
            self._json(public_config(self.server.config))
            return
        if path == "/api/health":
            self._json(self._health())
            return
        parts = path.strip("/").split("/")
        if len(parts) == 4 and parts[:2] == ["api", "runs"] and parts[3] == "image":
            run = self.server.registry.get(parts[2])
            if not run or not run.image_path or not run.image_path.is_file():
                self._error(HTTPStatus.NOT_FOUND, "Image not available")
                return
            self._serve_image(run.image_path)
            return
        if len(parts) == 3 and parts[:2] == ["api", "runs"]:
            run = self.server.registry.get(parts[2])
            if not run:
                self._error(HTTPStatus.NOT_FOUND, "Unknown run")
                return
            self._json(run.snapshot())
            return
        if len(parts) == 4 and parts[:2] == ["api", "runs"] and parts[3] == "events":
            run = self.server.registry.get(parts[2])
            if not run:
                self._error(HTTPStatus.NOT_FOUND, "Unknown run")
                return
            self._events(run)
            return
        self._error(HTTPStatus.NOT_FOUND, "Not found")

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            body = self._read_json()
            if path == "/api/runs":
                run = self.server.registry.create(str(body.get("topic", "")))
                self._json({"id": run.id, "status": run.status}, status=HTTPStatus.ACCEPTED)
                return
            if path == "/api/config":
                apply_runtime_agent_config(self.server.config, body.get("agents", {}))
                self._json(public_config(self.server.config))
                return
            parts = path.strip("/").split("/")
            if len(parts) == 4 and parts[:2] == ["api", "runs"] and parts[3] == "cancel":
                run = self.server.registry.get(parts[2])
                if not run:
                    self._error(HTTPStatus.NOT_FOUND, "Unknown run")
                    return
                run.cancel()
                self._json({"status": "cancellation_requested"}, status=HTTPStatus.ACCEPTED)
                return
            self._error(HTTPStatus.NOT_FOUND, "Not found")
        except (ValueError, json.JSONDecodeError) as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc))

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length > 1_000_000:
            raise ValueError("Request is too large")
        if not length:
            return {}
        value = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("JSON body must be an object")
        return value

    def _serve_file(self, name: str) -> None:
        if name not in {"index.html", "app.js", "styles.css"}:
            self._error(HTTPStatus.NOT_FOUND, "Not found")
            return
        path = STATIC_DIR / name
        data = path.read_bytes()
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def _json(self, value: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def _serve_image(self, path: Path) -> None:
        data = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def _error(self, status: HTTPStatus, message: str) -> None:
        self._json({"error": message}, status=status)

    def _events(self, run) -> None:
        try:
            cursor = int(self.headers.get("Last-Event-ID", "0"))
        except ValueError:
            cursor = 0
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        try:
            while True:
                with run.condition:
                    pending = [event for event in run.events if event.id > cursor]
                    terminal = run.status in {"completed", "cancelled", "stopped"}
                    if not pending and not terminal:
                        run.condition.wait(timeout=10)
                        pending = [event for event in run.events if event.id > cursor]
                        terminal = run.status in {"completed", "cancelled", "stopped"}
                for event in pending:
                    payload = json.dumps(event.to_dict(), ensure_ascii=False)
                    self.wfile.write(f"id: {event.id}\nevent: swarm\ndata: {payload}\n\n".encode("utf-8"))
                    self.wfile.flush()
                    cursor = event.id
                if terminal and cursor >= len(run.events):
                    return
                if not pending:
                    self.wfile.write(b": keep-alive\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            return

    def _health(self) -> dict[str, Any]:
        providers: dict[str, Any] = {}
        for name, config in self.server.config.providers.items():
            if config.kind == "demo":
                providers[name] = {"status": "ready", "detail": "offline deterministic demo"}
                continue
            if config.kind not in {"ollama", "ollama_image"}:
                providers[name] = {"status": "configured", "detail": "not probed to avoid external requests"}
                continue
            try:
                with urllib.request.urlopen(f"{config.base_url.rstrip('/')}/api/tags", timeout=2) as response:
                    data = json.loads(response.read().decode("utf-8"))
                providers[name] = {
                    "status": "ready",
                    "models": [model.get("name") for model in data.get("models", [])],
                }
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                providers[name] = {"status": "unavailable", "detail": str(exc)}
        return {"status": "ok", "providers": providers}

    def log_message(self, format: str, *args: Any) -> None:
        if self.path != "/api/health":
            super().log_message(format, *args)


def serve(config: AppConfig, host: str, port: int) -> None:
    server = MuseumServer((host, port), config)
    print(f"Tiny Museum Swarm is open at http://{host}:{port}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
