"""Data model for extracted documents.

The LLM returns loosely-typed JSON. These Pydantic models are the contract the
rest of the pipeline relies on: money becomes ``Decimal``, dates become
``datetime.date`` and common formatting noise ("€1.234,50", "03 Mar 2026") is
normalised *before* validation, so a slightly sloppy model answer still parses.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PlainSerializer,
    computed_field,
    field_validator,
)

# ---------------------------------------------------------------------------
# Lenient parsers
# ---------------------------------------------------------------------------

_NULLISH = {"", "null", "none", "n/a", "na", "-", "--", "—", "unknown"}
_MONTHS = {
    m: i
    for i, names in enumerate(
        [
            ("jan", "january"),
            ("feb", "february"),
            ("mar", "march"),
            ("apr", "april"),
            ("may",),
            ("jun", "june"),
            ("jul", "july"),
            ("aug", "august"),
            ("sep", "sept", "september"),
            ("oct", "october"),
            ("nov", "november"),
            ("dec", "december"),
        ],
        start=1,
    )
    for m in names
}


def parse_money(value: Any) -> Decimal | None:
    """Parse a money-ish value into a Decimal.

    Handles numbers, currency symbols/codes, thousands separators in both US
    and European styles, and accounting negatives such as ``(12.50)``.

    >>> parse_money("€1.234,50")
    Decimal('1234.50')
    >>> parse_money("(12.00)")
    Decimal('-12.00')
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))

    text = str(value).strip()
    if text.lower() in _NULLISH:
        return None

    negative = False
    if text.startswith("(") and text.endswith(")"):
        negative, text = True, text[1:-1]
    if text.endswith("-"):
        negative, text = True, text[:-1]
    if text.startswith("-"):
        negative, text = True, text[1:]

    # Drop currency symbols/codes and whitespace-style thousands separators.
    text = re.sub(r"[^\d.,\-]", "", text.replace(" ", "").replace("'", ""))
    if text.startswith("-"):
        negative, text = True, text[1:]
    if not text or not any(ch.isdigit() for ch in text):
        return None

    if "," in text and "." in text:
        # Whichever separator comes last is the decimal separator.
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        head, _, tail = text.rpartition(",")
        if len(tail) == 3 and head not in ("", "0"):
            text = text.replace(",", "")  # 1,234 -> thousands separator
        else:
            text = head.replace(",", "") + "." + tail  # 12,50 -> decimal comma
    elif text.count(".") > 1:
        text = text.replace(".", "")  # 1.234.567 -> thousands separators

    try:
        amount = Decimal(text)
    except InvalidOperation:
        return None
    return -amount if negative else amount


def parse_date(value: Any) -> date | None:
    """Parse common invoice date formats; return ``None`` when ambiguous.

    ISO (``2026-03-05``) is preferred and is what the prompt asks for. For
    slash dates like ``05/03/2026`` we only guess when one part is > 12;
    otherwise the value is ambiguous and we refuse to guess.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    text = str(value).strip()
    if text.lower() in _NULLISH:
        return None
    text = text.split("T")[0].strip()

    m = re.fullmatch(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", text)
    if m:
        return _safe_date(int(m[1]), int(m[2]), int(m[3]))

    m = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", text)  # 05.03.2026 is day-first
    if m:
        return _safe_date(int(m[3]), int(m[2]), int(m[1]))

    m = re.fullmatch(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", text)
    if m:
        a, b, year = int(m[1]), int(m[2]), int(m[3])
        if a > 12 >= b:
            return _safe_date(year, b, a)
        if b > 12 >= a:
            return _safe_date(year, a, b)
        if a == b:
            return _safe_date(year, a, b)
        return None  # 05/03/2026 could be March 5 or May 3

    cleaned = re.sub(r"[,.]", " ", text.lower())
    cleaned = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", cleaned)
    parts = cleaned.split()
    if len(parts) == 3:
        day = month = year = None
        for part in parts:
            if part.isdigit() and len(part) == 4:
                year = int(part)
            elif part.isdigit():
                day = int(part)
            elif part in _MONTHS:
                month = _MONTHS[part]
        if day and month and year:
            return _safe_date(year, month, day)
    return None


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _normalise_currency(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if text.lower() in _NULLISH:
        return None
    symbols = {"€": "EUR", "£": "GBP", "₹": "INR", "₩": "KRW", "₺": "TRY", "₫": "VND"}
    if text in symbols:
        return symbols[text]
    return text.upper()


def _to_float(value: Decimal | None) -> float | None:
    return None if value is None else float(value)


Money = Annotated[
    Decimal | None,
    BeforeValidator(parse_money),
    PlainSerializer(_to_float, when_used="json"),
]
LenientDate = Annotated[date | None, BeforeValidator(parse_date)]
Currency = Annotated[str | None, BeforeValidator(_normalise_currency)]

DocumentType = Literal["invoice", "receipt", "credit_note", "other"]


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return None if text.lower() in _NULLISH else text


OptionalStr = Annotated[str | None, BeforeValidator(_optional_str)]


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class LineItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    description: str = ""
    quantity: Money = None
    unit_price: Money = None
    amount: Money = None

    @field_validator("description", mode="before")
    @classmethod
    def _description(cls, value: Any) -> str:
        return "" if value is None else str(value).strip()


class ExtractedDocument(BaseModel):
    """Everything we pull out of one invoice / receipt."""

    model_config = ConfigDict(extra="ignore")

    document_type: DocumentType = "other"
    vendor_name: OptionalStr = None
    vendor_address: OptionalStr = None
    vendor_tax_id: OptionalStr = None
    customer_name: OptionalStr = None
    document_number: OptionalStr = None
    issue_date: LenientDate = None
    due_date: LenientDate = None
    currency: Currency = None
    subtotal: Money = None
    discount: Money = None
    other_charges: Money = None  # shipping, delivery, service fees, tips
    tax: Money = None
    total: Money = None
    line_items: list[LineItem] = Field(default_factory=list)

    @field_validator("document_type", mode="before")
    @classmethod
    def _doc_type(cls, value: Any) -> str:
        text = str(value or "").strip().lower().replace(" ", "_").replace("-", "_")
        aliases = {"bill": "invoice", "tax_invoice": "invoice", "credit_memo": "credit_note"}
        text = aliases.get(text, text)
        return text if text in {"invoice", "receipt", "credit_note"} else "other"

    @field_validator("line_items", mode="before")
    @classmethod
    def _items(cls, value: Any) -> Any:
        return [] if value is None else value


class Issue(BaseModel):
    """A problem found by the deterministic checks (or by the pipeline)."""

    level: Literal["error", "warning"]
    code: str
    message: str
    field: str | None = None


class ExtractionResult(BaseModel):
    """The outcome of processing one file, successful or not."""

    source: str
    document: ExtractedDocument | None = None
    issues: list[Issue] = Field(default_factory=list)
    model: str | None = None
    pages: int = 0
    elapsed_seconds: float = 0.0
    error: str | None = None
    raw_response: str | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def status(self) -> Literal["ok", "review", "failed"]:
        """``ok`` = passed every check, ``review`` = a human should look, ``failed`` = no usable data."""
        if self.error or self.document is None:
            return "failed"
        return "review" if self.issues else "ok"
