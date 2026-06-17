from __future__ import annotations

import csv
# Used to create the downloadable transaction CSV file.
import io
# Used like an in-memory text file while building the CSV.
import json
# Used to pass chart data from Python to JavaScript.
import sqlite3
# SQLite stores all expenses, budgets, and goals in one local database file.
from dataclasses import dataclass
# dataclass makes the Flash message class shorter and cleaner.
from datetime import date, datetime, timedelta
# date/datetime/timedelta help with today, month ranges, and goal deadlines.
from html import escape
# escape protects HTML output when user-entered text is displayed.
from http import HTTPStatus
# HTTPStatus gives readable names like OK, NOT_FOUND, and SEE_OTHER.
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
# These classes create a small web server without installing Flask or Django.
from pathlib import Path
# Path makes file and folder paths easier to manage.
from urllib.parse import parse_qs, urlparse
# These helpers read URLs and form/query parameters.


BASE_DIR = Path(__file__).resolve().parent
# BASE_DIR is the folder where app.py is located.
DATA_DIR = BASE_DIR / "data"
# DATA_DIR stores the SQLite database.
DB_PATH = DATA_DIR / "expenses.db"
# DB_PATH is the full path of the database file.
STATIC_DIR = BASE_DIR / "static"
# STATIC_DIR stores CSS and JavaScript files.

# Fixed dropdown values used by forms across the app.
CATEGORIES = [
    "Food",
    "Transport",
    "Shopping",
    "Bills",
    "Health",
    "Entertainment",
    "Education",
    "Travel",
    "Investment",
    "Salary",
    "Freelance",
    "Other",
]

PAYMENT_METHODS = ["Cash", "UPI", "Card", "Bank Transfer", "Wallet"]
# Payment method dropdown choices.
TRANSACTION_TYPES = ["expense", "income"]
# Transaction type dropdown choices.


@dataclass
class Flash:
    # Small message shown after saving/deleting records.
    kind: str
    message: str


def money(value: float) -> str:
    """Format numbers as Indian Rupee values for display."""
    sign = "-" if value < 0 else ""
    return f"{sign}Rs {abs(value):,.2f}"


def today_iso() -> str:
    """Return today's date in YYYY-MM-DD format for date inputs."""
    return date.today().isoformat()


def month_start() -> str:
    """Return the first day of the current month in YYYY-MM-DD format."""
    return date.today().replace(day=1).isoformat()


def connect() -> sqlite3.Connection:
    """Open the SQLite database and return rows like dictionaries."""
    DATA_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create tables and add demo data when the app is opened first time."""
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS transactions (
                -- Every income or expense record is stored here.
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tx_date TEXT NOT NULL,
                description TEXT NOT NULL,
                category TEXT NOT NULL,
                tx_type TEXT NOT NULL CHECK (tx_type IN ('expense', 'income')),
                amount REAL NOT NULL CHECK (amount >= 0),
                payment_method TEXT NOT NULL,
                notes TEXT DEFAULT '',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS budgets (
                -- One monthly budget limit is saved per category.
                category TEXT PRIMARY KEY,
                monthly_limit REAL NOT NULL CHECK (monthly_limit >= 0)
            );

            CREATE TABLE IF NOT EXISTS goals (
                -- Savings goals track progress toward a future target.
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                target_amount REAL NOT NULL,
                current_amount REAL NOT NULL DEFAULT 0,
                deadline TEXT NOT NULL
            );
            """
        )
        # If the database has no transactions, fill it with useful demo data.
        existing = conn.execute("SELECT COUNT(*) AS total FROM transactions").fetchone()["total"]
        if existing == 0:
            seed_data(conn)


