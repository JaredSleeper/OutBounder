from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI

from src import worker
from src.api import health, lists, targets
from src.auth import require_user
from src.db import close_db, init_db
from src.web import routes as web_routes


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    worker.start()
    yield
    await worker.stop()
    await close_db()


app = FastAPI(
    title="Outbounder",
    description="Rough list of people in → research-ready outbound table out",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(health.router)
app.include_router(web_routes.router, tags=["web"])
web_routes.mount_static(app)

auth = [Depends(require_user)]
app.include_router(lists.router, prefix="/api/lists", dependencies=auth)
app.include_router(targets.router, prefix="/api/targets", dependencies=auth)
