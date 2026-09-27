"""Build the static showcase page in showcase/ from a saved results file.

The page displays a recorded run (it never calls a model), so it can be hosted
for free as a static Hugging Face Space or on GitHub Pages.

    python -m doc2sheet samples -o results.xlsx --json results.json
    python scripts/build_showcase.py results.json --recorded "27 Sep 2026"
    python scripts/deploy_showcase.py --space doc2sheet
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from doc2sheet.loaders import load_document  # noqa: E402

SAMPLES = ROOT / "samples"
OUT = ROOT / "showcase"
TEMPLATE = Path(__file__).with_name("showcase_template.html")

# Display order and a one-line description of what each sample tests.
SAMPLE_INFO = {
    "invoice_pixel_pine_eur.pdf": (
        "Studio invoice · EUR",
        "Digital PDF with European formatting: 2 575,00 € and dd.mm.yyyy dates.",
    ),
    "invoice_harbor_vine_scanned.pdf": (
        "Scanned invoice · AUD",
        "Image-only scan, slightly rotated, with no text layer. Delivery is a separate charge plus 10% GST.",
    ),
    "receipt_blue_heron_photo.png": (
        "Receipt photo · USD",
        "Phone photo of a till receipt, with sales tax and a tip. '2 x Oat Latte $10.50' is a line total.",
    ),
    "invoice_kestrel_total_error.pdf": (
        "Wrong total · GBP",
        "Built with a deliberate £9.00 error in the printed total. "
        "The model copies it faithfully and the check catches it.",
    ),
}

SPACE_README = """---
title: Doc2Sheet
emoji: 🧾
colorFrom: green
colorTo: blue
sdk: static
app_file: index.html
pinned: false
license: mit
short_description: Invoices & receipts → validated spreadsheet (vision LLM)
tags:
  - document-ai
  - invoice
  - ocr
  - automation
---

# Doc2Sheet

Recorded results of Doc2Sheet on four sample documents. Source code, CLI and the Gradio app:
{github}
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("results", help="JSON written by `python -m doc2sheet ... --json`")
    parser.add_argument("--recorded", required=True, help='when the run was made, e.g. "27 Sep 2026"')
    parser.add_argument("--github", default="https://github.com/yesyesyanyan/doc2sheet")
    parser.add_argument("--author-url", default="https://github.com/yesyesyanyan")
    args = parser.parse_args()

    results = json.loads(Path(args.results).read_text(encoding="utf-8"))
    order = list(SAMPLE_INFO)
    results.sort(key=lambda r: order.index(r["source"]) if r["source"] in order else len(order))
    models = {r.get("model") for r in results if r.get("model")}

    assets = OUT / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    samples = {}
    for r in results:
        path = SAMPLES / r["source"]
        stem = path.stem
        (assets / f"{stem}.jpg").write_bytes(load_document(path, max_pages=1, max_side=1400).images[0])
        (assets / f"{stem}_thumb.jpg").write_bytes(load_document(path, max_pages=1, max_side=160).images[0])
        title, note = SAMPLE_INFO.get(r["source"], (r["source"], ""))
        samples[r["source"]] = {
            "title": title,
            "note": note,
            "image": f"assets/{stem}.jpg",
            "thumb": f"assets/{stem}_thumb.jpg",
        }

    data = {
        "model": ", ".join(sorted(models)) or "unknown model",
        "recorded": args.recorded,
        "github": args.github,
        "author_url": args.author_url,
        "results": results,
        "samples": samples,
    }
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    html = TEMPLATE.read_text(encoding="utf-8").replace("/*__DATA__*/", payload)
    (OUT / "index.html").write_text(html, encoding="utf-8")
    (OUT / "README.md").write_text(SPACE_README.format(github=args.github), encoding="utf-8")
    print(f"Built {OUT / 'index.html'} with {len(results)} documents")


if __name__ == "__main__":
    main()