def seed_data(conn: sqlite3.Connection) -> None:
    """Insert sample records so the dashboard and graphs are not empty."""
    today = date.today()
    # Sample data uses dates near today so the dashboard looks current.
    samples = [
        (today - timedelta(days=1), "Grocery run", "Food", "expense", 2450, "UPI"),
        (today - timedelta(days=2), "Metro card recharge", "Transport", "expense", 800, "Card"),
        (today - timedelta(days=3), "Freelance landing page", "Freelance", "income", 18000, "Bank Transfer"),
        (today - timedelta(days=5), "Electricity bill", "Bills", "expense", 3150, "UPI"),
        (today - timedelta(days=8), "Movie night", "Entertainment", "expense", 1200, "Card"),
        (today - timedelta(days=10), "Course subscription", "Education", "expense", 2600, "Card"),
        (today - timedelta(days=13), "Monthly salary", "Salary", "income", 72000, "Bank Transfer"),
        (today - timedelta(days=19), "Medicines", "Health", "expense", 950, "Cash"),
        (today - timedelta(days=24), "Mutual fund SIP", "Investment", "expense", 7000, "Bank Transfer"),
    ]
    conn.executemany(
        # executemany inserts many transactions with one SQL statement pattern.
        """
        INSERT INTO transactions
        (tx_date, description, category, tx_type, amount, payment_method, notes, created_at)
        VALUES (?, ?, ?, ?, ?, ?, '', ?)
        """,
        [(d.isoformat(), desc, cat, typ, amount, method, datetime.now().isoformat()) for d, desc, cat, typ, amount, method in samples],
    )
    conn.executemany(
        # Default budgets make the budget page useful immediately.
        "INSERT INTO budgets (category, monthly_limit) VALUES (?, ?)",
        [("Food", 10000), ("Transport", 3500), ("Bills", 9000), ("Entertainment", 5000), ("Shopping", 8000), ("Health", 4000)],
    )
    conn.execute(
        # One sample saving goal is added for the goals page.
        "INSERT INTO goals (title, target_amount, current_amount, deadline) VALUES (?, ?, ?, ?)",
        ("Emergency fund", 150000, 42000, (today + timedelta(days=180)).isoformat()),
    )


def rows(query: str, params: tuple = ()) -> list[sqlite3.Row]:
    """Run a SELECT query that returns many rows."""
    with connect() as conn:
        return conn.execute(query, params).fetchall()


def row(query: str, params: tuple = ()) -> sqlite3.Row | None:
    """Run a SELECT query that returns one row."""
    with connect() as conn:
        return conn.execute(query, params).fetchone()


def execute(query: str, params: tuple = ()) -> None:
    """Run an INSERT, UPDATE, or DELETE query."""
    with connect() as conn:
        conn.execute(query, params)


def redirect(handler: BaseHTTPRequestHandler, location: str, flash: Flash | None = None) -> None:
    """Redirect the browser after form submissions."""
    if flash:
        # Flash messages are passed through the URL after a redirect.
        separator = "&" if "?" in location else "?"
        location = f"{location}{separator}flash_kind={flash.kind}&flash={flash.message.replace(' ', '+')}"
    handler.send_response(HTTPStatus.SEE_OTHER)
    handler.send_header("Location", location)
    handler.end_headers()


def parse_body(handler: BaseHTTPRequestHandler) -> dict[str, str]:
    """Read form fields sent by a POST request."""
    length = int(handler.headers.get("Content-Length", "0"))
    # Read exactly the number of bytes sent by the browser form.
    body = handler.rfile.read(length).decode("utf-8")
    # parse_qs returns lists, so this converts each field to a single value.
    return {key: values[0] for key, values in parse_qs(body).items()}


