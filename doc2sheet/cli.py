"""Command line interface: batch-extract a folder of invoices into one spreadsheet.

python -m doc2sheet invoices/ -o results.xlsx
python -m doc2sheet "scans/*.jpg" --model Qwen/Qwen3-VL-8B-Instruct --json results.json
"""

from __future__ import annotations

import argparse
import glob
import logging
import sys
from pathlib import Path

from doc2sheet.config import HF_ROUTER_URL, Settings
from doc2sheet.export import write_csv, write_json, write_xlsx
from doc2sheet.extractor import extract_many
from doc2sheet.llm import JSON_MODES, OpenAICompatibleClient
from doc2sheet.loaders import SUPPORTED_SUFFIXES
from doc2sheet.schema import ExtractionResult


def expand_inputs(inputs: list[str]) -> list[Path]:
    """Accept files, folders and glob patterns (Windows shells don't expand globs)."""
    paths: list[Path] = []
    for item in inputs:
        matches = glob.glob(item) if any(ch in item for ch in "*?[") else [item]
        for match in matches:
            p = Path(match)
            if p.is_dir():
                paths += sorted(f for f in p.iterdir() if f.suffix.lower() in SUPPORTED_SUFFIXES)
            else:
                paths.append(p)
    seen: set[Path] = set()
    return [p for p in paths if not (p in seen or seen.add(p))]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="doc2sheet",
        description="Extract invoices & receipts (PDF/images) into a validated spreadsheet.",
    )
    parser.add_argument("inputs", nargs="+", help="files, folders or glob patterns")
    parser.add_argument("-o", "--xlsx", default="doc2sheet.xlsx", help="Excel output (default: %(default)s)")
    parser.add_argument("--csv", help="also write a one-row-per-document CSV")
    parser.add_argument("--json", help="also write full results as JSON")
    parser.add_argument("--model", help="model id (env: DOC2SHEET_MODEL)")
    parser.add_argument("--base-url", help="OpenAI-compatible base URL (env: DOC2SHEET_BASE_URL)")
    parser.add_argument("--api-key", help="API key (env: DOC2SHEET_API_KEY or HF_TOKEN)")
    parser.add_argument("--json-mode", choices=JSON_MODES, help="structured-output mode (default: auto)")
    parser.add_argument("--max-pages", type=int, help="pages per PDF sent to the model (default: 3)")
    parser.add_argument("--workers", type=int, default=4, help="files processed in parallel (default: 4)")
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s %(message)s")

    settings = Settings.from_env()
    files = expand_inputs(args.inputs)
    if not files:
        print("No input files found.", file=sys.stderr)
        return 2

    base_url = args.base_url or settings.base_url
    api_key = args.api_key or settings.api_key
    if not api_key and base_url.rstrip("/") == HF_ROUTER_URL:
        print(
            "No API key. Set HF_TOKEN (a Hugging Face token with 'Make calls to Inference Providers'),\n"
            "or point --base-url at another provider, e.g. a local Ollama: http://localhost:11434/v1",
            file=sys.stderr,
        )
        return 2

    llm = OpenAICompatibleClient.from_settings(
        settings, base_url=base_url, api_key=api_key, model=args.model, json_mode=args.json_mode
    )
    max_pages = args.max_pages or settings.max_pages
    print(f"Processing {len(files)} file(s) with {llm.model} ...")

    def progress(done: int, total: int, r: ExtractionResult) -> None:
        print(f"[{done}/{total}] {r.status.upper():7} {r.source}  {_summary(r)}")

    try:
        results = extract_many(
            files,
            llm,
            max_pages=max_pages,
            max_side=settings.max_image_side,
            workers=args.workers,
            on_progress=progress,
        )
    finally:
        llm.close()

    write_xlsx(results, args.xlsx)
    written = [args.xlsx]
    if args.csv:
        written.append(str(write_csv(results, args.csv)))
    if args.json:
        written.append(str(write_json(results, args.json)))

    counts = {s: sum(r.status == s for r in results) for s in ("ok", "review", "failed")}
    print(f"\nDone: {counts['ok']} ok, {counts['review']} need review, {counts['failed']} failed.")
    print("Wrote: " + ", ".join(written))
    return 1 if counts["failed"] else 0


def _summary(r: ExtractionResult) -> str:
    if r.error:
        return f"- {r.error}"
    d = r.document
    assert d is not None
    total = f"{d.currency or ''} {d.total:,.2f}".strip() if d.total is not None else "no total"
    note = f"  ({len(r.issues)} issue(s))" if r.issues else ""
    return f"{d.vendor_name or '?'} | {total} | {r.elapsed_seconds}s{note}"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
