from __future__ import annotations

from app import app
from commercial_routes import router as commercial_router


app.include_router(commercial_router)
