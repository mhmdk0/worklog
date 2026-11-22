"""WorkLog — track daily hours, then generate monthly reports and invoices."""

import calendar
import os
import re
import subprocess
import sys
import tempfile
from datetime import date, datetime, timedelta
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk
from tkinter import font as tkfont

import labels as task_labels
import pdfgen
from invoice_template import BLOCKS, FIELDS, TEMPLATE, TemplateError, fill_invoice
from storage import Storage, last_day

APP_DIR = os.path.dirname(os.path.abspath(__file__))
MAC = sys.platform == "darwin"
DB_PATH = os.environ.get("WORKLOG_DB") or os.path.join(APP_DIR, "data", "worklog.db")

ACCENT = "#005da2"
ACCENT_HOVER = "#004a82"
DANGER = "#c0392b"
CARD = ("#ffffff", "#232629")
PAGE_BG = ("#f3f5f8", "#1a1c1e")
SUBTLE = ("#6b7a8c", "#9aa6b2")
BORDER = ("#dfe4ea", "#33373b")
DAY_EMPTY = ("#eef1f5", "#2b2f33")
DAY_EMPTY_HOVER = ("#dde3ea", "#363b40")
DAY_LOGGED = ("#cfe2f3", "#17395a")
DAY_LOGGED_HOVER = ("#b9d4ec", "#1d4870")
DAY_LOGGED_TEXT = ("#003e6e", "#d6e7f7")
NOTE_BORDER = ("#4471c4", "#6fb1e8")
ROW_BG = ("#f6f8fb", "#2a2e32")


# ------------------------------------------------------------------ helpers
def fmt_h(value):
    return pdfgen.fmt_hours(value)


def parse_hours(text):
    text = (text or "").strip().replace(",", ".")
    if not text:
        return 0.0
    value = float(text)
    if value < 0 or value > 24 * 31:
        raise ValueError
    return value


def shift_month(year, month, delta):
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


def default_report_month(today=None):
    """Early in the month you're usually reporting on the previous one."""
    today = today or date.today()
    if today.day <= 15:
        return shift_month(today.year, today.month, -1)
    return today.year, today.month


def clean_lines(text):
    """Non-empty lines without leading bullets or numbering ("- ", "•", "1.", "2)")."""
    lines = []
    for line in text.splitlines():
        line = re.sub(r"^\s*(?:[-•*·]+|\d{1,2}[.)])\s*", "", line).strip()
        if line:
            lines.append(line)
    return lines


def text_lines(textbox):
    return clean_lines(textbox.get("1.0", "end-1c"))


def set_text(textbox, lines):
    textbox.delete("1.0", "end")
    textbox.insert("1.0", "\n".join(lines))


def set_entry(entry, value):
    entry.delete(0, "end")
    entry.insert(0, value)
    if not value and hasattr(entry, "_activate_placeholder"):
        entry._activate_placeholder()  # show the grey hint again


def open_path(path):
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as exc:
        messagebox.showerror("Could not open", f"{path}\n\n{exc}")


def build_invoice(path, settings, inv):
    """Fill the invoice template: the one set in Settings, or the built-in one."""
    return fill_invoice(settings.get("invoice_template") or TEMPLATE, path, inv, settings)


def parse_date(text):
    for fmt in ("%Y/%m/%d", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(text.strip(), fmt).date()
        except ValueError:
            pass
    raise ValueError(text)


# ------------------------------------------------------------ shared widgets
class Card(ctk.CTkFrame):
    def __init__(self, master, title=None, **kw):
        super().__init__(master, fg_color=CARD, corner_radius=12, border_width=1, border_color=BORDER, **kw)
        self.grid_columnconfigure(0, weight=1)
        if title:
            ctk.CTkLabel(self, text=title, font=ctk.CTkFont(size=15, weight="bold"), anchor="w").grid(
                row=0, column=0, sticky="ew", padx=18, pady=(14, 4)
            )


class StatCard(ctk.CTkFrame):
    def __init__(self, master, label, **kw):
        super().__init__(master, fg_color=CARD, corner_radius=12, border_width=1, border_color=BORDER, **kw)
        self.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(self, text=label.upper(), font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=SUBTLE, anchor="w").grid(row=0, column=0, sticky="ew", padx=16, pady=(12, 0))
        self.value = ctk.CTkLabel(self, text="0", font=ctk.CTkFont(size=28, weight="bold"),
                                  text_color=(ACCENT, "#6fb1e8"), anchor="w")
        self.value.grid(row=1, column=0, sticky="ew", padx=16)
        self.sub = ctk.CTkLabel(self, text="", font=ctk.CTkFont(size=12), text_color=SUBTLE, anchor="w")
        self.sub.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 10))

    def set(self, value, sub=""):
        self.value.configure(text=value)
        self.sub.configure(text=sub)


class MonthPicker(ctk.CTkFrame):
    def __init__(self, master, year, month, command):
        super().__init__(master, fg_color="transparent")
        self.year, self.month, self.command = year, month, command
        btn = dict(width=34, height=34, corner_radius=8, fg_color=DAY_EMPTY, hover_color=DAY_EMPTY_HOVER,
                   text_color=("gray10", "gray90"), font=ctk.CTkFont(size=16, weight="bold"))
        ctk.CTkButton(self, text="‹", command=lambda: self.step(-1), **btn).grid(row=0, column=0)
        self.label = ctk.CTkLabel(self, width=170, font=ctk.CTkFont(size=16, weight="bold"))
        self.label.grid(row=0, column=1, padx=6)
        ctk.CTkButton(self, text="›", command=lambda: self.step(1), **btn).grid(row=0, column=2)
        self._render()

    def _render(self):
        self.label.configure(text=f"{calendar.month_name[self.month]} {self.year}")

    def step(self, delta):
        self.set(*shift_month(self.year, self.month, delta))

    def set(self, year, month, notify=True):
        self.year, self.month = year, month
        self._render()
        if notify:
            self.command(year, month)


class DatePopup(ctk.CTkToplevel):
    """Small calendar used to pick a date for a DateField."""

    def __init__(self, field, initial):
        super().__init__(field)
        self.field = field
        self.title("Pick a date")
        self.resizable(False, False)
        self.transient(field.winfo_toplevel())
        self.year, self.month = initial.year, initial.month
        self.selected = initial

        head = ctk.CTkFrame(self, fg_color="transparent")
        head.grid(row=0, column=0, padx=12, pady=(12, 4), sticky="ew")
        head.grid_columnconfigure(1, weight=1)
        nav = dict(width=30, height=30, fg_color=DAY_EMPTY, hover_color=DAY_EMPTY_HOVER,
                   text_color=("gray10", "gray90"))
        ctk.CTkButton(head, text="‹", command=lambda: self._step(-1), **nav).grid(row=0, column=0)
        self.label = ctk.CTkLabel(head, font=ctk.CTkFont(size=14, weight="bold"))
        self.label.grid(row=0, column=1)
        ctk.CTkButton(head, text="›", command=lambda: self._step(1), **nav).grid(row=0, column=2)

        self.grid_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.grid_frame.grid(row=1, column=0, padx=12, pady=(0, 12))
        self._render()
        self.after(50, self._focus)

    def _focus(self):
        try:
            self.grab_set()
            self.focus_force()
        except Exception:  # noqa: BLE001 - grab can fail if the window isn't viewable yet
            pass

    def _step(self, delta):
        self.year, self.month = shift_month(self.year, self.month, delta)
        self._render()

    def _render(self):
        self.label.configure(text=f"{calendar.month_name[self.month]} {self.year}")
        for w in self.grid_frame.winfo_children():
            w.destroy()
        for i, name in enumerate(("Mo", "Tu", "We", "Th", "Fr", "Sa", "Su")):
            ctk.CTkLabel(self.grid_frame, text=name, text_color=SUBTLE, width=36).grid(row=0, column=i)
        for r, week in enumerate(calendar.Calendar().monthdayscalendar(self.year, self.month), 1):
            for c, day in enumerate(week):
                if not day:
                    continue
                d = date(self.year, self.month, day)
                chosen = d == self.selected
                ctk.CTkButton(
                    self.grid_frame, text=str(day), width=36, height=30, corner_radius=8,
                    fg_color=ACCENT if chosen else "transparent",
                    hover_color=ACCENT_HOVER if chosen else DAY_EMPTY_HOVER,
                    text_color="white" if chosen else ("gray10", "gray90"),
                    command=lambda d=d: self._pick(d),
                ).grid(row=r, column=c, padx=1, pady=1)

    def _pick(self, d):
        self.field.set(d)
        self.destroy()


class DateField(ctk.CTkFrame):
    def __init__(self, master, command=None):
        super().__init__(master, fg_color="transparent")
        self.command = command
        self.entry = ctk.CTkEntry(self, width=130, placeholder_text="YYYY/MM/DD")
        self.entry.grid(row=0, column=0)
        self.entry.bind("<FocusOut>", lambda _e: self.command and self.command())
        ctk.CTkButton(self, text="▾", width=32, fg_color=DAY_EMPTY, hover_color=DAY_EMPTY_HOVER,
                      text_color=("gray10", "gray90"), command=self._open).grid(row=0, column=1, padx=(4, 0))

    def _open(self):
        try:
            initial = self.get()
        except ValueError:
            initial = date.today()
        DatePopup(self, initial)

    def get(self):
        return parse_date(self.entry.get())

    def set(self, d):
        set_entry(self.entry, d.strftime("%Y/%m/%d"))
        if self.command:
            self.command()


