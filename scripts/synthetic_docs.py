"""Render synthetic onboarding documents as PDFs (reportlab) and scanned images.

Every document carries a visible "SYNTHETIC TEST DOCUMENT" banner. Layouts are
simplified look-alikes, not reproductions of official forms. Each type has two
layout variants (different label wording and arrangement) so extraction is not
tuned to a single template.
"""
from __future__ import annotations

import io
import random
from datetime import date

from PIL import Image, ImageFilter
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

W, H = A4
BANNER = "SYNTHETIC TEST DOCUMENT - NOT A REAL RECORD - VENDORGATE DEMO"


def fmt_date(d: date, style: str = "dmy") -> str:
    if style == "long":
        return d.strftime("%d %B %Y").lstrip("0")
    if style == "us":
        return d.strftime("%m/%d/%Y")
    return d.strftime("%d/%m/%Y")


class _Doc:
    """Tiny helper around a reportlab canvas that writes lines top-down."""

    def __init__(self, accent: str = "#1F4E79"):
        self.buf = io.BytesIO()
        self.c = canvas.Canvas(self.buf, pagesize=A4)
        self.c.setTitle("Synthetic document")
        self.y = H - 40
        self.accent = HexColor(accent)
        self._banner()

    def _banner(self) -> None:
        c = self.c
        c.setFillColor(HexColor("#B00020"))
        c.setFont("Helvetica-Bold", 8)
        c.drawCentredString(W / 2, H - 18, BANNER)
        c.drawCentredString(W / 2, 14, BANNER)
        c.setFillColor(HexColor("#000000"))

    def header(self, lines: list[str], size: int = 15) -> None:
        c = self.c
        c.setFillColor(self.accent)
        c.rect(36, self.y - 8 - 20 * len(lines), W - 72, 20 * len(lines) + 12, stroke=0, fill=1)
        c.setFillColor(HexColor("#FFFFFF"))
        y = self.y - 22
        for i, line in enumerate(lines):
            c.setFont("Helvetica-Bold", size if i == 0 else size - 4)
            c.drawString(48, y, line)
            y -= 20
        c.setFillColor(HexColor("#000000"))
        self.y = y - 20

    def title(self, text: str, size: int = 13) -> None:
        self.c.setFont("Helvetica-Bold", size)
        self.c.drawString(48, self.y, text)
        self.y -= 26

    def row(self, label: str, value: str, label_width: int = 210) -> None:
        self.c.setFont("Helvetica", 10)
        self.c.setFillColor(HexColor("#444444"))
        self.c.drawString(48, self.y, label)
        self.c.setFillColor(HexColor("#000000"))
        self.c.setFont("Helvetica-Bold", 10.5)
        self.c.drawString(48 + label_width, self.y, value)
        self.y -= 20

    def stacked(self, label: str, value: str) -> None:
        """Label on one line, value underneath (layout variant B)."""
        self.c.setFont("Helvetica", 8.5)
        self.c.setFillColor(HexColor("#555555"))
        self.c.drawString(48, self.y, label.upper())
        self.c.setFillColor(HexColor("#000000"))
        self.c.setFont("Helvetica", 11)
        self.c.drawString(48, self.y - 14, value)
        self.y -= 34

    def para(self, text: str, size: float = 10.5, width: int = 92) -> None:
        self.c.setFont("Helvetica", size)
        words, line = text.split(), ""
        for w in words:
            if len(line) + len(w) + 1 > width:
                self.c.drawString(48, self.y, line)
                self.y -= size + 5
                line = w
            else:
                line = f"{line} {w}".strip()
        if line:
            self.c.drawString(48, self.y, line)
            self.y -= size + 5
        self.y -= 8

    def tiny(self, text: str, color: str = "#BBBBBB") -> None:
        self.c.setFont("Helvetica", 6)
        self.c.setFillColor(HexColor(color))
        self.c.drawString(48, self.y, text)
        self.c.setFillColor(HexColor("#000000"))
        self.y -= 10

    def stamp(self, text: str) -> None:
        c = self.c
        c.saveState()
        c.setStrokeColor(HexColor("#B00020"))
        c.setFillColor(HexColor("#B00020"))
        c.setLineWidth(2)
        c.rect(W - 230, self.y - 6, 170, 30, stroke=1, fill=0)
        c.setFont("Helvetica-Bold", 16)
        c.drawCentredString(W - 145, self.y + 3, text)
        c.restoreState()
        self.y -= 44

    def signature(self, who: str) -> None:
        self.y -= 10
        self.c.setFont("Helvetica-Oblique", 10)
        self.c.drawString(48, self.y, "Authorised signatory")
        self.c.drawString(48, self.y - 14, who)
        self.y -= 34

    def pdf(self) -> bytes:
        self.c.showPage()
        self.c.save()
        return self.buf.getvalue()


