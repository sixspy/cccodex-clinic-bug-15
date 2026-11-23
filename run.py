from __future__ import annotations

import os

import cherrypy

from app.main import create_app


def main() -> None:
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "7600"))
    create_app()
    print(f"cc-clinic-lab on http://{host}:{port}/login", flush=True)
    cherrypy.config.update(
        {
            "server.socket_host": host,
            "server.socket_port": port,
            "engine.autoreload.on": False,
            "log.screen": True,
        }
    )
    cherrypy.engine.start()
    cherrypy.engine.block()


if __name__ == "__main__":
    main()
