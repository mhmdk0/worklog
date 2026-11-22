"""Fill the invoice template (templates/invoice-template.pdf).

Every value that changes is a placeholder word in the template (see FIELDS and BLOCKS), and each
one keeps the font, size and colour it has in the template:
  * a field alone in its cell is written centred, left- or right-aligned as listed in FIELDS;
    a field inside a sentence is replaced in place and the rest of that line follows it;
  * a block (inv_note, item_desc) is rich text from Settings, written from the placeholder's
    position: **bold**, __underline__ and {project}-style variables. item_desc wraps inside its
    table cell.
The placeholders are truly removed (redacted), not covered, so the template can be edited in
LibreOffice Draw and re-exported as long as the placeholder words stay intact.
"""

import calendar
import os
import re

import pymupdf

from fonts import font_path

TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates", "invoice-template.pdf")

# name: (meaning, alignment when alone in a cell, underlined)
FIELDS = {
    "inv_nb": ("Invoice number", "center", False),
    "issue_dt": ("Issue date (YYYY/MM/DD)", "center", False),
    "expiry_dt": ("Expiry date (YYYY/MM/DD)", "center", False),
    "start_day": ("First day of the period (1)", "center", False),
    "end_day": ("Last day of the period (30/31)", "center", False),
    "month_yr": ("Month and year of the period (e.g. Oct-2026, August-2026)", "center", False),
    "qty_hrs": ("Hours worked", "center", False),
    "unit_price": ("Hourly rate", "center", False),
    "line_amt": ("Line amount (hours × rate)", "center", False),
    "sub_total": ("Sub total", "center", False),
    "tax_pct": ("Tax percentage", "center", False),
    "total_amt": ("Total amount", "center", False),
    "from_name": ("Your name", "left", False),
    "from_addr1": ("Your address, line 1", "left", False),
    "from_addr2": ("Your address, line 2", "left", False),
    "from_phone": ("Your phone", "left", False),
    "from_email": ("Your email", "left", True),
    "to_org": ("Client organisation", "left", False),
    "to_contact": ("Client contact name", "left", False),
    "to_addr1": ("Client address, line 1", "left", False),
    "to_addr2": ("Client address, line 2", "left", False),
    "to_email": ("Client email", "left", True),
}
# name: (meaning, maximum number of lines; the font shrinks if the text needs more)
BLOCKS = {
    "inv_note": ("Note under the title (Settings → Invoice note)", 2),
    "item_desc": ("Line item description (Settings → Line description)", 4),
}
PLACEHOLDERS = {**{k: v[0] for k, v in FIELDS.items()}, **{k: v[0] for k, v in BLOCKS.items()}}
TOKEN = re.compile("|".join(sorted(PLACEHOLDERS, key=len, reverse=True)))

FONT_FILES = {
    ("Noto", False): "NotoSans-Regular.ttf",
    ("Noto", True): "NotoSans-Bold.ttf",
    ("Liberation", False): "LiberationSans-Regular.ttf",
    ("Liberation", True): "LiberationSans-Bold.ttf",
}
# Underline (offset below the baseline, thickness, shift right) in em, as LibreOffice draws it.
UNDERLINE = {"Noto": (0.069, 0.081, 0.0), "Liberation": (0.183, 0.1125, 0.07)}
LINE_SPACING = 1.3


class TemplateError(Exception):
    pass