# --------------------------------------------------------------- task labels
def chip_colors(db, name):
    """(background, hover, text) as CTk (light, dark) pairs for a label chip."""
    color = task_labels.color_of(name, db.labels())
    light, dark = task_labels.chip(color), task_labels.chip(color, dark=True)
    return tuple((a, b) for a, b in zip(light, dark))


def label_pill(master, db, name, text=None):
    """A static coloured pill (used for previews and per-label counts)."""
    bg, _hover, fg = chip_colors(db, name)
    return ctk.CTkLabel(master, text=text or name, fg_color=bg, text_color=fg, corner_radius=11, height=22,
                        font=ctk.CTkFont(size=11, weight="bold"), padx=8)


class LabelChip(ctk.CTkButton):
    """A task's label shown as a coloured pill; clicking it opens the label picker."""

    def __init__(self, master, db, name="", command=None):
        super().__init__(master, text="", width=86, height=26, corner_radius=13,
                         font=ctk.CTkFont(size=11, weight="bold"), command=self._open)
        self.db, self.on_change = db, command
        self.set(name)

    def set(self, name):
        self.name = name
        if name:
            bg, hover, fg = chip_colors(self.db, name)
            self.configure(text=name, fg_color=bg, hover_color=hover, text_color=fg, border_width=0)
        else:
            self.configure(text="+ Label", fg_color="transparent", hover_color=DAY_EMPTY_HOVER,
                           text_color=SUBTLE, border_width=1, border_color=BORDER)

    def _open(self):
        LabelPicker(self, self.name, self._picked)

    def _picked(self, name):
        self.set(name)
        if self.on_change:
            self.on_change(name)


class LabelPicker(ctk.CTkToplevel):
    """Drop-down under a LabelChip: pick a label, clear it, or type a new one."""

    def __init__(self, chip, current, command):
        super().__init__(chip)
        self.db, self.command = chip.db, command
        if MAC:
            # A borderless window can't take typing on macOS: use a small normal window there.
            self.title("Label")
            self.resizable(False, False)
            self.transient(chip.winfo_toplevel())
        else:
            self.overrideredirect(True)
        self.configure(fg_color=BORDER)
        box = ctk.CTkFrame(self, fg_color=CARD, corner_radius=0)
        box.pack(fill="both", expand=True, padx=1, pady=1)
        box.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(box, text="LABEL", text_color=SUBTLE, font=ctk.CTkFont(size=10, weight="bold"),
                     anchor="w").grid(row=0, column=0, sticky="ew", padx=10, pady=(8, 2))
        row = 1
        for label in self.db.labels():
            bg, hover, fg = chip_colors(self.db, label["name"])
            mark = "  ✓" if label["name"] == current else ""
            ctk.CTkButton(box, text=label["name"] + mark, anchor="w", height=28, corner_radius=14,
                          fg_color=bg, hover_color=hover, text_color=fg, font=ctk.CTkFont(size=12, weight="bold"),
                          command=lambda n=label["name"]: self._pick(n)).grid(
                row=row, column=0, sticky="ew", padx=8, pady=2)
            row += 1
        if current:
            ctk.CTkButton(box, text="Remove label", anchor="w", height=28, fg_color="transparent",
                          hover_color=DAY_EMPTY_HOVER, text_color=SUBTLE,
                          command=lambda: self._pick("")).grid(row=row, column=0, sticky="ew", padx=8, pady=2)
            row += 1
        self.new = ctk.CTkEntry(box, placeholder_text="New label, then Enter", height=30, width=190)
        self.new.grid(row=row, column=0, sticky="ew", padx=8, pady=(6, 8))
        self.new.bind("<Return>", self._create)

        self.update_idletasks()
        self.geometry(f"+{chip.winfo_rootx()}+{chip.winfo_rooty() + chip.winfo_height() + 4}")
        self.bind("<Escape>", lambda _e: self.destroy())
        self.bind("<Button-1>", self._click, add="+")
        self.after(30, self._grab)

    def _grab(self):
        try:
            self.grab_set()
            self.new.focus_force()
        except Exception:  # noqa: BLE001 - grab can fail if the window isn't viewable yet
            pass

    def _click(self, event):
        # With the grab on, a click anywhere else in the app lands here: close the picker.
        x, y = event.x_root - self.winfo_rootx(), event.y_root - self.winfo_rooty()
        if not (0 <= x < self.winfo_width() and 0 <= y < self.winfo_height()):
            self.destroy()

    def _create(self, _event=None):
        name = " ".join(self.new.get().split())
        if not name:
            return
        labels = self.db.labels()
        existing = next((label["name"] for label in labels if label["name"].lower() == name.lower()), None)
        if not existing:
            labels.append({"name": name, "color": task_labels.next_color(labels)})
            self.db.save_labels(labels)
        self._pick(existing or name)

    def _pick(self, name):
        self.destroy()
        self.command(name)


class TaskRow(ctk.CTkFrame):
    """One task: label chip, wrapping text that grows with its content, delete button."""

    def __init__(self, tasks, item):
        super().__init__(tasks.body, fg_color=ROW_BG, corner_radius=8)
        self.tasks = tasks
        self.grid_columnconfigure(1, weight=1)
        self.chip = LabelChip(self, tasks.db, item["label"], command=self._label_changed)
        self.chip.grid(row=0, column=0, sticky="nw", padx=(8, 4), pady=6)
        self.text = ctk.CTkTextbox(self, height=28, wrap="word", fg_color="transparent", border_width=0,
                                   corner_radius=0, border_spacing=2, activate_scrollbars=False,
                                   font=ctk.CTkFont(size=13))
        self.text.grid(row=0, column=1, sticky="ew", pady=2)
        self.text.insert("1.0", item["text"])
        ctk.CTkButton(self, text="✕", width=26, height=26, corner_radius=13, fg_color="transparent",
                      hover_color=DAY_EMPTY_HOVER, text_color=SUBTLE, command=self.remove).grid(
            row=0, column=2, sticky="ne", padx=(2, 6), pady=6)
        self._lines = 0
        tb = self.text._textbox
        tb.bind("<Configure>", self.fit, add="+")
        tb.bind("<KeyRelease>", self.fit, add="+")
        tb.bind("<Return>", self._enter)
        tb.bind("<KP_Enter>", self._enter)
        tb.bind("<BackSpace>", self._backspace)
        for mod in ("Alt", "Option") if MAC else ("Alt",):
            tb.bind(f"<{mod}-Up>", lambda _e: self.tasks.move(self, -1))
            tb.bind(f"<{mod}-Down>", lambda _e: self.tasks.move(self, 1))
        tb.bind("<<Paste>>", self._paste)

    def get(self):
        return {"text": " ".join(self.text.get("1.0", "end").split()), "label": self.chip.name}

    def fit(self, _event=None):
        """Grow or shrink the text box to show every wrapped line."""
        tb = self.text._textbox
        lines = max(1, (tb.count("1.0", "end", "displaylines") or (1,))[0])
        if lines != self._lines:
            self._lines = lines
            linespace = tb.tk.call("font", "metrics", tb.cget("font"), "-linespace")
            self.text.configure(height=(lines * linespace + 12) / self.text._get_widget_scaling())

    def focus_text(self, at_end=True):
        self.text.focus_set()
        self.text._textbox.mark_set("insert", "end-1c" if at_end else "1.0")

    def remove(self):
        self.tasks.remove(self)

    def _label_changed(self, _name):
        self.tasks.changed()

    def _enter(self, _event):
        self.tasks.insert_after(self, [{"text": "", "label": self.chip.name}]).focus_text()
        return "break"

    def _backspace(self, _event):
        if not self.text.get("1.0", "end").strip():
            self.tasks.remove(self, focus_previous=True)
            return "break"
        return None

    def _paste(self, _event):
        try:
            lines = [ln for ln in clean_lines(self.clipboard_get()) if ln]
        except tk.TclError:
            return None
        if len(lines) < 2:
            return None
        self.text._textbox.insert("insert", lines[0])
        self.tasks.insert_after(self, [{"text": ln, "label": self.chip.name} for ln in lines[1:]])
        return "break"


