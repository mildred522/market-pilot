from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

from app.api import agent, analysis, dashboard, files, location, operating, pre_open, projects
from app.db.session import init_db


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    init_db()
    yield


app = FastAPI(title="Restaurant Agent API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(projects.router)
app.include_router(dashboard.router)
app.include_router(pre_open.router)
app.include_router(files.router)
app.include_router(operating.router)
app.include_router(analysis.router)
app.include_router(location.router)
app.include_router(agent.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
