"""
Raw-bytes document intake service seam.

The authoritative implementation temporarily remains in
services.document_handlers while callers migrate to this dedicated service
surface. A follow-on body move will invert this import and leave
document_handlers as the compatibility facade.
"""

from services.document_handlers import intake_document_from_bytes

__all__ = ["intake_document_from_bytes"]
