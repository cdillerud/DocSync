"""One-time exact patch: enforce SharePoint production write protection."""

from pathlib import Path

path = Path("backend/services/sharepoint_service.py")
text = path.read_text(encoding="utf-8")


def replace_once(old: str, new: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"expected exactly one anchor, found {count}: {old[:120]!r}")
    text = text.replace(old, new, 1)


replace_once(
    '''logger = logging.getLogger(__name__)\n\nDEMO_MODE = os.environ.get("DEMO_MODE", "true").lower() == "true"\n''',
    '''logger = logging.getLogger(__name__)\n\nfrom services.sharepoint_write_guard_service import check_sharepoint_write_protection\n\nDEMO_MODE = os.environ.get("DEMO_MODE", "true").lower() == "true"\n''',
)

replace_once(
    '''async def upload_to_sharepoint(file_content: bytes, file_name: str, folder: str):\n    folder_for_url = str(folder or "").strip("/")\n''',
    '''async def upload_to_sharepoint(file_content: bytes, file_name: str, folder: str):\n    check_sharepoint_write_protection(\n        "upload_to_sharepoint",\n        target=SHAREPOINT_TARGET,\n        site_path=SHAREPOINT_SITE_PATH,\n    )\n    folder_for_url = str(folder or "").strip("/")\n''',
)

replace_once(
    '''async def create_sharing_link(drive_id: str, item_id: str):\n    if DEMO_MODE or not GRAPH_CLIENT_ID:\n''',
    '''async def create_sharing_link(drive_id: str, item_id: str):\n    check_sharepoint_write_protection(\n        "create_sharing_link",\n        target=SHAREPOINT_TARGET,\n        site_path=SHAREPOINT_SITE_PATH,\n    )\n    if DEMO_MODE or not GRAPH_CLIENT_ID:\n''',
)

replace_once(
    '''    This is part of delivery, not best-effort enrichment. A real Graph failure is\n    raised so the caller cannot report a successful, import-ready delivery when\n    the file exists but its parity metadata does not.\n    """\n    if DEMO_MODE or not GRAPH_CLIENT_ID:\n''',
    '''    This is part of delivery, not best-effort enrichment. A real Graph failure is\n    raised so the caller cannot report a successful, import-ready delivery when\n    the file exists but its parity metadata does not.\n    """\n    check_sharepoint_write_protection(\n        "write_sharepoint_parity_metadata",\n        target=SHAREPOINT_TARGET,\n        site_path=SHAREPOINT_SITE_PATH,\n    )\n    if DEMO_MODE or not GRAPH_CLIENT_ID:\n''',
)

replace_once(
    '''async def ensure_sharepoint_folder_exists(folder_path: str) -> bool:\n    """Create the requested folder hierarchy when it does not already exist."""\n    normalized_path = str(folder_path or "").strip("/")\n''',
    '''async def ensure_sharepoint_folder_exists(folder_path: str) -> bool:\n    """Create the requested folder hierarchy when it does not already exist."""\n    check_sharepoint_write_protection(\n        "ensure_sharepoint_folder_exists",\n        target=SHAREPOINT_TARGET,\n        site_path=SHAREPOINT_SITE_PATH,\n    )\n    normalized_path = str(folder_path or "").strip("/")\n''',
)

for operation in (
    "upload_to_sharepoint",
    "create_sharing_link",
    "write_sharepoint_parity_metadata",
    "ensure_sharepoint_folder_exists",
):
    needle = f'check_sharepoint_write_protection(\\n        "{operation}"'
    if needle not in text.replace("\r\n", "\n"):
        raise SystemExit(f"missing post-patch production guard for {operation}")

path.write_text(text, encoding="utf-8")
print("PASS: SharePoint production write guard patched into side-effect boundaries")
