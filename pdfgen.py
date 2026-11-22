"""PDF generation for monthly reports and invoices (ReportLab)."""

import calendar
from xml.sax.saxutils import escape

from reportlab.lib.colors import HexColor, white
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Flowable,
    HRFlowable,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

import labels as task_labels
from fonts import font_path

PAGE_W, PAGE_H = A4

BLUE = HexColor("#005da2")
NOTE_BLUE = HexColor("#4471c4")
CARD_BG = HexColor("#f1f6fb")
INK = HexColor("#1f2a37")
MUTED = HexColor("#6b7a8c")
RULE = HexColor("#d5dee8")

# ------------------------------------------------------------------- fonts
_FONT_FILES = {
    "Sans": ("NotoSans-Regular.ttf", "Helvetica"),
    "Sans-Bold": ("NotoSans-Bold.ttf", "Helvetica-Bold"),
    "Serif": ("LiberationSerif-Regular.ttf", "Times-Roman"),
    "Serif-Bold": ("LiberationSerif-Bold.ttf", "Times-Bold"),
}
FONTS = {}


def _register_fonts():
    if FONTS:
        return
    for name, (filename, fallback) in _FONT_FILES.items():
        path = font_path(filename)
        if path:
            pdfmetrics.registerFont(TTFont(name, path))
        FONTS[name] = name if path else fallback
    for family, regular, bold in (("Sans", "Sans", "Sans-Bold"), ("Serif", "Serif", "Serif-Bold")):
        if FONTS[regular] == regular and FONTS[bold] == bold:
            pdfmetrics.registerFontFamily(family, normal=regular, bold=bold, italic=regular, boldItalic=bold)


def _f(name):
    _register_fonts()
    return FONTS[name]


# ----------------------------------------------------------------- helpers
def fmt_hours(value):
    value = float(value or 0)
    return str(int(value)) if value.is_integer() else f"{value:g}"


def fmt_money(value, currency="$"):
    return f"{currency}{value:.2f}"


def _esc(text):
    return escape(text or "")


def _report_title(settings):
    return f"{settings.get('org_name', '').strip()} Monthly Report".strip()


# =================================================================== REPORT
class _Pill(Flowable):
    """A task label drawn as a rounded, tinted pill."""

    def __init__(self, text, color, font, width, size=7.5):
        super().__init__()
        self.text, self.font, self.size = text, font, size
        self.bg, _hover, self.fg = task_labels.chip(color)
        self.width, self.height = width, size + 6.5

    @staticmethod
    def width_for(text, font, size=7.5):
        return pdfmetrics.stringWidth(text, font, size) + 14

    def wrap(self, *_args):
        return self.width, self.height + 2  # 2pt above, to sit on the first text line

    def draw(self):
        c = self.canv
        c.setFillColor(HexColor(self.bg))
        c.roundRect(0, 0, self.width, self.height, self.height / 2, fill=1, stroke=0)
        c.setFillColor(HexColor(self.fg))
        c.setFont(self.font, self.size)
        c.drawCentredString(self.width / 2, (self.height - 0.72 * self.size) / 2, self.text)


def generate_report(path, settings, report, style="Modern"):
    """report: year, month, total_hours, meeting_hours, meetings (list of str),
    tasks and next_tasks (lists of {"text", "label"}; plain strings also work)."""
    report = dict(report, tasks=task_labels.items(report["tasks"]),
                  next_tasks=task_labels.items(report["next_tasks"]))
    if style == "Classic":
        _report_classic(path, settings, report)
    else:
        _report_modern(path, settings, report)


