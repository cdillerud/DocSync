"""
SharePoint Migration Service for GPI Document Hub

This service handles the discovery, classification, and migration of files
from the OneGamer SharePoint site to the One_Gamer-Flat-Test site.

Key features:
1. Discovery: Enumerate files from source SharePoint folder
2. Classification: Use AI to infer metadata for each file
3. Migration: Copy files to destination with metadata columns
"""

import os
import logging
import httpx
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)

# Configuration from environment
TENANT_ID = os.environ.get('TENANT_ID', '')
GRAPH_CLIENT_ID = os.environ.get('GRAPH_CLIENT_ID', '')
GRAPH_CLIENT_SECRET = os.environ.get('GRAPH_CLIENT_SECRET', '')

# Default source and destination for the POC
DEFAULT_SOURCE_SITE = "https://gamerpackaging1.sharepoint.com/sites/OneGamer"
DEFAULT_SOURCE_LIBRARY = "Documents"
DEFAULT_SOURCE_FOLDER = "Customer Relations"

DEFAULT_TARGET_SITE = "https://gamerpackaging1.sharepoint.com/sites/One_Gamer-Flat-Test"
DEFAULT_TARGET_LIBRARY = "Documents"

# Required columns in destination library
REQUIRED_COLUMNS = [
    {"name": "DocType", "type": "text"},
    {"name": "Department", "type": "text"},
    {"name": "CustomerName", "type": "text"},
    {"name": "VendorName", "type": "text"},
    {"name": "ProjectOrPartNumber", "type": "text"},
    {"name": "DocumentDate", "type": "dateTime"},
    {"name": "RetentionCategory", "type": "text"},
    {"name": "LegacyPath", "type": "text"},
    {"name": "LegacyUrl", "type": "text"},
]

# Classification confidence threshold
CONFIDENCE_THRESHOLD = 0.85


@dataclass
class MigrationCandidate:
    """Represents a file candidate for migration."""
    id: str
    source_site_url: str
    source_library_name: str
    source_item_id: str
    source_drive_id: str
    file_name: str
    legacy_path: str
    legacy_url: str
    status: str  # discovered, classified, ready_for_migration, migrated, error
    
    # Folder tree classification (from CSV lookup)
    level1: Optional[str] = None  # Department
    level2: Optional[str] = None  # Customer/Category
    level3: Optional[str] = None  # Sub-category
    level4: Optional[str] = None
    level5: Optional[str] = None
    classification_source: Optional[str] = None  # 'folder_tree', 'ai', 'hybrid'
    
    # AI metadata fields
    doc_type: Optional[str] = None
    department: Optional[str] = None
    customer_name: Optional[str] = None
    vendor_name: Optional[str] = None
    project_or_part_number: Optional[str] = None
    document_date: Optional[str] = None
    retention_category: Optional[str] = None
    classification_confidence: Optional[float] = None
    classification_method: Optional[str] = None
    
    # Migration result fields
    target_site_url: Optional[str] = None
    target_library_name: Optional[str] = None
    target_item_id: Optional[str] = None
    target_url: Optional[str] = None
    migration_timestamp: Optional[str] = None
    migration_error: Optional[str] = None
    
    # Timestamps
    created_utc: Optional[str] = None
    updated_utc: Optional[str] = None
    
    def to_dict(self) -> Dict:
        return asdict(self)


