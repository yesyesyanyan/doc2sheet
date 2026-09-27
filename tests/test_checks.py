import json
from datetime import date
from decimal import Decimal

from doc2sheet.checks import close_enough, run_checks
from doc2sheet.schema import ExtractedDocument
from tests.helpers import invoice_json

TODAY = date(2026, 9, 27)


def codes(doc: ExtractedDocument) -> set[str]:
    return {issue.code for issue in run_checks(doc, today=TODAY)}


def doc_from(**overrides) -> ExtractedDocument:
    return ExtractedDocument.model_validate(json.loads(invoice_json(**overrides)))


def test_correct_invoice_has_no_issues():
    assert run_checks(doc_from(), today=TODAY) == []


def test_close_enough_tolerates_rounding_only():
    assert close_enough(Decimal("100.00"), Decimal("100.01"))
    assert not close_enough(Decimal("100.00"), Decimal("100.10"))
    assert close_enough(Decimal("100000.00"), Decimal("100005.00"))  # 0.005% on a large amount


def test_total_mismatch_is_an_error():
    issues = run_checks(doc_from(total=3099.00), today=TODAY)
    mismatch = [i for i in issues if i.code == "total_mismatch"]
    assert mismatch and mismatch[0].level == "error"
    assert "3,099.00" in mismatch[0].message


def test_tax_inclusive_prices_are_accepted():
    # Gross prices: items add up to the total, VAT line is informational.
    doc = doc_from(subtotal=None, tax=515.00, total=2575.00)
    assert "total_mismatch" not in codes(doc)


def test_discount_and_other_charges_are_applied():
    doc = doc_from(discount=75.00, other_charges=20.00, tax=504.00, total=3024.00)
    assert "total_mismatch" not in codes(doc)


def test_line_math_and_items_vs_subtotal():
    items = json.loads(invoice_json())["line_items"]
    items[2]["amount"] = 310  # 2 x 150 != 310
    doc = doc_from(line_items=items)
    assert {"line_math", "items_vs_subtotal"} <= codes(doc)


def test_missing_values_are_reported():
    doc = ExtractedDocument(document_type="receipt")
    assert {"missing_total", "missing_vendor", "missing_date", "missing_currency"} <= codes(doc)


def test_date_and_currency_sanity():
    doc = doc_from(issue_date="2026-10-15", due_date="2026-10-01", currency="Euro")
    assert {"future_date", "due_before_issue", "invalid_currency"} <= codes(doc)


def test_negative_total_allowed_for_credit_notes():
    assert "negative_total" in codes(doc_from(subtotal=None, tax=None, total=-50, line_items=[]))
    credit = doc_from(document_type="credit_note", subtotal=None, tax=None, total=-50, line_items=[])
    assert "negative_total" not in codes(credit)


def test_not_an_invoice():
    assert "not_an_invoice" in codes(doc_from(document_type="other"))
