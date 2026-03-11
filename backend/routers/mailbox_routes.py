"""
GPI Document Hub — Mailbox Settings Router (Thin Wrapper)

Extracts /settings/mailbox-sources/* routes from server.py during modular refactor.
"""

from fastapi import APIRouter
import server

router = APIRouter(prefix="/settings", tags=["Mailbox Settings"])

# GET /settings/mailbox-sources
router.add_api_route("/mailbox-sources", server.list_mailbox_sources, methods=["GET"])

# GET /settings/mailbox-sources/polling-status
router.add_api_route("/mailbox-sources/polling-status", server.get_mailbox_polling_status, methods=["GET"])

# GET /settings/mailbox-sources/{mailbox_id}
router.add_api_route("/mailbox-sources/{mailbox_id}", server.get_mailbox_source, methods=["GET"])

# POST /settings/mailbox-sources
router.add_api_route("/mailbox-sources", server.create_mailbox_source, methods=["POST"])

# PUT /settings/mailbox-sources/{mailbox_id}
router.add_api_route("/mailbox-sources/{mailbox_id}", server.update_mailbox_source, methods=["PUT"])

# DELETE /settings/mailbox-sources/{mailbox_id}
router.add_api_route("/mailbox-sources/{mailbox_id}", server.delete_mailbox_source, methods=["DELETE"])

# POST /settings/mailbox-sources/{mailbox_id}/test-connection
router.add_api_route("/mailbox-sources/{mailbox_id}/test-connection", server.test_mailbox_connection, methods=["POST"])

# POST /settings/mailbox-sources/{mailbox_id}/poll-now
router.add_api_route("/mailbox-sources/{mailbox_id}/poll-now", server.poll_mailbox_now, methods=["POST"])
