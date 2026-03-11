"""
GPI Document Hub - Document Layout Fingerprinting Service

Detects structural patterns in documents and groups them into layout families.
Uses relative zones, token density, keyword signatures — NOT absolute coordinates.

KEY PRINCIPLES:
- NEVER stores absolute extraction coordinates
- NEVER creates rigid templates or vendor-specific field maps
- NEVER replaces OCR/AI extraction
- Uses relative zones (top/middle/bottom, left/center/right) only
- Purely probabilistic, structural, additive

Layout families are used as:
- Interpretation hints for the resolver
- Confidence modifiers
- Vendor-learning segmentation
- Anomaly detection (new format detection)
"""

import hashlib
import logging
import re
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Tuple

logger = logging.getLogger(__name__)

# Similarity threshold for assigning to existing family
FAMILY_SIMILARITY_THRESHOLD = 0.90
# Minimum documents to form a meaningful family
MIN_DOCS_FOR_FAMILY_STATS = 3
# Maximum layout family bias influence on resolver scoring
MAX_LAYOUT_FAMILY_BIAS = 0.15
# Fingerprint version for idempotency
FINGERPRINT_VERSION = "1.0"

# Keywords we look for in document zones
STRUCTURAL_KEYWORDS = {
    "invoice": ["invoice", "inv", "bill", "amount due", "total due", "remit to", "payment terms"],
    "bol": ["bill of lading", "bol", "b/l", "shipper", "consignee", "carrier", "pro number"],
    "po": ["purchase order", "po #", "p.o.", "buyer", "ship to", "deliver to"],
    "shipment": ["shipment", "tracking", "ship date", "delivery date", "freight"],
    "credit": ["credit memo", "credit note", "refund", "return"],
    "statement": ["statement", "account summary", "balance due", "aging"],
    "freight": ["freight charge", "weight", "class", "nmfc", "pieces", "pallets"],
}

# Relative page zones (thirds)
ZONE_MAP = {
    "top": (0.0, 0.33),
    "middle": (0.33, 0.66),
    "bottom": (0.66, 1.0),
}


# =============================================================================
# STRUCTURAL SIGNATURE GENERATION
# =============================================================================

