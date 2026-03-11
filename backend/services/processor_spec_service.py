"""
GPI Document Hub — Processor Spec Service

Generates structured implementation specifications from processor
discovery candidates. Outputs:
  1. Human-readable brief
  2. JSON spec
  3. Emergent-ready implementation prompt

NEVER auto-generates or deploys live processor code.

Collection: processor_specs
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)

# ─── Spec status constants ─────────────────────────────────────────────
SPEC_STATUS_DRAFT = "draft"
SPEC_STATUS_READY = "ready"
SPEC_STATUS_APPROVED = "approved"
SPEC_STATUS_IMPLEMENTED = "implemented"
SPEC_STATUS_REJECTED = "rejected"

VALID_STATUSES = {SPEC_STATUS_DRAFT, SPEC_STATUS_READY, SPEC_STATUS_APPROVED,
                  SPEC_STATUS_IMPLEMENTED, SPEC_STATUS_REJECTED}


class ProcessorSpecService:
    """Generate and manage processor implementation specifications."""

    def __init__(self, db, event_service=None):
        self.db = db
        self.event_service = event_service
        self.specs = db.processor_specs

    async def initialize(self):
        """Create indexes for processor_specs collection."""
        await self.specs.create_index("spec_id", unique=True)
        await self.specs.create_index("spec_status")
        await self.specs.create_index("layout_family_id")
        await self.specs.create_index("processor_name")
        await self.specs.create_index("created_at")
        logger.info("[ProcessorSpec] Indexes created")

    # ───────────────────────────────────────────────────────────────────
    # CRUD
    # ───────────────────────────────────────────────────────────────────
    async def create_spec(
        self,
        processor_name: str,
        layout_family_id: str = "",
        doc_type: str = "",
        description: str = "",
        sample_document_ids: Optional[List[str]] = None,
        detection_patterns: Optional[Dict] = None,
        field_mappings: Optional[List[Dict]] = None,
        vendor_hints: Optional[List[str]] = None,
        reference_hints: Optional[List[Dict]] = None,
        notes: str = "",
    ) -> Dict[str, Any]:
        """Create a new processor spec in DRAFT status."""
        spec_id = f"spec_{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).isoformat()

        spec = {
            "spec_id": spec_id,
            "processor_name": processor_name,
            "layout_family_id": layout_family_id,
            "doc_type": doc_type,
            "description": description,
            "spec_status": SPEC_STATUS_DRAFT,
            "sample_document_ids": sample_document_ids or [],
            "detection_patterns": detection_patterns or {
                "keywords": [],
                "layout_hints": [],
                "vendor_patterns": [],
            },
            "field_mappings": field_mappings or [],
            "vendor_hints": vendor_hints or [],
            "reference_hints": reference_hints or [],
            "notes": notes,
            "generated_brief": "",
            "generated_json_spec": {},
            "generated_prompt": "",
            "created_at": now,
            "updated_at": now,
        }

        await self.specs.insert_one(spec)
        # Remove _id before returning
        spec.pop("_id", None)
        logger.info("[ProcessorSpec] Created spec %s: %s", spec_id, processor_name)
        return spec

    async def get_spec(self, spec_id: str) -> Optional[Dict]:
        return await self.specs.find_one({"spec_id": spec_id}, {"_id": 0})

    async def list_specs(
        self,
        status: Optional[str] = None,
        limit: int = 50,
        skip: int = 0,
    ) -> Dict[str, Any]:
        query = {}
        if status:
            query["spec_status"] = status
        cursor = self.specs.find(query, {"_id": 0}).sort("created_at", -1).skip(skip).limit(limit)
        specs = await cursor.to_list(length=limit)
        total = await self.specs.count_documents(query)
        return {"specs": specs, "total": total, "limit": limit, "skip": skip}

    async def update_spec(self, spec_id: str, updates: Dict[str, Any]) -> Optional[Dict]:
        """Update spec fields. Does NOT allow changing spec_id."""
        updates.pop("spec_id", None)
        updates.pop("_id", None)
        updates["updated_at"] = datetime.now(timezone.utc).isoformat()

        result = await self.specs.find_one_and_update(
            {"spec_id": spec_id},
            {"$set": updates},
            return_document=True,
            projection={"_id": 0},
        )
        return result

    async def delete_spec(self, spec_id: str) -> bool:
        result = await self.specs.delete_one({"spec_id": spec_id})
        return result.deleted_count > 0

    async def set_status(self, spec_id: str, new_status: str) -> Optional[Dict]:
        if new_status not in VALID_STATUSES:
            return None
        return await self.update_spec(spec_id, {"spec_status": new_status})

    # ───────────────────────────────────────────────────────────────────
    # GENERATION — create outputs from spec data
    # ───────────────────────────────────────────────────────────────────
    async def generate_outputs(self, spec_id: str) -> Dict[str, Any]:
        """
        Generate all three outputs for a spec:
          1. Human-readable brief
          2. JSON spec
          3. Implementation prompt
        Updates the spec in-place and returns the generated outputs.
        """
        spec = await self.get_spec(spec_id)
        if not spec:
            return {"error": "Spec not found"}

        brief = self._generate_brief(spec)
        json_spec = self._generate_json_spec(spec)
        prompt = self._generate_prompt(spec)

        await self.update_spec(spec_id, {
            "generated_brief": brief,
            "generated_json_spec": json_spec,
            "generated_prompt": prompt,
            "spec_status": SPEC_STATUS_READY,
        })

        return {
            "spec_id": spec_id,
            "brief": brief,
            "json_spec": json_spec,
            "prompt": prompt,
        }

    async def generate_from_candidate(
        self,
        candidate_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Generate a spec from a processor discovery candidate.
        candidate_data should have:
          - processor_name
          - layout_family_id (optional)
          - doc_type
          - sample_texts or sample_document_ids
          - detected_fields
          - detected_vendor_patterns
          - detected_keywords
        """
        # Extract data from candidate
        processor_name = candidate_data.get("processor_name", "NewProcessor")
        layout_family_id = candidate_data.get("layout_family_id", "")
        doc_type = candidate_data.get("doc_type", "")
        description = candidate_data.get("description", f"Auto-generated spec for {processor_name}")

        # Build detection patterns from candidate
        detection_patterns = {
            "keywords": candidate_data.get("detected_keywords", []),
            "layout_hints": candidate_data.get("layout_hints", []),
            "vendor_patterns": candidate_data.get("detected_vendor_patterns", []),
        }

        # Build field mappings from detected fields
        field_mappings = []
        for field_name, field_info in (candidate_data.get("detected_fields") or {}).items():
            mapping = {
                "field_name": field_name,
                "field_type": field_info.get("type", "string"),
                "extraction_hint": field_info.get("hint", ""),
                "required": field_info.get("required", False),
                "sample_values": field_info.get("sample_values", []),
            }
            field_mappings.append(mapping)

        # Build reference hints
        reference_hints = []
        for ref in candidate_data.get("reference_patterns", []):
            reference_hints.append({
                "label": ref.get("label", "REF"),
                "pattern": ref.get("pattern", ""),
                "example": ref.get("example", ""),
            })

        spec = await self.create_spec(
            processor_name=processor_name,
            layout_family_id=layout_family_id,
            doc_type=doc_type,
            description=description,
            sample_document_ids=candidate_data.get("sample_document_ids", []),
            detection_patterns=detection_patterns,
            field_mappings=field_mappings,
            vendor_hints=candidate_data.get("vendor_hints", []),
            reference_hints=reference_hints,
            notes=f"Auto-generated from candidate: {candidate_data.get('source', 'unknown')}",
        )

        # Auto-generate outputs
        outputs = await self.generate_outputs(spec["spec_id"])
        spec.update(outputs)
        
        # Re-fetch to get updated spec_status after generation
        updated_spec = await self.get_spec(spec["spec_id"])
        if updated_spec:
            spec["spec_status"] = updated_spec["spec_status"]

        return spec

    # ───────────────────────────────────────────────────────────────────
    # STATS
    # ───────────────────────────────────────────────────────────────────
    async def get_stats(self) -> Dict[str, Any]:
        total = await self.specs.count_documents({})
        pipeline = [
            {"$group": {"_id": "$spec_status", "count": {"$sum": 1}}}
        ]
        by_status = {}
        async for doc in self.specs.aggregate(pipeline):
            by_status[doc["_id"]] = doc["count"]
        return {"total": total, "by_status": by_status}

    # ===================================================================
    # INTERNAL — generation logic
    # ===================================================================
    def _generate_brief(self, spec: Dict) -> str:
        """Generate a human-readable implementation brief."""
        lines = []
        lines.append(f"# Processor Implementation Brief: {spec['processor_name']}")
        lines.append("")
        lines.append(f"**Document Type:** {spec.get('doc_type', 'N/A')}")
        lines.append(f"**Layout Family:** {spec.get('layout_family_id', 'N/A')}")
        lines.append(f"**Description:** {spec.get('description', 'N/A')}")
        lines.append("")

        # Detection section
        lines.append("## Detection Criteria")
        det = spec.get("detection_patterns", {})
        if det.get("keywords"):
            lines.append(f"**Keywords:** {', '.join(det['keywords'])}")
        if det.get("layout_hints"):
            lines.append(f"**Layout Hints:** {', '.join(det['layout_hints'])}")
        if det.get("vendor_patterns"):
            lines.append(f"**Vendor Patterns:** {', '.join(det['vendor_patterns'])}")
        lines.append("")

        # Field mappings
        lines.append("## Field Mappings")
        for fm in spec.get("field_mappings", []):
            req = " (REQUIRED)" if fm.get("required") else ""
            lines.append(f"- **{fm['field_name']}** ({fm.get('field_type', 'string')}){req}")
            if fm.get("extraction_hint"):
                lines.append(f"  Hint: {fm['extraction_hint']}")
            if fm.get("sample_values"):
                lines.append(f"  Examples: {', '.join(str(v) for v in fm['sample_values'][:3])}")
        lines.append("")

        # Reference hints
        if spec.get("reference_hints"):
            lines.append("## Reference Patterns")
            for rh in spec["reference_hints"]:
                lines.append(f"- **{rh.get('label', 'REF')}**: `{rh.get('pattern', '')}`")
                if rh.get("example"):
                    lines.append(f"  Example: {rh['example']}")
            lines.append("")

        # Vendor hints
        if spec.get("vendor_hints"):
            lines.append("## Vendor Hints")
            lines.append(f"Known vendors: {', '.join(spec['vendor_hints'])}")
            lines.append("")

        # Sample documents
        if spec.get("sample_document_ids"):
            lines.append("## Sample Documents")
            for sid in spec["sample_document_ids"]:
                lines.append(f"- `{sid}`")
            lines.append("")

        if spec.get("notes"):
            lines.append("## Notes")
            lines.append(spec["notes"])

        return "\n".join(lines)

    def _generate_json_spec(self, spec: Dict) -> Dict:
        """Generate a structured JSON spec for the processor."""
        return {
            "processor_name": spec["processor_name"],
            "version": "1.0.0",
            "doc_type": spec.get("doc_type", ""),
            "layout_family_id": spec.get("layout_family_id", ""),
            "detection": {
                "keywords": spec.get("detection_patterns", {}).get("keywords", []),
                "layout_hints": spec.get("detection_patterns", {}).get("layout_hints", []),
                "vendor_patterns": spec.get("detection_patterns", {}).get("vendor_patterns", []),
            },
            "fields": [
                {
                    "name": fm["field_name"],
                    "type": fm.get("field_type", "string"),
                    "required": fm.get("required", False),
                    "extraction_hint": fm.get("extraction_hint", ""),
                }
                for fm in spec.get("field_mappings", [])
            ],
            "references": [
                {
                    "label": rh.get("label", "REF"),
                    "pattern": rh.get("pattern", ""),
                }
                for rh in spec.get("reference_hints", [])
            ],
            "vendor_hints": spec.get("vendor_hints", []),
        }

    def _generate_prompt(self, spec: Dict) -> str:
        """Generate an Emergent-ready implementation prompt."""
        lines = []
        lines.append(f"Create a document processor class called `{spec['processor_name']}` that inherits from `DocumentProcessor`.")
        lines.append("")
        lines.append(f"This processor handles **{spec.get('doc_type', 'unknown')}** documents.")
        lines.append(f"Description: {spec.get('description', 'N/A')}")
        lines.append("")

        # Detection
        det = spec.get("detection_patterns", {})
        lines.append("## detect() Method")
        lines.append("Return True if the document_text contains any of the following signals:")
        if det.get("keywords"):
            lines.append(f"- Keywords (case-insensitive): {', '.join(det['keywords'])}")
        if det.get("vendor_patterns"):
            lines.append(f"- Vendor patterns: {', '.join(det['vendor_patterns'])}")
        if det.get("layout_hints"):
            lines.append(f"- Layout hints: {', '.join(det['layout_hints'])}")
        lines.append("")

        # Extract
        lines.append("## extract() Method")
        lines.append("Extract the following fields using regex or text parsing:")
        for fm in spec.get("field_mappings", []):
            req = " (REQUIRED)" if fm.get("required") else ""
            hint = f" — {fm['extraction_hint']}" if fm.get("extraction_hint") else ""
            lines.append(f"- `{fm['field_name']}` ({fm.get('field_type', 'string')}){req}{hint}")
        lines.append("")

        # References
        if spec.get("reference_hints"):
            lines.append("## suggest_references() Method")
            lines.append("Return reference candidates for these patterns:")
            for rh in spec["reference_hints"]:
                lines.append(f"- Label: `{rh.get('label', 'REF')}`, Pattern: `{rh.get('pattern', '')}`")
            lines.append("")

        # Vendor
        if spec.get("vendor_hints"):
            lines.append("## suggest_vendor() Method")
            lines.append(f"Check if extracted fields match known vendors: {', '.join(spec['vendor_hints'])}")
            lines.append("")

        lines.append("## Implementation Notes")
        lines.append("- Inherit from `processors.document_processor.DocumentProcessor`")
        lines.append("- The processor must be stateless and pure-extraction only")
        lines.append("- No BC writes, no validation bypass")
        lines.append("- Register with priority 100-199")
        lines.append(f"- File location: `/app/backend/processors/{spec['processor_name'].lower()}_processor.py`")

        if spec.get("notes"):
            lines.append("")
            lines.append(f"Additional context: {spec['notes']}")

        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════
# Module-level singleton management
# ═══════════════════════════════════════════════════════════════════════
_instance: Optional[ProcessorSpecService] = None


def set_processor_spec_service(db, event_service=None) -> ProcessorSpecService:
    global _instance
    _instance = ProcessorSpecService(db, event_service)
    return _instance


def get_processor_spec_service() -> Optional[ProcessorSpecService]:
    return _instance