def layout(title: str, active: str, content: str, query: dict[str, list[str]] | None = None) -> bytes:
    """Wrap each page's content with the common sidebar, CSS, and JS."""
    query = query or {}
    # Read optional success/error messages from the URL query string.
    flash_message = query.get("flash", [""])[0]
    flash_kind = query.get("flash_kind", ["success"])[0]
    nav_items = [
        # Each tuple is: page URL, menu label.
        ("/", "Dashboard"),
        ("/transactions", "Transactions"),
        ("/budgets", "Budgets"),
        ("/reports", "Reports"),
        ("/goals", "Goals"),
    ]
    nav = "".join(
        # Mark the current page link as active in the sidebar.
        f'<a class="nav-link {"active" if label == active else ""}" href="{href}">{label}</a>'
        for href, label in nav_items
    )
    flash_html = f'<div class="flash {escape(flash_kind)}">{escape(flash_message)}</div>' if flash_message else ""
    # The page shell is shared by all pages to keep design consistent.
    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)} | Expense Tracker Pro</title>
  <link rel="stylesheet" href="/static/css/styles.css">
</head>
<body>
  <aside class="sidebar">
    <a class="brand" href="/">
      <span class="brand-mark">ET</span>
      <span><strong>Expense Tracker</strong><small>Pro</small></span>
    </a>
    <nav>{nav}</nav>
    <a class="export-link" href="/export">Export CSV</a>
  </aside>
  <main class="page">
    {flash_html}
    {content}
  </main>
  <script src="/static/js/charts.js"></script>
</body>
</html>"""
    return html.encode("utf-8")


def dashboard(query: dict[str, list[str]]) -> bytes:
    """Build the dashboard page with summary cards and chart data."""
    start = query.get("start", [month_start()])[0]
    # Dashboard date filters default to current month.
    end = query.get("end", [today_iso()])[0]
    summary = row(
        # Calculate total income and total expense for selected dates.
        """
        SELECT
          COALESCE(SUM(CASE WHEN tx_type='income' THEN amount ELSE 0 END), 0) AS income,
          COALESCE(SUM(CASE WHEN tx_type='expense' THEN amount ELSE 0 END), 0) AS expense
        FROM transactions WHERE tx_date BETWEEN ? AND ?
        """,
        (start, end),
    )
    income = float(summary["income"])
    # Convert SQLite values to normal floats before calculations.
    expense = float(summary["expense"])
    balance = income - expense
    recent = rows("SELECT * FROM transactions ORDER BY tx_date DESC, id DESC LIMIT 7")
    # Recent activity table shows only latest seven records.
    trend = rows(
        # Group by date so the bar chart can show daily income vs expense.
        """
        SELECT tx_date,
          SUM(CASE WHEN tx_type='income' THEN amount ELSE 0 END) AS income,
          SUM(CASE WHEN tx_type='expense' THEN amount ELSE 0 END) AS expense
        FROM transactions
        WHERE tx_date BETWEEN ? AND ?
        GROUP BY tx_date
        ORDER BY tx_date
        """,
        (start, end),
    )
    categories = rows(
        # Group expense totals by category for the donut chart.
        """
        SELECT category, SUM(amount) AS total
        FROM transactions
        WHERE tx_type='expense' AND tx_date BETWEEN ? AND ?
        GROUP BY category ORDER BY total DESC
        """,
        (start, end),
    )
    tx_rows = "".join(transaction_row(tx) for tx in recent)
    # Convert database rows into the JSON shape expected by charts.js.
    # Chart data is placed inside canvas data attributes and drawn by charts.js.
    data = {
        "trend": [{"label": r["tx_date"][5:], "income": r["income"], "expense": r["expense"]} for r in trend],
        "categories": [{"label": r["category"], "value": r["total"]} for r in categories],
    }
    content = f"""
<section class="page-head">
  <div>
    <p class="eyebrow">Overview</p>
    <h1>Financial dashboard</h1>
  </div>
  <form class="filter-form" method="get" action="/">
    <input type="date" name="start" value="{escape(start)}">
    <input type="date" name="end" value="{escape(end)}">
    <button type="submit">Apply</button>
  </form>
