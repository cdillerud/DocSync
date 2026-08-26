"""One-time exact patch: use null, not blank text, for absent SharePoint table ID."""

from pathlib import Path

path = Path("backend/services/sharepoint_service.py")
text = path.read_text(encoding="utf-8")

old = '''    source_table_id = ""\n    source_document_type = ""\n'''
new = '''    # Keep the payload compatible with either a SharePoint Number or Text\n    # column. An absent BC table is null, never a blank string masquerading as\n    # a number. Resolved table IDs below remain integers.\n    source_table_id = None\n    source_document_type = ""\n'''

if text.count(old) != 1:
    raise SystemExit(f"source table initializer: expected 1 match, found {text.count(old)}")
text = text.replace(old, new, 1)

if 'source_table_id = None' not in text:
    raise SystemExit("post-patch verification failed")

path.write_text(text, encoding="utf-8")
print("PASS: absent SharePoint source table ID is now null")

# Triggered after workflow creation so GitHub evaluates the one-time patch.
