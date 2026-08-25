"""One-time branch patch: wire mailbox provenance into both AP mail pollers.

This script is intentionally exact-match and fail-closed. It exists only to
apply the parity change to the large email polling module without hand-editing
unrelated code. The CI gate verifies the resulting production file.
"""

from pathlib import Path


path = Path("backend/services/email_polling_service.py")
text = path.read_text(encoding="utf-8")

legacy_old = '''                            # Lazy import to avoid circular dependency
                            from services.document_bytes_intake_service import intake_document_from_bytes
                            resolved_category = normalize_mailbox_category("AP")
                            logger.info(
                                "[Intake:legacy_ap] mailbox=%s configured_category=%s resolved_category=%s filename=%s",
                                EMAIL_POLLING_USER, "AP", resolved_category, filename,
                            )
                            intake_result = await intake_document_from_bytes(
                                file_content=content_bytes, filename=filename,
                                content_type=content_type, source="email_poll",
                                email_id=msg_id, subject=subject, sender=sender,
                                mailbox_category=resolved_category,
                            )
                            doc_id = intake_result.get("document", {}).get("id")
                            await record_mail_intake_log(
'''

legacy_new = '''                            # Lazy imports to avoid circular dependency
                            from services.document_bytes_intake_service import intake_document_from_bytes
                            from services.mailbox_provenance_service import persist_mailbox_provenance
                            resolved_category = normalize_mailbox_category("AP")
                            logger.info(
                                "[Intake:legacy_ap] mailbox=%s configured_category=%s resolved_category=%s filename=%s",
                                EMAIL_POLLING_USER, "AP", resolved_category, filename,
                            )
                            intake_result = await intake_document_from_bytes(
                                file_content=content_bytes, filename=filename,
                                content_type=content_type, source="email_poll",
                                email_id=msg_id, subject=subject, sender=sender,
                                mailbox_category=resolved_category,
                            )
                            doc_id = (
                                intake_result.get("document_id")
                                or intake_result.get("document", {}).get("id")
                            )
                            await persist_mailbox_provenance(
                                db,
                                doc_id,
                                mailbox_address=EMAIL_POLLING_USER,
                                mailbox_id="legacy_ap",
                                mailbox_category=resolved_category,
                                graph_message_id=msg_id,
                                internet_message_id=internet_msg_id,
                                attachment_id=att_id,
                                source="email_poll",
                            )
                            await record_mail_intake_log(
'''

dynamic_old = '''                                # Lazy import to avoid circular dependency
                                from services.document_bytes_intake_service import intake_document_from_bytes
                                resolved_category = normalize_mailbox_category(default_category)
'''

dynamic_new = '''                                # Lazy imports to avoid circular dependency
                                from services.document_bytes_intake_service import intake_document_from_bytes
                                from services.mailbox_provenance_service import persist_mailbox_provenance
                                resolved_category = normalize_mailbox_category(default_category)
'''

dynamic_call_old = '''                                doc_id = (
                                    result.get("document_id")
                                    or result.get("document", {}).get("id")
                                )
                                await record_mail_intake_log(
'''

dynamic_call_new = '''                                doc_id = (
                                    result.get("document_id")
                                    or result.get("document", {}).get("id")
                                )
                                await persist_mailbox_provenance(
                                    db,
                                    doc_id,
                                    mailbox_address=mailbox_address,
                                    mailbox_id=source_id,
                                    mailbox_category=resolved_category,
                                    graph_message_id=msg_id,
                                    internet_message_id=internet_msg_id,
                                    attachment_id=att_id,
                                    source="email",
                                )
                                await record_mail_intake_log(
'''

replacements = [
    (legacy_old, legacy_new, "legacy AP intake provenance"),
    (dynamic_old, dynamic_new, "dynamic intake provenance import"),
    (dynamic_call_old, dynamic_call_new, "dynamic intake provenance write"),
]

for old, new, label in replacements:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly 1 match, found {count}")
    text = text.replace(old, new, 1)

required = [
    "mailbox_address=EMAIL_POLLING_USER",
    "mailbox_address=mailbox_address",
    "internet_message_id=internet_msg_id",
    "persist_mailbox_provenance",
]
for needle in required:
    if needle not in text:
        raise SystemExit(f"post-patch verification missing: {needle}")

path.write_text(text, encoding="utf-8")
print("PASS: mailbox provenance wired into legacy AP and dynamic mailbox intake")
