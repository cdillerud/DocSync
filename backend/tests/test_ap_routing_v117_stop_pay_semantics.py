from services.ap_routing_learned_features_service import semantic_features


def _features(*, file_name="invoice.pdf", raw_text=""):
    return semantic_features(
        {
            "file_name": file_name,
            "raw_text": raw_text,
            "extracted_fields": {},
            "normalized_fields": {},
        }
    )


def test_explicit_stop_pay_recognizes_filename_safe_strong_variants():
    file_names = [
        "R+L_DP NOT PAY_recevied update invoice and pd.pdf",
        "vendor_DNP_123.pdf",
        "vendor_DO_NOT_PAY_123.pdf",
        "vendor-do-not-pay-123.pdf",
        "Anchor_invoice_issued_in_error.pdf",
    ]
    for file_name in file_names:
        assert "explicit_stop_pay" in _features(file_name=file_name), file_name


def test_explicit_stop_pay_preserves_existing_strong_prose_variants():
    texts = [
        "DO NOT PAY this invoice",
        "Don't pay this invoice",
        "Do not process this invoice",
        "Hold payment until corrected",
        "This invoice was issued in error and should be replaced.",
    ]
    for raw_text in texts:
        assert "explicit_stop_pay" in _features(raw_text=raw_text), raw_text

    typo_features = _features(file_name="Buske Tampa Dunnage Reconcilication - JE T01640 260616.pdf")
    assert "reconciliation" in typo_features
    assert "reconciliation" not in _features(file_name="vendor_reconcilicator_notes.pdf")

    bol_features = _features(file_name="118911_REILE'S_090326_BOL - need to receive.pdf")
    assert "bol" in bol_features
    assert "bol" not in _features(file_name="118911_REILE'S_BOLSTER_notes.pdf")


def test_explicit_stop_pay_rejects_loose_or_embedded_not_pay_tokens():
    file_names = [
        "invoice_NOT_PAY_ready.pdf",
        "invoice_ADNP_123.pdf",
        "invoice_DNPX_123.pdf",
        "invoice_DP_NOT_PAYMENT.pdf",
        "invoice_error_in_issuance_review.pdf",
    ]
    for file_name in file_names:
        assert "explicit_stop_pay" not in _features(file_name=file_name), file_name
