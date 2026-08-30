from services.document_bundle_reference_service import _merge_refs, _regex_supporting_refs


def test_supporting_page_regex_preserves_distinct_labels():
    refs = _regex_supporting_refs(
        [
            {
                "page": 2,
                "text": "Gamer PO # 113785\nBill of Lading: SMLMSEL6D6996600\nReference: SI-02-26-34711",
            }
        ]
    )
    assert refs["po_numbers"][0]["value"] == "113785"
    assert refs["bol_numbers"][0]["value"] == "SMLMSEL6D6996600"
    assert refs["reference_numbers"][0]["value"] == "SI-02-26-34711"


def test_strategic_packet_reference_is_not_recast_as_shipment():
    refs = _regex_supporting_refs(
        [
            {
                "page": 2,
                "text": "Receipt Number: 962222-1\nReference # 815734\nShipment # ER25-1560\nCustomer PO W117105",
            }
        ]
    )
    assert refs["receipt_numbers"][0]["value"] == "962222-1"
    assert refs["reference_numbers"][0]["value"] == "815734"
    assert refs["shipment_numbers"][0]["value"] == "ER25-1560"
    assert refs["po_numbers"][0]["value"] == "W117105"
    assert all(item["value"] != "815734" for item in refs["shipment_numbers"])


def test_merge_keeps_first_semantic_value_and_dedupes_case_insensitively():
    a = {"po_numbers": [{"value": "W117105", "source": "labeled_regex"}]}
    b = {"po_numbers": [{"value": "w117105", "source": "supporting_page_ai"}]}
    merged = _merge_refs(a, b)
    assert len(merged["po_numbers"]) == 1
    assert merged["po_numbers"][0]["value"] == "W117105"
