"""Run the source checkout with bounded reload watching."""
import os
from pathlib import Path

import uvicorn


if __name__ == "__main__":
    backend = Path(__file__).resolve().parent
    os.chdir(backend)
    os.environ["MARKET_PILOT_WORKSPACE"] = str(backend.parent)
    host = os.getenv("MARKET_PILOT_API_HOST", "127.0.0.1")
    port = int(os.getenv("MARKET_PILOT_API_PORT", "8000"))
    uvicorn.run(
        "app.main:app", host=host, port=port,
        reload=True, reload_dirs=[str(backend / "app")],
    )