class TaskList(ctk.CTkFrame):
    """Editable list of tasks, each with a coloured label chip (e.g. a project name)."""

    def __init__(self, master, db, placeholder, on_change=None):
        super().__init__(master, fg_color="transparent")
        self.db, self.on_change = db, None
        self.rows = []
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.body = ctk.CTkScrollableFrame(self, fg_color="transparent", corner_radius=0)
        self.body.grid(row=0, column=0, sticky="nsew")
        self.body.grid_columnconfigure(0, weight=1)
        self.empty = ctk.CTkLabel(self.body, text="No tasks yet. Add one below, or paste several lines at once.",
                                  text_color=SUBTLE)

        add = ctk.CTkFrame(self, fg_color="transparent")
        add.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        add.grid_columnconfigure(1, weight=1)
        self.new_chip = LabelChip(add, db, "")
        self.new_chip.grid(row=0, column=0, padx=(0, 6))
        self.new_entry = ctk.CTkEntry(add, placeholder_text=placeholder, height=34)
        self.new_entry.grid(row=0, column=1, sticky="ew")
        self.new_entry.bind("<Return>", self._add_from_entry)
        self.new_entry.bind("<KP_Enter>", self._add_from_entry)
        self.new_entry.bind("<<Paste>>", self._paste_into_entry)
        accent_button(add, "Add", self._add_from_entry, width=64, height=34).grid(row=0, column=2, padx=(6, 0))
        self._layout()
        self.on_change = on_change

    # -- data
    def get(self):
        return task_labels.items(row.get() for row in self.rows)

    def set(self, items):
        for row in self.rows:
            row.destroy()
        self.rows = [TaskRow(self, item) for item in task_labels.items(items)]
        self._layout()

    def add(self, items):
        """Append items whose text isn't already listed; returns how many were added."""
        seen = {item["text"].lower() for item in self.get()}
        new = [item for item in task_labels.items(items) if item["text"].lower() not in seen]
        for item in new:
            seen.add(item["text"].lower())
            self.rows.append(TaskRow(self, item))
        self._layout()
        return len(new)

    def refresh(self):
        """Re-colour the chips (labels may have been edited in Settings)."""
        for chip in [row.chip for row in self.rows] + [self.new_chip]:
            chip.set(chip.name)

    def changed(self):
        if self.on_change:
            self.on_change()

    # -- row operations
    def insert_after(self, row, items):
        i = self.rows.index(row) + 1
        new = [TaskRow(self, {"text": it["text"], "label": it["label"]}) for it in items]
        self.rows[i:i] = new
        self._layout()
        return new[-1]

    def remove(self, row, focus_previous=False):
        i = self.rows.index(row)
        self.rows.pop(i)
        row.destroy()
        self._layout()
        if focus_previous and i > 0:
            self.rows[i - 1].focus_text()
        elif focus_previous:
            self.new_entry.focus_set()

    def move(self, row, delta):
        i = self.rows.index(row)
        j = min(max(i + delta, 0), len(self.rows) - 1)
        self.rows.insert(j, self.rows.pop(i))
        self._layout()
        row.focus_text()
        return "break"

    def _layout(self):
        for i, row in enumerate(self.rows):
            row.grid(row=i, column=0, sticky="ew", pady=(0, 6), padx=(0, 4))
        if self.rows:
            self.empty.grid_forget()
        else:
            self.empty.grid(row=0, column=0, sticky="w", pady=8)
        self.changed()

    # -- the "add" bar
    def _add_from_entry(self, _event=None):
        text = self.new_entry.get().strip()
        if text:
            self.new_entry.delete(0, "end")
            self._append([text])
        return "break"

    def _paste_into_entry(self, _event):
        try:
            lines = [ln for ln in clean_lines(self.clipboard_get()) if ln]
        except tk.TclError:
            return None
        if len(lines) < 2:
            return None
        self._append(lines)
        return "break"

    def _append(self, lines):
        label = self.new_chip.name
        for text in lines:
            self.rows.append(TaskRow(self, {"text": text, "label": label}))
        self._layout()
        self.after(50, lambda: self.body._parent_canvas.yview_moveto(1.0))


class Page(ctk.CTkFrame):
    def __init__(self, app, title, subtitle):
        super().__init__(app.content, fg_color="transparent")
        self.app = app
        self.db = app.db
        self.grid_columnconfigure(0, weight=1)
        self.header = ctk.CTkFrame(self, fg_color="transparent")
        self.header.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        self.header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(self.header, text=title, font=ctk.CTkFont(size=26, weight="bold"), anchor="w").grid(
            row=0, column=0, sticky="w")
        ctk.CTkLabel(self.header, text=subtitle, text_color=SUBTLE, anchor="w").grid(
            row=1, column=0, sticky="w")

    def on_show(self):
        pass

    def on_save_shortcut(self):
        pass


def accent_button(master, text, command, **kw):
    kw.setdefault("height", 36)
    return ctk.CTkButton(master, text=text, command=command, fg_color=ACCENT, hover_color=ACCENT_HOVER,
                         font=ctk.CTkFont(size=13, weight="bold"), corner_radius=8, **kw)


def ghost_button(master, text, command, **kw):
    kw.setdefault("height", 36)
    return ctk.CTkButton(master, text=text, command=command, fg_color="transparent", border_width=1,
                         border_color=BORDER, text_color=("gray15", "gray85"), hover_color=DAY_EMPTY,
                         corner_radius=8, **kw)


