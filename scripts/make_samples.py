"""Generate the fictional sample documents in samples/.

Every company, address and number here is made up. The samples cover the cases
a real client pipeline meets: a digital PDF with European number formatting, a
phone photo of a receipt, a scanned (image-only) PDF, and an invoice whose
total is deliberately wrong so the validation checks have something to catch.

    python scripts/make_samples.py
"""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

OUT = Path(__file__).resolve().parent.parent / "samples"
FOOTER = "Fictional sample document generated for Doc2Sheet demos. Not a real company."


def eu(amount: float) -> str:
    """1234.5 -> '1 234,50'"""
    return f"{amount:,.2f}".replace(",", " ").replace(".", ",")


def us(amount: float) -> str:
    return f"{amount:,.2f}"


def draw_invoice(
    *,
    brand: str,
    accent: str,
    seller: list[str],
    buyer: list[str],
    meta: list[tuple[str, str]],
    columns: tuple[str, str, str, str],
    items: list[tuple[str, float, float]],
    totals: list[tuple[str, str]],
    money,
    note: str,
) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4
    left, right = 50, width - 50

    c.setFillColor(HexColor(accent))
    c.rect(0, height - 110, width, 110, stroke=0, fill=1)
    c.setFillColor(HexColor("#FFFFFF"))
    c.setFont("Helvetica-Bold", 22)
    c.drawString(left, height - 62, brand)
    c.setFont("Helvetica", 10)
    c.drawString(left, height - 82, seller[0])
    c.setFont("Helvetica-Bold", 26)
    c.drawRightString(right, height - 66, "INVOICE")

    c.setFillColor(HexColor("#222222"))
    y = height - 150
    c.setFont("Helvetica-Bold", 9)
    c.drawString(left, y, "FROM")
    c.drawString(left + 195, y, "BILL TO")
    c.setFont("Helvetica", 10)
    for i, line in enumerate(seller[1:]):
        c.drawString(left, y - 16 - i * 14, line)
    for i, line in enumerate(buyer):
        c.drawString(left + 195, y - 16 - i * 14, line)

    y = height - 150
    for i, (label, value) in enumerate(meta):
        c.setFont("Helvetica-Bold", 9)
        c.drawRightString(right - 100, y - i * 16, label)
        c.setFont("Helvetica", 10)
        c.drawRightString(right, y - i * 16, value)

    y = height - 290
    c.setFillColor(HexColor("#F1F3F5"))
    c.rect(left, y - 6, right - left, 22, stroke=0, fill=1)
    c.setFillColor(HexColor("#222222"))
    c.setFont("Helvetica-Bold", 9)
    c.drawString(left + 8, y + 2, columns[0])
    c.drawRightString(right - 190, y + 2, columns[1])
    c.drawRightString(right - 95, y + 2, columns[2])
    c.drawRightString(right - 8, y + 2, columns[3])

    c.setFont("Helvetica", 10)
    for description, qty, price in items:
        y -= 26
        c.drawString(left + 8, y, description)
        c.drawRightString(right - 190, y, f"{qty:g}")
        c.drawRightString(right - 95, y, money(price))
        c.drawRightString(right - 8, y, money(qty * price))
        c.setStrokeColor(HexColor("#E3E6EA"))
        c.line(left, y - 9, right, y - 9)

    y -= 40
    for i, (label, value) in enumerate(totals):
        last = i == len(totals) - 1
        c.setFont("Helvetica-Bold" if last else "Helvetica", 12 if last else 10)
        c.drawRightString(right - 110, y, label)
        c.drawRightString(right - 8, y, value)
        y -= 20 if not last else 0

    c.setFont("Helvetica", 9)
    c.setFillColor(HexColor("#555555"))
    c.drawString(left, 110, note)
    c.setFont("Helvetica-Oblique", 7.5)
    c.drawString(left, 40, FOOTER)
    c.showPage()
    c.save()
    return buf.getvalue()


