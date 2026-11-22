# WorkLog

A small desktop app for contractors who bill by the hour:

- **Time Log**: log the hours you worked each day (work and meetings) with a short description.
- **Monthly Report**: turn the month into a PDF report: total and meeting hours, the tasks you completed and
  what's planned for next month. Each task carries a coloured label (e.g. a project name). Two styles:
  *Modern* and *Classic*.
- **Invoice**: enter the hours, issue date and expiry date; WorkLog fills in an invoice PDF template with your
  details, the client's and the totals.

Everything stays on your computer in a local SQLite database. Runs on Linux and macOS.

## Install

You need **Python 3.9 or newer with Tk 8.6** (the GUI toolkit).

**macOS**

1. Install Python from [python.org/downloads](https://www.python.org/downloads/macos/). It includes a recent Tk.
   (Apple's built-in `/usr/bin/python3` ships Tk 8.5, which is too old. With Homebrew, install both
   `python` and `python-tk`.)
2. In Terminal:
   ```sh
   git clone https://github.com/mhmdk0/worklog.git
   cd worklog
   ./setup.sh
   ./install-launcher.sh      # adds WorkLog.app to ~/Applications
   ```
3. Open **WorkLog** from Launchpad. To keep it in the Dock: right-click its Dock icon → Options → Keep in Dock.

If `setup.sh` picks the wrong Python, point it at the right one, e.g.
`PYTHON=/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 ./setup.sh`.

**Linux (Ubuntu/Debian)**

```sh
sudo apt install python3-venv python3-tk
git clone https://github.com/mhmdk0/worklog.git
cd worklog
./setup.sh
./install-launcher.sh      # adds WorkLog to the app grid; pin it to the dock from there
```

**Without the launcher**, start it from the project folder with `./run.sh`. On macOS you can also
double-click `WorkLog.command` in Finder (it opens a Terminal window alongside the app).

If you move the folder, run `./install-launcher.sh` again.

## First run

WorkLog opens on **Settings**. Fill in your details, the client's (the "bill to" block on invoices), your
hourly rate and the next invoice number, then click **Save settings** (Ctrl+S, or ⌘S on macOS).

| Setting | Used for |
|---|---|
| Your details | report header and the "from" block of the invoice |
| Client | the "Customer Information" block of the invoice |
| Project, rate, currency, tax | the invoice line item and totals |
| Invoice note | the line under the INVOICE title (leave empty for none) |
| Line description | the text of the invoice line item |
| Organisation | the report title, e.g. "Acme Monthly Report" |
| Save PDFs to | reports go to its `reports/` folder, invoices to `invoices/` |
| Task labels | the labels you can put on report tasks (none at first: add your own, e.g. one per project or client) |

Files are named `name-doctype-month-year.pdf`, e.g. `Jane-Example-invoice-October-2026.pdf`.

## The invoice template

Invoices are made from [`templates/invoice-template.pdf`](templates/invoice-template.pdf). It's an ordinary PDF
in which every value that changes is a placeholder word. WorkLog removes each placeholder and writes the real
value in the same font, size and colour.

| Placeholder | Filled with |
|---|---|
| `inv_nb` | invoice number |
| `issue_dt`, `expiry_dt` | issue and expiry dates (YYYY/MM/DD) |
| `qty_hrs`, `unit_price`, `line_amt` | hours, hourly rate, hours × rate |
| `sub_total`, `tax_pct`, `total_amt` | totals |
| `from_name`, `from_addr1`, `from_addr2`, `from_phone`, `from_email` | your details |
| `to_org`, `to_contact`, `to_addr1`, `to_addr2`, `to_email` | the client's details |
| `inv_note` | Settings → Invoice note |
| `item_desc` | Settings → Line description (wraps inside its table cell) |
| `start_day`, `end_day`, `month_yr` | first and last day of the month, and e.g. `Oct-2026` |

**Invoice note and line description** are short rich-text strings:

- `**bold**` and `__underlined__` text;
- variables: `{project}`, `{start_day}`, `{end_day}`, `{month_yr}`, `{month}`, `{year}`, `{hours}`, and any
  setting such as `{name}` or `{client_org}`.

For example, the default line description

```
Hours of services for {project} between {start_day}**-{month_yr}** and {end_day}**-{month_yr}**
```

becomes "Hours of services for Website redesign between 1**-Oct-2026** and 31**-Oct-2026**", and the note
`Note: All the work was performed in __Portugal__` underlines the country.

Long values shrink to fit their cell. Email addresses are underlined.

**Using your own design.** Open the template in LibreOffice Draw (or make your own PDF), change whatever you
like, and keep the placeholder words intact: each placeholder must be a single word in the style you want.
Export it as PDF and choose it under Settings → Invoice template PDF. A field alone in its cell is
centred there (dates, amounts) or left-aligned (addresses); a field inside a sentence, like
`Invoice no. inv_nb`, has the rest of the line follow it. Use the Preview button to check the result.

## Your data

- Everything you enter lives in `data/worklog.db` inside this folder. It is in `.gitignore`, so it's never
  committed. Back it up like any other file.
- To keep the database somewhere else, start the app with `WORKLOG_DB=~/Documents/worklog.db ./run.sh`.

## Keyboard

| | Linux | macOS |
|---|---|---|
| Save the current page | Ctrl+S | ⌘S or Ctrl+S |
| New task below the current one | Enter | Return |
| Move a task up / down | Alt+↑ / Alt+↓ | Option+↑ / Option+↓ |
| Delete an empty task | Backspace | Delete |

Pasting several lines into a task list adds one task per line.

## Notes

- On macOS the menu bar shows "Python" rather than "WorkLog": the app runs on the Python you installed and
  isn't a signed, bundled application.
- Windows isn't packaged, but the app itself should run there:
  `py -m venv .venv`, `.venv\Scripts\pip install -r requirements.txt`, `.venv\Scripts\python app.py`.

## Project layout

| Path | What it is |
|---|---|
| `app.py` | the GUI (CustomTkinter) |
| `storage.py` | the SQLite database and default settings |
| `pdfgen.py` | the monthly report PDFs (ReportLab) |
| `invoice_template.py` | fills the invoice template (PyMuPDF) |
| `labels.py` | task labels and their colours |
| `fonts/` | Noto Sans and Liberation fonts, so PDFs look the same everywhere (SIL Open Font License, see `fonts/LICENSE-*.txt`) |
| `templates/invoice-template.pdf` | the invoice template |
