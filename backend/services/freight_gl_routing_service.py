"""
GPI Document Hub - Freight G/L Account Routing Service

Determines the correct General Ledger (G/L) account for freight-related invoices
based on document context, resolver results, and vendor behavior.

Classification flow:
1. Check if document/vendor is freight-related
2. Determine freight direction (inbound/outbound/transfer)
3. Determine sub-classification (international, drop-ship, dunnage, etc.)
4. Map to configured G/L account
5. Return recommendation with confidence and reasoning

Events emitted:
- freight.gl.classified
- freight.gl.override
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Tuple

logger = logging.getLogger(__name__)

# =============================================================================
# DEFAULT G/L ACCOUNT CONFIGURATION
# =============================================================================

DEFAULT_GL_ACCOUNTS = [
    {
        "account_id": "gl-inbound-raw",
        "gl_number": "5200-00",
        "gl_name": "Inbound Freight - Raw Materials",
        "direction": "inbound",
        "sub_type": "raw_materials",
        "description": "Freight charges for receiving raw materials and packaging components",
        "keywords": ["raw material", "packaging", "cans", "bottles", "glass", "metal", "caps", "lids"],
        "enabled": True,
        "priority": 10,
    },
    {
        "account_id": "gl-inbound-supplies",
        "gl_number": "5210-00",
        "gl_name": "Inbound Freight - Supplies",
        "direction": "inbound",
        "sub_type": "supplies",
        "description": "Freight charges for office and operational supplies",
        "keywords": ["supplies", "office", "maintenance", "repair"],
        "enabled": True,
        "priority": 20,
    },
    {
        "account_id": "gl-inbound-international",
        "gl_number": "5220-00",
        "gl_name": "Inbound Freight - International",
        "direction": "inbound",
        "sub_type": "international",
        "description": "International freight charges for inbound shipments",
        "keywords": ["international", "import", "customs", "duty", "ocean", "overseas"],
        "enabled": True,
        "priority": 5,
    },
    {
        "account_id": "gl-outbound-customer",
        "gl_number": "6100-00",
        "gl_name": "Outbound Freight - Customer Orders",
        "direction": "outbound",
        "sub_type": "customer_orders",
        "description": "Freight charges for shipping finished goods to customers",
        "keywords": ["customer", "delivery", "ship to", "consignee"],
        "enabled": True,
        "priority": 10,
    },
    {
        "account_id": "gl-outbound-dropship",
        "gl_number": "6110-00",
        "gl_name": "Outbound Freight - Drop Ship",
        "direction": "outbound",
        "sub_type": "drop_ship",
        "description": "Freight for drop-ship orders (vendor ships directly to customer)",
        "keywords": ["drop ship", "dropship", "direct ship"],
        "enabled": True,
        "priority": 5,
    },
    {
        "account_id": "gl-outbound-international",
        "gl_number": "6120-00",
        "gl_name": "Outbound Freight - International",
        "direction": "outbound",
        "sub_type": "international",
        "description": "International freight charges for outbound shipments",
        "keywords": ["export", "international", "overseas", "ocean freight"],
        "enabled": True,
        "priority": 5,
    },
    {
        "account_id": "gl-transfer",
        "gl_number": "6200-00",
        "gl_name": "Transfer Freight",
        "direction": "transfer",
        "sub_type": "warehouse_transfer",
        "description": "Freight charges for inter-warehouse or internal transfers",
        "keywords": ["transfer", "internal", "warehouse to warehouse", "relocation"],
        "enabled": True,
        "priority": 10,
    },
    {
        "account_id": "gl-dunnage-return",
        "gl_number": "5250-00",
        "gl_name": "Dunnage / Return Freight",
        "direction": "inbound",
        "sub_type": "dunnage_return",
        "description": "Freight charges for dunnage, pallet, and empty container returns",
        "keywords": ["dunnage", "pallet", "return", "empty", "container return"],
        "enabled": True,
        "priority": 3,
    },
    {
        "account_id": "gl-unclassified",
        "gl_number": "5900-00",
        "gl_name": "Freight - Unclassified",
        "direction": "unknown",
        "sub_type": "unclassified",
        "description": "Freight charges where direction could not be determined",
        "keywords": [],
        "enabled": True,
        "priority": 99,
    },
]

# =============================================================================
# FREIGHT CARRIER DETECTION
# =============================================================================

KNOWN_FREIGHT_CARRIERS = {
    "ups", "fedex", "usps", "dhl", "xpo", "old dominion", "estes",
    "saia", "yrc", "abf", "r+l carriers", "southeastern freight",
    "averitt", "dayton freight", "central transport", "pitt ohio",
    "tumalo creek", "tumalo creek transportation", "tumaloc",
    "conway", "con-way", "holland", "new penn", "reddaway",
    "a. duie pyle", "ward trucking", "rl carriers",
}

FREIGHT_VENDOR_KEYWORDS = [
    "freight", "trucking", "logistics", "transport", "shipping",
    "carrier", "express", "ltl", "truckload", "drayage",
    "cartage", "haulage", "courier",
]

# Direction detection keywords
INBOUND_KEYWORDS = [
    "inbound", "received", "receipt", "incoming", "purchase",
    "vendor", "supplier", "po ", "p.o.", "purchase order",
    "buying", "procurement", "arrive", "arrival",
]

OUTBOUND_KEYWORDS = [
    "outbound", "shipped", "shipping", "delivery", "deliver",
    "customer", "sales", "order", "consignee", "bill to",
    "ship to", "dispatch", "despatch", "sold to",
]

TRANSFER_KEYWORDS = [
    "transfer", "internal", "warehouse to warehouse",
    "intercompany", "inter-company", "relocation",
]

INTERNATIONAL_KEYWORDS = [
    "international", "import", "export", "customs", "duty",
    "ocean", "overseas", "sea freight", "air freight",
    "container", "bol ", "bill of lading",
]

DUNNAGE_KEYWORDS = [
    "dunnage", "pallet return", "empty return", "container return",
    "empty container", "return freight",
]

DROP_SHIP_KEYWORDS = [
    "drop ship", "dropship", "drop-ship", "direct ship",
    "blind ship",
]


# =============================================================================
# SERVICE CLASS
# =============================================================================

# Module-level singleton
_freight_gl_service: Optional["FreightGLRoutingService"] = None


def get_freight_gl_service() -> Optional["FreightGLRoutingService"]:
    return _freight_gl_service


def set_freight_gl_service(db, event_service=None, vendor_intel=None) -> "FreightGLRoutingService":
    global _freight_gl_service
    _freight_gl_service = FreightGLRoutingService(db, event_service, vendor_intel)
    return _freight_gl_service


class FreightGLRoutingService:
    """
    Classifies freight invoices and recommends G/L accounts.
    Uses document context, reference resolution results, and vendor intelligence.
    """

    def __init__(self, db, event_service=None, vendor_intel=None):
        self.db = db
        self.event_service = event_service
        self.vendor_intel = vendor_intel
        self.collection = db.freight_gl_accounts
        self.log_collection = db.freight_gl_classifications

    async def initialize(self):
        """Create indexes and seed default G/L accounts if empty."""
        await self.collection.create_index("account_id", unique=True)
        await self.collection.create_index("gl_number")
        await self.collection.create_index("direction")
        await self.log_collection.create_index("document_id")
        await self.log_collection.create_index("classified_at")

        count = await self.collection.count_documents({})
        if count == 0:
            for acct in DEFAULT_GL_ACCOUNTS:
                acct["created_at"] = datetime.now(timezone.utc).isoformat()
                acct["updated_at"] = acct["created_at"]
                await self.collection.insert_one(acct)
            logger.info("[FreightGL] Seeded %d default G/L accounts", len(DEFAULT_GL_ACCOUNTS))
        else:
            logger.info("[FreightGL] %d G/L accounts loaded", count)

    # =========================================================================
    # G/L ACCOUNT CRUD
    # =========================================================================

    async def list_accounts(self) -> List[Dict]:
        """List all configured G/L accounts."""
        return await self.collection.find({}, {"_id": 0}).sort("priority", 1).to_list(100)

    async def get_account(self, account_id: str) -> Optional[Dict]:
        return await self.collection.find_one({"account_id": account_id}, {"_id": 0})

    async def update_account(self, account_id: str, updates: Dict) -> Optional[Dict]:
        updates["updated_at"] = datetime.now(timezone.utc).isoformat()
        result = await self.collection.find_one_and_update(
            {"account_id": account_id},
            {"$set": updates},
            return_document=True,
        )
        if result:
            result.pop("_id", None)
        return result

    async def create_account(self, account: Dict) -> Dict:
        if not account.get("account_id"):
            account["account_id"] = f"gl-custom-{uuid.uuid4().hex[:8]}"
        account["created_at"] = datetime.now(timezone.utc).isoformat()
        account["updated_at"] = account["created_at"]
        await self.collection.insert_one(account)
        account.pop("_id", None)
        return account

    async def delete_account(self, account_id: str) -> bool:
        result = await self.collection.delete_one({"account_id": account_id})
        return result.deleted_count > 0

    # =========================================================================
    # CORE CLASSIFICATION
    # =========================================================================

    async def classify_document(self, doc: Dict) -> Dict:
        """
        Classify a document and recommend a G/L account.

        Returns a classification result with:
        - is_freight: bool
        - direction: inbound/outbound/transfer/unknown
        - sub_type: raw_materials/international/drop_ship/dunnage_return/etc.
        - recommended_gl: the G/L account recommendation
        - confidence: 0.0-1.0
        - reasoning: list of reasons for the classification
        - signals: all detected signals
        """
        signals = []
        direction_scores = {"inbound": 0.0, "outbound": 0.0, "transfer": 0.0, "unknown": 0.0}

        # --- Step 1: Is this a freight document? ---
        is_freight, freight_reasons = self._detect_freight(doc)
        signals.extend(freight_reasons)

        if not is_freight:
            return {
                "is_freight": False,
                "direction": None,
                "sub_type": None,
                "recommended_gl": None,
                "confidence": 0.0,
                "reasoning": ["Document is not freight-related"],
                "signals": signals,
                "classified_at": datetime.now(timezone.utc).isoformat(),
            }

        # --- Step 2: Determine direction ---
        # 2a. From reference resolution
        ref_intel = doc.get("reference_intelligence") or {}
        best_match = ref_intel.get("best_match") or {}
        if best_match.get("entity_type"):
            entity = best_match["entity_type"].lower()
            if entity in ("purchaseorder", "purchase_order", "purchaseinvoice", "purchase_invoice"):
                direction_scores["inbound"] += 3.0
                signals.append({"source": "resolver", "signal": f"BC match: {entity}", "direction": "inbound", "weight": 3.0})
            elif entity in ("salesorder", "sales_order", "salesinvoice", "sales_invoice", "salesshipment"):
                direction_scores["outbound"] += 3.0
                signals.append({"source": "resolver", "signal": f"BC match: {entity}", "direction": "outbound", "weight": 3.0})

        # 2b. From vendor intelligence
        if self.vendor_intel:
            vendor_name = self._get_vendor_name(doc)
            if vendor_name:
                profile = await self.vendor_intel.get_profile(vendor_name)
                if profile:
                    domain = (profile.get("typical_reference_domain") or "").lower()
                    if domain == "purchase":
                        direction_scores["inbound"] += 2.0
                        signals.append({"source": "vendor_intel", "signal": f"Typical domain: {domain}", "direction": "inbound", "weight": 2.0})
                    elif domain == "sales":
                        direction_scores["outbound"] += 2.0
                        signals.append({"source": "vendor_intel", "signal": f"Typical domain: {domain}", "direction": "outbound", "weight": 2.0})

        # 2c. From extracted text/keywords
        text_blob = self._build_text_blob(doc).lower()

        for kw in INBOUND_KEYWORDS:
            if kw in text_blob:
                direction_scores["inbound"] += 1.0
                signals.append({"source": "keywords", "signal": f"Keyword: '{kw}'", "direction": "inbound", "weight": 1.0})
                break  # count once

        for kw in OUTBOUND_KEYWORDS:
            if kw in text_blob:
                direction_scores["outbound"] += 1.0
                signals.append({"source": "keywords", "signal": f"Keyword: '{kw}'", "direction": "outbound", "weight": 1.0})
                break

        for kw in TRANSFER_KEYWORDS:
            if kw in text_blob:
                direction_scores["transfer"] += 2.0
                signals.append({"source": "keywords", "signal": f"Keyword: '{kw}'", "direction": "transfer", "weight": 2.0})
                break

        # 2d. From folder routing hints
        folder_path = doc.get("folder_path") or doc.get("routing_details", {}).get("folder_path") or ""
        if "dropship" in folder_path.lower() or "drop ship" in folder_path.lower():
            direction_scores["inbound"] += 1.5
            signals.append({"source": "folder", "signal": f"Folder: dropship", "direction": "inbound", "weight": 1.5})
        elif "warehouse" in folder_path.lower():
            direction_scores["inbound"] += 1.0
            signals.append({"source": "folder", "signal": f"Folder: warehouse", "direction": "inbound", "weight": 1.0})

        # Determine winning direction
        best_direction = max(direction_scores, key=direction_scores.get)
        best_score = direction_scores[best_direction]
        total_score = sum(direction_scores.values())

        if best_score == 0:
            best_direction = "unknown"
            confidence = 0.3
        else:
            confidence = min(best_score / max(total_score, 1), 1.0)

        # --- Step 3: Determine sub-type ---
        sub_type, sub_signals = self._detect_sub_type(doc, text_blob, best_direction)
        signals.extend(sub_signals)

        # --- Step 4: Find matching G/L account ---
        accounts = await self.list_accounts()
        recommended = self._match_gl_account(accounts, best_direction, sub_type)

        # Build reasoning
        reasoning = [s["signal"] for s in signals if s.get("weight", 0) >= 1.0]
        if not reasoning:
            reasoning = ["Freight detected but direction could not be determined with high confidence"]

        result = {
            "is_freight": True,
            "direction": best_direction,
            "direction_scores": {k: round(v, 2) for k, v in direction_scores.items()},
            "sub_type": sub_type,
            "recommended_gl": recommended,
            "confidence": round(confidence, 3),
            "reasoning": reasoning,
            "signals": signals,
            "classified_at": datetime.now(timezone.utc).isoformat(),
        }

        return result

    async def classify_and_save(self, doc_id: str) -> Dict:
        """Classify a document, save the result, and update the document."""
        doc = await self.db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
        if not doc:
            return {"error": "Document not found", "document_id": doc_id}

        result = await self.classify_document(doc)
        result["document_id"] = doc_id

        # Save classification log
        log_entry = {
            "id": str(uuid.uuid4()),
            "document_id": doc_id,
            **result,
        }
        await self.log_collection.replace_one(
            {"document_id": doc_id},
            log_entry,
            upsert=True,
        )

        # Update document with freight GL info
        update_fields = {
            "freight_gl_classification": {
                "is_freight": result["is_freight"],
                "direction": result.get("direction"),
                "sub_type": result.get("sub_type"),
                "confidence": result.get("confidence"),
                "classified_at": result.get("classified_at"),
            },
            "updated_utc": datetime.now(timezone.utc).isoformat(),
        }
        if result.get("recommended_gl"):
            update_fields["freight_gl_classification"]["gl_number"] = result["recommended_gl"]["gl_number"]
            update_fields["freight_gl_classification"]["gl_name"] = result["recommended_gl"]["gl_name"]
            update_fields["freight_gl_classification"]["account_id"] = result["recommended_gl"]["account_id"]

        await self.db.hub_documents.update_one(
            {"id": doc_id},
            {"$set": update_fields}
        )

        # Emit event
        if self.event_service:
            recommended_gl = result.get("recommended_gl") or {}
            await self.event_service.emit(
                event_type="freight.gl.classified",
                document_id=doc_id,
                status="completed",
                source_service="freight_gl_routing",
                payload={
                    "is_freight": result["is_freight"],
                    "direction": result.get("direction"),
                    "gl_number": recommended_gl.get("gl_number") if recommended_gl else None,
                    "confidence": result.get("confidence"),
                }
            )

        return result

    async def override_classification(self, doc_id: str, gl_account_id: str, reason: str = "") -> Dict:
        """Manually override the G/L classification for a document."""
        account = await self.get_account(gl_account_id)
        if not account:
            return {"error": "G/L account not found"}

        override = {
            "freight_gl_classification": {
                "is_freight": True,
                "direction": account["direction"],
                "sub_type": account["sub_type"],
                "gl_number": account["gl_number"],
                "gl_name": account["gl_name"],
                "account_id": account["account_id"],
                "confidence": 1.0,
                "classified_at": datetime.now(timezone.utc).isoformat(),
                "override": True,
                "override_reason": reason,
                "override_at": datetime.now(timezone.utc).isoformat(),
            },
            "updated_utc": datetime.now(timezone.utc).isoformat(),
        }

        await self.db.hub_documents.update_one(
            {"id": doc_id},
            {"$set": override}
        )

        # Update log
        await self.log_collection.update_one(
            {"document_id": doc_id},
            {"$set": {
                "override": True,
                "override_gl_account_id": gl_account_id,
                "override_reason": reason,
                "override_at": datetime.now(timezone.utc).isoformat(),
            }},
            upsert=True,
        )

        if self.event_service:
            await self.event_service.emit(
                event_type="freight.gl.override",
                document_id=doc_id,
                status="completed",
                source_service="freight_gl_routing",
                payload={
                    "gl_number": account["gl_number"],
                    "reason": reason,
                }
            )

        return {
            "status": "overridden",
            "document_id": doc_id,
            "gl_number": account["gl_number"],
            "gl_name": account["gl_name"],
        }

    # =========================================================================
    # BATCH CLASSIFICATION
    # =========================================================================

    async def batch_classify(
        self,
        document_ids: Optional[List[str]] = None,
        confidence_threshold: float = 0.5,
        skip_overrides: bool = True,
    ) -> Dict:
        """
        Batch-classify freight documents. Read-only with respect to BC.

        Args:
            document_ids: Specific doc IDs to process. If None, processes all freight-eligible docs.
            confidence_threshold: Flag items below this confidence for manual review.
            skip_overrides: If True, skip docs with existing manual overrides.

        Returns summary with direction counts, GL breakdown, and items needing review.
        """
        # Build query
        query: Dict[str, Any] = {}
        if document_ids:
            query["id"] = {"$in": document_ids}

        docs = await self.db.hub_documents.find(query, {"_id": 0}).to_list(1000)

        results = {
            "total_processed": 0,
            "freight_detected": 0,
            "non_freight": 0,
            "skipped_override": 0,
            "skipped_error": 0,
            "by_direction": {"inbound": 0, "outbound": 0, "transfer": 0, "unknown": 0},
            "by_gl_account": {},
            "needs_manual_review": [],
            "high_confidence": [],
            "classified_docs": [],
        }

        for doc in docs:
            doc_id = doc.get("id")
            if not doc_id:
                results["skipped_error"] += 1
                continue

            # Skip manually overridden
            existing = doc.get("freight_gl_classification") or {}
            if skip_overrides and existing.get("override"):
                results["skipped_override"] += 1
                continue

            try:
                classification = await self.classify_document(doc)
                results["total_processed"] += 1

                if not classification.get("is_freight"):
                    results["non_freight"] += 1
                    continue

                results["freight_detected"] += 1
                direction = classification.get("direction", "unknown")
                results["by_direction"][direction] = results["by_direction"].get(direction, 0) + 1

                gl = classification.get("recommended_gl") or {}
                gl_num = gl.get("gl_number", "unassigned")
                gl_name = gl.get("gl_name", "")
                if gl_num not in results["by_gl_account"]:
                    results["by_gl_account"][gl_num] = {"gl_name": gl_name, "count": 0}
                results["by_gl_account"][gl_num]["count"] += 1

                conf = classification.get("confidence", 0)
                doc_summary = {
                    "document_id": doc_id,
                    "file_name": doc.get("file_name", ""),
                    "vendor": self._get_vendor_name(doc),
                    "direction": direction,
                    "sub_type": classification.get("sub_type"),
                    "gl_number": gl_num,
                    "gl_name": gl_name,
                    "confidence": conf,
                }

                if conf < confidence_threshold:
                    doc_summary["review_reason"] = "Below confidence threshold"
                    results["needs_manual_review"].append(doc_summary)
                else:
                    results["high_confidence"].append(doc_summary)

                results["classified_docs"].append(doc_summary)

                # Save the classification (read-only: only writes to our own MongoDB, not BC)
                log_entry = {
                    "id": str(uuid.uuid4()),
                    "document_id": doc_id,
                    **classification,
                }
                await self.log_collection.replace_one(
                    {"document_id": doc_id}, log_entry, upsert=True
                )

                update_fields = {
                    "freight_gl_classification": {
                        "is_freight": True,
                        "direction": direction,
                        "sub_type": classification.get("sub_type"),
                        "confidence": conf,
                        "classified_at": classification.get("classified_at"),
                    },
                    "updated_utc": datetime.now(timezone.utc).isoformat(),
                }
                if gl.get("gl_number"):
                    update_fields["freight_gl_classification"]["gl_number"] = gl["gl_number"]
                    update_fields["freight_gl_classification"]["gl_name"] = gl["gl_name"]
                    update_fields["freight_gl_classification"]["account_id"] = gl.get("account_id")

                await self.db.hub_documents.update_one(
                    {"id": doc_id}, {"$set": update_fields}
                )

            except Exception as e:
                logger.error("[FreightGL] Batch error for doc %s: %s", doc_id, str(e))
                results["skipped_error"] += 1

        results["batch_completed_at"] = datetime.now(timezone.utc).isoformat()
        return results

    # =========================================================================
    # STATISTICS
    # =========================================================================

    async def get_stats(self) -> Dict:
        """Get freight G/L routing statistics."""
        total_classified = await self.log_collection.count_documents({})
        freight_count = await self.log_collection.count_documents({"is_freight": True})
        override_count = await self.log_collection.count_documents({"override": True})

        # Direction breakdown
        pipeline = [
            {"$match": {"is_freight": True}},
            {"$group": {
                "_id": "$direction",
                "count": {"$sum": 1},
                "avg_confidence": {"$avg": "$confidence"},
            }},
            {"$sort": {"count": -1}},
        ]
        by_direction = await self.log_collection.aggregate(pipeline).to_list(10)

        # G/L account breakdown
        gl_pipeline = [
            {"$match": {"is_freight": True, "recommended_gl.gl_number": {"$exists": True}}},
            {"$group": {
                "_id": "$recommended_gl.gl_number",
                "gl_name": {"$first": "$recommended_gl.gl_name"},
                "count": {"$sum": 1},
            }},
            {"$sort": {"count": -1}},
        ]
        by_gl = await self.log_collection.aggregate(gl_pipeline).to_list(20)

        return {
            "total_classified": total_classified,
            "freight_documents": freight_count,
            "non_freight": total_classified - freight_count,
            "manual_overrides": override_count,
            "by_direction": [
                {"direction": r["_id"], "count": r["count"], "avg_confidence": round(r["avg_confidence"] or 0, 3)}
                for r in by_direction
            ],
            "by_gl_account": [
                {"gl_number": r["_id"], "gl_name": r.get("gl_name", ""), "count": r["count"]}
                for r in by_gl
            ],
        }

    async def get_recent_classifications(self, limit: int = 20) -> List[Dict]:
        """Get recent freight classifications."""
        return await self.log_collection.find(
            {}, {"_id": 0}
        ).sort("classified_at", -1).limit(limit).to_list(limit)

    # =========================================================================
    # INTERNAL HELPERS
    # =========================================================================

    def _detect_freight(self, doc: Dict) -> Tuple[bool, List[Dict]]:
        """Detect if document is freight-related."""
        signals = []

        # Check document type
        doc_type = (doc.get("document_type") or doc.get("suggested_job_type") or "").lower()
        if doc_type in ("freight_document", "freight_invoice", "freight", "bol", "bill_of_lading", "shipping_document"):
            signals.append({"source": "doc_type", "signal": f"Document type: {doc_type}", "direction": "unknown", "weight": 5.0})
            return True, signals

        # Check if vendor is a freight carrier
        vendor_name = self._get_vendor_name(doc).lower()
        if vendor_name:
            for carrier in KNOWN_FREIGHT_CARRIERS:
                if carrier in vendor_name:
                    signals.append({"source": "vendor", "signal": f"Known freight carrier: {carrier}", "direction": "unknown", "weight": 4.0})
                    return True, signals
            for kw in FREIGHT_VENDOR_KEYWORDS:
                if kw in vendor_name:
                    signals.append({"source": "vendor_keyword", "signal": f"Vendor contains '{kw}'", "direction": "unknown", "weight": 3.0})
                    return True, signals

        # Check unified vendor match
        uvm = doc.get("unified_vendor_match") or {}
        if uvm.get("is_freight_carrier"):
            signals.append({"source": "unified_vendor", "signal": "Unified vendor match flagged as freight carrier", "direction": "unknown", "weight": 4.0})
            return True, signals

        # Check extracted fields for freight indicators
        text = self._build_text_blob(doc).lower()
        freight_text_kw = ["freight charge", "freight bill", "shipping charge", "delivery charge",
                           "transportation charge", "carrier charge", "ltl charge", "truckload"]
        for kw in freight_text_kw:
            if kw in text:
                signals.append({"source": "text", "signal": f"Text contains '{kw}'", "direction": "unknown", "weight": 2.0})
                return True, signals

        return False, signals

    def _detect_sub_type(self, doc: Dict, text: str, direction: str) -> Tuple[str, List[Dict]]:
        """Detect freight sub-type (international, drop-ship, dunnage, etc.)."""
        signals = []

        # Dunnage/returns check first (highest priority sub-type)
        for kw in DUNNAGE_KEYWORDS:
            if kw in text:
                signals.append({"source": "sub_type", "signal": f"Dunnage keyword: '{kw}'", "direction": direction, "weight": 2.0})
                return "dunnage_return", signals

        # Drop ship check
        for kw in DROP_SHIP_KEYWORDS:
            if kw in text:
                signals.append({"source": "sub_type", "signal": f"Drop ship keyword: '{kw}'", "direction": direction, "weight": 2.0})
                return "drop_ship", signals

        # International check
        for kw in INTERNATIONAL_KEYWORDS:
            if kw in text:
                signals.append({"source": "sub_type", "signal": f"International keyword: '{kw}'", "direction": direction, "weight": 1.5})
                return "international", signals

        # Transfer check
        for kw in TRANSFER_KEYWORDS:
            if kw in text:
                signals.append({"source": "sub_type", "signal": f"Transfer keyword: '{kw}'", "direction": "transfer", "weight": 2.0})
                return "warehouse_transfer", signals

        # Default based on direction
        if direction == "inbound":
            return "raw_materials", []
        elif direction == "outbound":
            return "customer_orders", []
        elif direction == "transfer":
            return "warehouse_transfer", []

        return "unclassified", []

    def _match_gl_account(self, accounts: List[Dict], direction: str, sub_type: str) -> Optional[Dict]:
        """Find the best matching G/L account."""
        # First: exact direction + sub_type match
        for acct in accounts:
            if not acct.get("enabled", True):
                continue
            if acct.get("direction") == direction and acct.get("sub_type") == sub_type:
                return {"gl_number": acct["gl_number"], "gl_name": acct["gl_name"], "account_id": acct["account_id"]}

        # Second: direction match (first by priority)
        for acct in accounts:
            if not acct.get("enabled", True):
                continue
            if acct.get("direction") == direction:
                return {"gl_number": acct["gl_number"], "gl_name": acct["gl_name"], "account_id": acct["account_id"]}

        # Fallback: unclassified
        for acct in accounts:
            if acct.get("sub_type") == "unclassified":
                return {"gl_number": acct["gl_number"], "gl_name": acct["gl_name"], "account_id": acct["account_id"]}

        return None

    def _get_vendor_name(self, doc: Dict) -> str:
        """Extract vendor name from document using all available sources."""
        return (
            doc.get("vendor_canonical") or
            doc.get("vendor_raw") or
            doc.get("matched_vendor_name") or
            (doc.get("extracted_fields") or {}).get("vendor") or
            (doc.get("normalized_fields") or {}).get("vendor") or
            (doc.get("ai_extraction") or {}).get("vendor") or
            ""
        )

    def _build_text_blob(self, doc: Dict) -> str:
        """Build a text blob from all relevant document fields for keyword scanning."""
        parts = [
            doc.get("file_name") or "",
            (doc.get("extracted_fields") or {}).get("description") or "",
            (doc.get("ai_extraction") or {}).get("description") or "",
            (doc.get("extracted_fields") or {}).get("notes") or "",
            doc.get("email_subject") or "",
            doc.get("email_body_snippet") or "",
            (doc.get("extracted_fields") or {}).get("shipping_terms") or "",
            (doc.get("extracted_fields") or {}).get("bol_number") or "",
        ]
        return " ".join(p for p in parts if p)
