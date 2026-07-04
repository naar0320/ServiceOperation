"""Build job report PDFs with wrapped text and aligned image grids."""

from __future__ import annotations

import re
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Image as RLImage
from reportlab.platypus import KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

APP_ROOT = Path(__file__).resolve().parent
LOGO_CANDIDATES = (
    APP_ROOT / "assets" / "AmmarBuilder_logo.jpeg",
    APP_ROOT / "assets" / "AmmarBuilder_logo.JPEG",
    APP_ROOT / "AmmarBuilder_logo.jpeg",
    APP_ROOT / "AmmarBuilder_logo.JPEG",
)

DETAIL_COLUMNS = [
    "Job ID",
    "Job Type",
    "Job Status",
    "Severity",
    "Priority",
    "Location",
    "Create By",
    "Create at",
    "Date",
    "Attend by",
    "Time Start",
    "Time End",
    "Task Description",
    "Action",
    "Remark",
    "Verify by",
    "Spare Parts Used",
]

PAGE_WIDTH, PAGE_HEIGHT = A4
MARGIN = 0.55 * inch
CONTENT_WIDTH = PAGE_WIDTH - 2 * MARGIN
LABEL_WIDTH = 1.8 * inch
VALUE_WIDTH = CONTENT_WIDTH - LABEL_WIDTH

GRID_COLS = 2
IMAGES_PER_PAGE = 8  # 2 columns × up to 4 rows per page
REPORT_TOP_MARGIN = 0.6 * inch
REPORT_BOTTOM_MARGIN = 0.55 * inch
IMAGE_CAPTION_H = 0.22 * inch
IMAGE_CELL_EXTRA = 14
IMAGE_H_MAX = 2.35 * inch
IMAGE_H_MIN = 0.48 * inch

IMAGE_PAGE_LABELS = {
    "Before": "Before Images",
    "After": "After Images",
    "Inspection": "Inspection Images",
    "Photos": "Photos",
}

CELL_PAD = 6
GRID_BORDER = colors.HexColor("#c8c8c8")
GRID_INNER = colors.HexColor("#d8d8d8")
DETAIL_BORDER = colors.HexColor("#bbbbbb")
DETAIL_INNER = colors.HexColor("#dddddd")


def _text_paragraph(text: str, style: ParagraphStyle) -> Paragraph:
    safe = escape(str(text or "")).replace("\n", "<br/>")
    return Paragraph(safe, style)


def _table_style_base() -> list[tuple]:
    return [
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]


