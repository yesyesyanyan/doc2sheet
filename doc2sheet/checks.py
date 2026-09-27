"""Deterministic sanity checks on extracted data.

LLMs are good readers but they can misread a digit or silently "fix" a total.
These checks don't trust the model: they recompute the arithmetic and flag
anything a human should look at before the data goes into accounting.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from decimal import Decimal

from doc2sheet.schema import ExtractedDocument, Issue

ZERO = Decimal("0")


def close_enough(a: Decimal, b: Decimal) -> bool:
    """Equal within rounding: 2 cents, or 0.01% for large amounts."""
    tolerance = max(Decimal("0.02"), abs(b) * Decimal("0.0001"))
    return abs(a - b) <= tolerance


def _fmt(value: Decimal) -> str:
    return f"{value:,.2f}"


def run_checks(doc: ExtractedDocument, *, today: date | None = None) -> list[Issue]:
    today = today or date.today()
    issues: list[Issue] = []

    def add(level: str, code: str, message: str, field: str | None = None) -> None:
        issues.append(Issue(level=level, code=code, message=message, field=field))  # type: ignore[arg-type]

    # -- presence ------------------------------------------------------------
    if doc.document_type == "other":
        add("warning", "not_an_invoice", "This does not look like an invoice or receipt.", "document_type")
    if doc.total is None:
        add("error", "missing_total", "No total amount found.", "total")
    if not doc.vendor_name:
        add("warning", "missing_vendor", "No vendor / seller name found.", "vendor_name")
    if doc.issue_date is None:
        add("warning", "missing_date", "No (unambiguous) issue date found.", "issue_date")
    if doc.currency is None:
        add("warning", "missing_currency", "Currency could not be determined.", "currency")
    elif not re.fullmatch(r"[A-Z]{3}", doc.currency):
        add("warning", "invalid_currency", f"'{doc.currency}' is not an ISO 4217 currency code.", "currency")

    # -- line arithmetic -----------------------------------------------------
    for number, item in enumerate(doc.line_items, start=1):
        if item.quantity is not None and item.unit_price is not None and item.amount is not None:
            expected = item.quantity * item.unit_price
            if not close_enough(expected, item.amount):
                label = item.description[:40] or f"line {number}"
                add(
                    "warning",
                    "line_math",
                    f"Line {number} ('{label}'): {item.quantity} × {_fmt(item.unit_price)} = "
                    f"{_fmt(expected)}, but the amount says {_fmt(item.amount)}.",
                    f"line_items[{number - 1}].amount",
                )

    amounts = [item.amount for item in doc.line_items]
    items_sum = sum(amounts, ZERO) if amounts and all(a is not None for a in amounts) else None

    if items_sum is not None and doc.subtotal is not None and not close_enough(items_sum, doc.subtotal):
        add(
            "warning",
            "items_vs_subtotal",
            f"Line items add up to {_fmt(items_sum)}, but the subtotal is {_fmt(doc.subtotal)}.",
            "subtotal",
        )

    # -- totals --------------------------------------------------------------
    base = doc.subtotal if doc.subtotal is not None else items_sum
    if base is not None and doc.total is not None:
        adjusted = base - (doc.discount or ZERO) + (doc.other_charges or ZERO)
        with_tax = adjusted + (doc.tax or ZERO)
        # Prices can be tax-exclusive (net + tax = total) or tax-inclusive
        # (gross prices; the tax line is informational). Accept either.
        if not (close_enough(with_tax, doc.total) or close_enough(adjusted, doc.total)):
            parts = [f"subtotal {_fmt(base)}"]
            if doc.discount:
                parts.append(f"− discount {_fmt(doc.discount)}")
            if doc.other_charges:
                parts.append(f"+ charges {_fmt(doc.other_charges)}")
            if doc.tax:
                parts.append(f"+ tax {_fmt(doc.tax)}")
            add(
                "error",
                "total_mismatch",
                f"Totals don't add up: {' '.join(parts)} = {_fmt(with_tax)}, "
                f"but the document total is {_fmt(doc.total)}.",
                "total",
            )

    if doc.total is not None and doc.total < 0 and doc.document_type != "credit_note":
        add("warning", "negative_total", "Total is negative but the document is not a credit note.", "total")

    # -- dates ---------------------------------------------------------------
    if doc.issue_date and doc.due_date and doc.due_date < doc.issue_date:
        add("warning", "due_before_issue", "Due date is before the issue date.", "due_date")
    if doc.issue_date and doc.issue_date > today + timedelta(days=1):
        add("warning", "future_date", f"Issue date {doc.issue_date} is in the future.", "issue_date")

    return issues
