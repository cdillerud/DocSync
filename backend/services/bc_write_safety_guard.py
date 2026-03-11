"""
GPI Document Hub - BC Write Safety Guard

This service ensures that NO write operations are performed against
Production BC until explicitly enabled.

Configuration:
- BC_WRITE_ENABLED: false (default) - blocks all BC writes
- BC_ENVIRONMENT: production - indicates we're targeting production

When writes are blocked:
- Logs event: bc.write_blocked
- Returns blocked response with reason
- Automation state remains "assisted" (not autonomous)
"""

import os
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from enum import Enum

logger = logging.getLogger(__name__)


class WriteBlockReason(str, Enum):
    """Reasons why a BC write was blocked."""
    PRODUCTION_WRITES_DISABLED = "production_writes_disabled"
    PILOT_MODE_ACTIVE = "pilot_mode_active"
    VALIDATION_FAILED = "validation_failed"
    MANUAL_BLOCK = "manual_block"


# Configuration from centralized bc_config
from services.bc_config import (
    BC_WRITE_ENABLED,
    BC_WRITE_ENVIRONMENT,
    BC_READ_ENVIRONMENT,
    check_write_allowed as _check_write,
)

BC_ENVIRONMENT = BC_WRITE_ENVIRONMENT

# Check if we're targeting production for writes
IS_PRODUCTION_ENVIRONMENT = "production" in BC_WRITE_ENVIRONMENT.lower()

logger.info(
    "[BC Write Guard] BC_WRITE_ENABLED=%s, WRITE_ENV=%s, READ_ENV=%s, WRITE_IS_PROD=%s",
    BC_WRITE_ENABLED, BC_WRITE_ENVIRONMENT, BC_READ_ENVIRONMENT, IS_PRODUCTION_ENVIRONMENT
)


class WriteAttemptResult:
    """Result of a write attempt check."""
    
    def __init__(
        self,
        allowed: bool,
        reason: str = None,
        document_id: str = None,
        attempted_action: str = None
    ):
        self.allowed = allowed
        self.reason = reason
        self.document_id = document_id
        self.attempted_action = attempted_action
        self.checked_at = datetime.now(timezone.utc).isoformat()
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "document_id": self.document_id,
            "attempted_action": self.attempted_action,
            "checked_at": self.checked_at
        }


class BCWriteSafetyGuard:
    """
    BC Write Safety Guard - prevents unintended writes to Production BC.
    
    All BC write operations must go through this guard.
    """
    
    def __init__(self, event_service=None):
        self.event_service = event_service
        self.write_enabled = BC_WRITE_ENABLED
        self.is_production = IS_PRODUCTION_ENVIRONMENT
        self.environment = BC_ENVIRONMENT
    
    def is_write_allowed(self) -> bool:
        """Check if BC writes are currently allowed."""
        return self.write_enabled
    
    async def check_write_permission(
        self,
        document_id: str,
        action: str,
        correlation_id: Optional[str] = None
    ) -> WriteAttemptResult:
        """
        Check if a write operation is permitted.
        
        Args:
            document_id: Document being processed
            action: The action being attempted (e.g., "create_purchase_invoice")
            correlation_id: For event correlation
            
        Returns:
            WriteAttemptResult indicating if write is allowed
        """
        # If writes are enabled, allow
        if self.write_enabled:
            logger.debug(
                "[BC Write Guard] Write ALLOWED for doc %s, action: %s",
                document_id[:8] if document_id else "N/A", action
            )
            return WriteAttemptResult(
                allowed=True,
                document_id=document_id,
                attempted_action=action
            )
        
        # Writes blocked
        reason = WriteBlockReason.PRODUCTION_WRITES_DISABLED.value
        
        logger.warning(
            "[BC Write Guard] Write BLOCKED for doc %s, action: %s, reason: %s",
            document_id[:8] if document_id else "N/A", action, reason
        )
        
        # Emit bc.write_blocked event
        if self.event_service:
            try:
                await self.event_service.emit(
                    event_type="bc.write_blocked",
                    document_id=document_id or "system",
                    status="blocked",
                    source_service="bc_write_safety_guard",
                    correlation_id=correlation_id,
                    payload={
                        "reason": reason,
                        "document_id": document_id,
                        "attempted_action": action,
                        "bc_environment": self.environment,
                        "is_production": self.is_production
                    }
                )
            except Exception as e:
                logger.error("[BC Write Guard] Failed to emit event: %s", str(e))
        
        return WriteAttemptResult(
            allowed=False,
            reason=reason,
            document_id=document_id,
            attempted_action=action
        )
    
    async def guard_create_purchase_invoice(
        self,
        document_id: str,
        invoice_data: Dict[str, Any],
        correlation_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Guard wrapper for create_purchase_invoice.
        
        Returns:
            - If allowed: {"allowed": True, "proceed": True}
            - If blocked: {"allowed": False, "reason": "...", "event_emitted": True}
        """
        result = await self.check_write_permission(
            document_id,
            "create_purchase_invoice",
            correlation_id
        )
        
        if result.allowed:
            return {
                "allowed": True,
                "proceed": True
            }
        
        return {
            "allowed": False,
            "reason": result.reason,
            "event_emitted": True,
            "message": f"BC write blocked: {result.reason}. Invoice data prepared but not created.",
            "prepared_data": {
                "vendor_no": invoice_data.get("vendor_no"),
                "vendor_name": invoice_data.get("vendor_name"),
                "invoice_number": invoice_data.get("vendor_invoice_number"),
                "amount": invoice_data.get("total_amount"),
                "bol_number": invoice_data.get("bol_number")
            }
        }
    
    async def guard_post_invoice(
        self,
        document_id: str,
        bc_invoice_id: str,
        correlation_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Guard wrapper for posting an invoice.
        """
        result = await self.check_write_permission(
            document_id,
            "post_purchase_invoice",
            correlation_id
        )
        
        if result.allowed:
            return {"allowed": True, "proceed": True}
        
        return {
            "allowed": False,
            "reason": result.reason,
            "event_emitted": True,
            "message": f"BC post blocked: {result.reason}"
        }
    
    def get_status(self) -> Dict[str, Any]:
        """Get current safety guard status."""
        return {
            "write_enabled": self.write_enabled,
            "environment": self.environment,
            "is_production": self.is_production,
            "status": "enabled" if self.write_enabled else "blocked",
            "message": "BC writes are ALLOWED" if self.write_enabled else "BC writes are BLOCKED (production safety)"
        }


# Global instance
_write_guard: Optional[BCWriteSafetyGuard] = None


def get_write_guard() -> BCWriteSafetyGuard:
    """Get or create the global write guard instance."""
    global _write_guard
    if _write_guard is None:
        _write_guard = BCWriteSafetyGuard()
    return _write_guard


def set_write_guard(event_service=None) -> BCWriteSafetyGuard:
    """Initialize the write guard with event service."""
    global _write_guard
    _write_guard = BCWriteSafetyGuard(event_service=event_service)
    return _write_guard


# Convenience function for use in existing code
async def check_bc_write_allowed(
    document_id: str,
    action: str,
    correlation_id: Optional[str] = None
) -> bool:
    """
    Quick check if BC write is allowed.
    
    Use this in existing code to wrap write operations.
    """
    guard = get_write_guard()
    result = await guard.check_write_permission(document_id, action, correlation_id)
    return result.allowed