class SharePointMigrationService:
    """Service for SharePoint file migration with AI-powered metadata inference."""
    
    def __init__(self, db):
        self.db = db
        self.collection = db.migration_candidates
        self.folder_classifications = db.folder_classifications
        self._token_cache = {}
    
    async def _lookup_folder_classification(self, file_name: str, folder_path: str) -> Optional[Dict]:
        """
        Lookup classification from the imported folder tree CSV.
        Returns the classification record if found.
        """
        # Try exact match on relative_path first
        record = await self.folder_classifications.find_one(
            {"file_name": file_name},
            {"_id": 0}
        )
        
        if record and record.get("level1"):
            return record
        
        # Try matching by folder path
        if folder_path:
            # Look for any file in the same folder path to get the classification
            record = await self.folder_classifications.find_one(
                {"folder_path": {"$regex": f"^{folder_path}", "$options": "i"}},
                {"_id": 0}
            )
            if record:
                return record
        
        return None
    
    def _map_folder_to_metadata(self, classification: Dict) -> Dict:
        """
        Map folder tree levels to document metadata fields.
        
        Level1 = Department (Customer Relations, Marketing, General, etc.)
        Level2 = Customer/Sub-department (Duke Cannon, Manufacturers - Vendors, etc.)
        Level3 = Document category (Spec Sheets, Art Work Files, etc.)
        """
        metadata = {
            "level1": classification.get("level1"),
            "level2": classification.get("level2"),
            "level3": classification.get("level3"),
            "level4": classification.get("level4"),
            "level5": classification.get("level5"),
        }
        
        level1 = classification.get("level1", "") or ""
        level2 = classification.get("level2", "") or ""
        level3 = classification.get("level3", "") or ""
        
        # Map Level1 to Department
        department_map = {
            "Customer Relations": "CustomerRelations",
            "Marketing": "Marketing",
            "Sales": "Sales",
            "General": "General",
            "Custom Projects": "CustomProjects",
            "HR Programs and Benefits": "HR",
            "Supplier Relations": "SupplierRelations",
            "Product Knowledge": "ProductKnowledge",
        }
        metadata["department"] = department_map.get(level1, level1 or "Unknown")
        
        # Level2 often contains customer name
        if level1 == "Customer Relations" and level2:
            metadata["customer_name"] = level2
        elif "Manufacturers" in level2 or "Vendors" in level2:
            # This is supplier-related
            if level3:
                metadata["vendor_name"] = level3
        
        # Infer doc_type from folder structure
        doc_type = "unknown"
        all_levels = f"{level1}/{level2}/{level3}/{classification.get('level4', '')}".lower()
        
        if "spec" in all_levels or "specification" in all_levels:
            doc_type = "spec_sheet"
        elif "art work" in all_levels or "artwork" in all_levels:
            doc_type = "artwork"
        elif "quote" in all_levels:
            doc_type = "quote"
        elif "contract" in all_levels or "agreement" in all_levels:
            doc_type = "contract"
        elif "invoice" in all_levels:
            doc_type = "invoice"
        elif "po" in all_levels or "purchase order" in all_levels:
            doc_type = "po"
        elif "sop" in all_levels or "procedure" in all_levels:
            doc_type = "sop"
        elif "marketing" in all_levels:
            doc_type = "marketing"
        elif "catalog" in all_levels:
            doc_type = "catalog"
        
        metadata["doc_type"] = doc_type
        
        # Set retention based on department
        retention_map = {
            "CustomerRelations": "CustomerComm_LongTerm",
            "Finance": "Accounting_7yrs",
            "HR": "Legal_10yrs",
            "Sales": "CustomerComm_LongTerm",
        }
        metadata["retention_category"] = retention_map.get(metadata["department"], "WorkingDoc_2yrs")
        
        return metadata
        
    async def _get_graph_token(self) -> str:
        """Get Microsoft Graph API token."""
        cache_key = "graph_token"
        cached = self._token_cache.get(cache_key)
        if cached and cached.get("expires_at", 0) > datetime.now().timestamp():
            return cached["token"]
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": GRAPH_CLIENT_ID,
                    "client_secret": GRAPH_CLIENT_SECRET,
                    "scope": "https://graph.microsoft.com/.default"
                }
            )
            if resp.status_code != 200:
                raise Exception(f"Failed to get Graph token: {resp.status_code} - {resp.text}")
            
            data = resp.json()
            token = data["access_token"]
            expires_in = data.get("expires_in", 3600)
            
            self._token_cache[cache_key] = {
                "token": token,
                "expires_at": datetime.now().timestamp() + expires_in - 60
            }
            return token
    
    async def _get_site_id(self, site_url: str, token: str) -> str:
        """Get SharePoint site ID from site URL."""
        # Parse site URL to get hostname and path
        # e.g., https://gamerpackaging1.sharepoint.com/sites/OneGamer
        parts = site_url.replace("https://", "").split("/sites/")
        hostname = parts[0]
        site_path = f"/sites/{parts[1]}" if len(parts) > 1 else ""
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"https://graph.microsoft.com/v1.0/sites/{hostname}:{site_path}:",
                headers={"Authorization": f"Bearer {token}"}
            )
            if resp.status_code != 200:
                raise Exception(f"Failed to get site ID for {site_url}: {resp.status_code} - {resp.text[:500]}")
            return resp.json()["id"]
    
    async def _get_drive_id(self, site_id: str, library_name: str, token: str) -> str:
        """Get drive ID for a document library."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"https://graph.microsoft.com/v1.0/sites/{site_id}/drives",
                headers={"Authorization": f"Bearer {token}"}
            )
            if resp.status_code != 200:
                raise Exception(f"Failed to get drives: {resp.status_code}")
            
            drives = resp.json().get("value", [])
            for drive in drives:
                if drive.get("name") == library_name:
                    return drive["id"]
            
            # Try to match by removing spaces or case-insensitive
            for drive in drives:
                if drive.get("name", "").lower() == library_name.lower():
                    return drive["id"]
            
            raise Exception(f"Drive '{library_name}' not found. Available: {[d['name'] for d in drives]}")
    
    async def _list_files_in_folder(
        self, 
        site_url: str, 
        library_name: str, 
        folder_path: str,
        token: str,
        recursive: bool = True
    ) -> List[Dict]:
        """List all files in a SharePoint folder, optionally recursively."""
        site_id = await self._get_site_id(site_url, token)
        drive_id = await self._get_drive_id(site_id, library_name, token)
        
        files = []
        folders_to_process = [folder_path]
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            while folders_to_process:
                current_folder = folders_to_process.pop(0)
                encoded_path = current_folder.replace(" ", "%20")
                
                # List items in the folder
                url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root:/{encoded_path}:/children"
                
                while url:
                    resp = await client.get(url, headers={"Authorization": f"Bearer {token}"})
                    if resp.status_code == 404:
                        logger.warning(f"Folder not found: {current_folder}")
                        break
                    if resp.status_code != 200:
                        raise Exception(f"Failed to list files: {resp.status_code} - {resp.text[:500]}")
                    
                    data = resp.json()
                    for item in data.get("value", []):
                        if "file" in item:
                            # Calculate the relative path from the root folder
                            rel_path = current_folder
                            files.append({
                                "id": item["id"],
                                "name": item["name"],
                                "size": item.get("size", 0),
                                "web_url": item.get("webUrl", ""),
                                "created_datetime": item.get("createdDateTime"),
                                "last_modified": item.get("lastModifiedDateTime"),
                                "drive_id": drive_id,
                                "folder_path": current_folder
                            })
                        elif "folder" in item and recursive:
                            # Add subfolder to process
                            subfolder_path = f"{current_folder}/{item['name']}"
                            folders_to_process.append(subfolder_path)
                    
                    # Handle pagination
                    url = data.get("@odata.nextLink")
        
        return files
    
    async def discover_candidates(
        self,
        source_site_url: str = DEFAULT_SOURCE_SITE,
        source_library_name: str = DEFAULT_SOURCE_LIBRARY,
        source_folder_path: str = DEFAULT_SOURCE_FOLDER
    ) -> Dict[str, int]:
        """
        Discover files in the source SharePoint folder and create migration candidates.
        
        Returns:
            Dict with total_discovered, new_candidates, existing_candidates counts
        """
        logger.info(f"Discovering files in {source_site_url}/{source_library_name}/{source_folder_path}")
        
        token = await self._get_graph_token()
        files = await self._list_files_in_folder(
            source_site_url, source_library_name, source_folder_path, token
        )
        
        new_count = 0
        existing_count = 0
        now = datetime.now(timezone.utc).isoformat()
        
        for file_info in files:
            source_item_id = file_info["id"]
            
            # Check if candidate already exists
            existing = await self.collection.find_one({"source_item_id": source_item_id})
            
            # Build legacy path and URL
            folder_in_lib = file_info.get("folder_path", source_folder_path)
            legacy_path = f"/{source_library_name}/{folder_in_lib}/{file_info['name']}"
            legacy_url = file_info["web_url"]
            
            candidate_data = {
                "source_site_url": source_site_url,
                "source_library_name": source_library_name,
                "source_item_id": source_item_id,
                "source_drive_id": file_info["drive_id"],
                "file_name": file_info["name"],
                "legacy_path": legacy_path,
                "legacy_url": legacy_url,
                "updated_utc": now
            }
            
            if existing:
                # Update existing record
                await self.collection.update_one(
                    {"source_item_id": source_item_id},
                    {"$set": candidate_data}
                )
                existing_count += 1
            else:
                # Create new candidate
                candidate_data.update({
                    "id": str(uuid.uuid4()),
                    "status": "discovered",
                    "created_utc": now,
                    # Initialize folder tree levels
                    "level1": None,
                    "level2": None,
                    "level3": None,
                    "level4": None,
                    "level5": None,
                    "classification_source": None,
                    # Initialize metadata fields as None
                    "doc_type": None,
                    "department": None,
                    "customer_name": None,
                    "vendor_name": None,
                    "project_or_part_number": None,
                    "document_date": None,
                    "retention_category": None,
                    "classification_confidence": None,
                    "classification_method": None,
                    "target_site_url": None,
                    "target_library_name": None,
                    "target_item_id": None,
                    "target_url": None,
                    "migration_timestamp": None,
                    "migration_error": None
                })
                
                # Lookup folder classification from imported CSV
                folder_class = await self._lookup_folder_classification(
                    file_info["name"],
                    folder_in_lib
                )
                
                if folder_class:
                    # Pre-populate from folder tree
                    metadata = self._map_folder_to_metadata(folder_class)
                    candidate_data.update({
                        "level1": folder_class.get("level1"),
                        "level2": folder_class.get("level2"),
                        "level3": folder_class.get("level3"),
                        "level4": folder_class.get("level4"),
                        "level5": folder_class.get("level5"),
                        "classification_source": "folder_tree",
                        "doc_type": metadata.get("doc_type"),
                        "department": metadata.get("department"),
                        "customer_name": metadata.get("customer_name"),
                        "vendor_name": metadata.get("vendor_name"),
                        "retention_category": metadata.get("retention_category"),
                        "classification_confidence": 0.9,  # High confidence from folder tree
                        "classification_method": "folder_tree_lookup",
                    })
                
                await self.collection.insert_one(candidate_data)
                new_count += 1
        
        total = len(files)
        logger.info(f"Discovery complete: {total} files found, {new_count} new, {existing_count} existing")
        
        return {
            "total_discovered": total,
            "new_candidates": new_count,
            "existing_candidates": existing_count
        }
    
    async def _get_file_content(self, drive_id: str, item_id: str, token: str) -> bytes:
        """Download file content from SharePoint."""
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.get(
                f"https://graph.microsoft.com/v1.0/drives/{drive_id}/items/{item_id}/content",
                headers={"Authorization": f"Bearer {token}"},
                follow_redirects=True
            )
            if resp.status_code != 200:
                raise Exception(f"Failed to download file: {resp.status_code}")
            return resp.content
    
    async def _extract_text_from_file(self, file_name: str, content: bytes) -> str:
        """Extract text from file for AI classification."""
        # For this POC, do basic text extraction
        ext = file_name.lower().split(".")[-1] if "." in file_name else ""
        
        if ext in ["txt", "csv"]:
            try:
                return content.decode("utf-8", errors="ignore")[:5000]
            except:
                return ""
        
        # For PDFs, try to extract text using a simple approach
        if ext == "pdf":
            try:
                # Look for text streams in PDF
                text = content.decode("latin-1", errors="ignore")
                # Extract readable text between common PDF markers
                readable_parts = []
                for line in text.split("\n"):
                    # Skip binary-heavy lines
                    if len(line) > 0 and sum(1 for c in line if 32 <= ord(c) < 127) / len(line) > 0.7:
                        readable_parts.append(line)
                return "\n".join(readable_parts)[:5000]
            except:
                return ""
        
        # For Office documents, return empty (would need specialized libraries)
        return ""
    
    async def _classify_with_ai(
        self, 
        file_name: str, 
        legacy_path: str, 
        text_content: str
    ) -> Dict[str, Any]:
        """Use AI to classify the file and extract metadata."""
        api_key = os.environ.get("EMERGENT_LLM_KEY")
        if not api_key:
            logger.warning("EMERGENT_LLM_KEY not configured")
            return {
                "doc_type": "unknown",
                "department": "Unknown",
                "confidence": 0.0,
                "error": "API key not configured"
            }
        
        try:
            from emergentintegrations.llm.chat import LlmChat, UserMessage
            
            # Build the classification prompt
            system_prompt = """You are a document classification expert for Gamer Packaging Inc.
