"""Entry point: `printbridge` starts the web UI."""
from __future__ import annotations

import uvicorn

from .config import Config
from .web.app import create_app


def main() -> None:
    config = Config.load()
    app = create_app(config)
    uvicorn.run(app, host=config.web.host, port=config.web.port)


if __name__ == "__main__":
    main()