# ================================================================ TIME LOG
class TimeLogPage(Page):
    def __init__(self, app):
        super().__init__(app, "Time Log", "Record your hours and what you worked on each day.")
        today = date.today()
        self.selected = today

        self.picker = MonthPicker(self.header, today.year, today.month, self._month_changed)
        self.picker.grid(row=0, column=1, rowspan=2, sticky="e")
        ghost_button(self.header, "Today", self._go_today, width=80).grid(row=0, column=2, rowspan=2, padx=(10, 0))

        # Stat cards
        stats = ctk.CTkFrame(self, fg_color="transparent")
        stats.grid(row=1, column=0, sticky="ew", pady=(0, 14))
        for i in range(4):
            stats.grid_columnconfigure(i, weight=1, uniform="stats")
        self.stat_total = StatCard(stats, "Total hours")
        self.stat_work = StatCard(stats, "Work")
        self.stat_meet = StatCard(stats, "Meetings")
        self.stat_days = StatCard(stats, "Days logged")
        for i, card in enumerate((self.stat_total, self.stat_work, self.stat_meet, self.stat_days)):
            card.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 6, 0 if i == 3 else 6))
        self.progress = ctk.CTkProgressBar(self.stat_total, height=6, progress_color=ACCENT)
        self.progress.grid(row=3, column=0, sticky="ew", padx=16, pady=(0, 14))

        # Calendar + editor
        middle = ctk.CTkFrame(self, fg_color="transparent")
        middle.grid(row=2, column=0, sticky="nsew")
        middle.grid_columnconfigure(1, weight=1)
        middle.grid_rowconfigure(0, weight=1)

        cal = Card(middle)
        cal.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        cal_grid = ctk.CTkFrame(cal, fg_color="transparent")
        cal_grid.grid(row=0, column=0, padx=14, pady=14)
        for i, name in enumerate(("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")):
            ctk.CTkLabel(cal_grid, text=name, text_color=SUBTLE, font=ctk.CTkFont(size=12, weight="bold")).grid(
                row=0, column=i, pady=(0, 4))
        self.day_buttons = []
        for r in range(6):
            for c in range(7):
                b = ctk.CTkButton(cal_grid, text="", width=58, height=46, corner_radius=8,
                                  font=ctk.CTkFont(size=12))
                b.grid(row=r + 1, column=c, padx=2, pady=2)
                self.day_buttons.append(b)

        editor = Card(middle)
        editor.grid(row=0, column=1, sticky="nsew")
        editor.grid_rowconfigure(4, weight=1)
        top = ctk.CTkFrame(editor, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=18, pady=(14, 6))
        top.grid_columnconfigure(1, weight=1)
        nav = dict(width=32, height=32, fg_color=DAY_EMPTY, hover_color=DAY_EMPTY_HOVER,
                   text_color=("gray10", "gray90"), font=ctk.CTkFont(size=15, weight="bold"))
        ctk.CTkButton(top, text="‹", command=lambda: self.select(self.selected - timedelta(days=1)), **nav).grid(
            row=0, column=0)
        self.date_label = ctk.CTkLabel(top, font=ctk.CTkFont(size=17, weight="bold"))
        self.date_label.grid(row=0, column=1)
        ctk.CTkButton(top, text="›", command=lambda: self.select(self.selected + timedelta(days=1)), **nav).grid(
            row=0, column=2)

        hours = ctk.CTkFrame(editor, fg_color="transparent")
        hours.grid(row=1, column=0, sticky="ew", padx=18, pady=(6, 0))
        hours.grid_columnconfigure((0, 1, 2), weight=1, uniform="h")
        ctk.CTkLabel(hours, text="Work hours", anchor="w", text_color=SUBTLE).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(hours, text="Meeting hours", anchor="w", text_color=SUBTLE).grid(row=0, column=1, sticky="w")
        ctk.CTkLabel(hours, text="Day total", anchor="w", text_color=SUBTLE).grid(row=0, column=2, sticky="w")
        self.work_entry = ctk.CTkEntry(hours, placeholder_text="0", height=36)
        self.work_entry.grid(row=1, column=0, sticky="ew", padx=(0, 8))
        self.meet_entry = ctk.CTkEntry(hours, placeholder_text="0", height=36)
        self.meet_entry.grid(row=1, column=1, sticky="ew", padx=(0, 8))
        self.day_total = ctk.CTkLabel(hours, text="0 h", font=ctk.CTkFont(size=20, weight="bold"),
                                      text_color=(ACCENT, "#6fb1e8"), anchor="w")
        self.day_total.grid(row=1, column=2, sticky="w")
        for e in (self.work_entry, self.meet_entry):
            e.bind("<KeyRelease>", lambda _e: self._update_day_total())

        ctk.CTkLabel(editor, text="What did you work on?  (one item per line)", anchor="w",
                     text_color=SUBTLE).grid(row=3, column=0, sticky="ew", padx=18, pady=(12, 2))
        self.desc = ctk.CTkTextbox(editor, height=140, wrap="word", border_width=1, border_color=BORDER,
                                   font=ctk.CTkFont(size=13))
        self.desc.grid(row=4, column=0, sticky="nsew", padx=18)

        actions = ctk.CTkFrame(editor, fg_color="transparent")
        actions.grid(row=5, column=0, sticky="ew", padx=18, pady=14)
        actions.grid_columnconfigure(2, weight=1)
        accent_button(actions, "Save entry", self.save, width=120).grid(row=0, column=0)
        self.delete_btn = ctk.CTkButton(actions, text="Delete", command=self.delete, width=90, height=36,
                                        fg_color="transparent", border_width=1, border_color=DANGER,
                                        text_color=DANGER, hover_color=("#fbe9e7", "#3a2220"), corner_radius=8)
        self.delete_btn.grid(row=0, column=1, padx=8)
        ctk.CTkLabel(actions, text="Ctrl+S to save", text_color=SUBTLE, font=ctk.CTkFont(size=11)).grid(
            row=0, column=2, sticky="e")

        # Month entries list
        lst = Card(self, title="Entries this month")
        lst.grid(row=3, column=0, sticky="nsew", pady=(14, 0))
        lst.grid_rowconfigure(1, weight=1)
        self.grid_rowconfigure(3, weight=1)
        self.list_frame = ctk.CTkScrollableFrame(lst, fg_color="transparent", height=150)
        self.list_frame.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 10))
        self.list_frame.grid_columnconfigure(4, weight=1)

        self.select(today)

    # -- data flow
    def on_show(self):
        self.refresh()

    def on_save_shortcut(self):
        self.save()

    def _go_today(self):
        self.select(date.today())

    def _month_changed(self, year, month):
        if (self.selected.year, self.selected.month) != (year, month):
            day = min(self.selected.day, last_day(year, month))
            self.selected = date(year, month, day)
            self._load_selected()
        self.refresh()

    def select(self, d):
        self.selected = d
        if (self.picker.year, self.picker.month) != (d.year, d.month):
            self.picker.set(d.year, d.month, notify=False)
        self._load_selected()
        self.refresh()

    def _load_selected(self):
        d = self.selected
        self.date_label.configure(text=d.strftime("%A, %d %B %Y"))
        entry = self.db.get_entry(d.isoformat())
        set_entry(self.work_entry, fmt_h(entry["work_hours"]) if entry else "")
        set_entry(self.meet_entry, fmt_h(entry["meeting_hours"]) if entry and entry["meeting_hours"] else "")
        set_text(self.desc, entry["description"].splitlines() if entry else [])
        self.delete_btn.configure(state="normal" if entry else "disabled")
        self._update_day_total()
        self.work_entry.focus_set()

    def _update_day_total(self):
        try:
            total = parse_hours(self.work_entry.get()) + parse_hours(self.meet_entry.get())
            self.day_total.configure(text=f"{fmt_h(total)} h", text_color=(ACCENT, "#6fb1e8"))
        except ValueError:
            self.day_total.configure(text="invalid", text_color=DANGER)

    def save(self):
        try:
            work = parse_hours(self.work_entry.get())
            meet = parse_hours(self.meet_entry.get())
        except ValueError:
            messagebox.showwarning("Invalid hours", "Hours must be numbers, e.g. 4 or 3.5")
            return
        if work + meet > 24:
            messagebox.showwarning("Invalid hours", "A day can't have more than 24 hours.")
            return
        desc = self.desc.get("1.0", "end-1c").strip()
        if not work and not meet and not desc:
            messagebox.showinfo("Nothing to save", "Enter some hours or a description first.")
            return
        self.db.save_entry(self.selected.isoformat(), work, meet, desc)
        self.delete_btn.configure(state="normal")
        self.app.toast(f"Saved {self.selected.strftime('%a %d %b')} — {fmt_h(work + meet)} h")
        self.refresh()

    def delete(self):
        if not messagebox.askyesno("Delete entry", f"Delete the entry for {self.selected.strftime('%d %B %Y')}?"):
            return
        self.db.delete_entry(self.selected.isoformat())
        self._load_selected()
        self.app.toast("Entry deleted")
        self.refresh()

    def refresh(self):
        year, month = self.picker.year, self.picker.month
        entries = {e["date"]: e for e in self.db.month_entries(year, month)}
        work, meet, days = self.db.month_totals(year, month)
        target = float(self.db.settings().get("monthly_target") or 0)
        total = work + meet
        self.stat_total.set(f"{fmt_h(total)} h", f"of {fmt_h(target)} h target" if target else "")
        self.progress.set(min(total / target, 1) if target else 0)
        self.stat_work.set(f"{fmt_h(work)} h", "development")
        self.stat_meet.set(f"{fmt_h(meet)} h", "meetings")
        working_days = sum(1 for d in range(1, last_day(year, month) + 1) if date(year, month, d).weekday() < 5)
        self.stat_days.set(str(days), f"of {working_days} working days")

        # Calendar
        today = date.today()
        weeks = calendar.Calendar().monthdayscalendar(year, month)
        flat = [d for w in weeks for d in w] + [0] * (42 - 7 * len(weeks))
        for btn, day in zip(self.day_buttons, flat):
            if not day:
                btn.configure(text="", state="disabled", fg_color="transparent", border_width=0)
                continue
            d = date(year, month, day)
            entry = entries.get(d.isoformat())
            hours = (entry["work_hours"] + entry["meeting_hours"]) if entry else 0
            label = f"{day}\n{fmt_h(hours)}h" if entry else f"{day}\n "
            if d == self.selected:
                colors = dict(fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color="white")
            elif entry:
                colors = dict(fg_color=DAY_LOGGED, hover_color=DAY_LOGGED_HOVER, text_color=DAY_LOGGED_TEXT)
            else:
                weekend = d.weekday() >= 5
                colors = dict(fg_color=DAY_EMPTY, hover_color=DAY_EMPTY_HOVER,
                              text_color=SUBTLE if weekend else ("gray15", "gray85"))
            btn.configure(text=label, state="normal", border_width=2 if d == today else 0,
                          border_color=NOTE_BORDER, command=lambda d=d: self.select(d), **colors)

        # Entries list
        for w in self.list_frame.winfo_children():
            w.destroy()
        if not entries:
            ctk.CTkLabel(self.list_frame, text="No entries yet — pick a day on the calendar and log your hours.",
                         text_color=SUBTLE).grid(row=0, column=0, columnspan=5, sticky="w", padx=10, pady=10)
            return
        heads = ("Date", "Work", "Meet", "Total", "Description")
        for c, h in enumerate(heads):
            ctk.CTkLabel(self.list_frame, text=h, text_color=SUBTLE, font=ctk.CTkFont(size=11, weight="bold"),
                         anchor="w").grid(row=0, column=c, sticky="w", padx=10)
        for r, e in enumerate(entries.values(), 1):
            d = date.fromisoformat(e["date"])
            first = (e["description"].splitlines() or [""])[0]
            extra = len([x for x in e["description"].splitlines() if x.strip()]) - 1
            summary = first[:90] + ("…" if len(first) > 90 else "") + (f"  (+{extra} more)" if extra > 0 else "")
            values = (d.strftime("%a %d"), fmt_h(e["work_hours"]), fmt_h(e["meeting_hours"]),
                      fmt_h(e["work_hours"] + e["meeting_hours"]), summary)
            for c, v in enumerate(values):
                lbl = ctk.CTkLabel(self.list_frame, text=v, anchor="w", cursor="hand2",
                                   font=ctk.CTkFont(size=13, weight="bold" if c == 0 else "normal"))
                lbl.grid(row=r, column=c, sticky="w", padx=10, pady=1)
                lbl.bind("<Button-1>", lambda _e, d=d: self.select(d))


