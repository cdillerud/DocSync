#!/usr/bin/env python3
"""
GPI Document Hub - Production Fix Script
========================================
Fixes the salesOrders bug where AP Invoices were incorrectly linked to salesOrders endpoint.

DEPLOYMENT:
1. Copy to VM: scp production_fix.py user@your-vm:/opt/gpi-hub/
2. Run: docker cp /opt/gpi-hub/production_fix.py gpi-backend:/tmp/
3. Execute: docker exec gpi-backend python3 /tmp/production_fix.py
4. Restart: docker restart gpi-backend
"""

import re

SERVER_PY = '/app/backend/server.py'

def main():
    print("Reading server.py...")
    with open(SERVER_PY, 'r') as f:
        content = f.read()
    
    # Backup original
    with open(SERVER_PY + '.backup', 'w') as f:
        f.write(content)
    print("Backup created at server.py.backup")
    
    fixes_applied = 0
    
    # Fix 1: Update function signature
    old_sig = 'async def link_document_to_bc(bc_record_id: str, share_link: str, file_name: str, file_content: bytes = None, content_type: str = None):'
    new_sig = 'async def link_document_to_bc(bc_record_id: str, share_link: str, file_name: str, file_content: bytes = None, content_type: str = None, bc_entity: str = "salesOrders"):'
    
    if old_sig in content:
        content = content.replace(old_sig, new_sig)
        fixes_applied += 1
        print("Fix 1: Updated function signature")
    else:
        print("Fix 1: Function signature already updated or not found")
    
    # Fix 2: Update attach_url
    old_attach = 'companies({company_id})/salesOrders({bc_record_id})/documentAttachments"'
    new_attach = 'companies({company_id})/{bc_entity}({bc_record_id})/documentAttachments"'
    
    if old_attach in content:
        content = content.replace(old_attach, new_attach)
        fixes_applied += 1
        print("Fix 2: Updated attach_url")
    else:
        print("Fix 2: attach_url already updated or not found")
    
    # Fix 3: Update content_url
    old_content = 'companies({company_id})/salesOrders({bc_record_id})/documentAttachments({attachment_id})/attachmentContent"'
    new_content = 'companies({company_id})/{bc_entity}({bc_record_id})/documentAttachments({attachment_id})/attachmentContent"'
    
    if old_content in content:
        content = content.replace(old_content, new_content)
        fixes_applied += 1
        print("Fix 3: Updated content_url")
    else:
        print("Fix 3: content_url already updated or not found")
    
    # Fix 4: Update reprocess_document to pass bc_entity
    # Find the section in reprocess_document and add bc_entity
    old_reprocess = '''    # If validation now passes and we have SharePoint info, try to link to BC
    # NOTE: Reprocess does NOT create drafts - only links to existing records
    share_link = doc.get("sharepoint_share_link_url")
    bc_record_id = validation_results.get("bc_record_id")
    
    if validation_results.get("all_passed") and decision in ("auto_link", "auto_create"):
        if share_link and bc_record_id and file_content:
            try:
                link_result = await link_document_to_bc(
                    bc_record_id=bc_record_id,
                    share_link=share_link,
                    file_name=doc["file_name"],
                    file_content=file_content
                )'''
    
    new_reprocess = '''    # If validation now passes and we have SharePoint info, try to link to BC
    # NOTE: Reprocess does NOT create drafts - only links to existing records
    share_link = doc.get("sharepoint_share_link_url")
    bc_record_id = validation_results.get("bc_record_id")
    
    # Get the correct BC entity from job config
    bc_entity = job_configs.get("bc_entity", "salesOrders")
    
    if validation_results.get("all_passed") and decision in ("auto_link", "auto_create"):
        if share_link and bc_record_id and file_content:
            try:
                link_result = await link_document_to_bc(
                    bc_record_id=bc_record_id,
                    share_link=share_link,
                    file_name=doc["file_name"],
                    file_content=file_content,
                    bc_entity=bc_entity
                )'''
    
    if old_reprocess in content:
        content = content.replace(old_reprocess, new_reprocess)
        fixes_applied += 1
        print("Fix 4: Updated reprocess_document to pass bc_entity")
    else:
        print("Fix 4: reprocess_document already updated or pattern not found")
    
    # Write updated content
    with open(SERVER_PY, 'w') as f:
        f.write(content)
    
    print(f"\nTotal fixes applied: {fixes_applied}")
    print("Server.py updated. Restart the backend to apply changes.")
    print("\nTo restore if needed: cp /app/backend/server.py.backup /app/backend/server.py")

if __name__ == '__main__':
    main()
