"""Sprint 1 sandbox entry point for the GPI Document Hub."""

import logging

from server import app, db
from routes.document_delivery import router, set_db

logger = logging.getLogger(__name__)

set_db(db)
app.include_router(router, prefix="/api")


@app.on_event("startup")
async def initialize_sprint1_document_delivery():
    """Initialize preview package storage indexes."""
    set_db(db)
    await db.zetadocs_delivery_packages.create_index(
        "package_id", unique=True, sparse=True
    )
    await db.zetadocs_delivery_packages.create_index(
        "correlation_id", unique=True, sparse=True
    )
    await db.zetadocs_delivery_packages.create_index("request_hash")
    await db.zetadocs_delivery_packages.create_index("status")
    await db.zetadocs_delivery_packages.create_index("created_utc")
    logger.info("Sprint 1 document delivery preflight API initialized")