# ================================================================== REPORT
class ReportPage(Page):
    def __init__(self, app):
        super().__init__(app, "Monthly Report", "Summarise the month and export a polished PDF report.")
        year, month = default_report_month()
        self.loaded = None
        self.picker = MonthPicker(self.header, year, month, self._month_changed)
        self.picker.grid(row=0, column=1, rowspan=2, sticky="e")

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.grid(row=1, column=0, sticky="nsew")
        self.grid_rowconfigure(1, weight=1)
        body.grid_columnconfigure(0, weight=3)
        body.grid_columnconfigure(1, weight=2)
        body.grid_rowconfigure(1, weight=1)

        # Details card
        details = Card(body, title="Details")
        details.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        row = ctk.CTkFrame(details, fg_color="transparent")
        row.grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 14))
        row.grid_columnconfigure(5, weight=1)

        who = ctk.CTkFrame(row, fg_color="transparent")
        who.grid(row=0, column=0, rowspan=2, sticky="w", padx=(0, 28))
        ctk.CTkLabel(who, text="CONTRACTOR", text_color=SUBTLE, font=ctk.CTkFont(size=11, weight="bold"),
                     anchor="w").grid(row=0, column=0, sticky="w")
        self.who_name = ctk.CTkLabel(who, font=ctk.CTkFont(size=14, weight="bold"), anchor="w")
        self.who_name.grid(row=1, column=0, sticky="w")
        self.who_email = ctk.CTkLabel(who, text_color=SUBTLE, anchor="w")
        self.who_email.grid(row=2, column=0, sticky="w")

        ctk.CTkLabel(row, text="Total hours (incl. meetings)", text_color=SUBTLE, anchor="w").grid(
            row=0, column=1, sticky="w")
        ctk.CTkLabel(row, text="Meeting hours", text_color=SUBTLE, anchor="w").grid(
            row=0, column=2, sticky="w", padx=(12, 0))
        self.total_entry = ctk.CTkEntry(row, width=170, height=36)
        self.total_entry.grid(row=1, column=1, sticky="w")
        self.meet_entry = ctk.CTkEntry(row, width=130, height=36)
        self.meet_entry.grid(row=1, column=2, sticky="w", padx=(12, 0))
        ghost_button(row, "Fill from Time Log", self.fill_hours, width=150).grid(row=1, column=3, padx=12)
        self.log_hint = ctk.CTkLabel(row, text="", text_color=SUBTLE, anchor="w", justify="left")
        self.log_hint.grid(row=2, column=1, columnspan=4, sticky="w", pady=(6, 0))

        # Tasks done
        tasks = Card(body, title="Tasks completed")
        tasks.grid(row=1, column=0, sticky="nsew", padx=(0, 12))
        tasks.grid_rowconfigure(2, weight=1)
        self.task_counts = ctk.CTkFrame(tasks, fg_color="transparent")
        self.task_counts.grid(row=0, column=0, sticky="e", padx=18, pady=(14, 4))
        alt = "Option" if MAC else "Alt"
        ctk.CTkLabel(tasks, text=f"Click a task's label to change it. Enter starts a new task, {alt}+↑/↓ reorders, "
                                 "and pasting several lines adds one task per line.",
                     text_color=SUBTLE, anchor="w", justify="left", wraplength=560).grid(
            row=1, column=0, sticky="ew", padx=18)
        self.tasks = TaskList(tasks, self.db, "Add a completed task…", on_change=self._update_counts)
        self.tasks.grid(row=2, column=0, sticky="nsew", padx=18, pady=6)
        tb = ctk.CTkFrame(tasks, fg_color="transparent")
        tb.grid(row=3, column=0, sticky="ew", padx=18, pady=(0, 14))
        ghost_button(tb, "Import from Time Log", self.import_tasks, width=170).grid(row=0, column=0)
        ghost_button(tb, "Add last month's plan", self.import_last_plan_as_tasks, width=170).grid(
            row=0, column=1, padx=8)

        # Right column: meetings + next month
        right = ctk.CTkFrame(body, fg_color="transparent")
        right.grid(row=1, column=1, sticky="nsew")
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(1, weight=1)

        meet = Card(right, title="Meetings")
        meet.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        self.meetings = ctk.CTkTextbox(meet, height=80, wrap="word", border_width=1, border_color=BORDER,
                                       font=ctk.CTkFont(size=13))
        self.meetings.grid(row=1, column=0, sticky="ew", padx=18, pady=(4, 14))

        nxt = Card(right, title="Planned for next month")
        nxt.grid(row=1, column=0, sticky="nsew")
        nxt.grid_rowconfigure(1, weight=1)
        self.next_tasks = TaskList(nxt, self.db, "Add a task for next month…")
        self.next_tasks.grid(row=1, column=0, sticky="nsew", padx=18, pady=(4, 6))
        ghost_button(nxt, "Copy last month's plan", self.copy_last_plan, width=180).grid(
            row=2, column=0, sticky="w", padx=18, pady=(0, 14))

        # Action bar
        bar = Card(self)
        bar.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        inner = ctk.CTkFrame(bar, fg_color="transparent")
        inner.grid(row=0, column=0, sticky="ew", padx=18, pady=12)
        inner.grid_columnconfigure(2, weight=1)
        ctk.CTkLabel(inner, text="Template", text_color=SUBTLE).grid(row=0, column=0, padx=(0, 10))
        self.style = ctk.CTkSegmentedButton(inner, values=["Modern", "Classic"], selected_color=ACCENT,
                                            selected_hover_color=ACCENT_HOVER)
        self.style.grid(row=0, column=1)
        ghost_button(inner, "Save draft", self.save_draft, width=110).grid(row=0, column=3, padx=(0, 8))
        ghost_button(inner, "Preview", self.preview, width=100).grid(row=0, column=4, padx=(0, 8))
        accent_button(inner, "Generate PDF", self.generate, width=150).grid(row=0, column=5)

        self.load_month()

    # -- helpers
    def _month(self):
        return self.picker.year, self.picker.month

    def on_show(self):
        s = self.db.settings()
        self.who_name.configure(text=s.get("name") or "— set your name in Settings —")
        self.who_email.configure(text=s.get("email", ""))
        self._update_hint()
        self.tasks.refresh()
        self.next_tasks.refresh()
        self._update_counts()

    def on_save_shortcut(self):
        self.save_draft()

    def _month_changed(self, _y, _m):
        if self.loaded:
            self._persist(*self.loaded)
        self.load_month()

    def _update_hint(self):
        work, meet, days = self.db.month_totals(*self._month())
        self.log_hint.configure(
            text=f"Time Log: {fmt_h(work)} h work + {fmt_h(meet)} h meetings = {fmt_h(work + meet)} h"
                 f"  ({days} days)" if days else "No Time Log entries for this month.")

    def load_month(self):
        year, month = self._month()
        s = self.db.settings()
        data = self.db.get_report(year, month)
        if data:
            set_entry(self.total_entry, data.get("total_hours", ""))
            set_entry(self.meet_entry, data.get("meeting_hours", ""))
            self.tasks.set(data.get("tasks", []))
            set_text(self.meetings, data.get("meetings", []))
            self.next_tasks.set(data.get("next_tasks", []))
            self.style.set(data.get("style") or s.get("report_style") or "Modern")
        else:
            set_entry(self.total_entry, "")
            set_entry(self.meet_entry, "")
            self.tasks.set([])
            set_text(self.meetings, [s.get("default_meetings")] if s.get("default_meetings") else [])
            self.next_tasks.set([])
            self.style.set(s.get("report_style") or "Modern")
            if self.db.month_totals(year, month)[2]:
                self.fill_hours(quiet=True)
        self.loaded = (year, month)
        self.on_show()

    def collect(self):
        total = parse_hours(self.total_entry.get())
        meet = parse_hours(self.meet_entry.get())
        year, month = self._month()
        return {
            "year": year, "month": month,
            "total_hours": total, "meeting_hours": meet,
            "tasks": self.tasks.get(),
            "meetings": text_lines(self.meetings),
            "next_tasks": self.next_tasks.get(),
            "style": self.style.get(),
        }

    def _persist(self, year, month):
        data = {
            "total_hours": self.total_entry.get().strip(),
            "meeting_hours": self.meet_entry.get().strip(),
            "tasks": self.tasks.get(),
            "meetings": text_lines(self.meetings),
            "next_tasks": self.next_tasks.get(),
            "style": self.style.get(),
        }
        empty = not any([data["total_hours"], data["meeting_hours"], data["tasks"], data["next_tasks"]])
        if not empty or self.db.get_report(year, month):
            self.db.save_report(year, month, data)

    # -- actions
    def fill_hours(self, quiet=False):
        work, meet, days = self.db.month_totals(*self._month())
        if not days:
            if not quiet:
                messagebox.showinfo("No entries", "There are no Time Log entries for this month.")
            return
        set_entry(self.total_entry, fmt_h(work + meet))
        set_entry(self.meet_entry, fmt_h(meet))
        if not quiet:
            self.app.toast("Hours filled from the Time Log")

    def import_tasks(self):
        lines = [ln for e in self.db.month_entries(*self._month()) for ln in clean_lines(e["description"])]
        added = self.tasks.add(lines)
        if not added:
            messagebox.showinfo("Nothing new", "No new descriptions found in this month's Time Log.")
            return
        self.app.toast(f"Imported {added} items — tidy them up and give each a label")

    def _last_plan(self):
        data = self.db.get_report(*shift_month(*self._month(), -1))
        return task_labels.items((data or {}).get("next_tasks", []))

    def copy_last_plan(self):
        plan = self._last_plan()
        if not plan:
            messagebox.showinfo("No previous plan", "No saved report with a plan exists for the previous month.")
            return
        self.next_tasks.add(plan)

    def import_last_plan_as_tasks(self):
        plan = self._last_plan()
        if not plan:
            messagebox.showinfo("No previous plan", "No saved report with a plan exists for the previous month.")
            return
        self.tasks.add(plan)

    def _update_counts(self):
        """Per-label task counts next to the "Tasks completed" title."""
        for w in self.task_counts.winfo_children():
            w.destroy()
        counts = {}
        for item in self.tasks.get():
            counts[item["label"]] = counts.get(item["label"], 0) + 1
        for i, (name, n) in enumerate(sorted(counts.items(), key=lambda kv: (not kv[0], -kv[1], kv[0]))):
            if name:
                label_pill(self.task_counts, self.db, name, f"{name}  {n}").grid(row=0, column=i, padx=(6, 0))
            else:
                ctk.CTkLabel(self.task_counts, text=f"{n} unlabelled", text_color=SUBTLE,
                             font=ctk.CTkFont(size=11)).grid(row=0, column=i, padx=(8, 0))

    def save_draft(self):
        self._persist(*self._month())
        self.app.toast("Report draft saved")

    def _validated(self):
        try:
            data = self.collect()
        except ValueError:
            messagebox.showwarning("Invalid hours", "Total and meeting hours must be numbers.")
            return None
        if data["meeting_hours"] > data["total_hours"]:
            messagebox.showwarning("Check hours", "Meeting hours can't exceed the total hours (total includes meetings).")
            return None
        if not data["tasks"]:
            if not messagebox.askyesno("No tasks", "The report has no tasks listed. Continue anyway?"):
                return None
        unlabelled = sum(not t["label"] for t in data["tasks"] + data["next_tasks"])
        if unlabelled and not messagebox.askyesno(
                "Missing labels", f"{unlabelled} task(s) have no label. Continue anyway?"):
            return None
        return data

    def preview(self):
        data = self._validated()
        if not data:
            return
        path = os.path.join(tempfile.gettempdir(), f"worklog-report-preview-{os.getpid()}.pdf")
        pdfgen.generate_report(path, self.db.settings(), data, data["style"])
        open_path(path)

    def generate(self):
        data = self._validated()
        if not data:
            return
        self._persist(*self._month())
        s = self.db.settings()
        path = self.app.output_path("reports", pdfgen.report_filename(s, data["year"], data["month"]))
        if not path:
            return
        pdfgen.generate_report(path, s, data, data["style"])
        self.app.toast(f"Report saved: {os.path.basename(path)}", path)
        open_path(path)


