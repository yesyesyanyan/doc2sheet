"""The pipeline: load file -> ask the model -> parse & validate -> repair once -> check."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

from pydantic import ValidationError

from doc2sheet.checks import run_checks
from doc2sheet.llm import LLMClient, ProviderError
from doc2sheet.loaders import LoaderError, load_document
from doc2sheet.prompts import EXTRACTION_SCHEMA, build_messages, parse_json_reply, repair_messages
from doc2sheet.schema import ExtractedDocument, ExtractionResult, Issue

log = logging.getLogger(__name__)

ProgressCallback = Callable[[int, int, ExtractionResult], None]


def extract_document(
    path: str | Path,
    llm: LLMClient,
    *,
    max_pages: int = 3,
    max_side: int = 1600,
    today: date | None = None,
) -> ExtractionResult:
    """Process one file. Never raises: failures are reported on the result."""
    started = time.perf_counter()
    result = ExtractionResult(source=Path(path).name, model=llm.model)
    try:
        _run(Path(path), llm, result, max_pages=max_pages, max_side=max_side, today=today)
    except Exception as exc:  # keep a batch alive no matter what one file does
        log.exception("Unexpected error while processing %s", path)
        result.error = f"Unexpected error: {type(exc).__name__}: {exc}"
    result.elapsed_seconds = round(time.perf_counter() - started, 2)
    return result


def _run(
    path: Path, llm: LLMClient, result: ExtractionResult, *, max_pages: int, max_side: int, today: date | None
) -> None:
    try:
        loaded = load_document(path, max_pages=max_pages, max_side=max_side)
    except LoaderError as exc:
        result.error = str(exc)
        return
    result.pages = loaded.page_count

    messages = build_messages(loaded)
    try:
        reply = llm.complete(messages, json_schema=EXTRACTION_SCHEMA)
        result.raw_response = reply
        try:
            document = _parse(reply)
        except (ValueError, ValidationError) as first_error:
            log.info("Invalid output for %s, asking the model to repair it: %s", path.name, first_error)
            reply = llm.complete(repair_messages(messages, reply, _short(first_error)), json_schema=EXTRACTION_SCHEMA)
            result.raw_response = reply
            document = _parse(reply)
    except ProviderError as exc:
        result.error = f"Model call failed: {exc}"
        return
    except (ValueError, ValidationError) as exc:
        result.error = f"Model output was still invalid after one repair attempt: {_short(exc)}"
        return

    result.document = document
    result.issues = run_checks(document, today=today)
    if loaded.truncated:
        result.issues.append(
            Issue(
                level="warning",
                code="pages_truncated",
                message=f"Only the first {len(loaded.images)} of {loaded.page_count} pages were read.",
            )
        )


def extract_many(
    paths: Sequence[str | Path],
    llm: LLMClient,
    *,
    max_pages: int = 3,
    max_side: int = 1600,
    workers: int = 4,
    on_progress: ProgressCallback | None = None,
    today: date | None = None,
) -> list[ExtractionResult]:
    """Process several files concurrently; results come back in input order."""
    results: list[ExtractionResult | None] = [None] * len(paths)
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {
            pool.submit(extract_document, p, llm, max_pages=max_pages, max_side=max_side, today=today): i
            for i, p in enumerate(paths)
        }
        for done, future in enumerate(as_completed(futures), start=1):
            index = futures[future]
            results[index] = future.result()
            if on_progress:
                on_progress(done, len(paths), results[index])
    return [r for r in results if r is not None]


def _parse(reply: str) -> ExtractedDocument:
    return ExtractedDocument.model_validate(parse_json_reply(reply))


def _short(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        errors = exc.errors()[:3]
        return "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in errors)
    return str(exc)[:300]
