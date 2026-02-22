"""
GPI Document Hub - Email Service

Provides email sending functionality with a clean interface that can be
swapped between providers (Mock, SendGrid, Microsoft Graph, etc.)

Current implementation: Mock provider that logs emails and stores in MongoDB
for verification during the 14-day shadow pilot.
"""

import os
import logging
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from enum import Enum
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)


class EmailProvider(str, Enum):
    """Supported email providers."""
    MOCK = "mock"
    SENDGRID = "sendgrid"
    MICROSOFT_GRAPH = "microsoft_graph"
    RESEND = "resend"


@dataclass
class EmailMessage:
    """Email message structure."""
    to: List[str]
    subject: str
    html_body: str
    text_body: Optional[str] = None
    attachments: Optional[List[Dict[str, Any]]] = None
    from_address: str = "noreply@gpi-hub.local"
    reply_to: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class EmailResult:
    """Result of an email send operation."""
    success: bool
    message_id: Optional[str] = None
    provider: str = "mock"
    error: Optional[str] = None
    timestamp: str = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now(timezone.utc).isoformat()
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# =============================================================================
# CONFIGURATION
# =============================================================================

# Current provider (can be changed via environment variable)
CURRENT_EMAIL_PROVIDER = EmailProvider(
    os.environ.get("EMAIL_PROVIDER", "mock").lower()
)

# Default sender
DEFAULT_FROM_ADDRESS = os.environ.get(
    "EMAIL_FROM_ADDRESS", 
    "GPI Document Hub <noreply@gpi-hub.local>"
)


# =============================================================================
# MOCK EMAIL PROVIDER
# =============================================================================

class MockEmailProvider:
    """
    Mock email provider for development and testing.
    
    Stores emails in MongoDB collection 'email_logs' for verification.
    Also logs to console for immediate visibility.
    """
    
    def __init__(self, db=None):
        self.db = db
        self._sent_emails = []  # In-memory backup if no DB
    
    async def send(self, message: EmailMessage) -> EmailResult:
        """
        Send an email (mock - stores in DB and logs).
        
        Args:
            message: EmailMessage to send
            
        Returns:
            EmailResult with success status
        """
        import uuid
        
        message_id = f"mock_{uuid.uuid4().hex[:12]}"
        timestamp = datetime.now(timezone.utc).isoformat()
        
        # Build log record
        email_record = {
            "message_id": message_id,
            "provider": "mock",
            "to": message.to,
            "subject": message.subject,
            "from_address": message.from_address,
            "html_body": message.html_body,
            "text_body": message.text_body,
            "attachments": message.attachments,
            "sent_at": timestamp,
            "status": "sent",  # Mock always succeeds
            "environment": os.environ.get("ENVIRONMENT", "development"),
        }
        
        # Log to console
        logger.info(
            f"[MOCK EMAIL] To: {', '.join(message.to)} | "
            f"Subject: {message.subject} | ID: {message_id}"
        )
        
        # Store in memory
        self._sent_emails.append(email_record)
        
        # Store in MongoDB if available
        if self.db is not None:
            try:
                await self.db.email_logs.insert_one(email_record)
                logger.debug(f"Email logged to MongoDB: {message_id}")
            except Exception as e:
                logger.warning(f"Failed to log email to MongoDB: {e}")
        
        return EmailResult(
            success=True,
            message_id=message_id,
            provider="mock",
            timestamp=timestamp
        )
    
    def get_sent_emails(self) -> List[Dict[str, Any]]:
        """Get list of sent emails (in-memory)."""
        return self._sent_emails.copy()
    
    def clear_sent_emails(self):
        """Clear in-memory sent emails (for testing)."""
        self._sent_emails.clear()


# =============================================================================
# FUTURE PROVIDER STUBS
# =============================================================================