# ================================================================= INVOICE
class InvoicePage(Page):
    def __init__(self, app):
        super().__init__(app, "Invoice", "Fills in your invoice template — just set the hours and dates.")
        year, month = default_report_month()
        self.picker = MonthPicker(self.header, year, month, lambda *_: self.load_month())
        self.picker.grid(row=0, column=1, rowspan=2, sticky="e")

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.grid(row=1, column=0, sticky="ew")
        body.grid_columnconfigure(0, weight=1)
        body.grid_columnconfigure(1, weight=1)

        form = Card(body, title="Invoice details")
        form.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        f = ctk.CTkFrame(form, fg_color="transparent")
        f.grid(row=1, column=0, sticky="ew", padx=18, pady=(4, 16))
        f.grid_columnconfigure(1, weight=1)

        def label(r, text):
            ctk.CTkLabel(f, text=text, text_color=SUBTLE, anchor="w").grid(row=r, column=0, sticky="w", pady=7,
                                                                           padx=(0, 14))

        label(0, "Hours worked")
        hrow = ctk.CTkFrame(f, fg_color="transparent")
        hrow.grid(row=0, column=1, sticky="w")
        self.hours = ctk.CTkEntry(hrow, width=130, height=36)
        self.hours.grid(row=0, column=0)
        self.hours.bind("<KeyRelease>", lambda _e: self.update_summary())
        ghost_button(hrow, "Use report / log hours", self.fill_hours, width=170, height=32).grid(
            row=0, column=1, padx=8)

        label(1, "Issue date")
        self.issue = DateField(f, command=self._issue_changed)
        self.issue.grid(row=1, column=1, sticky="w")
        label(2, "Expiry date")
        self.expiry = DateField(f, command=self.update_summary)
        self.expiry.grid(row=2, column=1, sticky="w")

        label(3, "Invoice number")
        self.number = ctk.CTkEntry(f, width=130, height=36)
        self.number.grid(row=3, column=1, sticky="w")
        self.number.bind("<KeyRelease>", lambda _e: self.update_summary())
        label(4, "Hourly rate")
        self.rate = ctk.CTkEntry(f, width=130, height=36)
        self.rate.grid(row=4, column=1, sticky="w")
        self.rate.bind("<KeyRelease>", lambda _e: self.update_summary())
        self.source_hint = ctk.CTkLabel(f, text="", text_color=SUBTLE, anchor="w", justify="left")
        self.source_hint.grid(row=5, column=0, columnspan=2, sticky="w", pady=(6, 0))

        # Summary card
        summ = Card(body)
        summ.grid(row=0, column=1, sticky="nsew")
        band = ctk.CTkFrame(summ, fg_color=ACCENT, corner_radius=10, height=56)
        band.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 0))
        band.grid_columnconfigure(0, weight=1)
        self.sum_title = ctk.CTkLabel(band, text="INVOICE", text_color="white",
                                      font=ctk.CTkFont(size=20, weight="bold"), anchor="e")
        self.sum_title.grid(row=0, column=0, sticky="e", padx=16, pady=10)
        lines = ctk.CTkFrame(summ, fg_color="transparent")
        lines.grid(row=1, column=0, sticky="ew", padx=20, pady=(12, 4))
        lines.grid_columnconfigure(1, weight=1)
        self.sum_values = {}
        for r, key in enumerate(("Bill to", "Period", "Issued", "Expires", "Line item", "Tax")):
            ctk.CTkLabel(lines, text=key, text_color=SUBTLE, anchor="w").grid(row=r, column=0, sticky="w",
                                                                              padx=(0, 18))
            self.sum_values[key] = ctk.CTkLabel(lines, text="", anchor="w", font=ctk.CTkFont(size=13))
            self.sum_values[key].grid(row=r, column=1, sticky="w")
        tot = ctk.CTkFrame(summ, fg_color=("#ddebf7", "#17324d"), corner_radius=10)
        tot.grid(row=2, column=0, sticky="ew", padx=20, pady=(4, 10))
        tot.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(tot, text="TOTAL AMOUNT", font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=(ACCENT, "#9cc8ee")).grid(row=0, column=0, sticky="w", padx=16, pady=14)
        self.sum_total = ctk.CTkLabel(tot, text="", font=ctk.CTkFont(size=26, weight="bold"),
                                      text_color=(ACCENT, "#e6f1fb"))
        self.sum_total.grid(row=0, column=1, sticky="e", padx=16)
        btns = ctk.CTkFrame(summ, fg_color="transparent")
        btns.grid(row=3, column=0, sticky="e", padx=20, pady=(4, 16))
        ghost_button(btns, "Preview", self.preview, width=100).grid(row=0, column=0, padx=(0, 8))
        accent_button(btns, "Generate invoice PDF", self.generate, width=190).grid(row=0, column=1)

        # History
        hist = Card(self, title="Invoices generated with WorkLog")
        hist.grid(row=2, column=0, sticky="nsew", pady=(12, 0))
        hist.grid_rowconfigure(1, weight=1)
        self.grid_rowconfigure(2, weight=1)
        self.history = ctk.CTkScrollableFrame(hist, fg_color="transparent")
        self.history.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 10))
        self.history.grid_columnconfigure(5, weight=1)

        self.load_month()

    def _month(self):
        return self.picker.year, self.picker.month

    def on_show(self):
        self.update_summary()
        self.refresh_history()

    def _suggested_hours(self):
        year, month = self._month()
        report = self.db.get_report(year, month)
        if report and str(report.get("total_hours", "")).strip():
            return report["total_hours"], "from the saved monthly report"
        work, meet, days = self.db.month_totals(year, month)
        if days:
            return fmt_h(work + meet), "from the Time Log"
        return "", ""

    def load_month(self):
        year, month = self._month()
        s = self.db.settings()
        existing = self.db.invoice_for_month(year, month)
        if existing:
            set_entry(self.hours, fmt_h(existing["hours"]))
            set_entry(self.number, str(existing["number"]))
            set_entry(self.rate, f"{existing['rate']:g}")
            self.issue.set(date.fromisoformat(existing["issue_date"]))
            self.expiry.set(date.fromisoformat(existing["expiry_date"]))
            self.source_hint.configure(text=f"Loaded invoice #{existing['number']} already issued for this month.")
        else:
            hours, source = self._suggested_hours()
            set_entry(self.hours, hours)
            set_entry(self.number, str(self.db.next_invoice_number()))
            set_entry(self.rate, s.get("rate", "20"))
            ny, nm = shift_month(year, month, 1)
            self.issue.set(date(ny, nm, 1))
            self.expiry.set(date(ny, nm, last_day(ny, nm)))
            self.source_hint.configure(text=f"Hours suggested {source}." if source else
                                       "No report or Time Log hours for this month yet.")
        self.update_summary()
        self.refresh_history()

    def fill_hours(self):
        hours, source = self._suggested_hours()
        if not source:
            messagebox.showinfo("No hours found", "No saved report or Time Log entries for this month.")
            return
        set_entry(self.hours, hours)
        self.source_hint.configure(text=f"Hours taken {source}.")
        self.update_summary()

    def _issue_changed(self):
        try:
            issue = self.issue.get()
            if not self.expiry.entry.get().strip():
                self.expiry.set(date(issue.year, issue.month, last_day(issue.year, issue.month)))
        except ValueError:
            pass
        self.update_summary()

    def collect(self):
        year, month = self._month()
        s = self.db.settings()
        return {
            "number": int(self.number.get().strip()),
            "year": year, "month": month,
            "hours": parse_hours(self.hours.get()),
            "rate": float(self.rate.get().strip()),
            "tax": float(s.get("tax") or 0),
            "issue_date": self.issue.get(),
            "expiry_date": self.expiry.get(),
        }

    def update_summary(self):
        s = self.db.settings()
        cur = s.get("currency") or "$"
        year, month = self._month()
        try:
            inv = self.collect()
        except ValueError:
            self.sum_total.configure(text="—")
            for label in self.sum_values.values():
                label.configure(text="")
            self.sum_values["Bill to"].configure(text="Fill in valid hours, dates, number and rate.")
            return
        subtotal = inv["hours"] * inv["rate"]
        total = subtotal * (1 + inv["tax"] / 100)
        self.sum_title.configure(text=f"INVOICE  #{inv['number']}")
        values = {
            "Bill to": s.get("client_org", ""),
            "Period": f"1 – {last_day(year, month)} {calendar.month_name[month]} {year}",
            "Issued": f"{inv['issue_date']:%Y/%m/%d}",
            "Expires": f"{inv['expiry_date']:%Y/%m/%d}",
            "Line item": f"{fmt_h(inv['hours'])} h × {pdfgen.fmt_money(inv['rate'], cur)}"
                         f"  =  {pdfgen.fmt_money(subtotal, cur)}",
            "Tax": f"{inv['tax']:.2f}%",
        }
        for key, text in values.items():
            self.sum_values[key].configure(text=text)
        self.sum_total.configure(text=pdfgen.fmt_money(total, cur))

    def _validated(self):
        try:
            inv = self.collect()
        except ValueError:
            messagebox.showwarning("Check the fields",
                                   "Please enter valid hours, rate, invoice number and dates (dates as YYYY/MM/DD).")
            return None
        if inv["hours"] <= 0:
            messagebox.showwarning("No hours", "Enter the number of hours to bill.")
            return None
        if inv["expiry_date"] < inv["issue_date"]:
            messagebox.showwarning("Check dates", "The expiry date is before the issue date.")
            return None
        return inv

    def preview(self):
        inv = self._validated()
        if not inv:
            return
        path = os.path.join(tempfile.gettempdir(), f"worklog-invoice-preview-{os.getpid()}.pdf")
        try:
            build_invoice(path, self.db.settings(), inv)
        except TemplateError as exc:
            messagebox.showerror("Invoice template", str(exc))
            return
        open_path(path)

    def generate(self):
        inv = self._validated()
        if not inv:
            return
        s = self.db.settings()
        path = self.app.output_path("invoices", pdfgen.invoice_filename(s, inv["year"], inv["month"]))
        if not path:
            return
        try:
            total = build_invoice(path, s, inv)
        except TemplateError as exc:
            messagebox.showerror("Invoice template", str(exc))
            return
        self.db.save_invoice({
            "number": inv["number"], "month": f"{inv['year']:04d}-{inv['month']:02d}",
            "hours": inv["hours"], "rate": inv["rate"], "tax": inv["tax"], "total": total,
            "issue_date": inv["issue_date"].isoformat(), "expiry_date": inv["expiry_date"].isoformat(),
            "file": path,
        })
        self.app.toast(f"Invoice #{inv['number']} saved: {os.path.basename(path)}", path)
        self.refresh_history()
        open_path(path)

    def refresh_history(self):
        for w in self.history.winfo_children():
            w.destroy()
        rows = self.db.invoices()
        if not rows:
            ctk.CTkLabel(self.history, text="No invoices generated yet.", text_color=SUBTLE).grid(
                row=0, column=0, sticky="w", padx=10, pady=8)
            return
        cur = self.db.settings().get("currency") or "$"
        for c, h in enumerate(("Number", "Period", "Hours", "Total", "Issued", "File")):
            ctk.CTkLabel(self.history, text=h, text_color=SUBTLE, font=ctk.CTkFont(size=11, weight="bold"),
                         anchor="w").grid(row=0, column=c, sticky="w", padx=10)
        for r, inv in enumerate(rows, 1):
            y, m = map(int, inv["month"].split("-"))
            vals = (f"#{inv['number']}", f"{calendar.month_name[m]} {y}", fmt_h(inv["hours"]),
                    pdfgen.fmt_money(inv["total"], cur), inv["issue_date"].replace("-", "/"))
            for c, v in enumerate(vals):
                ctk.CTkLabel(self.history, text=v, anchor="w").grid(row=r, column=c, sticky="w", padx=10)
            exists = inv["file"] and os.path.exists(inv["file"])
            ctk.CTkButton(self.history, text="Open" if exists else "missing", width=70, height=26,
                          state="normal" if exists else "disabled", fg_color="transparent", border_width=1,
                          border_color=BORDER, text_color=("gray15", "gray85"), hover_color=DAY_EMPTY,
                          command=lambda p=inv["file"]: open_path(p)).grid(row=r, column=5, sticky="w",
                                                                           padx=10, pady=2)


