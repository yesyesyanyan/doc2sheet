import json
from datetime import date

from doc2sheet.extractor import extract_document, extract_many
from doc2sheet.loaders import load_document
from tests.helpers import FakeLLM, invoice_json

TODAY = date(2026, 9, 27)


def test_happy_path_on_a_digital_pdf(samples):
    llm = FakeLLM([invoice_json()])
    result = extract_document(samples / "invoice_pixel_pine_eur.pdf", llm, today=TODAY)

    assert result.status == "ok", result.issues
    assert result.document.vendor_name.startswith("Pixel & Pine")
    assert result.pages == 1 and result.model == "fake/model"
    # the PDF's text layer and one page image were sent to the model
    user_content = llm.calls[0][1]["content"]
    assert "INV-2026-0142" in user_content[0]["text"]
    assert sum(part["type"] == "image_url" for part in user_content) == 1


def test_scanned_pdf_and_photo_are_sent_as_images_only(samples):
    for name in ("invoice_harbor_vine_scanned.pdf", "receipt_blue_heron_photo.png"):
        doc = load_document(samples / name)
        assert doc.images and doc.text == ""


def test_invalid_output_is_repaired_once(samples):
    llm = FakeLLM(["Sorry, here you go: {not json", invoice_json()])
    result = extract_document(samples / "invoice_pixel_pine_eur.pdf", llm, today=TODAY)
    assert result.status == "ok"
    assert len(llm.calls) == 2
    assert "could not be used" in llm.calls[1][-1]["content"]


def test_fails_cleanly_when_repair_also_fails(samples):
    llm = FakeLLM(["nope", "still nope"])
    result = extract_document(samples / "invoice_pixel_pine_eur.pdf", llm, today=TODAY)
    assert result.status == "failed"
    assert "still invalid" in result.error
    assert len(llm.calls) == 2


def test_wrong_total_on_the_document_is_flagged(samples):
    # The model faithfully copies the (wrong) printed total from the Kestrel sample.
    reply = json.dumps(
        {
            "document_type": "invoice",
            "vendor_name": "Kestrel Logistics Ltd",
            "document_number": "KL-88213",
            "issue_date": "2026-08-12",
            "due_date": "2026-09-11",
            "currency": "GBP",
            "subtotal": 383.40,
            "tax": 76.68,
            "total": 469.08,
            "line_items": [
                {"description": "Pallet freight", "quantity": 4, "unit_price": 85, "amount": 340},
                {"description": "Tail-lift surcharge", "quantity": 1, "unit_price": 25, "amount": 25},
                {"description": "Fuel surcharge", "quantity": 1, "unit_price": 18.40, "amount": 18.40},
            ],
        }
    )
    result = extract_document(samples / "invoice_kestrel_total_error.pdf", FakeLLM([reply]), today=TODAY)
    assert result.status == "review"
    assert [i.code for i in result.issues] == ["total_mismatch"]


def test_unsupported_and_missing_files(tmp_path):
    llm = FakeLLM([invoice_json()])
    text_file = tmp_path / "notes.txt"
    text_file.write_text("hello")
    assert "Unsupported file type" in extract_document(text_file, llm).error
    assert "not found" in extract_document(tmp_path / "missing.pdf", llm).error
    assert llm.calls == []


def test_corrupt_pdf(tmp_path):
    bad = tmp_path / "broken.pdf"
    bad.write_bytes(b"%PDF-1.7 this is not really a pdf")
    result = extract_document(bad, FakeLLM([invoice_json()]))
    assert result.status == "failed" and "Could not open PDF" in result.error


def test_unexpected_exceptions_do_not_escape(samples):
    def explode(_messages):
        raise RuntimeError("network cable unplugged")

    result = extract_document(samples / "invoice_pixel_pine_eur.pdf", FakeLLM(explode))
    assert result.status == "failed" and "network cable unplugged" in result.error


def test_extract_many_keeps_input_order_and_reports_progress(samples):
    files = sorted(samples.glob("*.*"))
    progress = []
    results = extract_many(
        files,
        FakeLLM(lambda _m: invoice_json()),
        workers=3,
        on_progress=lambda done, total, r: progress.append((done, total)),
        today=TODAY,
    )
    assert [r.source for r in results] == [f.name for f in files]
    assert sorted(progress) == [(i, len(files)) for i in range(1, len(files) + 1)]


def test_image_size_is_configurable(samples):
    import base64
    import io

    from PIL import Image

    llm = FakeLLM([invoice_json()])
    extract_document(samples / "receipt_blue_heron_photo.png", llm, max_side=512, today=TODAY)
    url = llm.calls[0][1]["content"][1]["image_url"]["url"]
    image = Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1])))
    assert max(image.size) <= 512