def invoice_pixel_pine() -> bytes:
    items = [
        ("Brand identity workshop (half day)", 1, 850.00),
        ("Logo design - 3 concepts, 2 revisions", 1, 1200.00),
        ("Business card layout", 2, 150.00),
        ("Social media templates", 5, 45.00),
    ]
    subtotal = sum(q * p for _, q, p in items)
    vat = round(subtotal * 0.20, 2)
    return draw_invoice(
        brand="Pixel & Pine Design Studio",
        accent="#2F5D50",
        seller=[
            "Branding - Illustration - Web",
            "Pixel & Pine Design Studio SARL",
            "14 Rue des Exemples",
            "69002 Lyon, France",
            "VAT: FR00999999999",
        ],
        buyer=["Maple Street Bakery Ltd", "Attn: Accounts Payable", "7 Sample Lane", "Dublin D02, Ireland"],
        meta=[
            ("Invoice no.", "INV-2026-0142"),
            ("Invoice date", "01.09.2026"),
            ("Due date", "01.10.2026"),
            ("Currency", "EUR"),
        ],
        columns=("DESCRIPTION", "QTY", "UNIT PRICE", "AMOUNT"),
        items=items,
        totals=[
            ("Subtotal (excl. VAT)", f"{eu(subtotal)} €"),
            ("VAT 20%", f"{eu(vat)} €"),
            ("Total due", f"{eu(subtotal + vat)} €"),
        ],
        money=eu,
        note="Payment by bank transfer within 30 days. IBAN: FR00 0000 0000 0000 0000 0000 000 (sample).",
    )


def invoice_kestrel_with_error() -> bytes:
    items = [
        ("Pallet freight Manchester -> Leeds", 4, 85.00),
        ("Tail-lift surcharge", 1, 25.00),
        ("Fuel surcharge", 1, 18.40),
    ]
    subtotal = sum(q * p for _, q, p in items)
    vat = round(subtotal * 0.20, 2)
    wrong_total = subtotal + vat + 9.00  # deliberate error for the validation demo
    return draw_invoice(
        brand="Kestrel Logistics Ltd",
        accent="#7A3E2B",
        seller=[
            "Same-day & pallet freight across the North",
            "Kestrel Logistics Ltd",
            "Unit 4, Example Trading Estate",
            "Manchester M00 0AA, United Kingdom",
            "VAT Reg: GB000000000",
        ],
        buyer=["Oakridge Garden Supplies", "22 Placeholder Road", "Leeds LS00 0ZZ"],
        meta=[
            ("Invoice no.", "KL-88213"),
            ("Date", "12 August 2026"),
            ("Payment due", "11 September 2026"),
        ],
        columns=("SERVICE", "QTY", "RATE (£)", "AMOUNT (£)"),
        items=items,
        totals=[
            ("Net", f"£{us(subtotal)}"),
            ("VAT @ 20%", f"£{us(vat)}"),
            ("TOTAL", f"£{us(wrong_total)}"),
        ],
        money=us,
        note="Thank you for your business. Terms: 30 days net.",
    )


def invoice_harbor_vine() -> bytes:
    items = [
        ("Canape platter (serves 20)", 3, 120.00),
        ("Event staff (hours)", 6, 45.00),
    ]
    subtotal = sum(q * p for _, q, p in items)
    delivery = 35.00
    gst = round((subtotal + delivery) * 0.10, 2)
    return draw_invoice(
        brand="Harbor & Vine Catering",
        accent="#1D4E89",
        seller=[
            "Events - Corporate - Private",
            "Harbor & Vine Catering Pty Ltd",
            "3/18 Example Wharf",
            "Sydney NSW 2000, Australia",
            "ABN 00 000 000 000",
        ],
        buyer=["Lumen Analytics", "Level 9, 100 Demo Street", "Sydney NSW 2000"],
        meta=[("Tax invoice #", "1045"), ("Issued", "22/07/2026"), ("Due", "05/08/2026")],
        columns=("ITEM", "QTY", "PRICE", "TOTAL"),
        items=items,
        totals=[
            ("Subtotal", f"A${us(subtotal)}"),
            ("Delivery", f"A${us(delivery)}"),
            ("GST 10%", f"A${us(gst)}"),
            ("Amount due", f"A${us(subtotal + delivery + gst)}"),
        ],
        money=us,
        note="Please quote the invoice number with your payment.",
    )