Your task is to analyze a file and extract metadata for organizing it in SharePoint.

You MUST respond with ONLY a JSON object in this exact format:
{
    "doc_type": "invoice | po | contract | sop | spec_sheet | quote | presentation | email_export | correspondence | report | artwork | unknown",
    "department": "CustomerRelations | Sales | Marketing | Finance | Quality | Operations | IT | HR | Unknown",
    "customer_name": "string or null",
    "vendor_name": "string or null",
    "project_or_part_number": "string or null",
    "document_date": "YYYY-MM-DD or null",
    "retention_category": "CustomerComm_LongTerm | WorkingDoc_2yrs | Accounting_7yrs | Legal_10yrs | Unknown",
    "confidence": 0.0 to 1.0
}

IMPORTANT CLASSIFICATION HINTS:
- The file path contains important context. "Customer Relations" folder strongly indicates CustomerRelations department.
- "Duke Cannon" is a major customer - if you see this name, set customer_name="Duke Cannon"
- Files with "Specification Binder" or "Spec Binder" are doc_type="spec_sheet"
- Files in "Art Work Files" are doc_type="artwork"
- Extract customer/vendor names if visible in the document or file name.
- Use document_date for the primary date in the document (invoice date, contract date, etc.)
- Date in filename like "(9.23.25)" means September 23, 2025 -> "2025-09-23"
- confidence should reflect how certain you are about all fields combined. Use 0.85+ for high confidence.

