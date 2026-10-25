from datetime import date
from backend.app.extraction.dates import parse_bill_date, financial_year_start, check_date

def test_parse_day_first():
    assert parse_bill_date("1/3/2024") == date(2024, 3, 1)
    assert parse_bill_date("28/3/24") == date(2024, 3, 28)

def test_parse_invalid():
    assert parse_bill_date("13/25/24") is None
    assert parse_bill_date(None) is None

def test_financial_year():
    assert financial_year_start("4283/23-24") == 2023
    assert financial_year_start("1338") is None

def test_check_date():
    assert check_date(date(2024, 3, 1), 2023) == []
    assert check_date(date(2024, 4, 1), 2023) == ["date is outside financial year 2023-24"]