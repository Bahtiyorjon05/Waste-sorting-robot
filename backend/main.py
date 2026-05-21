"""
main.py
========
EcoSort AI - application entry point (The Brain).

Builds the FastAPI app, starts the Sense-Think-Act loop on a background
thread, and serves the live dashboard.

Run it (on the Raspberry Pi, from the repo root):

    python -m backend.main

Then on your laptop open a browser at:

    http://<raspberry-pi-ip>:8000        (find the IP with:  hostname -I )

For auto-reload during development you can instead use:

    uvicorn backend.main:create_app --factory --host 0.0.0.0 --port 8000
"""

import argparse
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse

from .config import load_config
from .database import init_db
from .orchestrator import Orchestrator
from .routers import classify, feedback
from .state import SharedState

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(name)-20s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("ecosort")

# ui/index.html lives one directory up from this file (repo root / ui).
_UI_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "ui", "index.html",
)


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------
def create_app(config_path: str = "config.yaml") -> FastAPI:
    """Build and wire up the FastAPI application."""
    config = load_config(config_path)
    init_db(str(config.get("DATABASE_URL", "sqlite:///ecosort.db")))

    shared = SharedState()
    orchestrator = Orchestrator(config, config_path, shared)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # --- startup ---
        orchestrator.start()
        logger.info("=" * 58)
        logger.info("  EcoSort AI is live")
        logger.info("  Open the dashboard at  http://<this-device-ip>:%s",
                    config.get("WEB_PORT", 8000))
        logger.info("=" * 58)
        yield
        # --- shutdown ---
        logger.info("Shutdown requested - stopping the loop...")
        shared.running = False
        orchestrator.join(timeout=6.0)
        logger.info("EcoSort AI stopped cleanly.")

    app = FastAPI(title="EcoSort AI", version="2.0", lifespan=lifespan)
    app.state.shared = shared
    app.state.config = config

    app.include_router(classify.router)
    app.include_router(feedback.router)

    @app.get("/", response_class=HTMLResponse)
    async def dashboard() -> FileResponse:
        """Serve the live monitoring dashboard."""
        return FileResponse(_UI_FILE)

    return app


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="EcoSort AI server")
    parser.add_argument("--config", default="config.yaml",
                        help="Path to config.yaml")
    parser.add_argument("--host", default=None, help="Override WEB_HOST")
    parser.add_argument("--port", type=int, default=None, help="Override WEB_PORT")
    args = parser.parse_args()

    app = create_app(args.config)
    config = app.state.config
    host = args.host or str(config.get("WEB_HOST", "0.0.0.0"))
    port = args.port or int(config.get("WEB_PORT", 8000))

    import uvicorn
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
