"""UI-agnostic glue used by the web demo: credential rules, batch run, summary.

Kept out of app.py so it can be unit-tested without Gradio installed.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from doc2sheet.config import SUGGESTED_MODELS, Settings
from doc2sheet.export import (
    ISSUE_COLUMNS,
    LINE_ITEM_COLUMNS,
    as_table,
    document_rows,
    export_all,
    issue_rows,
    line_item_rows,
)
from doc2sheet.extractor import ProgressCallback, extract_many
from doc2sheet.llm import LLMClient
from doc2sheet.schema import ExtractionResult

# The columns shown in the UI table (the Excel file has all of them).
UI_DOCUMENT_COLUMNS = [
    "file",
    "status",
    "vendor",
    "number",
    "issue_date",
    "currency",
    "subtotal",
    "tax",
    "total",
    "issues",
]


class UserFacingError(ValueError):
    """An error whose message is safe and useful to show to the end user."""


@dataclass(frozen=True)
class Connection:
    base_url: str
    api_key: str | None
    model: str


def resolve_connection(
    settings: Settings,
    *,
    model: str | None,
    api_key: str | None,
    base_url: str | None,
    public_demo: bool,
) -> Connection:
    """Decide which endpoint, key and model a request may use.

    Security rules for a public demo:
    * the server's own key is only ever sent to the server's configured base URL
      (otherwise anyone could point the app at their own server and steal it);
    * the base URL can't be changed at all in public mode;
    * with the server's key, only the curated models can be used, so visitors
      can't burn the owner's credits on an expensive model.
    """
    user_key = (api_key or "").strip() or None
    chosen_model = (model or "").strip() or settings.model
    chosen_url = (base_url or "").strip().rstrip("/") or settings.base_url.rstrip("/")

    if public_demo and chosen_url != settings.base_url.rstrip("/"):
        raise UserFacingError(
            "The endpoint can't be changed in the public demo. Run the app locally to use another provider."
        )

    uses_server_url = chosen_url == settings.base_url.rstrip("/")
    key = user_key or (settings.api_key if uses_server_url else None)

    if uses_server_url and not key and "router.huggingface.co" in chosen_url:
        raise UserFacingError(
            "No API key is configured. Paste a Hugging Face token (with the "
            "'Make calls to Inference Providers' permission) in Model settings."
        )
    if public_demo and not user_key and chosen_model not in SUGGESTED_MODELS:
        raise UserFacingError(
            "Custom models need your own token in the public demo. "
            f"Pick one of: {', '.join(SUGGESTED_MODELS)} — or paste your token."
        )
    return Connection(base_url=chosen_url, api_key=key, model=chosen_model)


@dataclass
class BatchOutput:
    results: list[ExtractionResult]
    summary: str
    documents: list[list[Any]]
    line_items: list[list[Any]]
    issues: list[list[Any]]
    json: list[dict[str, Any]]
    files: dict[str, Path] = field(default_factory=dict)


def run_batch(
    paths: Sequence[str | Path],
    llm: LLMClient,
    *,
    out_dir: str | Path,
    max_pages: int = 3,
    max_side: int = 1600,
    workers: int = 3,
    on_progress: ProgressCallback | None = None,
) -> BatchOutput:
    results = extract_many(paths, llm, max_pages=max_pages, max_side=max_side, workers=workers, on_progress=on_progress)
    return BatchOutput(
        results=results,
        summary=summarise(results),
        documents=as_table(document_rows(results), UI_DOCUMENT_COLUMNS),
        line_items=as_table(line_item_rows(results), LINE_ITEM_COLUMNS),
        issues=as_table(issue_rows(results), ISSUE_COLUMNS),
        json=[r.model_dump(mode="json", exclude={"raw_response"}) for r in results],
        files=export_all(results, out_dir),
    )


def summarise(results: Sequence[ExtractionResult]) -> str:
    if not results:
        return "No documents processed."
    ok = sum(r.status == "ok" for r in results)
    review = sum(r.status == "review" for r in results)
    failed = sum(r.status == "failed" for r in results)
    seconds = sum(r.elapsed_seconds for r in results)
    parts = [f"**{len(results)} document(s)** processed ({seconds:.1f}s of model time)"]
    parts.append(f"✅ {ok} passed all checks")
    if review:
        parts.append(f"⚠️ {review} need review — see the *Issues* tab")
    if failed:
        parts.append(f"❌ {failed} failed")
    return " · ".join(parts)