# ---------------------------------------------------------------- India
def pan_card(d: dict, variant: str) -> bytes:
    doc = _Doc("#2E4053")
    if variant == "A":
        doc.header(["INCOME TAX DEPARTMENT", "Govt. of India (synthetic specimen)"])
        doc.title("Permanent Account Number Card")
        doc.row("Permanent Account Number", d["pan"])
        doc.row("Name", d["name"].upper())
        doc.row("Date of Incorporation/Formation", fmt_date(d["date"]))
    else:
        doc.header(["e-PAN", "Income Tax Department (synthetic specimen)"])
        doc.stacked("Name of holder", d["name"])
        doc.stacked("PAN", d["pan"])
        doc.stacked("Date of birth / incorporation", fmt_date(d["date"]))
        doc.para("This e-PAN is issued under the Permanent Account Number scheme. Synthetic layout for testing.")
    return doc.pdf()


def gst_certificate(d: dict, variant: str) -> bytes:
    doc = _Doc("#1E5631")
    if variant == "A":
        doc.header(["Government of India", "Form GST REG-06 - Registration Certificate"])
        doc.row("Registration Number", d["gstin"])
        doc.row("Legal Name", d["legal_name"])
        doc.row("Trade Name, if any", d["trade_name"] or "-")
        doc.row("Constitution of Business", d["constitution"])
        doc.row("Address of Principal Place of Business", d["address"][:48])
        if len(d["address"]) > 48:
            doc.row("", d["address"][48:])
        doc.row("Date of Liability", fmt_date(d["registration_date"]))
        doc.row("Period of Validity", f"From {fmt_date(d['registration_date'])} To Not Applicable")
        doc.row("Type of Registration", "Regular")
    else:
        doc.header(["Goods and Services Tax", "Registration Certificate (synthetic)"])
        doc.stacked("GSTIN", d["gstin"])
        doc.stacked("Legal Name of Business", d["legal_name"])
        doc.stacked("Trade Name", d["trade_name"] or "Not applicable")
        doc.stacked("Constitution of Business", d["constitution"])
        doc.stacked("Principal Place of Business", d["address"])
        doc.stacked("Date of Registration", fmt_date(d["registration_date"], "long"))
    doc.signature("Jurisdictional GST Officer (synthetic)")
    return doc.pdf()


def no_gst_declaration(d: dict, variant: str) -> bytes:
    doc = _Doc("#5D6D7E")
    doc.header([d["legal_name"], "Vendor letterhead (synthetic)"], size=13)
    doc.title("Declaration for Non-Registration under GST")
    doc.para(f"Date: {fmt_date(d['declaration_date'])}")
    doc.para(
        f"I/We, {d['legal_name']}, holding PAN {d['pan']}, hereby declare that we are not registered under "
        "the Goods and Services Tax Act as our aggregate turnover is below the threshold limit for registration. "
        "We undertake to inform you and provide our GSTIN as soon as we obtain registration."
    )
    doc.signature(d["signatory"])
    return doc.pdf()


