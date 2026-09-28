"""Run the source checkout with bounded reload watching."""
import os
from pathlib import Path

import uvicorn


if __name__ == "__main__":
    backend = Path(__file__).resolve().parent
    os.chdir(backend)
    os.environ["MARKET_PILOT_WORKSPACE"] = str(backend.parent)
    uvicorn.run(
        "app.main:app", host="127.0.0.1", port=8000,
        reload=True, reload_dirs=[str(backend / "app")],
    )