def _report_classic(path, settings, r):
    serif, serif_b, sans = _f("Serif"), _f("Serif-Bold"), _f("Sans")
    doc = SimpleDocTemplate(
        path, pagesize=A4, leftMargin=56, rightMargin=56, topMargin=56, bottomMargin=56,
        title=f"{_report_title(settings)} - {calendar.month_name[r['month']]} {r['year']}",
        author=settings.get("name", ""),
    )
    title = ParagraphStyle("t", fontName=serif_b, fontSize=22, leading=27, alignment=TA_CENTER)
    body = ParagraphStyle("b", fontName=serif, fontSize=12, leading=15)
    head = ParagraphStyle("h", fontName=serif_b, fontSize=18, leading=22, spaceBefore=18, spaceAfter=8)
    item = ParagraphStyle("i", parent=body, leftIndent=46, firstLineIndent=-8, spaceAfter=3)

    story = [
        Paragraph(_esc(_report_title(settings)), title),
        Paragraph(f"Month of {calendar.month_name[r['month']]}", title),
        Spacer(1, 38),
        Paragraph(f"Contractor: <b>{_esc(settings.get('name', ''))}</b>", body),
        Paragraph(
            f'<font name="{sans}" size="9" color="#1f5fa0"><u>{_esc(settings.get("email", ""))}</u></font>',
            ParagraphStyle("e", parent=body, leftIndent=36),
        ),
        Spacer(1, 12),
        Paragraph(f"Hours put: {fmt_hours(r['total_hours'])} hours in total.", body),
        Spacer(1, 6),
    ]

    labels = task_labels.parse(settings.get("labels"))

    def tag(label):
        if not label:
            return ""
        bg, _hover, fg = task_labels.chip(task_labels.color_of(label, labels))
        return (f'<font name="{_f("Sans-Bold")}" size="8" color="{fg}" backColor="{bg}">'
                f'&nbsp;{_esc(label)}&nbsp;</font>&nbsp; ')

    def section(heading, items):
        story.append(Paragraph(heading, head))
        for t in items:
            if isinstance(t, dict):
                story.append(Paragraph(f"- {tag(t['label'])}{_esc(t['text'])}", item))
            else:
                story.append(Paragraph(f"- {_esc(t)}", item))

    section("Tasks:", r["tasks"])
    if r["meetings"] or float(r["meeting_hours"] or 0):
        section(f"Meetings ({fmt_hours(r['meeting_hours'])} Hours):", r["meetings"])
    if r["next_tasks"]:
        section("To Do Next Month:", r["next_tasks"])
    doc.build(story)