def cancelled_cheque(d: dict, variant: str) -> bytes:
    doc = _Doc("#7D3C98")
    doc.header([d["bank_name"], f"Branch: {d['branch']}"])
    if variant == "A":
        doc.row("IFSC", d["ifsc"])
        doc.row("Date", "__ / __ / ____")
        doc.para("PAY ____________________________________________ OR BEARER")
        doc.para("RUPEES __________________________________________  Rs. ________")
        doc.row("A/c No.", d["account_number"])
        doc.row("Account holder", d["account_holder"].upper())
    else:
        doc.para(f"IFS Code: {d['ifsc']}     MICR: 000000000")
        doc.para("Pay _______________________________________ or Bearer")
        doc.stacked("Account Number", d["account_number"])
        doc.stacked("For", d["account_holder"])
    doc.stamp("CANCELLED")
    return doc.pdf()


def bank_letter(d: dict, variant: str, injection: str = "") -> bytes:
    """Bank confirmation letter for IN (IFSC), US (routing) or UK (sort code)."""
    doc = _Doc("#154360")
    doc.header([d["bank_name"], d.get("branch", "Corporate Banking")], size=14)
    country = d["country"]
    code_label, code_value = {
        "IN": ("IFSC", d.get("ifsc", "")),
        "US": ("ABA Routing Number", d.get("routing_number", "")),
        "GB": ("Sort Code", d.get("sort_code", "")),
    }[country]
    date_style = "us" if country == "US" else "long"
    if variant == "A":
        doc.para(f"Date: {fmt_date(d['letter_date'], date_style)}")
        doc.title("Bank Account Confirmation", 12)
        doc.para("To Whom It May Concern,")
        doc.para("This is to confirm that the following account is maintained with us and is active:")
        doc.row("Account Holder Name", d["account_holder"])
        doc.row("Account Number", d["account_number"])
        doc.row(code_label, code_value)
        doc.row("Account Type", d.get("account_type", "Current"))
    else:
        doc.para(f"{fmt_date(d['letter_date'], date_style)}")
        doc.title("Bank Account Verification Letter", 12)
        doc.para(
            f"We confirm that {d['account_holder']} holds account number {d['account_number']} with "
            f"{d['bank_name']} ({code_label} {code_value}). The account is in good standing."
        )
    if injection:
        doc.tiny(injection)
    doc.para("This letter is issued at the request of the customer without any liability on the bank.")
    doc.signature(f"Branch Manager, {d['bank_name']}")
    return doc.pdf()


def incorporation_certificate(d: dict, variant: str) -> bytes:
    doc = _Doc("#6E2C00")
    is_llp = d.get("llpin")
    id_label = "LLP Identification Number" if is_llp else "Corporate Identity Number"
    id_value = d.get("llpin") or d["cin"]
    act = "Limited Liability Partnership Act, 2008" if is_llp else "Companies Act, 2013"
    if variant == "A":
        doc.header(["Government of India", "Ministry of Corporate Affairs (synthetic)"])
        doc.title("Certificate of Incorporation")
        doc.para(
            f"I hereby certify that {d['company_name'].upper()} is incorporated on {fmt_date(d['incorporation_date'], 'long')} "
            f"under the {act} and that the {'LLP' if is_llp else 'company'} is limited."
        )
        doc.row(id_label, id_value)
        doc.para(f"Given under my hand at {d['roc_city']}.")
    else:
        doc.header(["Registrar of Companies", f"{d['roc_city']} (synthetic)"])
        doc.title("Certificate of Incorporation")
        doc.row("Name", d["company_name"])
        doc.row(id_label, id_value)
        doc.row("Date of Incorporation", fmt_date(d["incorporation_date"]))
        doc.row("Governing Act", act)
    doc.signature("Registrar of Companies (synthetic)")
    return doc.pdf()


