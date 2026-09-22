from __future__ import annotations

import argparse
import os

from .config import load_config
from .image_sidecar import ensure_image_service
from .models import ProviderConfig
from .server import serve


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Tiny Museum Swarm locally")
    parser.add_argument("--host", help="Bind host (default: config or TINY_MUSEUM_HOST)")
    parser.add_argument("--port", type=int, help="Bind port (default: config or TINY_MUSEUM_PORT)")
    parser.add_argument("--config", help="Path to agent configuration JSON")
    parser.add_argument("--demo", action="store_true", help="Use a deterministic offline provider for UI testing")
    args = parser.parse_args()

    config = load_config(args.config)
    if args.demo:
        config.image_generation.enabled = False
        config.providers["demo"] = ProviderConfig(kind="demo", base_url="demo://local")
        for agent in config.agents.values():
            agent.provider = "demo"
            agent.model = "museum-demo"
    else:
        ensure_image_service(config)
    host = args.host or os.getenv("TINY_MUSEUM_HOST") or str(config.server.get("host", "127.0.0.1"))
    port = args.port or int(os.getenv("TINY_MUSEUM_PORT", str(config.server.get("port", 8765))))
    serve(config, host, port)


if __name__ == "__main__":
    main()