class _Vars(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def _expand(text, variables):
    try:
        return (text or "").format_map(_Vars(variables))
    except (ValueError, IndexError):
        return text or ""


def invoice_values(invoice, settings):
    """Returns (field values, block texts, total)."""
    from pdfgen import fmt_hours, fmt_money

    currency = settings.get("currency") or "$"
    year, month = invoice["year"], invoice["month"]
    hours, rate = float(invoice["hours"]), float(invoice["rate"])
    tax = float(invoice.get("tax") or 0)
    subtotal = hours * rate
    total = subtotal * (1 + tax / 100)
    # Full month name when short ("August"), otherwise "Sep"/"Oct" style.
    name = calendar.month_name[month]
    month_label = name if len(name) <= 6 else calendar.month_abbr[month]
    values = {
        "inv_nb": str(invoice["number"]),
        "issue_dt": invoice["issue_date"].strftime("%Y/%m/%d"),
        "expiry_dt": invoice["expiry_date"].strftime("%Y/%m/%d"),
        "start_day": "1",
        "end_day": str(calendar.monthrange(year, month)[1]),
        "month_yr": f"{month_label}-{year}",
        "qty_hrs": fmt_hours(hours),
        "unit_price": fmt_money(rate, currency),
        "line_amt": fmt_money(subtotal, currency),
        "sub_total": fmt_money(subtotal, currency),
        "tax_pct": f"{tax:.2f}%",
        "total_amt": fmt_money(total, currency),
        "from_name": settings.get("name", ""),
        "from_addr1": settings.get("address1", ""),
        "from_addr2": settings.get("address2", ""),
        "from_phone": settings.get("phone", ""),
        "from_email": settings.get("email", ""),
        "to_org": settings.get("client_org", ""),
        "to_contact": settings.get("client_contact", ""),
        "to_addr1": settings.get("client_address1", ""),
        "to_addr2": settings.get("client_address2", ""),
        "to_email": settings.get("client_email", ""),
    }
    variables = {**settings, **values, "month": name, "year": str(year), "hours": values["qty_hrs"]}
    blocks = {
        "inv_note": _expand(settings.get("invoice_note"), variables),
        "item_desc": _expand(settings.get("invoice_description"), variables),
    }
    return values, blocks, total


def _rich(text):
    """'a **b** __c__' -> [(text, bold, underline)]"""
    runs, bold, underline = [], False, False
    for part in re.split(r"(\*\*|__)", text):
        if part == "**":
            bold = not bold
        elif part == "__":
            underline = not underline
        elif part:
            runs.append((part, bold, underline))
    return runs


def _spans(page):
    spans = []
    for block in page.get_text("rawdict")["blocks"]:
        for line in block.get("lines", []):
            for s in line["spans"]:
                s["text"] = "".join(ch["c"] for ch in s["chars"])
                s["bold"] = "Bold" in s["font"] or bool(s["flags"] & 16)
                s["family"] = "Liberation" if "Liberation" in s["font"] else "Noto"
                spans.append(s)
    return spans


def _chain(spans, span):
    """Non-blank spans touching `span` on the same baseline (one visual run of text), left to right."""
    y = span["origin"][1]
    row = sorted((s for s in spans if s["text"].strip() and abs(s["origin"][1] - y) < 1),
                 key=lambda s: s["bbox"][0])
    i = next(i for i, s in enumerate(row) if s is span)
    lo = hi = i
    while lo > 0 and row[lo]["bbox"][0] - row[lo - 1]["bbox"][2] < 3:
        lo -= 1
    while hi < len(row) - 1 and row[hi + 1]["bbox"][0] - row[hi]["bbox"][2] < 3:
        hi += 1
    return row[lo:hi + 1]


class _Editor:
    def __init__(self, page):
        self.page = page
        # Drawn boxes (table cells), read before any redaction is added.
        self.boxes = [d["rect"] for d in page.get_drawings() if d["rect"].width < page.rect.width - 10]
        self.texts = []       # (x, y, text, family, bold, size, color)
        self.underlines = []  # (rect, color)
        self.fonts = {}

    def font(self, family, bold):
        key = (family, bold)
        if key not in self.fonts:
            path = font_path(FONT_FILES[key])
            if not path:
                raise TemplateError(f"Font file fonts/{FONT_FILES[key]} is missing.")
            self.fonts[key] = pymupdf.Font(fontfile=path)
        return self.fonts[key]

    def width(self, text, family, bold, size):
        return self.font(family, bold).text_length(text, size)

    def cell(self, x, y):
        """The smallest drawn box (table cell) around (x, y), or None."""
        boxes = [r for r in self.boxes if r.x0 - 1 <= x < r.x1 - 20 and r.y0 <= y <= r.y1]
        return min(boxes, key=lambda r: r.width * r.height) if boxes else None

    def cell_right(self, x, y):
        """Right edge of the cell around (x, y); else the right page margin (as wide as the left one)."""
        box = self.cell(x, y)
        return box.x1 if box else self.page.rect.width - (x - 1)

    def redact(self, x0, x1, span):
        y0, y1 = span["bbox"][1], span["bbox"][3]
        # Shrunk vertically so neighbouring lines (whose boxes overlap slightly) are untouched.
        self.page.add_redact_annot(pymupdf.Rect(x0 + 0.3, y0 + 3, x1 - 0.3, y1 - 3), fill=False, cross_out=False)

    @staticmethod
    def color(span):
        c = span["color"]
        return ((c >> 16) / 255, ((c >> 8) & 255) / 255, (c & 255) / 255)

    def write(self, x, y, text, span, bold=None, underline=False, size=None):
        """Queue `text` at (x, y) in the span's style; returns its width."""
        bold = span["bold"] if bold is None else bold
        size = size or span["size"]
        w = self.width(text, span["family"], bold, size)
        self.texts.append((x, y, text, span["family"], bold, size, self.color(span)))
        if underline and text.strip():
            offset, thickness, shift = (v * size for v in UNDERLINE[span["family"]])
            self.underlines.append((pymupdf.Rect(x + shift, y + offset, x + shift + w, y + offset + thickness),
                                    self.color(span)))
        return w

    def field(self, span, text, align, underline):
        self.redact(span["bbox"][0], span["bbox"][2], span)
        x0, y = span["origin"]
        size = span["size"]
        w = self.width(text, span["family"], span["bold"], size)
        # A long value shrinks to fit its cell (or, for left-aligned text, the page margin).
        box = self.cell(x0 + 1, y - 2)
        room = (box.x1 - x0 if align == "left" else box.width - 4) if box else (
            self.page.rect.width - 2 * x0 + 2 if align == "left" else w)
        if w > room > 0:
            size *= room / w
            w = room
        x = {"left": x0,
             "right": span["bbox"][2] - w,
             "center": (span["bbox"][0] + span["bbox"][2]) / 2 - w / 2}[align]
        self.write(x, y, text, span, underline=underline, size=size)

    def inline(self, runs, start_char):
        """runs: [(new_text, span), ...] laid out left to right from start_char's position."""
        x, y = start_char["origin"]
        first = True
        for text, span in runs:
            self.redact(start_char["bbox"][0] if first else span["bbox"][0], span["bbox"][2], span)
            first = False
            x += self.write(x, y, text, span)

    def block(self, span, text, max_lines):
        """Rich text from the placeholder's origin, wrapped at the cell's right edge."""
        self.redact(span["bbox"][0], span["bbox"][2], span)
        x, y = span["origin"]
        width = self.cell_right(x + 1, y - 2) - x
        # **bold** adds to the template's own style (a bold placeholder makes the whole block bold).
        runs = [(t, b or span["bold"], u) for t, b, u in _rich(text)]
        size = span["size"]
        lines = self._wrap(runs, span["family"], size, width)
        while len(lines) > max_lines and size > 7:
            size -= 0.25
            lines = self._wrap(runs, span["family"], size, width)
        for i, line in enumerate(lines):
            lx = x
            for part, bold, underline in line:
                lx += self.write(lx, y + i * size * LINE_SPACING, part, span, bold, underline, size)

    def _wrap(self, runs, family, size, width):
        """Greedy word wrap of styled runs; breaks only at spaces."""
        atoms = []  # ("word" | "space", [(text, bold, underline), ...])
        for text, bold, underline in runs:
            for piece in re.findall(r"\S+|\s+", text):
                if piece.isspace():
                    atoms.append(("space", [(piece, bold, underline)]))
                elif atoms and atoms[-1][0] == "word":
                    atoms[-1][1].append((piece, bold, underline))
                else:
                    atoms.append(("word", [(piece, bold, underline)]))

        lines, line, used = [], [], 0.0
        for kind, parts in atoms:
            w = sum(self.width(t, family, b, size) for t, b, _u in parts)
            if kind == "word" and line and used + w > width:
                trailing = []
                while line and line[-1][0].isspace():
                    trailing.insert(0, line.pop())
                lines.append(line)
                # One space ends the line; any further spaces start the next one (as LibreOffice does).
                extra = "".join(t for t, _b, _u in trailing)[1:]
                line = [(extra, *trailing[-1][1:])] if extra else []
                used = self.width(extra, family, trailing[-1][1], size) if extra else 0.0
            if kind == "space" and not line:
                continue
            line.extend(parts)
            used += w
        if line:
            lines.append(line)
        return lines

    def apply(self):
        self.page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE,
                                   graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
                                   text=pymupdf.PDF_REDACT_TEXT_REMOVE)
        names = {}
        for key in sorted({(t[3], t[4]) for t in self.texts}):
            names[key] = f"wl-{key[0].lower()}{'-bold' if key[1] else ''}"
            self.page.insert_font(fontname=names[key], fontfile=font_path(FONT_FILES[key]))
        for x, y, text, family, bold, size, color in self.texts:
            if text.strip():
                self.page.insert_text((x, y), text, fontname=names[(family, bold)], fontsize=size, color=color)
        for rect, color in self.underlines:
            self.page.draw_rect(rect, color=None, fill=color, width=0)


