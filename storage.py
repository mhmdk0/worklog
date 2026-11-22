"""SQLite-backed storage for time entries, report drafts, invoices and settings."""

import calendar
import json
import os
import sqlite3
from datetime import datetime

import labels as task_labels

DEFAULT_SETTINGS = {
    # Your details (used on reports and invoices)
    "name": "",
    "email": "",
    "address1": "",
    "address2": "",
    "phone": "",
    # Client (bill to)
    "client_org": "",
    "client_contact": "",
    "client_address1": "",
    "client_address2": "",
    "client_email": "",
    # Invoice
    "project": "",
    "rate": "",
    "currency": "$",
    "tax": "0",
    "next_invoice_number": "1",
    # Rich text on the invoice: **bold**, __underline__ and {project}, {start_day}, {end_day}, {month_yr}, ...
    "invoice_note": "",
    "invoice_description": "Hours of services for {project} between {start_day}**-{month_yr}** "
                           "and {end_day}**-{month_yr}**",
    # Reports & files
    "org_name": "",
    "monthly_target": "160",
    "report_style": "Modern",
    "default_meetings": "Meetings with the team for syncing changes/adding new tasks.",
    "output_dir": os.path.join(os.path.expanduser("~"), "Documents", "WorkLog"),
    "invoice_template": "",  # empty = the built-in templates/invoice-template.pdf
    "appearance": "System",
    # Task labels: JSON list of {"name", "color"}
    "labels": "[]",
}


def month_key(year, month):
    return f"{year:04d}-{month:02d}"


class Storage:
    def __init__(self, path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS entries (
                date TEXT PRIMARY KEY,          -- YYYY-MM-DD
                work_hours REAL NOT NULL DEFAULT 0,
                meeting_hours REAL NOT NULL DEFAULT 0,
                description TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS reports (
                month TEXT PRIMARY KEY,         -- YYYY-MM
                data TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS invoices (
                number INTEGER PRIMARY KEY,
                month TEXT NOT NULL,
                hours REAL NOT NULL,
                rate REAL NOT NULL,
                tax REAL NOT NULL,
                total REAL NOT NULL,
                issue_date TEXT NOT NULL,
                expiry_date TEXT NOT NULL,
                file TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            """
        )
        self.conn.commit()

    @staticmethod
    def _now():
        return datetime.now().isoformat(timespec="seconds")

    # ---------------------------------------------------------------- settings
    def settings(self):
        result = dict(DEFAULT_SETTINGS)
        for row in self.conn.execute("SELECT key, value FROM settings"):
            result[row["key"]] = row["value"]
        return result

    def save_settings(self, values):
        self.conn.executemany(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            [(k, str(v)) for k, v in values.items()],
        )
        self.conn.commit()

    def labels(self):
        return task_labels.parse(self.settings().get("labels"))

    def save_labels(self, labels):
        self.save_settings({"labels": task_labels.dumps(labels)})

    # ----------------------------------------------------------------- entries
    def get_entry(self, date_str):
        row = self.conn.execute("SELECT * FROM entries WHERE date = ?", (date_str,)).fetchone()
        return dict(row) if row else None

    def save_entry(self, date_str, work_hours, meeting_hours, description):
        self.conn.execute(
            "INSERT OR REPLACE INTO entries (date, work_hours, meeting_hours, description, updated_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (date_str, work_hours, meeting_hours, description, self._now()),
        )
        self.conn.commit()

    def delete_entry(self, date_str):
        self.conn.execute("DELETE FROM entries WHERE date = ?", (date_str,))
        self.conn.commit()

    def month_entries(self, year, month):
        rows = self.conn.execute(
            "SELECT * FROM entries WHERE date LIKE ? ORDER BY date", (month_key(year, month) + "-%",)
        )
        return [dict(r) for r in rows]

    def month_totals(self, year, month):
        """Return (work_hours, meeting_hours, days_logged) for a month."""
        row = self.conn.execute(
            "SELECT COALESCE(SUM(work_hours), 0), COALESCE(SUM(meeting_hours), 0), COUNT(*)"
            " FROM entries WHERE date LIKE ?",
            (month_key(year, month) + "-%",),
        ).fetchone()
        return row[0], row[1], row[2]

    # ----------------------------------------------------------------- reports
    def get_report(self, year, month):
        row = self.conn.execute("SELECT data FROM reports WHERE month = ?", (month_key(year, month),)).fetchone()
        return json.loads(row["data"]) if row else None

    def save_report(self, year, month, data):
        self.conn.execute(
            "INSERT OR REPLACE INTO reports (month, data, updated_at) VALUES (?, ?, ?)",
            (month_key(year, month), json.dumps(data), self._now()),
        )
        self.conn.commit()

    # ---------------------------------------------------------------- invoices
    def invoice_for_month(self, year, month):
        row = self.conn.execute(
            "SELECT * FROM invoices WHERE month = ? ORDER BY number DESC LIMIT 1", (month_key(year, month),)
        ).fetchone()
        return dict(row) if row else None

    def invoices(self):
        return [dict(r) for r in self.conn.execute("SELECT * FROM invoices ORDER BY number DESC")]

    def save_invoice(self, rec):
        self.conn.execute(
            "INSERT OR REPLACE INTO invoices"
            " (number, month, hours, rate, tax, total, issue_date, expiry_date, file, created_at)"
            " VALUES (:number, :month, :hours, :rate, :tax, :total, :issue_date, :expiry_date, :file, :created_at)",
            {**rec, "created_at": self._now()},
        )
        # Keep the auto-numbering ahead of anything already issued.
        if rec["number"] + 1 > self.next_invoice_number():
            self.save_settings({"next_invoice_number": rec["number"] + 1})
        self.conn.commit()

    def next_invoice_number(self):
        configured = int(self.settings().get("next_invoice_number") or 1)
        row = self.conn.execute("SELECT MAX(number) FROM invoices").fetchone()
        issued = (row[0] or 0) + 1
        return max(configured, issued)


def last_day(year, month):
    return calendar.monthrange(year, month)[1]