# ================================================================ SETTINGS
SETTINGS_SECTIONS = [
    ("Your details", "Shown on every report and invoice.", [
        ("name", "Full name"), ("email", "Email"), ("address1", "Address line 1"),
        ("address2", "Address line 2"), ("phone", "Phone"),
    ]),
    ("Client (bill to)", "The customer block on the invoice.", [
        ("client_org", "Organisation"), ("client_contact", "Contact name"),
        ("client_address1", "Address line 1"), ("client_address2", "Address line 2"),
        ("client_email", "Email"),
    ]),
    ("Invoice", "Note and line description: **bold**, __underline__, {project}, {start_day}, {month_yr}…", [
        ("project", "Project"), ("rate", "Hourly rate"), ("currency", "Currency symbol"), ("tax", "Tax (%)"),
        ("next_invoice_number", "Next invoice number"), ("invoice_note", "Invoice note"),
        ("invoice_description", "Line description"),
    ]),
    ("Reports", "Monthly report defaults.", [
        ("org_name", "Organisation (report title)"), ("monthly_target", "Monthly hours target"),
        ("default_meetings", "Default meetings line"),
    ]),
]


class SettingsPage(Page):
    def __init__(self, app):
        super().__init__(app, "Settings", "Set these once — they're used for all reports and invoices.")
        scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        scroll.grid(row=1, column=0, sticky="nsew")
        self.grid_rowconfigure(1, weight=1)
        scroll.grid_columnconfigure((0, 1), weight=1, uniform="s")
        self.entries = {}

        for i, (title, hint, fields) in enumerate(SETTINGS_SECTIONS):
            card = Card(scroll, title=title)
            card.grid(row=i // 2, column=i % 2, sticky="nsew", padx=(0 if i % 2 == 0 else 6, 6 if i % 2 == 0 else 0),
                      pady=(0, 12))
            ctk.CTkLabel(card, text=hint, text_color=SUBTLE, anchor="w", justify="left", wraplength=500).grid(
                row=1, column=0, sticky="ew", padx=18)
            grid = ctk.CTkFrame(card, fg_color="transparent")
            grid.grid(row=2, column=0, sticky="ew", padx=18, pady=(6, 14))
            grid.grid_columnconfigure(1, weight=1)
            for r, (key, lbl) in enumerate(fields):
                ctk.CTkLabel(grid, text=lbl, anchor="w").grid(row=r, column=0, sticky="w", pady=4, padx=(0, 12))
                e = ctk.CTkEntry(grid, height=34)
                e.grid(row=r, column=1, sticky="ew", pady=4)
                self.entries[key] = e

        files = Card(scroll, title="Files & appearance")
        files.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        g = ctk.CTkFrame(files, fg_color="transparent")
        g.grid(row=1, column=0, sticky="ew", padx=18, pady=(4, 14))
        g.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(g, text="Save PDFs to", anchor="w").grid(row=0, column=0, sticky="w", padx=(0, 12))
        self.entries["output_dir"] = ctk.CTkEntry(g, height=34)
        self.entries["output_dir"].grid(row=0, column=1, sticky="ew")
        ghost_button(g, "Browse…", self._browse, width=90, height=34).grid(row=0, column=2, padx=(8, 0))
        ctk.CTkLabel(g, text="Default report template", anchor="w").grid(row=1, column=0, sticky="w", pady=(10, 0))
        self.style = ctk.CTkSegmentedButton(g, values=["Modern", "Classic"], selected_color=ACCENT,
                                            selected_hover_color=ACCENT_HOVER)
        self.style.grid(row=1, column=1, sticky="w", pady=(10, 0))
        ctk.CTkLabel(g, text="Appearance", anchor="w").grid(row=2, column=0, sticky="w", pady=(10, 0))
        self.appearance = ctk.CTkSegmentedButton(g, values=["System", "Light", "Dark"], selected_color=ACCENT,
                                                 selected_hover_color=ACCENT_HOVER,
                                                 command=ctk.set_appearance_mode)
        self.appearance.grid(row=2, column=1, sticky="w", pady=(10, 0))
        ctk.CTkLabel(g, text="Invoice template PDF", anchor="w").grid(row=3, column=0, sticky="w", pady=(10, 0))
        self.entries["invoice_template"] = ctk.CTkEntry(
            g, height=34, placeholder_text="Built-in template (templates/invoice-template.pdf)")
        self.entries["invoice_template"].grid(row=3, column=1, sticky="ew", pady=(10, 0))
        ghost_button(g, "Browse…", self._browse_template, width=90, height=34).grid(
            row=3, column=2, padx=(8, 0), pady=(10, 0))
        ctk.CTkLabel(g, text="Leave empty for the built-in template. Invoices are made by filling these "
                             "placeholder words in the PDF:\n" + ", ".join(FIELDS) + ",\n" + ", ".join(BLOCKS)
                             + " (the invoice note and line description above).",
                     text_color=SUBTLE, anchor="w", justify="left", wraplength=760).grid(
            row=4, column=1, columnspan=2, sticky="w", pady=(4, 0))

        labels_card = Card(scroll, title="Task labels")
        labels_card.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        ctk.CTkLabel(labels_card, text="Labels you can put on report tasks. Changes here apply right away. "
                                       "Removing a label doesn't change tasks that already use it.",
                     text_color=SUBTLE, anchor="w").grid(row=1, column=0, sticky="ew", padx=18)
        self.label_rows = ctk.CTkFrame(labels_card, fg_color="transparent")
        self.label_rows.grid(row=2, column=0, sticky="ew", padx=18, pady=(8, 0))
        add = ctk.CTkFrame(labels_card, fg_color="transparent")
        add.grid(row=3, column=0, sticky="w", padx=18, pady=(8, 14))
        self.new_label = ctk.CTkEntry(add, placeholder_text="New label, e.g. a project", width=220, height=34)
        self.new_label.grid(row=0, column=0)
        self.new_label.bind("<Return>", lambda _e: self._add_label())
        ghost_button(add, "Add label", self._add_label, width=100, height=34).grid(row=0, column=1, padx=(8, 0))

        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=2, column=0, sticky="e", pady=(10, 0))
        accent_button(bar, "Save settings", self.save, width=150).grid(row=0, column=0)

    def _render_labels(self):
        for w in self.label_rows.winfo_children():
            w.destroy()
        labels = self.db.labels()
        if not labels:
            ctk.CTkLabel(self.label_rows, text="No labels yet.", text_color=SUBTLE).grid(row=0, column=0, sticky="w")
        for r, label in enumerate(labels):
            label_pill(self.label_rows, self.db, label["name"]).grid(row=r, column=0, sticky="w", pady=3,
                                                                     padx=(0, 16))
            dots = ctk.CTkFrame(self.label_rows, fg_color="transparent")
            dots.grid(row=r, column=1, sticky="w")
            for c, color in enumerate(task_labels.PALETTE):
                chosen = color == label["color"]
                ctk.CTkButton(dots, text="✓" if chosen else "", width=22, height=22, corner_radius=11,
                              fg_color=color, hover_color=color, text_color="white",
                              font=ctk.CTkFont(size=11, weight="bold"),
                              command=lambda n=label["name"], col=color: self._recolor_label(n, col)).grid(
                    row=0, column=c, padx=2)
            ctk.CTkButton(self.label_rows, text="Remove", width=70, height=26, fg_color="transparent",
                          hover_color=DAY_EMPTY_HOVER, text_color=SUBTLE,
                          command=lambda n=label["name"]: self._remove_label(n)).grid(
                row=r, column=2, sticky="w", padx=(12, 0))

    def _add_label(self):
        name = " ".join(self.new_label.get().split())
        labels = self.db.labels()
        if not name or any(label["name"].lower() == name.lower() for label in labels):
            return
        labels.append({"name": name, "color": task_labels.next_color(labels)})
        self.db.save_labels(labels)
        self.new_label.delete(0, "end")
        self._render_labels()

    def _recolor_label(self, name, color):
        labels = self.db.labels()
        for label in labels:
            if label["name"] == name:
                label["color"] = color
        self.db.save_labels(labels)
        self._render_labels()

    def _remove_label(self, name):
        if messagebox.askyesno("Remove label", f"Remove the label “{name}” from the list?"):
            self.db.save_labels([label for label in self.db.labels() if label["name"] != name])
            self._render_labels()

    def _browse(self):
        d = filedialog.askdirectory(initialdir=self.entries["output_dir"].get() or os.path.expanduser("~"))
        if d:
            set_entry(self.entries["output_dir"], d)

    def _browse_template(self):
        current = self.entries["invoice_template"].get()
        path = filedialog.askopenfilename(initialdir=os.path.dirname(current) if current else APP_DIR,
                                          filetypes=[("PDF", "*.pdf")])
        if path:
            set_entry(self.entries["invoice_template"], path)

    def on_show(self):
        s = self.db.settings()
        for key, e in self.entries.items():
            set_entry(e, s.get(key, ""))
        self.style.set(s.get("report_style") or "Modern")
        self.appearance.set(s.get("appearance") or "System")
        self._render_labels()

    def on_save_shortcut(self):
        self.save()

    def save(self):
        values = {k: e.get().strip() for k, e in self.entries.items()}
        for key, label in (("rate", "Hourly rate"), ("tax", "Tax"), ("monthly_target", "Monthly target")):
            try:
                float(values[key] or 0)
            except ValueError:
                messagebox.showwarning("Invalid value", f"{label} must be a number.")
                return
        if values["invoice_template"] and not os.path.exists(values["invoice_template"]):
            messagebox.showwarning("Invalid value", "The invoice template PDF doesn't exist.")
            return
        if not values["next_invoice_number"].isdigit():
            messagebox.showwarning("Invalid value", "Next invoice number must be a whole number.")
            return
        values["report_style"] = self.style.get()
        values["appearance"] = self.appearance.get()
        self.db.save_settings(values)
        self.app.toast("Settings saved")