RESPOND ONLY WITH THE JSON OBJECT, NO OTHER TEXT."""
            
            user_content = f"""Classify this file:

File name: {file_name}
Legacy path: {legacy_path}

"""
            if text_content:
                user_content += f"Document text (excerpt):\n{text_content[:3000]}"
            else:
                user_content += "No text content available - classify based on file name and path only."
            
            # Use the same pattern as ai_classifier.py
            chat = LlmChat(
                api_key=api_key,
                session_id=f"migration_classify_{file_name[:30]}",
                system_message=system_prompt
            ).with_model("gemini", "gemini-2.0-flash")
            
            user_message = UserMessage(text=user_content)
            response = await chat.send_message(user_message)
            
            logger.info(f"AI classification response for {file_name}: {response[:200]}")
            
            # Parse JSON response
            import json
            response_text = response.strip()
            
            # Handle markdown code blocks
            if response_text.startswith("```"):
                lines = response_text.split("\n")
                response_text = "\n".join(lines[1:-1])
            if response_text.startswith("```json"):
                response_text = response_text[7:]
            if response_text.endswith("```"):
                response_text = response_text[:-3]
            
            result = json.loads(response_text.strip())
            result["classification_method"] = "ai_with_path" if text_content else "ai_filename_only"
            
            return result
            
        except Exception as e:
            logger.error(f"AI classification error: {e}")
            return {
                "doc_type": "unknown",
                "department": "Unknown",
                "confidence": 0.0,
                "error": str(e)
            }
    
    async def classify_candidates(self, max_count: int = 25) -> Dict[str, int]:
        """
        Classify discovered candidates using AI.
        
        Args:
            max_count: Maximum number of candidates to process
            
        Returns:
            Dict with processed, updated, high_confidence, low_confidence counts
        """
        logger.info(f"Classifying up to {max_count} candidates")
        
        # Get candidates to classify
        cursor = self.collection.find(
            {"status": {"$in": ["discovered", "classified"]}}
        ).limit(max_count)
        
        candidates = await cursor.to_list(length=max_count)
        
        if not candidates:
            logger.info("No candidates to classify")
            return {"processed": 0, "updated": 0, "high_confidence": 0, "low_confidence": 0}
        
        token = await self._get_graph_token()
        processed = 0
        high_confidence = 0
        low_confidence = 0
        now = datetime.now(timezone.utc).isoformat()
        
        for candidate in candidates:
            try:
                # Try to get file content for better classification
                text_content = ""
                try:
                    content = await self._get_file_content(
                        candidate["source_drive_id"],
                        candidate["source_item_id"],
                        token
                    )
                    text_content = await self._extract_text_from_file(
                        candidate["file_name"],
                        content
                    )
                except Exception as e:
                    logger.warning(f"Could not extract content from {candidate['file_name']}: {e}")
                
                # Classify with AI
                result = await self._classify_with_ai(
                    candidate["file_name"],
                    candidate["legacy_path"],
                    text_content
                )
                
                confidence = result.get("confidence", 0.0)
                new_status = "ready_for_migration" if confidence >= CONFIDENCE_THRESHOLD else "classified"
                
                if confidence >= CONFIDENCE_THRESHOLD:
                    high_confidence += 1
                else:
                    low_confidence += 1
                
                # Update candidate
                update_data = {
                    "doc_type": result.get("doc_type"),
                    "department": result.get("department"),
                    "customer_name": result.get("customer_name"),
                    "vendor_name": result.get("vendor_name"),
                    "project_or_part_number": result.get("project_or_part_number"),
                    "document_date": result.get("document_date"),
                    "retention_category": result.get("retention_category"),
                    "classification_confidence": confidence,
                    "classification_method": result.get("classification_method", "ai"),
                    "status": new_status,
                    "updated_utc": now
                }
                
                await self.collection.update_one(
                    {"id": candidate["id"]},
                    {"$set": update_data}
                )
                
                processed += 1
                
            except Exception as e:
                logger.error(f"Error classifying {candidate.get('file_name')}: {e}")
                await self.collection.update_one(
                    {"id": candidate["id"]},
                    {"$set": {
                        "status": "error",
                        "migration_error": str(e),
                        "updated_utc": now
                    }}
                )
        
        logger.info(f"Classification complete: {processed} processed, {high_confidence} high confidence, {low_confidence} low confidence")
        
        return {
            "processed": processed,
            "updated": processed,
            "high_confidence": high_confidence,
            "low_confidence": low_confidence
        }
    
    async def _ensure_destination_columns(
        self,
        site_id: str,
        list_id: str,
        token: str
    ) -> None:
        """Ensure required columns exist in destination library."""
        async with httpx.AsyncClient(timeout=60.0) as client:
            # Get existing columns
            resp = await client.get(
                f"https://graph.microsoft.com/v1.0/sites/{site_id}/lists/{list_id}/columns",
                headers={"Authorization": f"Bearer {token}"}
            )
            
            if resp.status_code != 200:
                logger.warning(f"Could not get columns: {resp.status_code}")
                return
            
            existing_columns = {col["name"] for col in resp.json().get("value", [])}
            
            # Create missing columns
            for col_def in REQUIRED_COLUMNS:
                if col_def["name"] not in existing_columns:
                    logger.info(f"Creating column: {col_def['name']}")
                    
                    col_payload = {
                        "name": col_def["name"],
                        "displayName": col_def["name"]
                    }
                    
                    if col_def["type"] == "text":
                        col_payload["text"] = {"allowMultipleLines": col_def["name"] in ["LegacyPath", "LegacyUrl"]}
                    elif col_def["type"] == "dateTime":
                        col_payload["dateTime"] = {"displayAs": "default"}
                    
                    create_resp = await client.post(
                        f"https://graph.microsoft.com/v1.0/sites/{site_id}/lists/{list_id}/columns",
                        headers={
                            "Authorization": f"Bearer {token}",
                            "Content-Type": "application/json"
                        },
                        json=col_payload
                    )
                    
                    if create_resp.status_code not in (200, 201):
                        logger.warning(f"Could not create column {col_def['name']}: {create_resp.status_code} - {create_resp.text[:200]}")
    
    async def _get_list_id(self, site_id: str, library_name: str, token: str) -> str:
        """Get the list ID for a document library."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"https://graph.microsoft.com/v1.0/sites/{site_id}/lists",
                headers={"Authorization": f"Bearer {token}"}
            )
            
            if resp.status_code != 200:
                raise Exception(f"Failed to get lists: {resp.status_code}")
            
            lists = resp.json().get("value", [])
            for lst in lists:
                if lst.get("displayName") == library_name or lst.get("name") == library_name:
                    return lst["id"]
            
            raise Exception(f"List '{library_name}' not found")
    
    async def migrate_candidates(
        self,
        target_site_url: str = DEFAULT_TARGET_SITE,
        target_library_name: str = DEFAULT_TARGET_LIBRARY,
        max_count: int = 20,
        only_ids: Optional[List[str]] = None
    ) -> Dict[str, int]:
        """
        Migrate ready candidates to the target SharePoint site.
        
        Args:
            target_site_url: Destination SharePoint site URL
            target_library_name: Destination library name
            max_count: Maximum number of files to migrate
            only_ids: Optional list of specific candidate IDs to migrate
            
        Returns:
            Dict with attempted, migrated, errors counts
        """
        logger.info(f"Migrating up to {max_count} candidates to {target_site_url}")
        
        # Get candidates to migrate
        if only_ids:
            cursor = self.collection.find({"id": {"$in": only_ids}})
        else:
            cursor = self.collection.find({"status": "ready_for_migration"}).limit(max_count)
        
        candidates = await cursor.to_list(length=max_count if not only_ids else len(only_ids))
        
        if not candidates:
            logger.info("No candidates ready for migration")
            return {"attempted": 0, "migrated": 0, "errors": 0}
        
        token = await self._get_graph_token()
        
        # Get target site and drive info
        target_site_id = await self._get_site_id(target_site_url, token)
        target_drive_id = await self._get_drive_id(target_site_id, target_library_name, token)
        target_list_id = await self._get_list_id(target_site_id, target_library_name, token)
        
        # Ensure destination columns exist
        await self._ensure_destination_columns(target_site_id, target_list_id, token)
        
        attempted = 0
        migrated = 0
        errors = 0
        now = datetime.now(timezone.utc).isoformat()
        
        async with httpx.AsyncClient(timeout=120.0) as client:
            for candidate in candidates:
                attempted += 1
                
                # Skip already migrated
                if candidate.get("status") == "migrated" and candidate.get("target_item_id"):
                    logger.info(f"Skipping already migrated: {candidate['file_name']}")
                    continue
                
                try:
                    # Download file from source
                    file_content = await self._get_file_content(
                        candidate["source_drive_id"],
                        candidate["source_item_id"],
                        token
                    )
                    
                    # Upload to destination
                    file_name = candidate["file_name"]
                    upload_url = f"https://graph.microsoft.com/v1.0/drives/{target_drive_id}/root:/{file_name}:/content"
                    
                    upload_resp = await client.put(
                        upload_url,
                        headers={
                            "Authorization": f"Bearer {token}",
                            "Content-Type": "application/octet-stream"
                        },
                        content=file_content
                    )
                    
                    if upload_resp.status_code not in (200, 201):
                        raise Exception(f"Upload failed: {upload_resp.status_code} - {upload_resp.text[:200]}")
                    
                    new_item = upload_resp.json()
                    new_item_id = new_item["id"]
                    new_web_url = new_item.get("webUrl", "")
                    
                    # Update metadata on the new item
                    # Get the list item ID
                    list_item_resp = await client.get(
                        f"https://graph.microsoft.com/v1.0/drives/{target_drive_id}/items/{new_item_id}/listItem",
                        headers={"Authorization": f"Bearer {token}"}
                    )
                    
                    if list_item_resp.status_code == 200:
                        list_item_id = list_item_resp.json()["id"]
                        
                        # Prepare metadata fields
                        fields = {
                            "DocType": candidate.get("doc_type") or "unknown",
                            "Department": candidate.get("department") or "Unknown",
                            "CustomerName": candidate.get("customer_name") or "",
                            "VendorName": candidate.get("vendor_name") or "",
                            "ProjectOrPartNumber": candidate.get("project_or_part_number") or "",
                            "RetentionCategory": candidate.get("retention_category") or "Unknown",
                            "LegacyPath": candidate.get("legacy_path") or "",
                            "LegacyUrl": candidate.get("legacy_url") or ""
                        }
                        
                        # Add DocumentDate if available
                        if candidate.get("document_date"):
                            fields["DocumentDate"] = candidate["document_date"]
                        
                        # Update list item fields
                        update_resp = await client.patch(
                            f"https://graph.microsoft.com/v1.0/sites/{target_site_id}/lists/{target_list_id}/items/{list_item_id}/fields",
                            headers={
                                "Authorization": f"Bearer {token}",
                                "Content-Type": "application/json"
                            },
                            json=fields
                        )
                        
                        if update_resp.status_code not in (200, 201):
                            logger.warning(f"Could not update metadata for {file_name}: {update_resp.status_code}")
                    
                    # Update candidate record
                    await self.collection.update_one(
                        {"id": candidate["id"]},
                        {"$set": {
                            "status": "migrated",
                            "target_site_url": target_site_url,
                            "target_library_name": target_library_name,
                            "target_item_id": new_item_id,
                            "target_url": new_web_url,
                            "migration_timestamp": now,
                            "migration_error": None,
                            "updated_utc": now
                        }}
                    )
                    
                    migrated += 1
                    logger.info(f"Migrated: {file_name}")
                    
                except Exception as e:
                    errors += 1
                    error_msg = str(e)[:250]
                    logger.error(f"Error migrating {candidate.get('file_name')}: {error_msg}")
                    
                    await self.collection.update_one(
                        {"id": candidate["id"]},
                        {"$set": {
                            "status": "error",
                            "migration_error": error_msg,
                            "updated_utc": now
                        }}
                    )
        
        logger.info(f"Migration complete: {attempted} attempted, {migrated} migrated, {errors} errors")
        
        return {
            "attempted": attempted,
            "migrated": migrated,
            "errors": errors
        }
    
    async def get_summary(self) -> Dict[str, Any]:
        """Get summary statistics for migration candidates."""
        total = await self.collection.count_documents({})
        
        # Count by status
        status_counts = {}
        for status in ["discovered", "classified", "ready_for_migration", "migrated", "error"]:
            count = await self.collection.count_documents({"status": status})
            status_counts[status] = count
        
        # Count by doc_type
        doc_type_counts = {}
        pipeline = [
            {"$match": {"doc_type": {"$ne": None}}},
            {"$group": {"_id": "$doc_type", "count": {"$sum": 1}}}
        ]
        async for doc in self.collection.aggregate(pipeline):
            doc_type_counts[doc["_id"]] = doc["count"]
        
        # Count by confidence bands
        confidence_bands = {
            "high_90_plus": await self.collection.count_documents({"classification_confidence": {"$gte": 0.9}}),
            "medium_85_90": await self.collection.count_documents({
                "classification_confidence": {"$gte": 0.85, "$lt": 0.9}
            }),
            "low_below_85": await self.collection.count_documents({
                "classification_confidence": {"$lt": 0.85, "$ne": None}
            }),
            "not_classified": await self.collection.count_documents({"classification_confidence": None})
        }
        
        return {
            "total_candidates": total,
            "by_status": status_counts,
            "by_doc_type": doc_type_counts,
            "by_confidence": confidence_bands
        }
    
    async def get_candidates(
        self,
        status: Optional[str] = None,
        doc_type: Optional[str] = None,
        min_confidence: Optional[float] = None,
        max_confidence: Optional[float] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict]:
        """Get migration candidates with optional filters."""
        query = {}
        
        if status:
            query["status"] = status
        if doc_type:
            query["doc_type"] = doc_type
        if min_confidence is not None:
            query.setdefault("classification_confidence", {})["$gte"] = min_confidence
        if max_confidence is not None:
            query.setdefault("classification_confidence", {})["$lte"] = max_confidence
        
        cursor = self.collection.find(query, {"_id": 0}).skip(offset).limit(limit).sort("created_utc", -1)
        return await cursor.to_list(length=limit)
    
    async def get_candidate_by_id(self, candidate_id: str) -> Optional[Dict]:
        """Get a single candidate by ID."""
        return await self.collection.find_one({"id": candidate_id}, {"_id": 0})
    
    async def update_candidate(self, candidate_id: str, updates: Dict) -> bool:
        """Update a candidate's fields (for manual editing)."""
        allowed_fields = [
            "doc_type", "department", "customer_name", "vendor_name",
            "project_or_part_number", "document_date", "retention_category",
            "status"
        ]
        
        filtered_updates = {k: v for k, v in updates.items() if k in allowed_fields}
        if not filtered_updates:
            return False
        
        filtered_updates["updated_utc"] = datetime.now(timezone.utc).isoformat()
        
        result = await self.collection.update_one(
            {"id": candidate_id},
            {"$set": filtered_updates}
        )
        
        return result.modified_count > 0