</section>
<section class="metrics">
  <article><span>Total income</span><strong class="positive">{money(income)}</strong></article>
  <article><span>Total expense</span><strong class="negative">{money(expense)}</strong></article>
  <article><span>Net balance</span><strong class="{"positive" if balance >= 0 else "negative"}">{money(balance)}</strong></article>
  <article><span>Savings rate</span><strong>{(balance / income * 100 if income else 0):.1f}%</strong></article>
</section>
<section class="grid two">
  <article class="panel">
    <div class="panel-title"><h2>Income vs expense</h2></div>
    <canvas id="trendChart" data-chart='{escape(json.dumps(data["trend"]))}'></canvas>
  </article>
  <article class="panel">
    <div class="panel-title"><h2>Spending by category</h2></div>
    <canvas id="categoryChart" data-chart='{escape(json.dumps(data["categories"]))}'></canvas>
  </article>
</section>
<section class="panel">
  <div class="panel-title"><h2>Recent activity</h2><a href="/transactions">View all</a></div>
  <table>
    <thead><tr><th>Date</th><th>Description</th><th>Category</th><th>Method</th><th>Amount</th></tr></thead>
    <tbody>{tx_rows or '<tr><td colspan="5">No transactions yet.</td></tr>'}</tbody>
  </table>
</section>
"""
    return layout("Dashboard", "Dashboard", content, query)


def transaction_row(tx: sqlite3.Row, include_actions: bool = False) -> str:
    """Return one HTML table row for a transaction."""
    amount = money(tx["amount"])
    cls = "negative" if tx["tx_type"] == "expense" else "positive"
    actions = ""
    if include_actions:
        # Delete button is shown only on the full transactions page.
        actions = f"""
        <td class="actions">
          <form method="post" action="/delete-transaction">
            <input type="hidden" name="id" value="{tx["id"]}">
            <button class="icon danger" type="submit" title="Delete transaction">Delete</button>
          </form>
        </td>"""
    return f"""
<tr>
  <td>{escape(tx["tx_date"])}</td>
  <td><strong>{escape(tx["description"])}</strong><small>{escape(tx["notes"] or "")}</small></td>
  <td><span class="pill">{escape(tx["category"])}</span></td>
  <td>{escape(tx["payment_method"])}</td>
  <td class="{cls}">{amount}</td>
  {actions}
</tr>"""


def option_tags(options: list[str], selected: str = "") -> str:
    """Create reusable <option> tags for select dropdowns."""
    return "".join(
        f'<option value="{escape(item)}" {"selected" if item == selected else ""}>{escape(item.title())}</option>'
        for item in options
    )


def transactions(query: dict[str, list[str]]) -> bytes:
    """Build transaction add/search/filter page."""
    search = query.get("search", [""])[0].strip()
    # Read all optional filters from the URL query string.
    category = query.get("category", [""])[0]
    tx_type = query.get("tx_type", [""])[0]
    start = query.get("start", [""])[0]
    end = query.get("end", [""])[0]
    clauses = []
    # clauses stores SQL filter pieces; params stores safe values for ? marks.
    params: list[str] = []
    if search:
        # Search checks both description and notes.
        clauses.append("(description LIKE ? OR notes LIKE ?)")
        params.extend([f"%{search}%", f"%{search}%"])
    if category:
        # Add category filter only when user selected one.
        clauses.append("category = ?")
        params.append(category)
    if tx_type:
        # Add income/expense filter only when selected.
        clauses.append("tx_type = ?")
        params.append(tx_type)
    if start:
        # Start date filter means records on or after this date.
        clauses.append("tx_date >= ?")
        params.append(start)
    if end:
        # End date filter means records on or before this date.
        clauses.append("tx_date <= ?")
        params.append(end)
    # Filters are added only when the user fills them, keeping the query flexible.
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    txs = rows(f"SELECT * FROM transactions {where} ORDER BY tx_date DESC, id DESC", tuple(params))
    # Build the visible table after filters are applied.
    tx_table = "".join(transaction_row(tx, include_actions=True) for tx in txs)
    content = f"""
