from datetime import date
from decimal import Decimal

import pytest

from doc2sheet.schema import ExtractedDocument, ExtractionResult, Issue, parse_date, parse_money


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("€1.234,50", "1234.50"),
        ("$1,234.50", "1234.50"),
        ("1 234,50 EUR", "1234.50"),
        ("CHF 1'234.50", "1234.50"),
        ("12,50", "12.50"),
        ("1,234", "1234"),
        ("0,125", "0.125"),
        ("1.234.567", "1234567"),
        ("(12.00)", "-12.00"),
        ("12.50-", "-12.50"),
        ("-7", "-7"),
        (42, "42"),
        (3.5, "3.5"),
    ],
)
def test_parse_money(raw, expected):
    assert parse_money(raw) == Decimal(expected)


@pytest.mark.parametrize("raw", [None, "", "n/a", "-", "abc", True])
def test_parse_money_nullish(raw):
    assert parse_money(raw) is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026-03-05", date(2026, 3, 5)),
        ("2026/03/05", date(2026, 3, 5)),
        ("2026-03-05T10:00:00Z", date(2026, 3, 5)),
        ("05.03.2026", date(2026, 3, 5)),  # dotted = day first
        ("25/03/2026", date(2026, 3, 25)),  # day > 12, unambiguous
        ("03/25/2026", date(2026, 3, 25)),  # US style, unambiguous
        ("March 5, 2026", date(2026, 3, 5)),
        ("5th Mar 2026", date(2026, 3, 5)),
        ("12 August 2026", date(2026, 8, 12)),
    ],
)
def test_parse_date(raw, expected):
    assert parse_date(raw) == expected


@pytest.mark.parametrize("raw", ["05/03/2026", "31/02/2026", "soon", "", None])
def test_parse_date_refuses_to_guess(raw):
    assert parse_date(raw) is None


def test_document_normalises_sloppy_model_output():
    doc = ExtractedDocument.model_validate(
        {
            "document_type": "Tax Invoice",
            "vendor_name": "  ",
            "currency": "€",
            "total": "1.234,50",
            "line_items": None,
            "unexpected_key": "ignored",
        }
    )
    assert doc.document_type == "invoice"
    assert doc.vendor_name is None
    assert doc.currency == "EUR"
    assert doc.total == Decimal("1234.50")
    assert doc.line_items == []


def test_unknown_document_type_becomes_other():
    assert ExtractedDocument.model_validate({"document_type": "menu"}).document_type == "other"


def test_money_serialises_as_number_in_json():
    doc = ExtractedDocument(total=Decimal("10.50"))
    assert doc.model_dump(mode="json")["total"] == 10.5


def test_result_status():
    doc = ExtractedDocument(total=Decimal("1"))
    assert ExtractionResult(source="a.pdf", document=doc).status == "ok"
    warning = Issue(level="warning", code="x", message="y")
    assert ExtractionResult(source="a.pdf", document=doc, issues=[warning]).status == "review"
    assert ExtractionResult(source="a.pdf", error="boom").status == "failed"
    assert ExtractionResult(source="a.pdf").model_dump()["status"] == "failed"