# ---------------------------------------------------------------- US / UK
def w9(d: dict, variant: str) -> bytes:
    doc = _Doc("#1B2631")
    doc.header(["Form W-9 (Rev. March 2024) - simplified synthetic layout",
                "Request for Taxpayer Identification Number and Certification"], size=12)
    rows = [
        ("1 Name of entity/individual", d["name"]),
        ("2 Business name/disregarded entity", d["business_name"] or ""),
        ("3a Federal tax classification", d["tax_classification"]),
        ("5 Address", d["address_line"]),
        ("6 City, state, and ZIP code", d["city_state_zip"]),
        ("Part I  Employer identification number", d["ein"]),
    ]
    if variant == "B":
        rows = [rows[5], rows[0], rows[1], rows[2], rows[3], rows[4]]
    for label, value in rows:
        doc.row(label, value, label_width=230)
    doc.para("Part II Certification: Under penalties of perjury, I certify that the number shown on this form is "
             "my correct taxpayer identification number.")
    doc.row("Signature of U.S. person", d["signer"])
    doc.row("Date", fmt_date(d["signature_date"], "us"))
    return doc.pdf()


def company_registration_certificate(d: dict, variant: str) -> bytes:
    doc = _Doc("#0B5345")
    if variant == "A":
        doc.header(["Companies House (synthetic)", "Certificate of Incorporation of a Private Limited Company"], size=13)
        doc.row("Company Number", d["company_number"])
        doc.para(
            f"The Registrar of Companies for England and Wales hereby certifies that {d['company_name'].upper()} "
            f"is this day incorporated under the Companies Act 2006 as a private company, that the company is "
            f"limited by shares, and the situation of its registered office is in England and Wales."
        )
        doc.para(f"Given at Companies House, Cardiff, on {fmt_date(d['incorporation_date'], 'long')}")
    else:
        doc.header(["Certificate of Incorporation", "Companies House (synthetic)"], size=13)
        doc.stacked("Company name", d["company_name"])
        doc.stacked("Company number", d["company_number"])
        doc.stacked("Date of incorporation", fmt_date(d["incorporation_date"], "long"))
        doc.stacked("Company type", "Private company limited by shares")
    return doc.pdf()


RENDERERS = {
    "pan_card": pan_card,
    "gst_certificate": gst_certificate,
    "no_gst_declaration": no_gst_declaration,
    "cancelled_cheque": cancelled_cheque,
    "bank_letter": bank_letter,
    "incorporation_certificate": incorporation_certificate,
    "w9": w9,
    "company_registration_certificate": company_registration_certificate,
}


# ---------------------------------------------------------------- scans
def scan_image(pdf_bytes: bytes, seed: int, angle: float = 1.4) -> bytes:
    """Rasterise page 1, rotate slightly, add noise and blur, return JPEG bytes."""
    import pypdfium2 as pdfium

    rng = random.Random(seed)
    page = pdfium.PdfDocument(pdf_bytes)[0]
    img = page.render(scale=130 / 72).to_pil().convert("L")
    img = img.rotate(angle, expand=True, fillcolor=245)
    pixels = img.load()
    width, height = img.size
    for _ in range(width * height // 60):  # salt-and-pepper speckle like a photocopy
        x, y = rng.randrange(width), rng.randrange(height)
        pixels[x, y] = rng.choice((30, 90, 200, 255))
    img = img.filter(ImageFilter.GaussianBlur(0.6))
    out = io.BytesIO()
    img.convert("RGB").save(out, format="JPEG", quality=55)
    return out.getvalue()


def image_to_pdf(jpeg_bytes: bytes) -> bytes:
    """Wrap a scan in a PDF with no text layer (what a scanner app produces)."""
    out = io.BytesIO()
    Image.open(io.BytesIO(jpeg_bytes)).save(out, format="PDF", resolution=130)
    return out.getvalue()
