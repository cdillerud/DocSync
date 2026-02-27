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
# Updated based on File MetaData Structure.xlsx
REQUIRED_COLUMNS = [
    # Core metadata from Excel structure
    {"name": "AcctType", "type": "choice", "choices": ["Manufacturers / Vendors", "Customer Accounts", "Corporate Internal", "System Resources"]},
    {"name": "AcctName", "type": "text"},
    {"name": "DocumentType", "type": "choice", "choices": [
        "Supplier Documents", "Marketing Literature", "Capabilities / Catalogs", "SOPs / Resources",
        "Plant Warehouse List", "Dunnage", "Product Specification Sheet", "Product Pack-Out Specs",
        "Product Drawings", "Graphical Die Line", "Forecasts", "Inventory Reports", "Transaction History",
        "Price List", "Misc.", "Customer Documents", "Drawing Approval", "Specification Approval",
        "Prototype Approval", "Graphics Approval", "Project Timeline", "Supplier Quote", "Customer Quote",
        "Cost Analysis", "Training", "Agreement Resources", "New Business Dev Resources", "Quality Documents",
        "Claims/Cases", "Warehouse & Consignment", "Invoice & Hold Agreement", "Supply Agreement",
        "Supply Addendum", "Other"
    ]},
    {"name": "DocumentSubType", "type": "text"},
    {"name": "DocumentStatus", "type": "choice", "choices": ["Active", "Archived", "Pending"]},
    # Legacy fields for migration tracking
    {"name": "LegacyPath", "type": "text"},
    {"name": "LegacyUrl", "type": "text"},
    # Additional metadata inferred by hybrid classification
    {"name": "ProjectOrPartNumber", "type": "text"},
    {"name": "DocumentDate", "type": "dateTime"},
    {"name": "RetentionCategory", "type": "text"},
    # Folder tree levels (for auditing the source classification)
    {"name": "Level1", "type": "text"},
    {"name": "Level2", "type": "text"},
    {"name": "Level3", "type": "text"},
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
    
    # NEW: Metadata fields from File MetaData Structure.xlsx
    acct_type: Optional[str] = None  # Manufacturers/Vendors, Customer Accounts, Corporate Internal, System Resources
    acct_name: Optional[str] = None  # Actual account/customer/vendor name
    document_type: Optional[str] = None  # New expanded doc type from Excel
    document_sub_type: Optional[str] = None  # Sub-type within document_type
    document_status: Optional[str] = None  # Active, Archived, Pending
    
    # Legacy AI metadata fields (kept for backwards compatibility)
    doc_type: Optional[str] = None  # Original simple doc_type
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
        Updated to align with File MetaData Structure.xlsx
        
        Level1 = Department (Customer Relations, Marketing, General, etc.)
        Level2 = Customer/Sub-department (Duke Cannon, Manufacturers - Vendors, etc.)
        Level3 = Document category (Spec Sheets, Art Work Files, etc.)
        """
        level1 = classification.get("level1", "") or ""
        level2 = classification.get("level2", "") or ""
        level3 = classification.get("level3", "") or ""
        level4 = classification.get("level4", "") or ""
        level5 = classification.get("level5", "") or ""
        
        metadata = {
            "level1": level1,
            "level2": level2,
            "level3": level3,
            "level4": classification.get("level4"),
            "level5": classification.get("level5"),
            # Initialize new Excel-based fields
            "acct_type": None,
            "acct_name": None,
            "document_type": None,
            "document_sub_type": None,
            "document_status": "Active",  # Default to Active for migration
        }
        
        # ============================================================
        # Map to NEW Excel Metadata Structure
        # ============================================================
        
        # 1. Determine AcctType and extract customer/vendor name based on folder structure
        
        # Pattern 1: Customer Relations/[CustomerName]/...
        if level1 == "Customer Relations":
            metadata["acct_type"] = "Customer Accounts"
            if level2:
                metadata["acct_name"] = level2
                metadata["customer_name"] = level2
        
        # Pattern 2: General/Manufacturers - Vendors/[VendorName]/...
        elif level1 == "General" and level2 == "Manufacturers - Vendors":
            metadata["acct_type"] = "Manufacturers / Vendors"
            if level3:
                metadata["acct_name"] = level3
                metadata["vendor_name"] = level3
        
        # Pattern 3: General/Supply Chain/[Category]/[VendorName]/...
        elif level1 == "General" and level2 == "Supply Chain":
            metadata["acct_type"] = "Manufacturers / Vendors"
            # Level3 might be category (Ball, CanPack, Glass) or vendor
            # Level4 might be vendor or sub-category
            if level4 and level4 not in ["Suppliers", "Megan", ""]:
                metadata["acct_name"] = level4
                metadata["vendor_name"] = level4
            elif level3:
                metadata["acct_name"] = level3
                metadata["vendor_name"] = level3
        
        # Pattern 4: Supplier Relations/[SupplierName]/...
        elif level1 == "Supplier Relations":
            metadata["acct_type"] = "Manufacturers / Vendors"
            if level2:
                metadata["acct_name"] = level2
                metadata["vendor_name"] = level2
        
        # Pattern 5: Custom Projects/[CustomerOrProjectName]/...
        elif level1 == "Custom Projects":
            metadata["acct_type"] = "Customer Accounts"
            if level2:
                metadata["acct_name"] = level2
                metadata["customer_name"] = level2
        
        # Pattern 6: Customer Quotes.../[CustomerName]/...
        elif "Customer" in level1 and "Quote" in level1:
            metadata["acct_type"] = "Customer Accounts"
            if level2:
                metadata["acct_name"] = level2
                metadata["customer_name"] = level2
        
        # Pattern 7: General/New Vendor Set-Up Information/...
        elif level1 == "General" and "Vendor" in (level2 or ""):
            metadata["acct_type"] = "Manufacturers / Vendors"
            if level3:
                metadata["acct_name"] = level3
                metadata["vendor_name"] = level3
        
        # Pattern 8: General/Agreement Resources/... or other internal
        elif level1 in ["General", "Corporate Internal", "HR Programs and Benefits", "Product Knowledge", "Marketing", "Sales"]:
            metadata["acct_type"] = "Corporate Internal"
            # Check if Level3 or Level4 looks like a company name (not a category)
            category_keywords = ["archive", "resources", "template", "form", "training", "sop", "guide", "report"]
            if level3 and not any(kw in level3.lower() for kw in category_keywords):
                # Might be a company name
                if level2 in ["Agreement Resources", "New Business Development Resources"]:
                    metadata["acct_name"] = level3
        
        # Pattern 9: System Resources
        elif level1 == "System Resources":
            metadata["acct_type"] = "System Resources"
        
        # Default fallback
        else:
            metadata["acct_type"] = "Corporate Internal"
            if level2 and level2 not in ["", "Archive", "Templates", "Forms"]:
                metadata["acct_name"] = level2
        
        # 2. Map to DocumentType based on folder structure
        all_levels = f"{level1}/{level2}/{level3}/{level4}/{level5}".lower()
        
        document_type_map = {
            # Product specifications
            ("spec sheet", "specification", "spec binder"): "Product Specification Sheet",
            ("product drawing", "drawing"): "Product Drawings",
            ("die line", "die-line", "dieline"): "Graphical Die Line",
            ("pack-out", "packout", "pack out"): "Product Pack-Out Specs",
            # Art and marketing
            ("art work", "artwork"): "Product Drawings",  # or could be Marketing Literature
            ("marketing", "literature"): "Marketing Literature",
            ("catalog", "capabilities"): "Capabilities / Catalogs",
            # Quotes and pricing
            ("quote",): "Customer Quote" if "customer" in all_levels else "Supplier Quote",
            ("price list", "pricing"): "Price List",
            ("cost analysis",): "Cost Analysis",
            # Approvals
            ("drawing approval",): "Drawing Approval",
            ("specification approval", "spec approval"): "Specification Approval",
            ("prototype approval",): "Prototype Approval",
            ("graphics approval",): "Graphics Approval",
            # Operations
            ("sop", "procedure", "resource"): "SOPs / Resources",
            ("training",): "Training",
            ("warehouse", "dunnage"): "Warehouse & Consignment",
            # Agreements
            ("agreement", "contract"): "Agreement Resources",
            ("supply agreement",): "Supply Agreement",
            ("addendum",): "Supply Addendum",
            # Quality
            ("quality", "claim", "case"): "Quality Documents",
            # Transaction-related
            ("invoice",): "Invoice & Hold Agreement",
            ("forecast",): "Forecasts",
            ("inventory",): "Inventory Reports",
            ("transaction",): "Transaction History",
            # Development
            ("new business", "development"): "New Business Dev Resources",
            ("project timeline",): "Project Timeline",
        }
        
        document_type = "Other"  # Default
        for keywords, doc_type_value in document_type_map.items():
            for keyword in keywords:
                if keyword in all_levels:
                    document_type = doc_type_value
                    break
            if document_type != "Other":
                break
        
        metadata["document_type"] = document_type
        
        # 3. Set DocumentSubType from Level3 or Level4 if specific
        if level3 and level3 not in ["Art Work Files", "Spec Sheets"]:
            metadata["document_sub_type"] = level3
        elif level4:
            metadata["document_sub_type"] = level4
        
        # ============================================================
        # Legacy field mapping (for backwards compatibility)
        # ============================================================
        
        # Map Level1 to legacy Department field - expanded mapping
        department_map = {
            "Customer Relations": "CustomerRelations",
            "Marketing": "Marketing",
            "Sales": "Sales",
            "General": "Operations",  # Will refine based on Level2
            "Custom Projects": "Engineering",
            "HR Programs and Benefits": "HR",
            "Supplier Relations": "Purchasing",
            "Product Knowledge": "Engineering",
            "Quality": "Quality",
            "Warehouse": "Warehouse",
            "Operations": "Operations",
            "Finance": "Finance",
            "Accounting": "Finance",
            "IT": "IT",
            "Engineering": "Engineering",
            "Purchasing": "Purchasing",
        }
        
        # Try to determine department from path context
        department = department_map.get(level1)
        
        # Refine department for "General" based on Level2
        if level1 == "General":
            level2_dept_map = {
                "Manufacturers - Vendors": "Purchasing",
                "Supply Chain": "Purchasing",
                "Marketing": "Marketing",
                "HR For Employees": "HR",
                "Inside Sale Resources": "Sales",
                "New Business Development Resources": "Sales",
                "Accounting Forms": "Finance",
                "Agreement Resources": "Operations",
                "GAMER SOP's": "Operations",
                "Product Knowledge": "Engineering",
                "System Resources": "IT",
                "New Vendor Set-Up Information": "Purchasing",
                "Sales Meeting Presentations": "Sales",
            }
            department = level2_dept_map.get(level2, "Operations")
        
        if not department:
            # Infer from all_levels if Level1 doesn't match
            all_lower = all_levels.lower()
            if "customer relation" in all_lower:
                department = "CustomerRelations"
            elif "sales" in all_lower or "order" in all_lower:
                department = "Sales"
            elif "marketing" in all_lower:
                department = "Marketing"
            elif "quality" in all_lower or "claim" in all_lower or "inspection" in all_lower:
                department = "Quality"
            elif "warehouse" in all_lower or "shipping" in all_lower or "wh doc" in all_lower:
                department = "Warehouse"
            elif "purchasing" in all_lower or "vendor" in all_lower or "supplier" in all_lower:
                department = "Purchasing"
            elif "engineering" in all_lower or "spec" in all_lower or "drawing" in all_lower:
                department = "Engineering"
            elif "operation" in all_lower or "production" in all_lower or "manufacturing" in all_lower:
                department = "Operations"
            elif "finance" in all_lower or "accounting" in all_lower or "invoice" in all_lower:
                department = "Finance"
            elif "hr" in all_lower or "human resource" in all_lower or "benefit" in all_lower:
                department = "HR"
            elif "it" in all_lower or "system" in all_lower or "technical" in all_lower:
                department = "IT"
            else:
                department = level1 if level1 else "Unknown"
        
        metadata["department"] = department
        
        # Infer legacy doc_type from folder structure (simpler categories)
        doc_type = "unknown"
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
        
        # Set retention based on document type
        retention_map = {
            "Product Specification Sheet": "CustomerComm_LongTerm",
            "Product Drawings": "CustomerComm_LongTerm",
            "Agreement Resources": "Legal_10yrs",
            "Supply Agreement": "Legal_10yrs",
            "Quality Documents": "Legal_10yrs",
            "Invoice & Hold Agreement": "Accounting_7yrs",
            "Training": "WorkingDoc_2yrs",
            "SOPs / Resources": "WorkingDoc_2yrs",
        }
        metadata["retention_category"] = retention_map.get(document_type, "WorkingDoc_2yrs")
        
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
                    # NEW: Initialize Excel metadata fields
                    "acct_type": None,
                    "acct_name": None,
                    "document_type": None,
                    "document_sub_type": None,
                    "document_status": "Active",
                    # Legacy metadata fields
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
                        # NEW: Excel metadata fields
                        "acct_type": metadata.get("acct_type"),
                        "acct_name": metadata.get("acct_name"),
                        "document_type": metadata.get("document_type"),
                        "document_sub_type": metadata.get("document_sub_type"),
                        "document_status": metadata.get("document_status", "Active"),
                        # Legacy fields
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
            except Exception:
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
            except Exception:
                return ""
        
        # For Office documents, return empty (would need specialized libraries)
        return ""
    
    async def _classify_with_ai(
        self, 
        file_name: str, 
        legacy_path: str, 
        text_content: str
    ) -> Dict[str, Any]:
        """Use AI to classify the file and extract metadata aligned with File MetaData Structure.xlsx."""
        api_key = os.environ.get("EMERGENT_LLM_KEY")
        if not api_key:
            logger.warning("EMERGENT_LLM_KEY not configured")
            return {
                "acct_type": "Corporate Internal",
                "document_type": "Other",
                "document_status": "Active",
                "department": "Unknown",
                "confidence": 0.0,
                "error": "API key not configured"
            }
        
        try:
            from emergentintegrations.llm.chat import LlmChat, UserMessage
            
            # Build the classification prompt aligned with Excel metadata structure
            system_prompt = """You are a document classification expert for Gamer Packaging Inc (GPI), a packaging company.
Your task is to analyze a file and extract metadata aligned with our SharePoint flat structure.

You MUST respond with ONLY a JSON object in this exact format:
{
    "acct_type": "Manufacturers / Vendors | Customer Accounts | Corporate Internal | System Resources",
    "acct_name": "string - The customer or vendor name (e.g., 'Duke Cannon', 'Menasha Packaging')",
    "department": "CustomerRelations | Sales | Marketing | Operations | Quality | Finance | HR | IT | Purchasing | Warehouse | Engineering | Unknown",
    "document_type": "One of: Supplier Documents, Marketing Literature, Capabilities / Catalogs, SOPs / Resources, Plant Warehouse List, Dunnage, Product Specification Sheet, Product Pack-Out Specs, Product Drawings, Graphical Die Line, Forecasts, Inventory Reports, Transaction History, Price List, Misc., Customer Documents, Drawing Approval, Specification Approval, Prototype Approval, Graphics Approval, Project Timeline, Supplier Quote, Customer Quote, Cost Analysis, Training, Agreement Resources, New Business Dev Resources, Quality Documents, Claims/Cases, Warehouse & Consignment, Invoice & Hold Agreement, Supply Agreement, Supply Addendum, Other",
    "document_sub_type": "string - More specific classification (e.g., 'Beard Care', 'Face Care', 'Corrugated')",
    "document_status": "Active | Archived | Pending",
    "project_or_part_number": "string or null - Part numbers like BT-1000-110, GPI-12345",
    "document_date": "YYYY-MM-DD or null - Date from filename or document",
    "retention_category": "CustomerComm_LongTerm | WorkingDoc_2yrs | Accounting_7yrs | Legal_10yrs | Unknown",
    "confidence": 0.0 to 1.0
}

CRITICAL DEPARTMENT CLASSIFICATION RULES:
1. "Customer Relations" in path → department = "CustomerRelations", acct_type = "Customer Accounts"
2. "Sales" in path OR sales orders/quotes → department = "Sales"
3. "Marketing" in path OR marketing materials → department = "Marketing"
4. "Quality" in path OR quality docs/claims/inspections → department = "Quality"
5. "Warehouse" or "WH" or "Shipping" in path → department = "Warehouse"
6. "Purchasing" or vendor-related procurement → department = "Purchasing"
7. "Engineering" or technical drawings/specs → department = "Engineering"
8. "Operations" or production/manufacturing docs → department = "Operations"
9. "Finance" or "Accounting" or invoices/payments → department = "Finance"
10. "HR" or employee/benefits docs → department = "HR"
11. "IT" or technical/system docs → department = "IT"

ACCT_TYPE RULES:
- If dealing with a CUSTOMER (someone GPI sells to): acct_type = "Customer Accounts"
- If dealing with a VENDOR/SUPPLIER (someone GPI buys from): acct_type = "Manufacturers / Vendors"
- If internal company docs with no external party: acct_type = "Corporate Internal"

DOCUMENT TYPE HINTS:
- "Spec Binder", "Specification" → "Product Specification Sheet"
- "Art Work", "Artwork", "Die Line" → "Product Drawings" or "Graphical Die Line"
- "Quote" from customer → "Customer Quote"; Quote to customer → "Supplier Quote"
- "PO", "Purchase Order" → "Supplier Documents"
- "Invoice" → "Invoice & Hold Agreement"
- "SOP", "Procedure", "Guide" → "SOPs / Resources"
- "Agreement", "Contract" → "Agreement Resources" or "Supply Agreement"

DATE PATTERNS IN FILENAMES:
- "(9.23.25)" = September 23, 2025 → "2025-09-23"
- "2025-01-15" → "2025-01-15"
- "01152025" → "2025-01-15"

RESPOND ONLY WITH THE JSON OBJECT, NO OTHER TEXT."""
            
            user_content = f"""Classify this file for Gamer Packaging Inc:

File name: {file_name}
Full path: {legacy_path}

"""
            if text_content:
                user_content += f"Document text (first 3000 chars):\n{text_content[:3000]}"
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
            
            # Ensure all required fields exist with sensible defaults
            result.setdefault("document_status", "Active")
            result.setdefault("acct_type", "Corporate Internal")
            result.setdefault("document_type", "Other")
            result.setdefault("department", "Unknown")
            
            return result
            
        except Exception as e:
            logger.error(f"AI classification error: {e}")
            return {
                "acct_type": "Corporate Internal",
                "document_type": "Other",
                "document_status": "Active",
                "department": "Unknown",
                "confidence": 0.0,
                "error": str(e)
            }
    
    async def classify_candidates(self, max_count: int = 25) -> Dict[str, int]:
        """
        Classify discovered candidates using HYBRID approach:
        1. First check if folder tree classification already exists
        2. Use AI only for additional metadata (dates, part numbers) or unmatched paths
        
        Args:
            max_count: Maximum number of candidates to process
            
        Returns:
            Dict with processed, updated, high_confidence, low_confidence, folder_tree_matches counts
        """
        logger.info(f"Classifying up to {max_count} candidates (hybrid approach)")
        
        # Get candidates to classify
        cursor = self.collection.find(
            {"status": {"$in": ["discovered", "classified"]}}
        ).limit(max_count)
        
        candidates = await cursor.to_list(length=max_count)
        
        if not candidates:
            logger.info("No candidates to classify")
            return {"processed": 0, "updated": 0, "high_confidence": 0, "low_confidence": 0, "folder_tree_matches": 0}
        
        token = await self._get_graph_token()
        processed = 0
        high_confidence = 0
        low_confidence = 0
        folder_tree_matches = 0
        now = datetime.now(timezone.utc).isoformat()
        
        for candidate in candidates:
            try:
                # Check if we already have folder tree classification
                has_folder_tree = candidate.get("classification_source") == "folder_tree"
                existing_confidence = candidate.get("classification_confidence", 0.0) or 0.0
                
                # If folder tree gives us high confidence, we mainly need AI for dates/part numbers
                if has_folder_tree and existing_confidence >= 0.85:
                    folder_tree_matches += 1
                    
                    # Use AI only for extracting dates and part numbers from filename
                    ai_result = await self._extract_dates_and_parts(
                        candidate["file_name"],
                        candidate["legacy_path"]
                    )
                    
                    # Determine document_status from path
                    legacy_path_lower = (candidate.get("legacy_path") or "").lower()
                    document_status = "Archived" if "previous version" in legacy_path_lower else "Active"
                    
                    # Merge AI results with folder tree data
                    update_data = {
                        "document_date": ai_result.get("document_date") or candidate.get("document_date"),
                        "project_or_part_number": ai_result.get("project_or_part_number") or candidate.get("project_or_part_number"),
                        "document_status": document_status,
                        "classification_source": "hybrid",
                        "classification_method": "folder_tree_plus_ai",
                        "status": "ready_for_migration",
                        "updated_utc": now
                    }
                    
                    await self.collection.update_one(
                        {"id": candidate["id"]},
                        {"$set": update_data}
                    )
                    high_confidence += 1
                    
                else:
                    # No folder tree match - use full AI classification
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
                    
                    # Full AI classification
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
                    
                    # Update candidate with AI results (includes new Excel metadata fields)
                    update_data = {
                        # NEW: Excel metadata fields
                        "acct_type": result.get("acct_type"),
                        "acct_name": result.get("acct_name"),
                        "document_type": result.get("document_type"),
                        "document_sub_type": result.get("document_sub_type"),
                        "document_status": result.get("document_status", "Active"),
                        # Legacy fields
                        "doc_type": result.get("doc_type"),
                        "department": result.get("department"),
                        "customer_name": result.get("customer_name") or result.get("acct_name"),
                        "vendor_name": result.get("vendor_name"),
                        "project_or_part_number": result.get("project_or_part_number"),
                        "document_date": result.get("document_date"),
                        "retention_category": result.get("retention_category"),
                        "classification_confidence": confidence,
                        "classification_source": "ai",
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
        
        logger.info(f"Classification complete: {processed} processed, {folder_tree_matches} folder tree matches, {high_confidence} high confidence, {low_confidence} low confidence")
        
        return {
            "processed": processed,
            "updated": processed,
            "high_confidence": high_confidence,
            "low_confidence": low_confidence,
            "folder_tree_matches": folder_tree_matches
        }
    
    async def _extract_dates_and_parts(self, file_name: str, legacy_path: str) -> Dict[str, Any]:
        """
        Use AI to extract just dates and part numbers from filename.
        Lighter-weight than full classification.
        """
        import re
        
        result = {"document_date": None, "project_or_part_number": None}
        
        # Try regex extraction first (fast, no API call)
        # Date patterns like (9.23.25), (09-23-2025), etc.
        date_patterns = [
            r'\((\d{1,2})[./](\d{1,2})[./](\d{2,4})\)',  # (9.23.25) or (9/23/25)
            r'(\d{1,2})[./](\d{1,2})[./](\d{2,4})',      # 9.23.25
            r'(\d{4})-(\d{2})-(\d{2})',                   # 2025-09-23
        ]
        
        for pattern in date_patterns:
            match = re.search(pattern, file_name)
            if match:
                groups = match.groups()
                if len(groups) == 3:
                    try:
                        # Handle different formats
                        if len(groups[0]) == 4:  # YYYY-MM-DD
                            year, month, day = groups
                        else:
                            month, day, year = groups
                            if len(year) == 2:
                                year = "20" + year
                        result["document_date"] = f"{year}-{month.zfill(2)}-{day.zfill(2)}"
                        break
                    except (ValueError, IndexError):
                        pass
        
        # Part number patterns
        part_patterns = [
            r'([A-Z]{2,4}[-_]?\d{3,6})',  # GPI-12345, ABC123
            r'(\d{5,8})',                   # 12345678 (5-8 digit numbers)
        ]
        
        for pattern in part_patterns:
            match = re.search(pattern, file_name)
            if match:
                result["project_or_part_number"] = match.group(1)
                break
        
        return result
    
    async def _ensure_destination_columns(
        self,
        site_id: str,
        list_id: str,
        token: str
    ) -> Dict[str, str]:
        """
        Ensure required columns exist in destination library based on Excel metadata structure.
        Returns a mapping of our column names to SharePoint internal names.
        """
        column_mapping = {}  # Maps our names to SharePoint internal names
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            # Get existing columns
            resp = await client.get(
                f"https://graph.microsoft.com/v1.0/sites/{site_id}/lists/{list_id}/columns",
                headers={"Authorization": f"Bearer {token}"}
            )
            
            if resp.status_code != 200:
                logger.warning(f"Could not get columns: {resp.status_code} - {resp.text[:200]}")
                return column_mapping
            
            existing_columns_data = resp.json().get("value", [])
            # Build lookup by both name and displayName (case-insensitive)
            existing_by_name = {}
            existing_by_display = {}
            for col in existing_columns_data:
                col_name = col.get("name", "")
                col_display = col.get("displayName", "")
                existing_by_name[col_name.lower()] = col_name
                existing_by_display[col_display.lower()] = col_name
            
            logger.info(f"Existing columns in destination: {list(existing_by_name.keys())}")
            
            # Create missing columns
            for col_def in REQUIRED_COLUMNS:
                target_name = col_def["name"]
                target_lower = target_name.lower()
                
                # Check if column already exists (by name or displayName)
                if target_lower in existing_by_name:
                    column_mapping[target_name] = existing_by_name[target_lower]
                    logger.debug(f"Column exists: {target_name} -> {column_mapping[target_name]}")
                    continue
                elif target_lower in existing_by_display:
                    column_mapping[target_name] = existing_by_display[target_lower]
                    logger.debug(f"Column exists (by display): {target_name} -> {column_mapping[target_name]}")
                    continue
                
                # Column doesn't exist - create it
                logger.info(f"Creating column: {target_name} (type: {col_def['type']})")
                
                col_payload = {
                    "name": target_name,
                    "displayName": target_name
                }
                
                if col_def["type"] == "text":
                    # Use multi-line text for potentially long fields
                    col_payload["text"] = {
                        "allowMultipleLines": target_name in ["LegacyPath", "LegacyUrl", "DocumentSubType"]
                    }
                elif col_def["type"] == "dateTime":
                    col_payload["dateTime"] = {"displayAs": "default"}
                elif col_def["type"] == "choice":
                    # SharePoint choice column
                    col_payload["choice"] = {
                        "allowTextEntry": True,  # Allow custom values
                        "choices": col_def.get("choices", []),
                        "displayAs": "dropDownMenu"
                    }
                
                create_resp = await client.post(
                    f"https://graph.microsoft.com/v1.0/sites/{site_id}/lists/{list_id}/columns",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json"
                    },
                    json=col_payload
                )
                
                if create_resp.status_code in (200, 201):
                    created_col = create_resp.json()
                    internal_name = created_col.get("name", target_name)
                    column_mapping[target_name] = internal_name
                    logger.info(f"Created column: {target_name} -> {internal_name}")
                else:
                    error_text = create_resp.text[:300]
                    logger.warning(f"Could not create column {target_name}: {create_resp.status_code} - {error_text}")
                    # Still add to mapping with assumed name - SharePoint might accept it
                    column_mapping[target_name] = target_name
        
        return column_mapping
    
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

    async def _upload_large_file(
        self,
        drive_id: str,
        file_name: str,
        file_content: bytes,
        token: str
    ) -> Dict[str, Any]:
        """
        Upload large files using resumable upload session.
        Required for files > 4MB.
        
        Returns the created item info.
        """
        CHUNK_SIZE = 10 * 1024 * 1024  # 10MB chunks (must be multiple of 320KB)
        
        async with httpx.AsyncClient(timeout=300.0) as client:
            # Create upload session
            create_session_url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root:/{file_name}:/createUploadSession"
            
            session_resp = await client.post(
                create_session_url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json"
                },
                json={
                    "item": {
                        "@microsoft.graph.conflictBehavior": "replace",
                        "name": file_name
                    }
                }
            )
            
            if session_resp.status_code not in (200, 201):
                raise Exception(f"Failed to create upload session: {session_resp.status_code} - {session_resp.text[:200]}")
            
            upload_url = session_resp.json()["uploadUrl"]
            file_size = len(file_content)
            
            # Upload in chunks
            start = 0
            while start < file_size:
                end = min(start + CHUNK_SIZE, file_size)
                chunk = file_content[start:end]
                
                content_range = f"bytes {start}-{end-1}/{file_size}"
                
                chunk_resp = await client.put(
                    upload_url,
                    headers={
                        "Content-Length": str(len(chunk)),
                        "Content-Range": content_range
                    },
                    content=chunk
                )
                
                if chunk_resp.status_code == 202:
                    # More chunks needed
                    start = end
                    logger.debug(f"Uploaded chunk {start}/{file_size} for {file_name}")
                elif chunk_resp.status_code in (200, 201):
                    # Upload complete
                    logger.info(f"Large file upload complete: {file_name} ({file_size} bytes)")
                    return chunk_resp.json()
                else:
                    raise Exception(f"Chunk upload failed: {chunk_resp.status_code} - {chunk_resp.text[:200]}")
            
            raise Exception("Upload session completed without final response")
    
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
        
        # Ensure destination columns exist and get mapping
        column_mapping = await self._ensure_destination_columns(target_site_id, target_list_id, token)
        logger.info(f"Column mapping: {column_mapping}")
        
        attempted = 0
        migrated = 0
        errors = 0
        metadata_errors = 0
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
                    
                    file_name = candidate["file_name"]
                    file_size = len(file_content)
                    
                    # Use chunked upload for files > 4MB
                    if file_size > 4 * 1024 * 1024:
                        logger.info(f"Using chunked upload for large file: {file_name} ({file_size} bytes)")
                        new_item = await self._upload_large_file(
                            target_drive_id,
                            file_name,
                            file_content,
                            token
                        )
                    else:
                        # Simple upload for small files
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
                    
                    metadata_write_status = "not_attempted"
                    metadata_write_error = None
                    
                    if list_item_resp.status_code == 200:
                        list_item_id = list_item_resp.json()["id"]
                        
                        # Use column mapping to get correct SharePoint column names
                        def get_col(name):
                            return column_mapping.get(name, name)
                        
                        # Prepare metadata fields - our custom columns only
                        fields = {
                            # Excel metadata columns
                            get_col("AcctType"): candidate.get("acct_type") or "Corporate Internal",
                            get_col("AcctName"): candidate.get("acct_name") or candidate.get("customer_name") or candidate.get("vendor_name") or "",
                            get_col("DocumentType"): candidate.get("document_type") or "Other",
                            get_col("DocumentSubType"): candidate.get("document_sub_type") or "",
                            get_col("DocumentStatus"): candidate.get("document_status") or "Active",
                            # Legacy/tracking fields
                            get_col("ProjectOrPartNumber"): candidate.get("project_or_part_number") or "",
                            get_col("RetentionCategory"): candidate.get("retention_category") or "Unknown",
                            get_col("LegacyPath"): candidate.get("legacy_path") or "",
                            get_col("LegacyUrl"): candidate.get("legacy_url") or "",
                            # Folder tree levels for auditing
                            get_col("Level1"): candidate.get("level1") or "",
                            get_col("Level2"): candidate.get("level2") or "",
                            get_col("Level3"): candidate.get("level3") or "",
                        }
                        
                        # Add DocumentDate if available
                        if candidate.get("document_date"):
                            fields[get_col("DocumentDate")] = candidate["document_date"]
                        
                        logger.info(f"Writing metadata for {file_name}: {list(fields.keys())}")
                        
                        # Update list item fields
                        update_resp = await client.patch(
                            f"https://graph.microsoft.com/v1.0/sites/{target_site_id}/lists/{target_list_id}/items/{list_item_id}/fields",
                            headers={
                                "Authorization": f"Bearer {token}",
                                "Content-Type": "application/json"
                            },
                            json=fields
                        )
                        
                        if update_resp.status_code in (200, 201):
                            metadata_write_status = "success"
                            logger.info(f"Metadata written successfully for {file_name}")
                        else:
                            metadata_write_status = "failed"
                            metadata_write_error = update_resp.text[:300]
                            metadata_errors += 1
                            logger.warning(f"Could not update metadata for {file_name}: {update_resp.status_code} - {metadata_write_error}")
                    else:
                        metadata_write_status = "list_item_not_found"
                        logger.warning(f"Could not get list item for {file_name}: {list_item_resp.status_code}")
                    
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
                            "metadata_write_status": metadata_write_status,
                            "metadata_write_error": metadata_write_error,
                            "updated_utc": now
                        }}
                    )
                    
                    migrated += 1
                    logger.info(f"Migrated: {file_name} (metadata: {metadata_write_status})")
                    
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
        
        logger.info(f"Migration complete: {attempted} attempted, {migrated} migrated, {errors} errors, {metadata_errors} metadata failures")
        
        return {
            "attempted": attempted,
            "migrated": migrated,
            "errors": errors,
            "metadata_errors": metadata_errors
        }
    
    async def get_summary(self) -> Dict[str, Any]:
        """Get summary statistics for migration candidates including new Excel metadata."""
        total = await self.collection.count_documents({})
        
        # Count by status
        status_counts = {}
        for status in ["discovered", "classified", "ready_for_migration", "migrated", "error"]:
            count = await self.collection.count_documents({"status": status})
            status_counts[status] = count
        
        # Count by legacy doc_type
        doc_type_counts = {}
        pipeline = [
            {"$match": {"doc_type": {"$ne": None}}},
            {"$group": {"_id": "$doc_type", "count": {"$sum": 1}}}
        ]
        async for doc in self.collection.aggregate(pipeline):
            doc_type_counts[doc["_id"]] = doc["count"]
        
        # Count by NEW document_type (from Excel structure)
        document_type_counts = {}
        pipeline = [
            {"$match": {"document_type": {"$ne": None}}},
            {"$group": {"_id": "$document_type", "count": {"$sum": 1}}}
        ]
        async for doc in self.collection.aggregate(pipeline):
            document_type_counts[doc["_id"]] = doc["count"]
        
        # Count by acct_type
        acct_type_counts = {}
        pipeline = [
            {"$match": {"acct_type": {"$ne": None}}},
            {"$group": {"_id": "$acct_type", "count": {"$sum": 1}}}
        ]
        async for doc in self.collection.aggregate(pipeline):
            acct_type_counts[doc["_id"]] = doc["count"]
        
        # Count by document_status
        document_status_counts = {}
        pipeline = [
            {"$match": {"document_status": {"$ne": None}}},
            {"$group": {"_id": "$document_status", "count": {"$sum": 1}}}
        ]
        async for doc in self.collection.aggregate(pipeline):
            document_status_counts[doc["_id"]] = doc["count"]
        
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
        
        # Count by classification source (hybrid tracking)
        classification_source = {
            "folder_tree": await self.collection.count_documents({"classification_source": "folder_tree"}),
            "hybrid": await self.collection.count_documents({"classification_source": "hybrid"}),
            "ai": await self.collection.count_documents({"classification_source": "ai"}),
            "not_classified": await self.collection.count_documents({"classification_source": None})
        }
        
        # Count by Level1 (Department from folder tree)
        level1_counts = {}
        pipeline = [
            {"$match": {"level1": {"$ne": None}}},
            {"$group": {"_id": "$level1", "count": {"$sum": 1}}}
        ]
        async for doc in self.collection.aggregate(pipeline):
            level1_counts[doc["_id"]] = doc["count"]
        
        return {
            "total_candidates": total,
            "by_status": status_counts,
            "by_doc_type": doc_type_counts,  # Legacy
            "by_document_type": document_type_counts,  # NEW: Excel structure
            "by_acct_type": acct_type_counts,  # NEW: Excel structure
            "by_document_status": document_status_counts,  # NEW: Excel structure
            "by_confidence": confidence_bands,
            "by_classification_source": classification_source,
            "by_level1": level1_counts
        }
    
    async def get_candidates(
        self,
        status: Optional[str] = None,
        exclude_status: Optional[str] = None,
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
        if exclude_status:
            query["status"] = {"$ne": exclude_status}
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
            # NEW: Excel metadata fields
            "acct_type", "acct_name", "document_type", "document_sub_type", "document_status",
            # Legacy fields
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

    async def apply_metadata_to_migrated(self, candidate_id: str) -> Dict[str, Any]:
        """
        Apply metadata to an already migrated file in SharePoint.
        
        This is used to fix metadata on files that were migrated before columns existed.
        """
        candidate = await self.get_candidate_by_id(candidate_id)
        if not candidate:
            return {"success": False, "error": "Candidate not found", "status": "not_found"}
        
        if candidate.get("status") != "migrated" or not candidate.get("target_item_id"):
            return {"success": False, "error": "Candidate must be migrated with target_item_id", "status": "invalid_state"}
        
        try:
            token = await self._get_graph_token()
            
            # Get target site info
            target_site_url = candidate.get("target_site_url", DEFAULT_TARGET_SITE)
            target_library_name = candidate.get("target_library_name", DEFAULT_TARGET_LIBRARY)
            target_item_id = candidate["target_item_id"]
            
            target_site_id = await self._get_site_id(target_site_url, token)
            target_drive_id = await self._get_drive_id(target_site_id, target_library_name, token)
            target_list_id = await self._get_list_id(target_site_id, target_library_name, token)
            
            # Ensure columns exist
            column_mapping = await self._ensure_destination_columns(target_site_id, target_list_id, token)
            
            # Get the list item ID
            async with httpx.AsyncClient(timeout=60.0) as client:
                list_item_resp = await client.get(
                    f"https://graph.microsoft.com/v1.0/drives/{target_drive_id}/items/{target_item_id}/listItem",
                    headers={"Authorization": f"Bearer {token}"}
                )
                
                if list_item_resp.status_code != 200:
                    error_msg = f"Could not get list item: {list_item_resp.status_code}"
                    return {"success": False, "error": error_msg, "status": "list_item_error"}
                
                list_item_id = list_item_resp.json()["id"]
                
                # Use column mapping to get correct SharePoint column names
                def get_col(name):
                    return column_mapping.get(name, name)
                
                # Prepare metadata fields
                fields = {
                    get_col("AcctType"): candidate.get("acct_type") or "Corporate Internal",
                    get_col("AcctName"): candidate.get("acct_name") or candidate.get("customer_name") or candidate.get("vendor_name") or "",
                    get_col("DocumentType"): candidate.get("document_type") or "Other",
                    get_col("DocumentSubType"): candidate.get("document_sub_type") or "",
                    get_col("DocumentStatus"): candidate.get("document_status") or "Active",
                    get_col("ProjectOrPartNumber"): candidate.get("project_or_part_number") or "",
                    get_col("RetentionCategory"): candidate.get("retention_category") or "Unknown",
                    get_col("LegacyPath"): candidate.get("legacy_path") or "",
                    get_col("LegacyUrl"): candidate.get("legacy_url") or "",
                    get_col("Level1"): candidate.get("level1") or "",
                    get_col("Level2"): candidate.get("level2") or "",
                    get_col("Level3"): candidate.get("level3") or "",
                }
                
                if candidate.get("document_date"):
                    fields[get_col("DocumentDate")] = candidate["document_date"]
                
                logger.info(f"Applying metadata to {candidate['file_name']}: {list(fields.keys())}")
                
                # Update list item fields
                update_resp = await client.patch(
                    f"https://graph.microsoft.com/v1.0/sites/{target_site_id}/lists/{target_list_id}/items/{list_item_id}/fields",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json"
                    },
                    json=fields
                )
                
                if update_resp.status_code in (200, 201):
                    # Update candidate record
                    now = datetime.now(timezone.utc).isoformat()
                    await self.collection.update_one(
                        {"id": candidate_id},
                        {"$set": {
                            "metadata_write_status": "success",
                            "metadata_write_error": None,
                            "updated_utc": now
                        }}
                    )
                    return {"success": True, "status": "success"}
                else:
                    error_msg = update_resp.text[:300]
                    await self.collection.update_one(
                        {"id": candidate_id},
                        {"$set": {
                            "metadata_write_status": "failed",
                            "metadata_write_error": error_msg,
                            "updated_utc": datetime.now(timezone.utc).isoformat()
                        }}
                    )
                    return {"success": False, "error": error_msg, "status": "failed"}
        
        except Exception as e:
            error_msg = str(e)[:250]
            logger.error(f"Error applying metadata to {candidate_id}: {error_msg}")
            return {"success": False, "error": error_msg, "status": "exception"}