def _full_width_wrapper(flowable, *, left: int = 0, right: int = 0) -> Table:
    """Wrap a block so its outer edge matches the details table width."""
    wrapper = Table([[flowable]], colWidths=[CONTENT_WIDTH])
    wrapper.setStyle(TableStyle(_table_style_base() + [
        ("LEFTPADDING", (0, 0), (-1, -1), left),
        ("RIGHTPADDING", (0, 0), (-1, -1), right),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return wrapper


def _scaled_image(img_bytes: bytes, max_width: float, max_height: float) -> RLImage:
    reader = ImageReader(BytesIO(img_bytes))
    iw, ih = reader.getSize()
    if iw <= 0 or ih <= 0:
        return RLImage(BytesIO(img_bytes), width=max_width, height=max_height)

    scale = min(max_width / iw, max_height / ih, 1.0)
    return RLImage(BytesIO(img_bytes), width=iw * scale, height=ih * scale)


def _centered_image_box(img_bytes: bytes, box_w: float, box_h: float) -> Table:
    """Center an image inside a fixed box so grid lines stay even."""
    try:
        img = _scaled_image(img_bytes, box_w - 4, box_h - 4)
    except Exception:
        img = Paragraph("<font size=7>(Image unavailable)</font>", getSampleStyleSheet()["Normal"])

    box = Table([[img]], colWidths=[box_w], rowHeights=[box_h])
    box.setStyle(TableStyle(_table_style_base() + [
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOX", (0, 0), (-1, -1), 0.3, GRID_INNER),
    ]))
    return box


def image_caption_from_path(path: str) -> str:
    name = path.split("/")[-1].lower()
    if "_before_" in name:
        kind = "Before"
    elif "_after_" in name:
        kind = "After"
    elif "_inspection_" in name:
        kind = "Inspection"
    else:
        kind = "Photo"
    return f"{kind} — {path.split('/')[-1]}"


def _image_section(caption: str) -> str:
    head = caption.split("—")[0].strip().lower()
    if head.startswith("before"):
        return "Before"
    if head.startswith("after"):
        return "After"
    if head.startswith("inspection"):
        return "Inspection"
    return "Photos"


def _image_sort_key(caption: str) -> tuple[int, str]:
    match = re.search(r"_(\d+)\.", caption.lower()) or re.search(r"photo\s*(\d+)", caption.lower())
    number = int(match.group(1)) if match else 0
    return number, caption.lower()


def _grid_rows(image_count: int) -> int:
    """Rows needed for a 2-column grid."""
    if image_count <= 0:
        return 0
    return (image_count + GRID_COLS - 1) // GRID_COLS


def _chunk_image_items(
    items: list[tuple[str, bytes]],
    chunk_size: int = IMAGES_PER_PAGE,
) -> list[list[tuple[str, bytes]]]:
    if not items:
        return []
    return [items[i : i + chunk_size] for i in range(0, len(items), chunk_size)]


def _compute_image_height_for_section(item_count: int) -> float:
    """Scale image cells to fill one dedicated page for this section."""
    page_usable = PAGE_HEIGHT - REPORT_TOP_MARGIN - REPORT_BOTTOM_MARGIN
    total_rows = _grid_rows(item_count)
    if total_rows == 0:
        return IMAGE_H_MAX

    page_header_h = 0.55 * inch
    available = page_usable - page_header_h - 0.12 * inch
    row_overhead = IMAGE_CAPTION_H + IMAGE_CELL_EXTRA
    image_h = (available / total_rows) - row_overhead
    if image_h < IMAGE_H_MIN:
        image_h = max((available / total_rows) - row_overhead, 0.38 * inch)

    return max(IMAGE_H_MIN, min(IMAGE_H_MAX, image_h))


def _short_caption(caption: str) -> str:
    if "—" in caption:
        return caption.split("—", 1)[1].strip()
    return caption


def _group_image_items(
    image_items: list[tuple[str, bytes]],
) -> list[tuple[str, list[tuple[str, bytes]]]]:
    groups: dict[str, list[tuple[str, bytes]]] = {
        "Before": [],
        "After": [],
        "Inspection": [],
        "Photos": [],
    }
    for caption, img_bytes in image_items:
        groups[_image_section(caption)].append((caption, img_bytes))

    ordered: list[tuple[str, list[tuple[str, bytes]]]] = []
    for section in ("Before", "After", "Inspection", "Photos"):
        items = sorted(groups[section], key=lambda item: _image_sort_key(item[0]))
        if items:
            ordered.append((section, items))
    return ordered


def _empty_grid_cell(cell_w: float, row_h: float) -> Table:
    cell = Table([[""]], colWidths=[cell_w], rowHeights=[row_h])
    cell.setStyle(TableStyle(_table_style_base() + [
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fafafa")),
        ("BOX", (0, 0), (-1, -1), 0.3, GRID_INNER),
    ]))
    return cell


def _image_grid_cell(
    caption: str,
    img_bytes: bytes,
    *,
    cell_w: float,
    caption_h: float,
    image_h: float,
    caption_style: ParagraphStyle,
) -> Table:
    inner_w = cell_w - (2 * CELL_PAD)
    caption_para = _text_paragraph(_short_caption(caption), caption_style)
    image_box = _centered_image_box(img_bytes, inner_w, image_h)

    cell = Table(
        [[caption_para], [image_box]],
        colWidths=[cell_w],
        rowHeights=[caption_h, image_h + CELL_PAD],
    )
    cell.setStyle(TableStyle(_table_style_base() + [
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (0, 0), "MIDDLE"),
        ("VALIGN", (0, 1), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), CELL_PAD),
        ("RIGHTPADDING", (0, 0), (-1, -1), CELL_PAD),
        ("TOPPADDING", (0, 0), (-1, 0), 4),
        ("BOTTOMPADDING", (0, -1), (-1, -1), 4),
        ("BOX", (0, 0), (-1, -1), 0.4, GRID_INNER),
    ]))
    return cell


def _image_grid_table(
    items: list[tuple[str, bytes]],
    *,
    image_h: float,
    caption_style: ParagraphStyle,
) -> Table:
    cols = GRID_COLS
    col_w = CONTENT_WIDTH / cols
    caption_h = IMAGE_CAPTION_H
    row_h = caption_h + image_h + CELL_PAD + 8

    grid_rows: list[list] = []
    row: list = []
    for caption, img_bytes in items:
        row.append(_image_grid_cell(
            caption,
            img_bytes,
            cell_w=col_w,
            caption_h=caption_h,
            image_h=image_h,
            caption_style=caption_style,
        ))
        if len(row) == cols:
            grid_rows.append(row)
            row = []

    if row:
        while len(row) < cols:
            row.append(_empty_grid_cell(col_w, row_h))
        grid_rows.append(row)

    table = Table(
        grid_rows,
        colWidths=[col_w] * cols,
        rowHeights=[row_h] * len(grid_rows),
    )
    table.setStyle(TableStyle(_table_style_base() + [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("BOX", (0, 0), (-1, -1), 0.6, GRID_BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, GRID_BORDER),
    ]))
    return _full_width_wrapper(table)


def _append_image_sections(
    elements: list,
    image_items: list[tuple[str, bytes]],
    job_id: str,
    *,
    section_style: ParagraphStyle,
    subtitle_style: ParagraphStyle,
    caption_style: ParagraphStyle,
) -> None:
    """Render Before, After, etc. on separate pages; split when a section has >8 photos."""
    groups = _group_image_items(image_items)
    if not groups:
        return

    for group_name, items in groups:
        chunks = _chunk_image_items(items)
        section_label = IMAGE_PAGE_LABELS.get(group_name, group_name)
        multi_page = len(chunks) > 1

        for page_idx, chunk in enumerate(chunks, start=1):
            elements.append(PageBreak())

            image_h = _compute_image_height_for_section(len(chunk))
            rows = _grid_rows(len(chunk))
            title = section_label
            if multi_page:
                title = f"{section_label} — page {page_idx} of {len(chunks)}"

            page_block = [
                _full_width_wrapper(Paragraph(title, section_style)),
                _full_width_wrapper(
                    Paragraph(
                        f"<b>Job ID:</b> {escape(job_id)} · "
                        f"<font size=8 color='#666666'>"
                        f"2 columns · {rows} row{'s' if rows != 1 else ''} · "
                        f"{len(chunk)} photo{'s' if len(chunk) != 1 else ''} on this page"
                        f"</font>",
                        subtitle_style,
                    ),
                ),
                Spacer(1, 0.1 * inch),
                _image_grid_table(chunk, image_h=image_h, caption_style=caption_style),
            ]
            elements.append(KeepTogether(page_block))


def _load_logo_bytes() -> bytes | None:
    for path in LOGO_CANDIDATES:
        if path.exists():
            return path.read_bytes()
    return None


def _report_header_block(
    job_id: str,
    *,
    title_style: ParagraphStyle,
    subtitle_style: ParagraphStyle,
) -> Table:
    """Logo and report title aligned on one row."""
    text_w = CONTENT_WIDTH - 1.45 * inch
    title_block = Table(
        [
            [Paragraph("Job Report — Ammar Builders Maintenance", title_style)],
            [Paragraph(f"<b>Job ID:</b> {escape(job_id)}", subtitle_style)],
        ],
        colWidths=[text_w],
    )
    title_block.setStyle(TableStyle(_table_style_base() + [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
    ]))

    logo_bytes = _load_logo_bytes()
    if logo_bytes:
        logo_w = 1.35 * inch
        logo_h = 0.95 * inch
        logo = _scaled_image(logo_bytes, logo_w, logo_h)
        header = Table(
            [[logo, title_block]],
            colWidths=[logo_w + 0.1 * inch, text_w],
        )
        header.setStyle(TableStyle(_table_style_base() + [
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN", (0, 0), (0, 0), "LEFT"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ]))
        return _full_width_wrapper(header)

    title_block = Table(
        [
            [Paragraph("Job Report — Ammar Builders Maintenance", title_style)],
            [Paragraph(f"<b>Job ID:</b> {escape(job_id)}", subtitle_style)],
        ],
        colWidths=[CONTENT_WIDTH],
    )
    title_block.setStyle(TableStyle(_table_style_base() + [
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    return _full_width_wrapper(title_block)


def _details_table(
    job_data: dict,
    *,
    label_style: ParagraphStyle,
    value_style: ParagraphStyle,
) -> Table:
    rows: list[list] = [
        [_text_paragraph("Field", label_style), _text_paragraph("Details", label_style)],
    ]

    for col in DETAIL_COLUMNS:
        if col in job_data and job_data[col] not in (None, ""):
            rows.append([
                _text_paragraph(col, label_style),
                _text_paragraph(str(job_data[col]), value_style),
            ])

    for key, value in job_data.items():
        if key in DETAIL_COLUMNS or str(key).startswith("__") or value in (None, ""):
            continue
        rows.append([
            _text_paragraph(str(key), label_style),
            _text_paragraph(str(value), value_style),
        ])

    table = Table(rows, colWidths=[LABEL_WIDTH, VALUE_WIDTH], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eef5")),
        ("BACKGROUND", (0, 1), (0, -1), colors.HexColor("#f7f7f7")),
        ("BOX", (0, 0), (-1, -1), 0.6, DETAIL_BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, DETAIL_INNER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (0, 0), (0, -1), "LEFT"),
        ("ALIGN", (1, 0), (1, -1), "LEFT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return _full_width_wrapper(table)


def build_job_report_pdf(
    job_data: dict,
    image_items: list[tuple[str, bytes]] | None = None,
    *,
    include_images: bool = True,
    generated_at: str = "",
    footer_note: str = "",
) -> BytesIO:
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=0.6 * inch,
        bottomMargin=0.55 * inch,
    )
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "ReportTitle",
        parent=styles["Heading1"],
        fontSize=17,
        alignment=TA_LEFT,
        spaceAfter=6,
        textColor=colors.HexColor("#1a1a1a"),
    )
    subtitle_style = ParagraphStyle(
        "ReportSubtitle",
        parent=styles["Normal"],
        fontSize=10,
        spaceAfter=10,
        textColor=colors.HexColor("#444444"),
    )
    label_style = ParagraphStyle(
        "FieldLabel",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=9,
        leading=11,
        alignment=TA_LEFT,
    )
    value_style = ParagraphStyle(
        "FieldValue",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=12,
        alignment=TA_LEFT,
        wordWrap="CJK",
    )
    section_style = ParagraphStyle(
        "Section",
        parent=styles["Heading2"],
        fontSize=11,
        spaceBefore=6,
        spaceAfter=4,
    )
    caption_style = ParagraphStyle(
        "Caption",
        parent=styles["Normal"],
        fontSize=7,
        leading=9,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#555555"),
        spaceBefore=0,
        spaceAfter=0,
    )
    footer_style = ParagraphStyle(
        "Footer",
        parent=styles["Normal"],
        fontSize=8,
        textColor=colors.HexColor("#777777"),
    )

    job_id = str(job_data.get("Job ID", "report"))
    elements = [
        _report_header_block(job_id, title_style=title_style, subtitle_style=subtitle_style),
        _details_table(job_data, label_style=label_style, value_style=value_style),
    ]

    if include_images and image_items:
        _append_image_sections(
            elements,
            image_items[:16],
            job_id,
            section_style=section_style,
            subtitle_style=subtitle_style,
            caption_style=caption_style,
        )

    footer_parts = []
    if footer_note:
        footer_parts.append(escape(footer_note))
    if generated_at:
        footer_parts.append(f"Generated {escape(generated_at)}")
    if footer_parts:
        elements.append(Spacer(1, 0.1 * inch))
        elements.append(_full_width_wrapper(Paragraph(" · ".join(footer_parts), footer_style)))

    doc.build(elements)
    buffer.seek(0)
    return buffer