def _split_text_into_zones(text: str) -> Dict[str, str]:
    """Split text into top/middle/bottom zones by line count."""
    if not text:
        return {"top": "", "middle": "", "bottom": ""}

    lines = text.split("\n")
    total = len(lines)
    if total == 0:
        return {"top": "", "middle": "", "bottom": ""}

    third = max(total // 3, 1)
    return {
        "top": "\n".join(lines[:third]),
        "middle": "\n".join(lines[third:2*third]),
        "bottom": "\n".join(lines[2*third:]),
    }


def _compute_token_density(text: str) -> Dict[str, float]:
    """Compute token density per zone (tokens per line)."""
    zones = _split_text_into_zones(text)
    densities = {}
    for zone_name, zone_text in zones.items():
        lines = [line for line in zone_text.split("\n") if line.strip()]
        if not lines:
            densities[zone_name] = 0.0
            continue
        total_tokens = sum(len(line.split()) for line in lines)
        densities[zone_name] = round(total_tokens / len(lines), 2)
    return densities


def _compute_keyword_signature(text: str) -> Dict[str, Dict[str, List[str]]]:
    """
    Find which keyword categories appear in which zones.
    Returns: {category: {zone: [keywords_found]}}
    """
    zones = _split_text_into_zones(text)
    signature = {}

    for category, keywords in STRUCTURAL_KEYWORDS.items():
        category_sig = {}
        for zone_name, zone_text in zones.items():
            zone_lower = zone_text.lower()
            found = [kw for kw in keywords if kw in zone_lower]
            if found:
                category_sig[zone_name] = found
        if category_sig:
            signature[category] = category_sig

    return signature


def _detect_tables(text: str) -> Dict[str, Any]:
    """
    Detect table-like structures by looking for consistent column patterns.
    Uses relative zone positioning, never absolute coordinates.
    """
    lines = text.split("\n") if text else []
    total_lines = len(lines)
    if total_lines == 0:
        return {"table_count": 0, "table_zones": [], "avg_columns": 0}

    # Detect lines that look tabular (multiple whitespace-separated columns)
    table_regions = []
    consecutive_tabular = 0
    region_start = 0

    for i, line in enumerate(lines):
        # A "tabular" line has 3+ columns separated by 2+ spaces or tabs
        cols = re.split(r'\s{2,}|\t', line.strip())
        cols = [c for c in cols if c.strip()]
        if len(cols) >= 3:
            if consecutive_tabular == 0:
                region_start = i
            consecutive_tabular += 1
        else:
            if consecutive_tabular >= 3:
                zone = "top" if region_start < total_lines / 3 else (
                    "middle" if region_start < 2 * total_lines / 3 else "bottom"
                )
                table_regions.append({
                    "zone": zone,
                    "row_count": consecutive_tabular,
                    "relative_start": round(region_start / total_lines, 2),
                })
            consecutive_tabular = 0

    # Handle trailing table
    if consecutive_tabular >= 3:
        zone = "top" if region_start < total_lines / 3 else (
            "middle" if region_start < 2 * total_lines / 3 else "bottom"
        )
        table_regions.append({
            "zone": zone,
            "row_count": consecutive_tabular,
            "relative_start": round(region_start / total_lines, 2),
        })

    avg_cols = 0
    if table_regions:
        avg_cols = round(sum(r["row_count"] for r in table_regions) / len(table_regions), 1)

    return {
        "table_count": len(table_regions),
        "table_zones": [r["zone"] for r in table_regions],
        "avg_rows_per_table": avg_cols,
        "table_regions": table_regions,
    }


def _compute_whitespace_distribution(text: str) -> Dict[str, float]:
    """Compute whitespace ratio per zone."""
    zones = _split_text_into_zones(text)
    ratios = {}
    for zone_name, zone_text in zones.items():
        if not zone_text:
            ratios[zone_name] = 0.0
            continue
        total_chars = len(zone_text)
        whitespace_chars = sum(1 for c in zone_text if c in (' ', '\t', '\n'))
        ratios[zone_name] = round(whitespace_chars / max(total_chars, 1), 3)
    return ratios


def _compute_header_footer_density(text: str) -> Dict[str, float]:
    """Compute relative header and footer density."""
    lines = text.split("\n") if text else []
    total = len(lines)
    if total < 6:
        return {"header_density": 0.0, "footer_density": 0.0}

    header_lines = lines[:max(total // 10, 3)]
    footer_lines = lines[-max(total // 10, 3):]

    header_tokens = sum(len(hl.split()) for hl in header_lines if hl.strip())
    footer_tokens = sum(len(fl.split()) for fl in footer_lines if fl.strip())

    body_tokens = sum(len(bl.split()) for bl in lines if bl.strip())
    body_tokens = max(body_tokens, 1)

    return {
        "header_density": round(header_tokens / body_tokens, 4),
        "footer_density": round(footer_tokens / body_tokens, 4),
    }


def _count_label_clusters(text: str) -> Dict[str, int]:
    """Count occurrences of known label patterns in document."""
    text_lower = (text or "").lower()
    clusters = {}
    label_patterns = {
        "invoice_labels": [r"invoice\s*#", r"invoice\s+number", r"inv\s*#", r"inv\s+no"],
        "po_labels": [r"p\.?o\.?\s*#", r"purchase\s+order", r"po\s+number"],
        "bol_labels": [r"b\.?o\.?l\.?\s*#", r"bill\s+of\s+lading", r"b/l"],
        "shipment_labels": [r"shipment\s*#", r"ship\s+date", r"tracking"],
        "date_labels": [r"date\s*:", r"invoice\s+date", r"due\s+date", r"ship\s+date"],
        "amount_labels": [r"total\s*:", r"amount\s+due", r"subtotal", r"grand\s+total"],
        "reference_labels": [r"ref\s*#", r"reference", r"customer\s+ref"],
    }
    for cluster_name, patterns in label_patterns.items():
        count = 0
        for pat in patterns:
            count += len(re.findall(pat, text_lower))
        if count > 0:
            clusters[cluster_name] = count
    return clusters


def generate_structural_signature(text: str, page_count: int = 1) -> Dict[str, Any]:
    """
    Generate a complete structural signature for a document.
    Uses only relative positioning — never absolute coordinates.
    """
    line_count = len(text.split("\n")) if text else 0

    signature = {
        "page_count": page_count,
        "line_count": line_count,
        "token_density": _compute_token_density(text),
        "keyword_signature": _compute_keyword_signature(text),
        "table_signature": _detect_tables(text),
        "whitespace_distribution": _compute_whitespace_distribution(text),
        "header_footer": _compute_header_footer_density(text),
        "label_clusters": _count_label_clusters(text),
        "version": FINGERPRINT_VERSION,
    }

    return signature


def compute_fingerprint_hash(signature: Dict[str, Any]) -> str:
    """
    Compute a deterministic hash from the structural signature.
    This is the 'layout fingerprint'.
    """
    # Build a canonical string from signature components
    parts = []
    parts.append(f"pc:{signature.get('page_count', 0)}")
    parts.append(f"lc:{signature.get('line_count', 0) // 10}")  # bucket by 10s

    td = signature.get("token_density", {})
    for zone in ["top", "middle", "bottom"]:
        parts.append(f"td_{zone}:{int(td.get(zone, 0))}")

    ks = signature.get("keyword_signature", {})
    for cat in sorted(ks.keys()):
        zones = sorted(ks[cat].keys())
        parts.append(f"kw_{cat}:{','.join(zones)}")

    ts = signature.get("table_signature", {})
    parts.append(f"tc:{ts.get('table_count', 0)}")
    parts.append(f"tz:{','.join(sorted(ts.get('table_zones', [])))}")

    lc = signature.get("label_clusters", {})
    for cluster_name in sorted(lc.keys()):
        parts.append(f"lbl_{cluster_name}:{min(lc[cluster_name], 5)}")  # cap at 5

    hf = signature.get("header_footer", {})
    parts.append(f"hd:{int(hf.get('header_density', 0) * 100)}")
    parts.append(f"fd:{int(hf.get('footer_density', 0) * 100)}")

    canonical = "|".join(parts)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


# =============================================================================
# SIMILARITY SCORING
# =============================================================================

def compute_family_similarity(sig_a: Dict, sig_b: Dict) -> float:
    """
    Compute structural similarity between two signatures.
    Returns a score between 0.0 and 1.0.
    """
    scores = []
    weights = []

    # 1. Page count similarity (weight: 0.10)
    pc_a = sig_a.get("page_count", 1)
    pc_b = sig_b.get("page_count", 1)
    pc_sim = 1.0 if pc_a == pc_b else max(0, 1.0 - abs(pc_a - pc_b) * 0.3)
    scores.append(pc_sim)
    weights.append(0.10)

    # 2. Token density pattern similarity (weight: 0.20)
    td_a = sig_a.get("token_density", {})
    td_b = sig_b.get("token_density", {})
    td_diffs = []
    for zone in ["top", "middle", "bottom"]:
        a_val = td_a.get(zone, 0)
        b_val = td_b.get(zone, 0)
        max_val = max(a_val, b_val, 1)
        td_diffs.append(1.0 - abs(a_val - b_val) / max_val)
    td_sim = sum(td_diffs) / len(td_diffs) if td_diffs else 0
    scores.append(td_sim)
    weights.append(0.20)

    # 3. Keyword signature similarity (weight: 0.25)
    ks_a = set()
    for cat, zones in sig_a.get("keyword_signature", {}).items():
        for z in zones:
            ks_a.add(f"{cat}:{z}")
    ks_b = set()
    for cat, zones in sig_b.get("keyword_signature", {}).items():
        for z in zones:
            ks_b.add(f"{cat}:{z}")
    if ks_a or ks_b:
        intersection = ks_a & ks_b
        union = ks_a | ks_b
        ks_sim = len(intersection) / len(union) if union else 0
    else:
        ks_sim = 1.0  # both empty = same
    scores.append(ks_sim)
    weights.append(0.25)

    # 4. Table structure similarity (weight: 0.20)
    ts_a = sig_a.get("table_signature", {})
    ts_b = sig_b.get("table_signature", {})
    tc_a = ts_a.get("table_count", 0)
    tc_b = ts_b.get("table_count", 0)
    tc_sim = 1.0 if tc_a == tc_b else max(0, 1.0 - abs(tc_a - tc_b) * 0.25)
    tz_a = set(ts_a.get("table_zones", []))
    tz_b = set(ts_b.get("table_zones", []))
    if tz_a or tz_b:
        tz_sim = len(tz_a & tz_b) / len(tz_a | tz_b)
    else:
        tz_sim = 1.0
    table_sim = (tc_sim + tz_sim) / 2
    scores.append(table_sim)
    weights.append(0.20)

    # 5. Label cluster similarity (weight: 0.15)
    lc_a = sig_a.get("label_clusters", {})
    lc_b = sig_b.get("label_clusters", {})
    all_clusters = set(list(lc_a.keys()) + list(lc_b.keys()))
    if all_clusters:
        cluster_diffs = []
        for c in all_clusters:
            a_v = min(lc_a.get(c, 0), 5)
            b_v = min(lc_b.get(c, 0), 5)
            cluster_diffs.append(1.0 - abs(a_v - b_v) / 5)
        lc_sim = sum(cluster_diffs) / len(cluster_diffs)
    else:
        lc_sim = 1.0
    scores.append(lc_sim)
    weights.append(0.15)

    # 6. Header/footer density similarity (weight: 0.10)
    hf_a = sig_a.get("header_footer", {})
    hf_b = sig_b.get("header_footer", {})
    hd_diff = abs(hf_a.get("header_density", 0) - hf_b.get("header_density", 0))
    fd_diff = abs(hf_a.get("footer_density", 0) - hf_b.get("footer_density", 0))
    hf_sim = 1.0 - min((hd_diff + fd_diff) / 2, 1.0)
    scores.append(hf_sim)
    weights.append(0.10)

    # Weighted sum
    total_weight = sum(weights)
    similarity = sum(s * w for s, w in zip(scores, weights)) / total_weight
    return round(similarity, 4)


# =============================================================================
# MAIN SERVICE CLASS
# =============================================================================

class LayoutFingerprintService:
    """
    Manages document layout fingerprints and layout families.
    Groups structurally similar documents for vendor-learning segmentation.
    """

    def __init__(self, db, event_service=None):
        self.db = db
        self.event_service = event_service
        self.fingerprints_collection = db.document_layout_fingerprints
        self.families_collection = db.layout_families

    async def initialize(self):
        """Create indexes."""
        await self.fingerprints_collection.create_index("document_id", unique=True)
        await self.fingerprints_collection.create_index("vendor_no")
        await self.fingerprints_collection.create_index("layout_family_id")
        await self.fingerprints_collection.create_index("layout_fingerprint")
        await self.fingerprints_collection.create_index("created_at")

        await self.families_collection.create_index("layout_family_id", unique=True)
        await self.families_collection.create_index("vendor_no")
        await self.families_collection.create_index("document_type")
        await self.families_collection.create_index([("vendor_no", 1), ("document_type", 1)])
        await self.families_collection.create_index("status")

        logger.info("[LayoutFingerprint] Indexes created")

    # =========================================================================
    # FINGERPRINT GENERATION (Part 2)
    # =========================================================================

    async def generate_fingerprint(
        self,
        document_id: str,
        document_text: str,
        document: Dict[str, Any],
        force: bool = False
    ) -> Optional[Dict[str, Any]]:
        """
        Generate a layout fingerprint for a document.
        Idempotent: skips if already computed for same content hash.
        """
        if not document_text or len(document_text.strip()) < 50:
            return None

        # Idempotency check
        content_hash = hashlib.sha256(document_text.encode()).hexdigest()[:16]
        if not force:
            existing = await self.fingerprints_collection.find_one(
                {"document_id": document_id},
                {"_id": 0, "layout_hash": 1, "layout_fingerprint_version": 1}
            )
            if (existing and
                    existing.get("layout_hash") == content_hash and
                    existing.get("layout_fingerprint_version") == FINGERPRINT_VERSION):
                return await self.fingerprints_collection.find_one(
                    {"document_id": document_id}, {"_id": 0}
                )

        # Extract document metadata
        vendor_no = ""
        vendor_name = ""
        uvm = document.get("unified_vendor_match") or {}
        if uvm:
            vendor_no = uvm.get("bc_vendor_no", "")
            vendor_name = uvm.get("bc_vendor_name", "") or uvm.get("matched_name", "")
        if not vendor_name:
            vendor_name = document.get("vendor_raw") or document.get("matched_vendor_name") or ""
        if not vendor_no:
            vendor_no = vendor_name

        doc_type = document.get("document_type") or document.get("suggested_job_type") or "Unknown"
        page_count = document.get("page_count") or 1

        # Generate structural signature
        structural_sig = generate_structural_signature(document_text, page_count)
        fingerprint_hash = compute_fingerprint_hash(structural_sig)

        now = datetime.now(timezone.utc).isoformat()

        fingerprint_doc = {
            "document_id": document_id,
            "vendor_no": vendor_no,
            "vendor_name": vendor_name,
            "document_type": doc_type,
            "layout_fingerprint": fingerprint_hash,
            "layout_family_id": None,
            "layout_similarity_score": None,
            "page_count": page_count,
            "structural_signature": structural_sig,
            "keyword_signature": structural_sig.get("keyword_signature", {}),
            "table_signature": structural_sig.get("table_signature", {}),
            "header_signature": structural_sig.get("header_footer", {}),
            "footer_signature": structural_sig.get("header_footer", {}),
            "token_density_signature": structural_sig.get("token_density", {}),
            "layout_fingerprint_version": FINGERPRINT_VERSION,
            "layout_hash": content_hash,
            "layout_last_run": now,
            "new_layout_detected": False,
            "created_at": now,
        }

        # Assign to family
        family_id, similarity, is_new = await self._assign_to_family(
            fingerprint_hash, structural_sig, vendor_no, doc_type
        )
        fingerprint_doc["layout_family_id"] = family_id
        fingerprint_doc["layout_similarity_score"] = similarity
        fingerprint_doc["new_layout_detected"] = is_new

        # Upsert fingerprint
        await self.fingerprints_collection.update_one(
            {"document_id": document_id},
            {"$set": fingerprint_doc, "$setOnInsert": {"first_created_at": now}},
            upsert=True
        )

        # Emit events
        if self.event_service:
            await self.event_service.emit(
                event_type="layout.fingerprint.generated",
                document_id=document_id,
                source_service="layout_fingerprint",
                payload={
                    "layout_fingerprint": fingerprint_hash,
                    "layout_family_id": family_id,
                    "similarity": similarity,
                    "new_layout_detected": is_new,
                }
            )
            if is_new:
                await self.event_service.emit(
                    event_type="layout.new_family.detected",
                    document_id=document_id,
                    source_service="layout_fingerprint",
                    payload={
                        "vendor_no": vendor_no,
                        "vendor_name": vendor_name,
                        "document_type": doc_type,
                        "layout_family_id": family_id,
                    }
                )

        logger.info(
            "[LayoutFingerprint] Doc %s: fp=%s family=%s sim=%.2f new=%s",
            document_id[:8], fingerprint_hash[:8], family_id[:12] if family_id else "none",
            similarity or 0, is_new
        )

        return fingerprint_doc

    # =========================================================================
    # FAMILY ASSIGNMENT (Part 3)
    # =========================================================================

    async def _assign_to_family(
        self,
        fingerprint_hash: str,
        signature: Dict,
        vendor_no: str,
        doc_type: str
    ) -> Tuple[str, float, bool]:
        """
        Assign a fingerprint to an existing or new layout family.
        Returns: (family_id, similarity_score, is_new_family)
        """
        # Look for existing families for this vendor + doc type
        cursor = self.families_collection.find(
            {"vendor_no": vendor_no, "document_type": doc_type, "status": "active"},
            {"_id": 0}
        )
        existing_families = await cursor.to_list(50)

        best_family = None
        best_similarity = 0.0

        for family in existing_families:
            centroid = family.get("fingerprint_centroid", {})
            if not centroid:
                continue
            sim = compute_family_similarity(signature, centroid)
            if sim > best_similarity:
                best_similarity = sim
                best_family = family

        now = datetime.now(timezone.utc).isoformat()

        if best_family and best_similarity >= FAMILY_SIMILARITY_THRESHOLD:
            # Assign to existing family
            family_id = best_family["layout_family_id"]
            await self.families_collection.update_one(
                {"layout_family_id": family_id},
                {
                    "$inc": {"documents_count": 1},
                    "$set": {"last_seen": now},
                }
            )
            return family_id, best_similarity, False
        else:
            # Create new family
            vendor_prefix = re.sub(r'[^A-Z0-9]', '', (vendor_no or "UNKNOWN").upper())[:10]
            type_prefix = re.sub(r'[^A-Z0-9]', '', (doc_type or "UNK").upper())[:8]
            suffix = fingerprint_hash[:6].upper()
            family_id = f"{vendor_prefix}_{type_prefix}_{suffix}"

            family_doc = {
                "layout_family_id": family_id,
                "vendor_no": vendor_no,
                "document_type": doc_type,
                "fingerprint_centroid": signature,
                "documents_count": 1,
                "first_seen": now,
                "last_seen": now,
                "status": "active",
                "notes": "",
                "performance_metrics": {
                    "automation_success_count": 0,
                    "automation_total_count": 0,
                    "automation_success_rate": 0.0,
                    "resolution_success_count": 0,
                    "resolution_total_count": 0,
                    "resolution_success_rate": 0.0,
                    "mislabel_count": 0,
                    "reference_label_distribution": {},
                    "bc_entity_distribution": {},
                },
                "created_at": now,
            }

            try:
                await self.families_collection.insert_one(family_doc)
            except Exception:
                # Duplicate key — race condition; re-fetch
                existing = await self.families_collection.find_one(
                    {"layout_family_id": family_id}, {"_id": 0}
                )
                if existing:
                    await self.families_collection.update_one(
                        {"layout_family_id": family_id},
                        {"$inc": {"documents_count": 1}, "$set": {"last_seen": now}}
                    )
                    return family_id, best_similarity, False

            return family_id, best_similarity, True

    # =========================================================================
    # VENDOR INTELLIGENCE PER FAMILY (Part 5)
    # =========================================================================

    async def update_family_metrics(
        self,
        document_id: str,
        resolution_success: bool = False,
        automation_success: bool = False,
        mislabel_detected: bool = False,
        reference_label: str = None,
        bc_entity_type: str = None
    ):
        """Update layout family performance metrics after document processing."""
        fp = await self.fingerprints_collection.find_one(
            {"document_id": document_id},
            {"_id": 0, "layout_family_id": 1}
        )
        if not fp or not fp.get("layout_family_id"):
            return

        family_id = fp["layout_family_id"]

        update_ops = {
            "$inc": {
                "performance_metrics.resolution_total_count": 1,
            },
            "$set": {
                "last_seen": datetime.now(timezone.utc).isoformat(),
            }
        }

        if resolution_success:
            update_ops["$inc"]["performance_metrics.resolution_success_count"] = 1
        if automation_success:
            update_ops["$inc"]["performance_metrics.automation_total_count"] = 1
            update_ops["$inc"]["performance_metrics.automation_success_count"] = 1
        if mislabel_detected:
            update_ops["$inc"]["performance_metrics.mislabel_count"] = 1
        if reference_label:
            update_ops["$inc"][f"performance_metrics.reference_label_distribution.{reference_label}"] = 1
        if bc_entity_type:
            update_ops["$inc"][f"performance_metrics.bc_entity_distribution.{bc_entity_type}"] = 1

        await self.families_collection.update_one(
            {"layout_family_id": family_id},
            update_ops
        )

        # Recompute rates
        family = await self.families_collection.find_one(
            {"layout_family_id": family_id}, {"_id": 0, "performance_metrics": 1}
        )
        if family:
            pm = family.get("performance_metrics", {})
            res_total = pm.get("resolution_total_count", 0)
            res_success = pm.get("resolution_success_count", 0)
            auto_total = pm.get("automation_total_count", 0)
            auto_success = pm.get("automation_success_count", 0)

            await self.families_collection.update_one(
                {"layout_family_id": family_id},
                {"$set": {
                    "performance_metrics.resolution_success_rate": round(res_success / max(res_total, 1), 4),
                    "performance_metrics.automation_success_rate": round(auto_success / max(auto_total, 1), 4),
                }}
            )

    # =========================================================================
    # RESOLVER INTEGRATION (Part 6)
    # =========================================================================

    async def get_resolver_bias(self, document_id: str) -> Dict[str, Any]:
        """
        Get layout family bias for resolver scoring.
        Returns soft scoring hints based on family history.
        """
        fp = await self.fingerprints_collection.find_one(
            {"document_id": document_id},
            {"_id": 0, "layout_family_id": 1, "layout_similarity_score": 1,
             "new_layout_detected": 1, "layout_fingerprint": 1}
        )
        if not fp or not fp.get("layout_family_id"):
            return {"has_layout_bias": False}

        family_id = fp["layout_family_id"]
        family = await self.families_collection.find_one(
            {"layout_family_id": family_id},
            {"_id": 0}
        )
        if not family:
            return {"has_layout_bias": False}

        pm = family.get("performance_metrics", {})
        docs_count = family.get("documents_count", 0)

        # Need minimum docs for meaningful bias
        if docs_count < MIN_DOCS_FOR_FAMILY_STATS:
            return {
                "has_layout_bias": False,
                "layout_family_id": family_id,
                "reason": "insufficient_data",
                "documents_count": docs_count,
            }

        # Compute entity-type biases from family history
        entity_dist = pm.get("bc_entity_distribution", {})
        total_entities = sum(entity_dist.values()) if entity_dist else 0
        entity_biases = {}

        if total_entities >= MIN_DOCS_FOR_FAMILY_STATS:
            for entity_type, count in entity_dist.items():
                freq = count / total_entities
                if freq >= 0.5:
                    # Strong bias toward this entity type
                    bias = min(freq * 0.15, MAX_LAYOUT_FAMILY_BIAS)
                    entity_biases[entity_type] = round(bias, 4)

        # Compute reference label biases
        label_dist = pm.get("reference_label_distribution", {})
        total_labels = sum(label_dist.values()) if label_dist else 0
        label_biases = {}

        if total_labels >= MIN_DOCS_FOR_FAMILY_STATS:
            for label, count in label_dist.items():
                freq = count / total_labels
                if freq >= 0.5:
                    label_biases[label] = round(freq, 4)

        return {
            "has_layout_bias": bool(entity_biases),
            "layout_family_id": family_id,
            "layout_fingerprint": fp.get("layout_fingerprint"),
            "layout_similarity_score": fp.get("layout_similarity_score"),
            "new_layout_detected": fp.get("new_layout_detected", False),
            "documents_count": docs_count,
            "entity_biases": entity_biases,
            "label_biases": label_biases,
            "automation_success_rate": pm.get("automation_success_rate", 0),
            "resolution_success_rate": pm.get("resolution_success_rate", 0),
            "mislabel_count": pm.get("mislabel_count", 0),
        }

    # =========================================================================
    # ADMIN QUERIES (Part 9)
    # =========================================================================

    async def get_all_families(
        self, vendor_no: str = None, doc_type: str = None,
        status: str = "active", skip: int = 0, limit: int = 100
    ) -> List[Dict]:
        """Get all layout families with optional filters."""
        query = {}
        if vendor_no:
            query["vendor_no"] = vendor_no
        if doc_type:
            query["document_type"] = doc_type
        if status:
            query["status"] = status

        cursor = self.families_collection.find(
            query, {"_id": 0}
        ).sort("documents_count", -1).skip(skip).limit(limit)
        return await cursor.to_list(limit)

    async def get_family_detail(self, family_id: str) -> Optional[Dict]:
        """Get detailed info about a layout family including recent documents."""
        family = await self.families_collection.find_one(
            {"layout_family_id": family_id}, {"_id": 0}
        )
        if not family:
            return None

        # Get recent documents in this family
        cursor = self.fingerprints_collection.find(
            {"layout_family_id": family_id},
            {"_id": 0, "document_id": 1, "vendor_name": 1, "document_type": 1,
             "layout_fingerprint": 1, "layout_similarity_score": 1, "created_at": 1}
        ).sort("created_at", -1).limit(20)
        recent_docs = await cursor.to_list(20)
        family["recent_documents"] = recent_docs

        return family

    async def get_families_by_vendor(self, vendor_no: str) -> List[Dict]:
        """Get all families for a specific vendor, grouped."""
        cursor = self.families_collection.find(
            {"vendor_no": vendor_no, "status": "active"},
            {"_id": 0}
        ).sort("documents_count", -1)
        return await cursor.to_list(50)

    async def get_family_stats(self) -> Dict[str, Any]:
        """Aggregate stats across all layout families."""
        total = await self.families_collection.count_documents({"status": "active"})
        total_fingerprints = await self.fingerprints_collection.count_documents({})
        new_layouts = await self.fingerprints_collection.count_documents({"new_layout_detected": True})

        # Vendor count
        vendor_pipeline = [
            {"$match": {"status": "active"}},
            {"$group": {"_id": "$vendor_no"}},
            {"$count": "count"}
        ]
        vendor_agg = await self.families_collection.aggregate(vendor_pipeline).to_list(1)
        vendor_count = vendor_agg[0]["count"] if vendor_agg else 0

        # Doc type distribution
        type_pipeline = [
            {"$match": {"status": "active"}},
            {"$group": {"_id": "$document_type", "count": {"$sum": 1}, "total_docs": {"$sum": "$documents_count"}}},
            {"$sort": {"total_docs": -1}}
        ]
        type_dist = await self.families_collection.aggregate(type_pipeline).to_list(20)

        # Top families by doc count
        top_families = await self.families_collection.find(
            {"status": "active"}, {"_id": 0}
        ).sort("documents_count", -1).limit(10).to_list(10)

        return {
            "total_families": total,
            "total_fingerprints": total_fingerprints,
            "new_layouts_detected": new_layouts,
            "vendors_with_families": vendor_count,
            "document_type_distribution": [
                {"doc_type": d["_id"], "family_count": d["count"], "total_docs": d["total_docs"]}
                for d in type_dist
            ],
            "top_families": [
                {
                    "layout_family_id": f["layout_family_id"],
                    "vendor_no": f["vendor_no"],
                    "document_type": f["document_type"],
                    "documents_count": f["documents_count"],
                    "first_seen": f.get("first_seen"),
                    "last_seen": f.get("last_seen"),
                    "automation_success_rate": f.get("performance_metrics", {}).get("automation_success_rate", 0),
                    "resolution_success_rate": f.get("performance_metrics", {}).get("resolution_success_rate", 0),
                }
                for f in top_families
            ],
        }

    async def get_fingerprint_for_document(self, document_id: str) -> Optional[Dict]:
        """Get fingerprint for a specific document."""
        return await self.fingerprints_collection.find_one(
            {"document_id": document_id}, {"_id": 0}
        )

    # =========================================================================
    # ALERTING INTEGRATION (Part 10)
    # =========================================================================

    async def get_families_needing_attention(self) -> List[Dict]:
        """
        Get families that need attention:
        - New families for high-volume vendors
        - Families with low automation success
        - Families with rising mislabel rates
        """
        alerts = []

        # Families with low automation success (< 50%) and enough data
        low_auto_cursor = self.families_collection.find(
            {
                "status": "active",
                "documents_count": {"$gte": MIN_DOCS_FOR_FAMILY_STATS},
                "performance_metrics.automation_success_rate": {"$lt": 0.5, "$gt": 0},
                "performance_metrics.automation_total_count": {"$gte": MIN_DOCS_FOR_FAMILY_STATS},
            },
            {"_id": 0}
        ).limit(20)
        low_auto = await low_auto_cursor.to_list(20)
        for f in low_auto:
            alerts.append({
                "type": "low_automation",
                "severity": "warning",
                "layout_family_id": f["layout_family_id"],
                "vendor_no": f["vendor_no"],
                "document_type": f["document_type"],
                "automation_rate": f["performance_metrics"].get("automation_success_rate", 0),
                "documents_count": f["documents_count"],
                "message": f"Layout family {f['layout_family_id']} has low automation success rate",
            })

        # Families with high mislabel count
        high_mislabel_cursor = self.families_collection.find(
            {
                "status": "active",
                "performance_metrics.mislabel_count": {"$gte": 5},
            },
            {"_id": 0}
        ).limit(20)
        high_mislabel = await high_mislabel_cursor.to_list(20)
        for f in high_mislabel:
            alerts.append({
                "type": "high_mislabel",
                "severity": "warning",
                "layout_family_id": f["layout_family_id"],
                "vendor_no": f["vendor_no"],
                "document_type": f["document_type"],
                "mislabel_count": f["performance_metrics"].get("mislabel_count", 0),
                "documents_count": f["documents_count"],
                "message": f"Layout family {f['layout_family_id']} has rising mislabel rate",
            })

        return alerts

    # =========================================================================
    # BACKWARDS COMPAT: BATCH ENRICHMENT (Part 12)
    # =========================================================================

    async def backfill_fingerprints(self, limit: int = 100) -> Dict[str, Any]:
        """
        Generate fingerprints for documents that don't have one yet.
        Safe for incremental runs.
        """
        cursor = self.db.hub_documents.find(
            {
                "id": {"$exists": True},
                "$or": [
                    {"extracted_text": {"$exists": True, "$ne": None}},
                    {"raw_text": {"$exists": True, "$ne": None}},
                ],
            },
            {"_id": 0, "id": 1}
        ).limit(limit * 2)
        doc_ids = [d["id"] for d in await cursor.to_list(limit * 2)]

        # Filter out already fingerprinted
        existing_cursor = self.fingerprints_collection.find(
            {"document_id": {"$in": doc_ids}},
            {"_id": 0, "document_id": 1}
        )
        existing_ids = {d["document_id"] for d in await existing_cursor.to_list(len(doc_ids))}
        missing_ids = [did for did in doc_ids if did not in existing_ids][:limit]

        generated = 0
        skipped = 0
        errors = 0

        for doc_id in missing_ids:
            try:
                doc = await self.db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
                if not doc:
                    skipped += 1
                    continue
                text = doc.get("extracted_text") or doc.get("raw_text") or ""
                if len(text.strip()) < 50:
                    skipped += 1
                    continue
                result = await self.generate_fingerprint(doc_id, text, doc)
                if result:
                    generated += 1
                else:
                    skipped += 1
            except Exception as e:
                logger.warning("[LayoutFingerprint] Backfill error for %s: %s", doc_id[:8], str(e))
                errors += 1

        return {
            "candidates": len(missing_ids),
            "generated": generated,
            "skipped": skipped,
            "errors": errors,
        }


# =============================================================================
# GLOBAL INSTANCE
# =============================================================================

_layout_fingerprint_service: Optional[LayoutFingerprintService] = None


def get_layout_fingerprint_service() -> Optional[LayoutFingerprintService]:
    return _layout_fingerprint_service


def set_layout_fingerprint_service(db, event_service=None) -> LayoutFingerprintService:
    global _layout_fingerprint_service
    _layout_fingerprint_service = LayoutFingerprintService(db, event_service)
    return _layout_fingerprint_service