class MicrosoftGraphEmailProvider:
    """
    Microsoft Graph API email provider.
    
    TODO: Implement when ready to integrate with Entra ID.
    Will use Microsoft Graph API to send emails via user's mailbox.
    """
    
    def __init__(self, client_id: str, client_secret: str, tenant_id: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self.tenant_id = tenant_id
        raise NotImplementedError("Microsoft Graph provider not yet implemented")
    
    async def send(self, message: EmailMessage) -> EmailResult:
        raise NotImplementedError("Microsoft Graph provider not yet implemented")


# =============================================================================
# EMAIL SERVICE (Main Interface)
# =============================================================================

class EmailService:
    """
    Main email service class providing a unified interface for sending emails.
    
    Usage:
        service = EmailService(db=database)
        result = await service.send_email(
            to=["user@example.com"],
            subject="Test",
            html_body="<h1>Hello</h1>"
        )
    """
    
    def __init__(self, db=None, provider: EmailProvider = None):
        self.db = db
        self.provider_type = provider or CURRENT_EMAIL_PROVIDER
        self._provider = None
    
    def _get_provider(self):
        """Get or create the email provider instance."""
        if self._provider is None:
            if self.provider_type == EmailProvider.MOCK:
                self._provider = MockEmailProvider(db=self.db)
            elif self.provider_type == EmailProvider.MICROSOFT_GRAPH:
                raise NotImplementedError("Microsoft Graph provider not configured")
            elif self.provider_type == EmailProvider.SENDGRID:
                raise NotImplementedError("SendGrid provider not configured")
            elif self.provider_type == EmailProvider.RESEND:
                raise NotImplementedError("Resend provider not configured")
            else:
                # Default to mock
                self._provider = MockEmailProvider(db=self.db)
        return self._provider
    
    async def send_email(
        self,
        to: List[str],
        subject: str,
        html_body: str,
        text_body: Optional[str] = None,
        attachments: Optional[List[Dict[str, Any]]] = None,
        from_address: Optional[str] = None,
        reply_to: Optional[str] = None
    ) -> EmailResult:
        """
        Send an email.
        
        Args:
            to: List of recipient email addresses
            subject: Email subject
            html_body: HTML content of the email
            text_body: Optional plain text version
            attachments: Optional list of attachments
            from_address: Optional sender address (uses default if not provided)
            reply_to: Optional reply-to address
            
        Returns:
            EmailResult with success status and message ID
        """
        message = EmailMessage(
            to=to,
            subject=subject,
            html_body=html_body,
            text_body=text_body,
            attachments=attachments,
            from_address=from_address or DEFAULT_FROM_ADDRESS,
            reply_to=reply_to
        )
        
        provider = self._get_provider()
        return await provider.send(message)
    
    async def get_email_logs(
        self,
        limit: int = 50,
        skip: int = 0,
        subject_filter: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Get email logs from the database.
        
        Args:
            limit: Maximum number of logs to return
            skip: Number of logs to skip (for pagination)
            subject_filter: Optional filter by subject (contains)
            
        Returns:
            List of email log records
        """
        if self.db is None:
            # Return in-memory logs from mock provider
            provider = self._get_provider()
            if isinstance(provider, MockEmailProvider):
                emails = provider.get_sent_emails()
                if subject_filter:
                    emails = [e for e in emails if subject_filter.lower() in e.get("subject", "").lower()]
                return emails[skip:skip + limit]
            return []
        
        # Query MongoDB
        query = {}
        if subject_filter:
            query["subject"] = {"$regex": subject_filter, "$options": "i"}
        
        cursor = self.db.email_logs.find(
            query,
            {"_id": 0}
        ).sort("sent_at", -1).skip(skip).limit(limit)
        
        return await cursor.to_list(limit)


# =============================================================================
# CONVENIENCE FUNCTION
# =============================================================================

# Global service instance (initialized with db in server.py)
_email_service: Optional[EmailService] = None


def get_email_service() -> EmailService:
    """Get the global email service instance."""
    global _email_service
    if _email_service is None:
        _email_service = EmailService()
    return _email_service


def set_email_service(service: EmailService):
    """Set the global email service instance."""
    global _email_service
    _email_service = service


async def send_email(
    to: List[str],
    subject: str,
    html_body: str,
    attachments: Optional[List[Dict[str, Any]]] = None
) -> EmailResult:
    """
    Convenience function to send an email using the global service.
    
    Args:
        to: List of recipient email addresses
        subject: Email subject
        html_body: HTML content
        attachments: Optional attachments
        
    Returns:
        EmailResult
    """
    service = get_email_service()
    return await service.send_email(
        to=to,
        subject=subject,
        html_body=html_body,
        attachments=attachments
    )