def _report_modern(path, settings, r):
    sans, bold = _f("Sans"), _f("Sans-Bold")
    year, month = r["year"], r["month"]
    month_name = calendar.month_name[month]
    last = calendar.monthrange(year, month)[1]
    total = float(r["total_hours"] or 0)
    meetings_h = float(r["meeting_hours"] or 0)
    dev_h = max(total - meetings_h, 0)
    margin = 50
    band_h = 128

    def first_page(c, doc):
        c.saveState()
        c.setFillColor(BLUE)
        c.rect(0, PAGE_H - band_h, PAGE_W, band_h, fill=1, stroke=0)
        c.setFillColor(NOTE_BLUE)
        c.rect(0, PAGE_H - band_h - 4, PAGE_W, 4, fill=1, stroke=0)

        c.setFillColor(HexColor("#bcd6ee"))
        c.setFont(bold, 8.5)
        org = settings.get("org_name", "").strip().upper()
        c.drawString(margin, PAGE_H - 44, f"{org}  ·  MONTHLY REPORT" if org else "MONTHLY REPORT", charSpace=1.4)
        c.setFillColor(white)
        c.setFont(bold, 30)
        c.drawString(margin, PAGE_H - 82, f"{month_name} {year}")
        c.setFillColor(HexColor("#d4e5f5"))
        c.setFont(sans, 10)
        c.drawString(margin, PAGE_H - 104, f"Reporting period: 1 – {last} {month_name} {year}")

        right = PAGE_W - margin
        c.setFillColor(HexColor("#bcd6ee"))
        c.setFont(bold, 8.5)
        c.drawRightString(right, PAGE_H - 44, "CONTRACTOR")
        c.setFillColor(white)
        c.setFont(bold, 13)
        c.drawRightString(right, PAGE_H - 63, settings.get("name", ""))
        c.setFillColor(HexColor("#d4e5f5"))
        c.setFont(sans, 9.5)
        c.drawRightString(right, PAGE_H - 79, settings.get("email", ""))
        if settings.get("project"):
            c.drawRightString(right, PAGE_H - 94, settings["project"])
        c.restoreState()
        footer(c, doc)

    def later_pages(c, doc):
        c.saveState()
        c.setFillColor(BLUE)
        c.rect(0, PAGE_H - 8, PAGE_W, 8, fill=1, stroke=0)
        c.setFont(bold, 9)
        c.setFillColor(MUTED)
        c.drawString(margin, PAGE_H - 34, f"Monthly Report — {month_name} {year}")
        c.drawRightString(PAGE_W - margin, PAGE_H - 34, settings.get("name", ""))
        c.restoreState()
        footer(c, doc)

    def footer(c, doc):
        c.saveState()
        c.setStrokeColor(RULE)
        c.setLineWidth(0.6)
        c.line(margin, 42, PAGE_W - margin, 42)
        c.setFont(sans, 8)
        c.setFillColor(MUTED)
        c.drawString(margin, 28, "  ·  ".join(filter(None, (settings.get("name"), settings.get("email")))))
        c.drawRightString(PAGE_W - margin, 28, f"Page {doc.page}")
        c.restoreState()

    doc = SimpleDocTemplate(
        path, pagesize=A4, leftMargin=margin, rightMargin=margin, topMargin=band_h + 30, bottomMargin=64,
        title=f"{_report_title(settings)} - {month_name} {year}",
        author=settings.get("name", ""),
    )
    width = PAGE_W - 2 * margin

    num_style = ParagraphStyle("num", fontName=bold, fontSize=24, leading=28, textColor=BLUE)
    lbl_style = ParagraphStyle("lbl", fontName=bold, fontSize=7.5, leading=10, textColor=MUTED)
    h_style = ParagraphStyle("h", fontName=bold, fontSize=14, leading=18, textColor=INK)
    body = ParagraphStyle("body", fontName=sans, fontSize=10.5, leading=15, textColor=INK)
    idx_style = ParagraphStyle("idx", fontName=bold, fontSize=10, leading=15, textColor=BLUE)
    bullet_style = ParagraphStyle("bul", parent=body, textColor=BLUE, fontName=bold)

    def card(value, label):
        return [Paragraph(value, num_style), Paragraph(label.upper(), lbl_style)]

    cards = [
        card(f"{fmt_hours(total)}<font size=12> h</font>", "Total hours"),
        card(f"{fmt_hours(dev_h)}<font size=12> h</font>", "Development"),
        card(f"{fmt_hours(meetings_h)}<font size=12> h</font>", "Meetings"),
        card(str(len(r["tasks"])), "Tasks completed"),
    ]
    gap = 10
    card_w = (width - 3 * gap) / 4
    stats = Table(
        [[cards[0], "", cards[1], "", cards[2], "", cards[3]]],
        colWidths=[card_w, gap, card_w, gap, card_w, gap, card_w],
    )
    stats_style = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 11),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
    ]
    for col in (0, 2, 4, 6):
        stats_style += [
            ("BACKGROUND", (col, 0), (col, 0), CARD_BG),
            ("LINEBEFORE", (col, 0), (col, 0), 3, BLUE),
        ]
    stats.setStyle(TableStyle(stats_style))

    story = [stats, Spacer(1, 22)]

    def heading(title, aside=""):
        aside_html = f'<font name="{sans}" size="10" color="#6b7a8c">   {aside}</font>' if aside else ""
        return [
            Paragraph(f"{title}{aside_html}", h_style),
            Spacer(1, 5),
            HRFlowable(width="100%", thickness=0.8, color=RULE, spaceAfter=6),
        ]

    labels = task_labels.parse(settings.get("labels"))

    def item_table(rows, numbered):
        """rows: task dicts (drawn with their label pill) or plain strings."""
        tags = [t["label"] for t in rows if isinstance(t, dict) and t["label"]]
        pill_w = max((_Pill.width_for(tag, bold) for tag in tags), default=0)
        data = []
        for i, t in enumerate(rows, 1):
            text, tag = (t["text"], t["label"]) if isinstance(t, dict) else (t, "")
            marker = Paragraph(f"{i:02d}", idx_style) if numbered else Paragraph("•", bullet_style)
            row = [marker]
            if tags:
                row.append(_Pill(tag, task_labels.color_of(tag, labels), bold, pill_w) if tag else "")
            data.append(row + [Paragraph(_esc(text), body)])
        widths = [28 if numbered else 18] + ([pill_w + 10] if tags else []) + [None]
        tbl = Table(data, colWidths=widths)
        style = [
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 2),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]
        if numbered and len(data) > 1:
            style.append(("LINEBELOW", (0, 0), (-1, -2), 0.4, HexColor("#e7edf3")))
        tbl.setStyle(TableStyle(style))
        return tbl

    if r["tasks"]:
        story += heading("Tasks Completed", f"{len(r['tasks'])} items")
        story += [item_table(r["tasks"], numbered=True), Spacer(1, 20)]
    if r["meetings"] or meetings_h:
        story.append(KeepTogether(
            heading("Meetings", f"{fmt_hours(meetings_h)} hours") + [item_table(r["meetings"], numbered=False)]
        ))
        story.append(Spacer(1, 20))
    if r["next_tasks"]:
        story.append(KeepTogether(
            heading("Planned for Next Month") + [item_table(r["next_tasks"], numbered=False)]
        ))

    doc.build(story, onFirstPage=first_page, onLaterPages=later_pages)


def _filename(settings, doctype, year, month):
    """name-doctype-month-year, e.g. Jane-Example-invoice-October-2026.pdf"""
    name = "-".join((settings.get("name") or "Work").split())
    return f"{name}-{doctype}-{calendar.month_name[month]}-{year}.pdf"


def report_filename(settings, year, month):
    return _filename(settings, "report", year, month)


def invoice_filename(settings, year, month):
    return _filename(settings, "invoice", year, month)