<section class="page-head">
  <div><p class="eyebrow">Ledger</p><h1>Transactions</h1></div>
</section>
<section class="grid form-grid">
  <article class="panel">
    <h2>Add transaction</h2>
    <form class="stack-form" method="post" action="/add-transaction">
      <label>Date<input required type="date" name="tx_date" value="{today_iso()}"></label>
      <label>Description<input required name="description" placeholder="e.g. Office lunch"></label>
      <div class="inline-fields">
        <label>Type<select name="tx_type">{option_tags(TRANSACTION_TYPES)}</select></label>
        <label>Amount<input required type="number" min="0" step="0.01" name="amount" placeholder="0.00"></label>
      </div>
      <div class="inline-fields">
        <label>Category<select name="category">{option_tags(CATEGORIES)}</select></label>
        <label>Method<select name="payment_method">{option_tags(PAYMENT_METHODS)}</select></label>
      </div>
      <label>Notes<textarea name="notes" rows="3" placeholder="Optional details"></textarea></label>
      <button type="submit">Save transaction</button>
    </form>
  </article>
  <article class="panel">
    <h2>Search and filters</h2>
    <form class="stack-form" method="get" action="/transactions">
      <label>Search<input name="search" value="{escape(search)}" placeholder="description or notes"></label>
      <div class="inline-fields">
        <label>Category<select name="category"><option value="">All</option>{option_tags(CATEGORIES, category)}</select></label>
        <label>Type<select name="tx_type"><option value="">All</option>{option_tags(TRANSACTION_TYPES, tx_type)}</select></label>
      </div>
      <div class="inline-fields">
        <label>From<input type="date" name="start" value="{escape(start)}"></label>
        <label>To<input type="date" name="end" value="{escape(end)}"></label>
      </div>
      <button type="submit">Filter list</button>
    </form>
  </article>
</section>
<section class="panel">
  <div class="panel-title"><h2>All transactions</h2><span>{len(txs)} records</span></div>
  <table>
    <thead><tr><th>Date</th><th>Description</th><th>Category</th><th>Method</th><th>Amount</th><th></th></tr></thead>
    <tbody>{tx_table or '<tr><td colspan="6">No transactions match your filters.</td></tr>'}</tbody>
  </table>
</section>
"""
    return layout("Transactions", "Transactions", content, query)


def budgets(query: dict[str, list[str]]) -> bytes:
    """Build budget page and compare monthly limits with actual spending."""
    month = query.get("month", [date.today().strftime("%Y-%m")])[0]
    # Month input gives YYYY-MM; convert it to first and last date of month.
    start = f"{month}-01"
    y, m = map(int, month.split("-"))
    next_month = date(y + (m == 12), 1 if m == 12 else m + 1, 1)
    # Last day of selected month is one day before next month starts.
    end = (next_month - timedelta(days=1)).isoformat()
    data = rows(
        # LEFT JOIN keeps budgets visible even if no spending happened yet.
        """
        SELECT b.category, b.monthly_limit, COALESCE(SUM(t.amount), 0) AS spent
        FROM budgets b
        LEFT JOIN transactions t
          ON t.category = b.category AND t.tx_type='expense' AND t.tx_date BETWEEN ? AND ?
        GROUP BY b.category, b.monthly_limit
        ORDER BY spent DESC
        """,
        (start, end),
    )
    cards = ""
    for item in data:
        # For each budget, calculate how much of the limit is already used.
        limit = item["monthly_limit"]
        spent = item["spent"]
        pct = min((spent / limit * 100) if limit else 0, 100)
        # cap percentage at 100 so progress bars do not overflow.
        cards += f"""
<article class="budget-card">
  <div><strong>{escape(item["category"])}</strong><span>{money(spent)} / {money(limit)}</span></div>
  <div class="progress"><i style="width:{pct:.1f}%"></i></div>
  <small>{pct:.1f}% used</small>
