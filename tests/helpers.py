"""Shared test helpers (importable from tests)."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "samples"


class FakeLLM:
    """Stands in for a real model: returns canned replies and records the calls."""

    def __init__(self, replies: list[str] | Callable[[list[dict[str, Any]]], str], model: str = "fake/model"):
        self.model = model
        self._replies = replies
        self.calls: list[list[dict[str, Any]]] = []

    def complete(self, messages: list[dict[str, Any]], *, json_schema: dict | None = None) -> str:
        self.calls.append(messages)
        if callable(self._replies):
            return self._replies(messages)
        return self._replies[min(len(self.calls), len(self._replies)) - 1]


def invoice_json(**overrides: Any) -> str:
    """A correct extraction of samples/invoice_pixel_pine_eur.pdf."""
    data: dict[str, Any] = {
        "document_type": "invoice",
        "vendor_name": "Pixel & Pine Design Studio SARL",
        "vendor_address": "14 Rue des Exemples, 69002 Lyon, France",
        "vendor_tax_id": "FR00999999999",
        "customer_name": "Maple Street Bakery Ltd",
        "document_number": "INV-2026-0142",
        "issue_date": "2026-09-01",
        "due_date": "2026-10-01",
        "currency": "EUR",
        "subtotal": 2575.00,
        "discount": None,
        "other_charges": None,
        "tax": 515.00,
        "total": 3090.00,
        "line_items": [
            {"description": "Brand identity workshop (half day)", "quantity": 1, "unit_price": 850, "amount": 850},
            {"description": "Logo design", "quantity": 1, "unit_price": 1200, "amount": 1200},
            {"description": "Business card layout", "quantity": 2, "unit_price": 150, "amount": 300},
            {"description": "Social media templates", "quantity": 5, "unit_price": 45, "amount": 225},
        ],
    }
    data.update(overrides)
    return json.dumps(data)
