import re
from datetime import date
DATE_RE = re.compile(r"(\d{1,2})\s*[/.\-]\s*(\d{1,2})\s*[/.\-]\s*(\d{2,4})")
FY_RE = re.compile(r"(?<!\d)(?:20)?(\d{2})\s*[-/]\s*(\d{2})(?!\d)")
def parse_bill_date(text):
    if not text: return None
    m = DATE_RE.search(text)
    if not m: return None
    day, month, year = (int(g) for g in m.groups())
    if year < 100: year += 2000
    try: return date(year, month, day)
    except ValueError: return None
def financial_year_start(bill_number):
    if not bill_number: return None
    for m in FY_RE.finditer(bill_number):
        first, second = int(m.group(1)), int(m.group(2))
        if second == (first + 1) % 100: return 2000 + first
    return None
def check_date(bill_date, fy_start, today=None):
    if bill_date is None: return ["date missing or unreadable"]
    today = today or date.today(); problems = []
    if bill_date > today: problems.append("date is in the future")
    if fy_start and not (date(fy_start, 4, 1) <= bill_date <= date(fy_start + 1, 3, 31)):
        problems.append(f"date is outside financial year {fy_start}-{(fy_start + 1) % 100:02d}")
    return problems