</article>"""
    budget_rows = "".join(
        f"""
<tr>
  <td>{escape(item["category"])}</td>
  <td>{money(item["monthly_limit"])}</td>
  <td>{money(item["spent"])}</td>
  <td>{money(item["monthly_limit"] - item["spent"])}</td>
</tr>"""
        for item in data
    )
    content = f"""
<section class="page-head">
  <div><p class="eyebrow">Planning</p><h1>Budgets</h1></div>
  <form class="filter-form" method="get" action="/budgets">
    <input type="month" name="month" value="{escape(month)}">
    <button type="submit">View</button>
  </form>
</section>
<section class="grid form-grid">
  <article class="panel">
    <h2>Create or update budget</h2>
    <form class="stack-form" method="post" action="/save-budget">
      <label>Category<select name="category">{option_tags(CATEGORIES)}</select></label>
      <label>Monthly limit<input required type="number" min="0" step="0.01" name="monthly_limit" placeholder="10000"></label>
      <button type="submit">Save budget</button>
    </form>
  </article>
  <article class="panel">
    <h2>Budget health</h2>
    <div class="budget-list">{cards or '<p>No budgets configured yet.</p>'}</div>
  </article>
</section>
<section class="panel">
  <div class="panel-title"><h2>Budget table</h2></div>
  <table><thead><tr><th>Category</th><th>Limit</th><th>Spent</th><th>Remaining</th></tr></thead><tbody>{budget_rows or '<tr><td colspan="4">No budgets yet.</td></tr>'}</tbody></table>
</section>
"""
    return layout("Budgets", "Budgets", content, query)


def reports(query: dict[str, list[str]]) -> bytes:
    """Build reports page with yearly charts and top expenses."""
    year = int(query.get("year", [str(date.today().year)])[0])
    # Reports can be changed to any year using the year input.
    monthly = rows(
        # Monthly cash flow groups income and expense by YYYY-MM.
        """
        SELECT substr(tx_date, 1, 7) AS month,
          SUM(CASE WHEN tx_type='income' THEN amount ELSE 0 END) AS income,
          SUM(CASE WHEN tx_type='expense' THEN amount ELSE 0 END) AS expense
        FROM transactions
        WHERE substr(tx_date, 1, 4)=?
        GROUP BY substr(tx_date, 1, 7)
        ORDER BY month
        """,
        (str(year),),
    )
    method = rows(
        # Payment method chart shows how expenses were paid.
        """
        SELECT payment_method AS label, SUM(amount) AS value
        FROM transactions
        WHERE tx_type='expense' AND substr(tx_date, 1, 4)=?
        GROUP BY payment_method ORDER BY value DESC
        """,
        (str(year),),
    )
    top = rows(
        # Top expenses table helps identify the largest spending items.
        """
        SELECT description, category, amount, tx_date
        FROM transactions
        WHERE tx_type='expense' AND substr(tx_date, 1, 4)=?
        ORDER BY amount DESC LIMIT 8
        """,
        (str(year),),
    )
    data = {
        "monthly": [{"label": r["month"], "income": r["income"], "expense": r["expense"]} for r in monthly],
        "method": [{"label": r["label"], "value": r["value"]} for r in method],
    }
    top_rows = "".join(
        f"<tr><td>{escape(r['tx_date'])}</td><td>{escape(r['description'])}</td><td>{escape(r['category'])}</td><td class='negative'>{money(r['amount'])}</td></tr>"
        for r in top
    )
    content = f"""
<section class="page-head">
  <div><p class="eyebrow">Analytics</p><h1>Reports</h1></div>
  <form class="filter-form" method="get" action="/reports">
    <input type="number" name="year" min="2000" max="2100" value="{year}">
    <button type="submit">Analyze</button>
  </form>