# ===================================================================== APP
class App(ctk.CTk):
    def __init__(self):
        self.db = Storage(DB_PATH)
        settings = self.db.settings()
        ctk.set_appearance_mode(settings.get("appearance") or "System")
        ctk.set_default_color_theme("blue")
        super().__init__(fg_color=PAGE_BG, className="WorkLog")
        families = set(tkfont.families(self))
        for family in ("Inter", "Ubuntu", "Noto Sans", "Cantarell", "DejaVu Sans", "Segoe UI", "Helvetica Neue"):
            if family in families:
                ctk.ThemeManager.theme["CTkFont"]["family"] = family
                break
        self.title("WorkLog — hours, reports & invoices")
        icon = os.path.join(APP_DIR, "assets", "worklog.png")
        if os.path.exists(icon):
            self._icon = tk.PhotoImage(file=icon)
            self.iconphoto(True, self._icon)
        width = min(1320, self.winfo_screenwidth() - 40)
        height = min(880, self.winfo_screenheight() - 90)
        self.geometry(f"{width}x{height}")
        self.minsize(min(1180, width), min(760, height))
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Sidebar
        side = ctk.CTkFrame(self, width=220, corner_radius=0, fg_color=("#0b3d66", "#111315"))
        side.grid(row=0, column=0, sticky="nsw")
        side.grid_propagate(False)
        side.grid_rowconfigure(6, weight=1)
        side.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(side, text="WorkLog", text_color="white", font=ctk.CTkFont(size=24, weight="bold"),
                     anchor="w").grid(row=0, column=0, sticky="ew", padx=22, pady=(26, 0))
        ctk.CTkLabel(side, text="Hours · Reports · Invoices", text_color="#9cc1e3",
                     font=ctk.CTkFont(size=12), anchor="w").grid(row=1, column=0, sticky="ew", padx=22,
                                                                 pady=(0, 24))

        self.content = ctk.CTkFrame(self, fg_color="transparent")
        self.content.grid(row=0, column=1, sticky="nsew", padx=26, pady=(22, 8))
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)

        self.pages = {
            "Time Log": TimeLogPage(self),
            "Monthly Report": ReportPage(self),
            "Invoice": InvoicePage(self),
            "Settings": SettingsPage(self),
        }
        self.nav = {}
        for i, name in enumerate(self.pages):
            b = ctk.CTkButton(side, text=name, anchor="w", height=42, corner_radius=8,
                              font=ctk.CTkFont(size=14, weight="bold"), fg_color="transparent",
                              text_color="#d7e6f4", hover_color=("#13507f", "#22262a"),
                              command=lambda n=name: self.show(n))
            b.grid(row=2 + i, column=0, sticky="ew", padx=12, pady=3)
            self.nav[name] = b

        self.status = ctk.CTkLabel(side, text="", text_color="#9cc1e3", font=ctk.CTkFont(size=11),
                                   wraplength=190, justify="left", anchor="w")
        self.status.grid(row=7, column=0, sticky="ew", padx=22, pady=(0, 6))
        ctk.CTkLabel(side, text=f"Data: {os.path.relpath(DB_PATH, os.path.dirname(APP_DIR))}",
                     text_color="#6f93b5", font=ctk.CTkFont(size=10), anchor="w").grid(
            row=8, column=0, sticky="ew", padx=22, pady=(0, 16))

        # Status line under the page content
        self.toast_row = ctk.CTkFrame(self.content, fg_color="transparent", height=46)
        self.toast_row.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        self.toast_row.grid_propagate(False)
        self.toast_row.grid_columnconfigure(0, weight=1)
        self.toast_bar = ctk.CTkFrame(self.toast_row, fg_color=("#e3f0fb", "#17324d"), corner_radius=10)
        self.toast_label = ctk.CTkLabel(self.toast_bar, text="", text_color=(ACCENT, "#d6e7f7"),
                                        font=ctk.CTkFont(size=13, weight="bold"))
        self.toast_label.grid(row=0, column=0, padx=16, pady=8)
        self.toast_open = ctk.CTkButton(self.toast_bar, text="Show in folder", width=110, height=28,
                                        fg_color=ACCENT, hover_color=ACCENT_HOVER)
        self._toast_job = None

        self.bind_all("<Control-s>", lambda _e: self.current.on_save_shortcut())
        if MAC:
            self.bind_all("<Command-s>", lambda _e: self.current.on_save_shortcut())
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.current = None
        if settings.get("name"):
            self.show("Time Log")
        else:  # first run
            self.show("Settings")
            self.after(300, lambda: self.toast("Welcome! Fill in your details, then click Save settings."))

    def show(self, name):
        if self.current is self.pages["Monthly Report"] and name != "Monthly Report":
            self.current._persist(*self.current._month())  # keep report edits when switching tabs
        for n, page in self.pages.items():
            page.grid_forget()
            self.nav[n].configure(fg_color="transparent")
        self.nav[name].configure(fg_color=("#13507f", "#22262a"))
        page = self.pages[name]
        page.grid(row=0, column=0, sticky="nsew")
        self.current = page
        page.on_show()

    def toast(self, message, path=None):
        self.toast_label.configure(text=message)
        if path:
            self.toast_open.configure(command=lambda: open_path(os.path.dirname(path)))
            self.toast_open.grid(row=0, column=1, padx=(0, 10))
        else:
            self.toast_open.grid_forget()
        self.toast_bar.grid(row=0, column=0, sticky="e")
        if self._toast_job:
            self.after_cancel(self._toast_job)
        self._toast_job = self.after(8000 if path else 3500, self.toast_bar.grid_forget)

    def output_path(self, subfolder, filename):
        """Path for a generated PDF: <Save PDFs to>/<subfolder>/<filename> ("reports" or "invoices")."""
        base = self.db.settings().get("output_dir") or os.path.expanduser("~")
        folder = os.path.join(base, subfolder)
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, filename)
        if os.path.exists(path):
            choice = messagebox.askyesnocancel(
                "File exists", f"{filename} already exists in\n{folder}\n\n"
                               "Yes = overwrite it\nNo = choose another name\nCancel = do nothing")
            if choice is None:
                return None
            if choice is False:
                path = filedialog.asksaveasfilename(initialdir=folder, initialfile=filename,
                                                    defaultextension=".pdf", filetypes=[("PDF", "*.pdf")])
                return path or None
        return path

    def _on_close(self):
        report = self.pages["Monthly Report"]
        if report.loaded:
            report._persist(*report.loaded)
        self.destroy()


if __name__ == "__main__":
    App().mainloop()
