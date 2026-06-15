"""Sprint 1 sandbox entry point."""

from server import app, db
from routes.document_delivery import router, set_db

set_db(db)
app.include_router(router, prefix="/api")