def rasterise_as_scan(pdf_bytes: bytes) -> bytes:
    """Render a PDF page and degrade it like an office scanner, then wrap it as an image-only PDF."""
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(pdf_bytes)
    image = pdf[0].render(scale=150 / 72).to_pil().convert("L")
    pdf.close()
    image = image.rotate(0.9, resample=Image.Resampling.BICUBIC, expand=True, fillcolor=250)
    noise = Image.effect_noise(image.size, 18).point(lambda v: 128 + (v - 128) // 3)
    image = Image.blend(image, noise, 0.08).filter(ImageFilter.GaussianBlur(0.5))
    out = io.BytesIO()
    image.convert("RGB").save(out, format="PDF", resolution=150)
    return out.getvalue()


def _font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    names = ["DejaVuSansMono-Bold.ttf" if bold else "DejaVuSansMono.ttf", "cour.ttf", "Courier New.ttf"]
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def receipt_blue_heron() -> bytes:
    """A café receipt photographed on a table (slightly rotated, uneven light)."""
    items = [("Oat Latte", 2, 5.25), ("Blueberry Scone", 1, 3.75), ("Cold Brew", 1, 4.50), ("Avocado Toast", 1, 9.00)]
    subtotal = sum(q * p for _, q, p in items)
    tax = round(subtotal * 0.1035, 2)
    tip = 4.00
    total = subtotal + tax + tip

    w, h = 560, 1040
    paper = Image.new("L", (w, h), 247)
    d = ImageDraw.Draw(paper)
    regular, bold, big = _font(22), _font(22, bold=True), _font(34, bold=True)
    y = 40

    def centre(text: str, font: ImageFont.ImageFont, dy: int = 34) -> None:
        nonlocal y
        tw = d.textlength(text, font=font)
        d.text(((w - tw) / 2, y), text, font=font, fill=30)
        y += dy

    def row(left: str, right: str, font: ImageFont.ImageFont = regular) -> None:
        nonlocal y
        d.text((36, y), left, font=font, fill=30)
        d.text((w - 36 - d.textlength(right, font=font), y), right, font=font, fill=30)
        y += 32

    centre("BLUE HERON COFFEE CO.", big, 48)
    centre("400 Example Ave, Seattle WA", regular)
    centre("(000) 555-0199", regular, 50)
    row("Date: 09/14/2026", "10:42 AM")
    row("Order #A-3317", "Server: Jo")
    y += 10
    d.line((36, y, w - 36, y), fill=90, width=2)
    y += 18
    for name, qty, price in items:
        row(f"{qty} x {name}", f"${qty * price:.2f}")
    y += 8
    d.line((36, y, w - 36, y), fill=90, width=2)
    y += 18
    row("Subtotal", f"${subtotal:.2f}")
    row("Sales tax 10.35%", f"${tax:.2f}")
    row("Tip", f"${tip:.2f}")
    row("TOTAL", f"${total:.2f}", bold)
    y += 24
    row("VISA **** 0000", f"${total:.2f}")
    y += 30
    centre("Thank you! Come again :)", regular, 40)
    d.text((36, h - 60), "Fictional sample receipt - Doc2Sheet demo", font=_font(15), fill=120)

    # Place the receipt on a "table", rotate a little and add soft lighting.
    table = Image.new("RGB", (760, 1200), (121, 96, 76))
    receipt = paper.convert("RGB").rotate(-2.2, resample=Image.Resampling.BICUBIC, expand=True, fillcolor=(0, 0, 0))
    mask = paper.point(lambda _: 255).rotate(-2.2, resample=Image.Resampling.BICUBIC, expand=True, fillcolor=0)
    table.paste(receipt, (90, 70), mask)
    shade = Image.radial_gradient("L").resize(table.size).point(lambda v: 255 - v // 3)
    table = Image.composite(table, Image.new("RGB", table.size, (40, 32, 26)), shade)
    table = table.filter(ImageFilter.GaussianBlur(0.6))
    out = io.BytesIO()
    table.save(out, format="PNG", optimize=True)
    return out.getvalue()


def main() -> None:
    OUT.mkdir(exist_ok=True)
    files = {
        "invoice_pixel_pine_eur.pdf": invoice_pixel_pine(),
        "receipt_blue_heron_photo.png": receipt_blue_heron(),
        "invoice_harbor_vine_scanned.pdf": rasterise_as_scan(invoice_harbor_vine()),
        "invoice_kestrel_total_error.pdf": invoice_kestrel_with_error(),
    }
    for name, data in files.items():
        (OUT / name).write_bytes(data)
        print(f"wrote samples/{name} ({len(data) // 1024} KB)")


if __name__ == "__main__":
    main()