</section>
<section class="grid two">
  <article class="panel">
    <div class="panel-title"><h2>Monthly cash flow</h2></div>
    <canvas id="monthlyChart" data-chart='{escape(json.dumps(data["monthly"]))}'></canvas>
  </article>
  <article class="panel">
    <div class="panel-title"><h2>Payment method mix</h2></div>
    <canvas id="methodChart" data-chart='{escape(json.dumps(data["method"]))}'></canvas>
  </article>
</section>
<section class="panel">
  <div class="panel-title"><h2>Top expenses</h2></div>
  <table><thead><tr><th>Date</th><th>Description</th><th>Category</th><th>Amount</th></tr></thead><tbody>{top_rows or '<tr><td colspan="4">No expenses found.</td></tr>'}</tbody></table>
</section>
"""
    return layout("Reports", "Reports", content, query)


def goals(query: dict[str, list[str]]) -> bytes:
    """Build savings goals page and show progress bars."""
    goal_rows = rows("SELECT * FROM goals ORDER BY deadline ASC")
    # Goals closest to deadline are displayed first.
    cards = ""
    for g in goal_rows:
        # Calculate goal completion percentage and days left.
        pct = min((g["current_amount"] / g["target_amount"] * 100) if g["target_amount"] else 0, 100)
        days = (datetime.strptime(g["deadline"], "%Y-%m-%d").date() - date.today()).days
        cards += f"""
<article class="goal-card">
  <div>
    <strong>{escape(g["title"])}</strong>
    <span>{money(g["current_amount"])} / {money(g["target_amount"])}</span>
  </div>
  <div class="progress"><i style="width:{pct:.1f}%"></i></div>
  <small>{pct:.1f}% funded · {days} days left</small>
  <form method="post" action="/delete-goal"><input type="hidden" name="id" value="{g["id"]}"><button class="link-button danger" type="submit">Delete</button></form>
</article>"""
    content = f"""
<section class="page-head">
  <div><p class="eyebrow">Future money</p><h1>Savings goals</h1></div>
</section>
<section class="grid form-grid">
  <article class="panel">
    <h2>Add goal</h2>
    <form class="stack-form" method="post" action="/add-goal">
      <label>Goal name<input required name="title" placeholder="New laptop"></label>
      <div class="inline-fields">
        <label>Target<input required type="number" min="1" step="0.01" name="target_amount"></label>
        <label>Saved<input required type="number" min="0" step="0.01" name="current_amount" value="0"></label>
      </div>
      <label>Deadline<input required type="date" name="deadline" value="{(date.today() + timedelta(days=90)).isoformat()}"></label>
      <button type="submit">Save goal</button>
    </form>
  </article>
  <article class="panel">
    <h2>Goal progress</h2>
    <div class="goal-list">{cards or '<p>No goals yet.</p>'}</div>
  </article>
