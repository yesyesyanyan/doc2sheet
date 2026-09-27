"""Doc2Sheet web demo (Gradio). Runs locally with `python app.py` and on Hugging Face Spaces."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import gradio as gr
import pandas as pd

from doc2sheet.config import SUGGESTED_MODELS, Settings
from doc2sheet.export import ISSUE_COLUMNS, LINE_ITEM_COLUMNS
from doc2sheet.llm import OpenAICompatibleClient
from doc2sheet.loaders import SUPPORTED_SUFFIXES, load_document
from doc2sheet.service import UI_DOCUMENT_COLUMNS, UserFacingError, resolve_connection, run_batch

ROOT = Path(__file__).resolve().parent
SAMPLES_DIR = ROOT / "samples"
SAMPLE_FILES = sorted(p for p in SAMPLES_DIR.glob("*") if p.suffix.lower() in SUPPORTED_SUFFIXES)

SETTINGS = Settings.from_env()
# On Hugging Face Spaces SPACE_ID is set automatically -> lock down the public demo.
PUBLIC_DEMO = os.getenv("DOC2SHEET_PUBLIC_DEMO", "1" if os.getenv("SPACE_ID") else "0") == "1"
MAX_FILES = int(os.getenv("DOC2SHEET_MAX_FILES", "5" if PUBLIC_DEMO else "50"))
GITHUB_URL = os.getenv("DOC2SHEET_GITHUB_URL", "https://github.com/yesyesyanyan/doc2sheet")

HEADER = f"""
# 🧾 Doc2Sheet — invoices & receipts → validated spreadsheet

Drop in PDFs, scans or phone photos. A vision LLM reads them, Pydantic enforces the schema,
and **deterministic checks re-do the arithmetic** so wrong totals get flagged instead of silently
landing in your books. Export to Excel, CSV or JSON. · [Source code on GitHub]({GITHUB_URL})
"""

FOOTER = """
**How it works:** PDF pages are rendered to images (and the text layer is kept when there is one) →
one call to an OpenAI-compatible vision model with a strict JSON schema → parse & validate, with one
automatic repair round if the output is malformed → checks: line maths, items vs subtotal,
subtotal − discount + charges + tax = total, dates, currency.

**Privacy:** files are sent to the selected model provider and are not stored by this app. Please don't
upload confidential documents to the public demo — run it locally (it also works fully offline with Ollama).
The four samples are fictional.
"""


def _sample_previews() -> list[tuple[str, str]]:
    """Small preview images of the sample documents for the gallery."""
    out_dir = Path(tempfile.mkdtemp(prefix="doc2sheet_previews_"))
    previews = []
    for path in SAMPLE_FILES:
        try:
            doc = load_document(path, max_pages=1, max_side=700)
        except Exception:  # a broken sample should never stop the app from starting
            continue
        preview = out_dir / f"{path.stem}.jpg"
        preview.write_bytes(doc.images[0])
        previews.append((str(preview), path.name))
    return previews


def _frame(rows: list[list], columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=columns)


def extract(files, model, api_key, base_url, progress=gr.Progress()):
    paths = [Path(f if isinstance(f, str) else f.name) for f in (files or [])]
    if not paths:
        raise gr.Error("Upload at least one PDF or image — or click “Try the sample documents”.")
    if len(paths) > MAX_FILES:
        gr.Warning(f"This demo processes up to {MAX_FILES} files at a time; the rest were skipped.")
        paths = paths[:MAX_FILES]

    try:
        conn = resolve_connection(SETTINGS, model=model, api_key=api_key, base_url=base_url, public_demo=PUBLIC_DEMO)
    except UserFacingError as exc:
        raise gr.Error(str(exc)) from exc

    llm = OpenAICompatibleClient.from_settings(SETTINGS, base_url=conn.base_url, api_key=conn.api_key, model=conn.model)
    progress(0, desc=f"Sending {len(paths)} document(s) to {conn.model}…")

    def on_progress(done: int, total: int, result) -> None:
        progress(done / total, desc=f"{done}/{total} done ({result.source})")

    try:
        output = run_batch(
            paths,
            llm,
            out_dir=tempfile.mkdtemp(prefix="doc2sheet_"),
            max_pages=SETTINGS.max_pages,
            max_side=SETTINGS.max_image_side,
            on_progress=on_progress,
        )
    finally:
        llm.close()

    return (
        output.summary,
        _frame(output.documents, UI_DOCUMENT_COLUMNS),
        _frame(output.line_items, LINE_ITEM_COLUMNS),
        _frame(output.issues, ISSUE_COLUMNS),
        output.json,
        [str(p) for p in output.files.values()],
    )


def load_samples() -> list[str]:
    return [str(p) for p in SAMPLE_FILES]


with gr.Blocks(title="Doc2Sheet — invoice & receipt extractor") as demo:
    gr.Markdown(HEADER)

    with gr.Row():
        with gr.Column(scale=2, min_width=320):
            files = gr.File(
                label=f"Invoices & receipts (PDF / PNG / JPG · up to {MAX_FILES})",
                file_count="multiple",
                file_types=sorted(SUPPORTED_SUFFIXES),
            )
            with gr.Row():
                run_btn = gr.Button("Extract", variant="primary")
                sample_btn = gr.Button("Try the sample documents", variant="secondary")

            with gr.Accordion("Model settings", open=False):
                model = gr.Dropdown(
                    choices=SUGGESTED_MODELS,
                    value=SETTINGS.model,
                    allow_custom_value=True,
                    label="Vision model",
                    info="Any image-capable chat model on the endpoint below.",
                )
                api_key = gr.Textbox(
                    label="Your API key (optional)",
                    type="password",
                    placeholder="Leave empty to use the demo's token",
                )
                base_url = gr.Textbox(
                    label="OpenAI-compatible base URL",
                    value=SETTINGS.base_url,
                    visible=not PUBLIC_DEMO,
                    info="e.g. http://localhost:11434/v1 for Ollama, https://api.openai.com/v1 for OpenAI",
                )

            if SAMPLE_FILES:
                gr.Gallery(
                    value=_sample_previews(),
                    label="Sample documents (fictional) — one has a deliberate total error",
                    columns=4,
                    height=230,
                )

        with gr.Column(scale=3, min_width=420):
            summary = gr.Markdown("Results will appear here.")
            with gr.Tabs():
                with gr.Tab("Documents"):
                    documents = gr.Dataframe(value=_frame([], UI_DOCUMENT_COLUMNS), interactive=False)
                with gr.Tab("Line items"):
                    line_items = gr.Dataframe(value=_frame([], LINE_ITEM_COLUMNS), interactive=False)
                with gr.Tab("Issues"):
                    issues = gr.Dataframe(value=_frame([], ISSUE_COLUMNS), interactive=False)
                with gr.Tab("JSON"):
                    raw_json = gr.JSON()
            downloads = gr.File(label="Download: Excel · CSV · JSON", file_count="multiple", interactive=False)

    gr.Markdown(FOOTER)

    inputs = [files, model, api_key, base_url]
    outputs = [summary, documents, line_items, issues, raw_json, downloads]
    run_btn.click(extract, inputs=inputs, outputs=outputs, api_name="extract")
    sample_btn.click(load_samples, outputs=files).then(extract, inputs=inputs, outputs=outputs)


if __name__ == "__main__":
    demo.queue(default_concurrency_limit=2, max_size=20)
    demo.launch(
        theme=gr.themes.Soft(primary_hue="emerald"),
        allowed_paths=[str(SAMPLES_DIR)],
    )
