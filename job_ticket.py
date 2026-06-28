"""Generate job submission ticket (PNG / JPEG / PDF) after Job Entry save."""

from __future__ import annotations

from datetime import datetime
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Image as RLImage
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

APP_ROOT = Path(__file__).resolve().parent
LOGO_CANDIDATES = (
    APP_ROOT / "assets" / "AmmarBuilder_logo.jpeg",
    APP_ROOT / "assets" / "AmmarBuilder_logo.JPEG",
    APP_ROOT / "AmmarBuilder_logo.jpeg",
    APP_ROOT / "AmmarBuilder_logo.JPEG",
)

TICKET_TITLE = "Job Information"
STATUS_LINE = "This job report has been submitted."
TICKET_ROWS = [
    ("Date", "Date"),
    ("Job ID", "Job ID"),
    ("Location", "Location"),
    ("Job Type", "Job Type"),
    ("Job Status", "Job Status"),
]

BLUE = "#5B9BD5"
RED = "#C62828"
BORDER = "#BDBDBD"
TEXT = "#222222"
LABEL_BG = "#F7F7F7"


def _logo_path() -> Path | None:
    for path in LOGO_CANDIDATES:
        if path.exists():
            return path
    return None


def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = ["arialbd.ttf", "Arial Bold.ttf"] if bold else ["arial.ttf", "Arial.ttf"]
    for name in candidates:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def format_ticket_date(value: str) -> str:
    """Display date as DD-MM-YYYY on the ticket."""
    raw = str(value or "").strip()
    if not raw:
        return datetime.now().strftime("%d-%m-%Y")
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(raw[:19], fmt).strftime("%d-%m-%Y")
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(raw).strftime("%d-%m-%Y")
    except ValueError:
        return raw


def ticket_details(record: dict) -> dict[str, str]:
    return {
        "Date": format_ticket_date(record.get("Date") or record.get("Create at", "")),
        "Job ID": str(record.get("Job ID", "")).strip(),
        "Location": str(record.get("Location", "")).strip(),
        "Job Type": str(record.get("Job Type", "")).strip(),
        "Job Status": str(record.get("Job Status", "")).strip(),
    }


def build_ticket_image(record: dict, image_format: str = "PNG") -> bytes:
    """Render ticket as PNG or JPEG bytes (Coway-style layout)."""
    details = ticket_details(record)
    width = 620
    pad = 28
    logo_h = 88
    header_h = 42
    status_h = 34
    row_h = 38
    body_h = row_h * len(TICKET_ROWS) + pad * 2
    height = pad + logo_h + 16 + header_h + 12 + status_h + 12 + body_h + pad

    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    font_label = _load_font(15)
    font_value = _load_font(16)
    font_value_bold = _load_font(18, bold=True)
    font_header = _load_font(17, bold=True)
    font_status = _load_font(14)
    font_logo = _load_font(12)

    y = pad

    logo = _logo_path()
    if logo:
        logo_img = Image.open(logo).convert("RGBA")
        max_w, max_h = 220, logo_h
        scale = min(max_w / logo_img.width, max_h / logo_img.height, 1.0)
        new_size = (int(logo_img.width * scale), int(logo_img.height * scale))
        logo_img = logo_img.resize(new_size, Image.Resampling.LANCZOS)
        bg = Image.new("RGB", new_size, "white")
        bg.paste(logo_img, mask=logo_img.split()[-1] if logo_img.mode == "RGBA" else None)
        x_logo = (width - new_size[0]) // 2
        img.paste(bg, (x_logo, y))
        y += new_size[1] + 14
    else:
        draw.text((width // 2, y), "Ammar Builder Enterprise", fill=BLUE, anchor="mt", font=font_logo)
        y += 36

    header_box = [pad, y, width - pad, y + header_h]
    draw.rounded_rectangle(header_box, radius=6, fill=BLUE)
    draw.text((width // 2, y + header_h // 2), TICKET_TITLE, fill="white", anchor="mm", font=font_header)
    y += header_h + 14

    draw.text((pad + 8, y), STATUS_LINE, fill=RED, font=font_status)
    y += status_h

    box_top = y
    box = [pad, box_top, width - pad, box_top + body_h]
    draw.rectangle(box, outline=BORDER, width=2)

    inner_y = box_top + pad
    label_x = pad + 16
    value_x = pad + 190

    for label, key in TICKET_ROWS:
        draw.text((label_x, inner_y), f"{label}:", fill=TEXT, font=font_label)
        value = details.get(key, "")
        value_font = font_value_bold if key == "Job ID" else font_value
        draw.text((value_x, inner_y - 1), value, fill=TEXT, font=value_font)
        inner_y += row_h

    buf = BytesIO()
    fmt = image_format.upper()
    if fmt == "JPEG":
        img.save(buf, format="JPEG", quality=92)
    else:
        img.save(buf, format="PNG")
    buf.seek(0)
    return buf.getvalue()


def build_ticket_pdf(record: dict) -> BytesIO:
    """Render ticket as a single-page PDF."""
    details = ticket_details(record)
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=0.85 * inch,
        rightMargin=0.85 * inch,
        topMargin=0.7 * inch,
        bottomMargin=0.6 * inch,
    )
    styles = getSampleStyleSheet()
    elements = []

    logo = _logo_path()
    if logo:
        reader = ImageReader(str(logo))
        iw, ih = reader.getSize()
        scale = min(2.2 * inch / iw, 0.9 * inch / ih)
        elements.append(RLImage(str(logo), width=iw * scale, height=ih * scale))
        elements.append(Spacer(1, 0.15 * inch))

    header_style = ParagraphStyle(
        "TicketHeader",
        parent=styles["Normal"],
        fontSize=14,
        alignment=TA_CENTER,
        textColor=colors.white,
        backColor=colors.HexColor(BLUE),
        leading=18,
        spaceBefore=4,
        spaceAfter=4,
    )
    elements.append(Paragraph(TICKET_TITLE, header_style))
    elements.append(Spacer(1, 0.12 * inch))

    status_style = ParagraphStyle(
        "TicketStatus",
        parent=styles["Normal"],
        fontSize=11,
        textColor=colors.HexColor(RED),
        fontName="Helvetica-Oblique",
    )
    elements.append(Paragraph(STATUS_LINE, status_style))
    elements.append(Spacer(1, 0.12 * inch))

    rows = []
    for label, key in TICKET_ROWS:
        value = details.get(key, "")
        if key == "Job ID":
            value = f"<b>{value}</b>"
        rows.append([label, value])

    table = Table(rows, colWidths=[1.6 * inch, 4.0 * inch])
    table.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 1, colors.HexColor(BORDER)),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor(BORDER)),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor(LABEL_BG)),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 11),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    elements.append(table)

    doc.build(elements)
    buffer.seek(0)
    return buffer