</section>
"""
    return layout("Goals", "Goals", content, query)


def export_csv(handler: BaseHTTPRequestHandler) -> None:
    """Download all transactions as a CSV file."""
    txs = rows("SELECT tx_date, description, category, tx_type, amount, payment_method, notes FROM transactions ORDER BY tx_date DESC")
    # StringIO lets csv.writer create CSV text in memory.
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["date", "description", "category", "type", "amount", "payment_method", "notes"])
    # Write one CSV row for each transaction.
    writer.writerows([list(tx) for tx in txs])
    data = output.getvalue().encode("utf-8")
    handler.send_response(HTTPStatus.OK)
    handler.send_header("Content-Type", "text/csv; charset=utf-8")
    handler.send_header("Content-Disposition", "attachment; filename=expense-tracker-export.csv")
    # Content-Disposition tells the browser to download the file.
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


class ExpenseHandler(BaseHTTPRequestHandler):
    """Main web server handler: maps URLs to pages and form actions."""

    def do_GET(self) -> None:
        # GET requests display pages, static files, or CSV downloads.
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        routes = {
            # Map each URL path to the function that builds that page.
            "/": dashboard,
            "/transactions": transactions,
            "/budgets": budgets,
            "/reports": reports,
            "/goals": goals,
        }
        if parsed.path.startswith("/static/"):
            # CSS and JS files are served from the static folder.
            self.serve_static(parsed.path)
            return
        if parsed.path == "/export":
            # Export route downloads CSV instead of showing an HTML page.
            export_csv(self)
            return
        if parsed.path in routes:
            # Normal page route: build HTML and send it.
            self.send_html(routes[parsed.path](query))
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        # POST requests receive form data and update the database.
        parsed = urlparse(self.path)
        form = parse_body(self)
        try:
            if parsed.path == "/add-transaction":
                # Save a new income or expense from the transaction form.
                execute(
                    """
                    INSERT INTO transactions
                    (tx_date, description, category, tx_type, amount, payment_method, notes, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        form["tx_date"],
                        form["description"].strip(),
                        form["category"],
                        form["tx_type"],
                        float(form["amount"]),
                        form["payment_method"],
                        form.get("notes", "").strip(),
                        datetime.now().isoformat(),
                    ),
                )
                redirect(self, "/transactions", Flash("success", "Transaction saved"))
            elif parsed.path == "/delete-transaction":
                # Delete one transaction using its hidden id field.
                execute("DELETE FROM transactions WHERE id=?", (form["id"],))
                redirect(self, "/transactions", Flash("success", "Transaction deleted"))
            elif parsed.path == "/save-budget":
                # Insert a new budget or update the existing category budget.
                execute(
                    """
                    INSERT INTO budgets (category, monthly_limit)
                    VALUES (?, ?)
                    ON CONFLICT(category) DO UPDATE SET monthly_limit=excluded.monthly_limit
                    """,
                    (form["category"], float(form["monthly_limit"])),
                )
                redirect(self, "/budgets", Flash("success", "Budget saved"))
            elif parsed.path == "/add-goal":
                # Save a new savings goal.
                execute(
                    "INSERT INTO goals (title, target_amount, current_amount, deadline) VALUES (?, ?, ?, ?)",
                    (form["title"].strip(), float(form["target_amount"]), float(form["current_amount"]), form["deadline"]),
                )
                redirect(self, "/goals", Flash("success", "Goal saved"))
            elif parsed.path == "/delete-goal":
                # Delete one savings goal using its hidden id field.
                execute("DELETE FROM goals WHERE id=?", (form["id"],))
                redirect(self, "/goals", Flash("success", "Goal deleted"))
            else:
                self.send_error(HTTPStatus.NOT_FOUND)
        except (KeyError, ValueError, sqlite3.Error) as exc:
            # If form data is missing or invalid, show an error message.
            redirect(self, parsed.path, Flash("danger", f"Could not save: {exc}"))

    def send_html(self, body: bytes) -> None:
        """Send an HTML response back to the browser."""
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def serve_static(self, url_path: str) -> None:
        """Serve local CSS and JavaScript files from the static folder."""
        relative = url_path.replace("/static/", "", 1)
        # Resolve the requested static file path safely.
        target = (STATIC_DIR / relative).resolve()
        if STATIC_DIR.resolve() not in target.parents:
            # Prevent users from requesting files outside the static folder.
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        if not target.exists():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content_type = "text/css" if target.suffix == ".css" else "application/javascript"
        # Read the CSS/JS file and send it to the browser.
        data = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt: str, *args: object) -> None:
        # Keep normal server logs visible in the terminal.
        print(f"[{self.log_date_time_string()}] {fmt % args}")


def main() -> None:
    """Start the local web app."""
    init_db()
    # The app runs only on this computer, not on the public internet.
    host = "127.0.0.1"
    port = 8000
    # ThreadingHTTPServer can handle multiple browser requests at once.
    server = ThreadingHTTPServer((host, port), ExpenseHandler)
    print(f"Expense Tracker Pro running at http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