def fill_invoice(template_path, out_path, invoice, settings):
    """Fill the template's placeholders and save to out_path. Returns the invoice total."""
    values, blocks, total = invoice_values(invoice, settings)
    sub = lambda text: TOKEN.sub(lambda m: values.get(m.group(), ""), text)  # noqa: E731

    if not os.path.exists(template_path):
        raise TemplateError(f"Invoice template not found:\n{template_path}")
    doc = pymupdf.open(template_path)
    page = doc[0]
    spans = _spans(page)
    if not any(TOKEN.search(s["text"]) for s in spans):
        doc.close()
        raise TemplateError(f"No placeholders (inv_nb, issue_dt, ...) found in\n{template_path}")

    ed = _Editor(page)
    done = set()
    for span in spans:
        if id(span) in done or not TOKEN.search(span["text"]):
            continue
        chain = _chain(spans, span)
        done.update(id(s) for s in chain)
        word = span["text"].strip()
        if len(chain) == 1 and word in BLOCKS:
            ed.block(span, blocks[word], BLOCKS[word][1])
        elif len(chain) == 1 and word in FIELDS:
            ed.field(span, values[word], FIELDS[word][1], FIELDS[word][2])
        else:
            # Placeholder inside a sentence: rewrite from the first placeholder to the end of the run.
            k = next(i for i, s in enumerate(chain) if TOKEN.search(s["text"]))
            cut = TOKEN.search(chain[k]["text"]).start()
            runs = [(sub(chain[k]["text"][cut:]), chain[k])] + [(sub(s["text"]), s) for s in chain[k + 1:]]
            ed.inline(runs, chain[k]["chars"][cut])

    ed.apply()
    month = calendar.month_name[invoice["month"]]
    doc.set_metadata({**doc.metadata, "title": f"Invoice {invoice['number']} - {month} {invoice['year']}",
                      "author": settings.get("name", "")})
    doc.subset_fonts()
    doc.save(out_path, garbage=3, deflate=True)
    doc.close()
    return total
