import re
from datetime import date

Date_re=re.compile(r"(\d{1,2})\s*[/.\-]\s*(\d{1,2})\s*[/.\-]\s*(\d{2,4})")

def parse_bill_date(text:str | None)->date |None:
    """Read an Indian day-first date like '1/3/2024' or '28-3-24'."""
    if not text:
        return None
    m=Date_re.search(text)
    if not m:
        return None
    day,month,year=(int(g) for g in m.groups())
    if year<100:
        year += 2000
    try:
        return date(year,month,day)
    except ValueError:
        return None

fy_re=re.compile(r"(?<!\d)(?:20)?(\d{2})\s*[-/]\s*(\d{2})(?!\d)")

def financial_year_start(bill_number:str | None)-> int |None:
    """'4283/23-24' -> 2023. None if no financial year is found."""
    if not bill_number:
        return None
    for m in fy_re.finditer(bill_number):
        first,second=int(m.group(1)),int(m.group(2))
        if second==(first+1)%100:
            return 2000+first
    return None

def check_date(bill_date:date|None,fy_start:int|None,today:date|None=None)->list[str]:
    """Return a list of problems. An empty list means the date looks fine."""
    if bill_date is None:
        return []
    today=today or date.today()
    problems=[]
    if bill_date>today:
        problems.append("date is in the future")
    if fy_start and not (date(fy_start, 4, 1) <= bill_date <= date(fy_start + 1, 3, 31)):
        problems.append(f"date is outside financial year {fy_start}-{(fy_start + 1) % 100:02d}")
    return problems