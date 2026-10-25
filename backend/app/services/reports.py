"""Reports built from confirmed transactions: monthly summary and supplier dues."""
import re
import sqlite3


def previous_month(month: str) -> str:
    year, mon = int(month[:4]), int(month[5:])
    return f"{year - 1}-12" if mon == 1 else f"{year}-{mon - 1:02d}"


def monthly_summary(conn: sqlite3.Connection, month: str) -> dict:
    """Totals for a month (YYYY-MM), by type and category, compared with the month before."""
    if not re.fullmatch(r"\d{4}-\d{2}", month):
        raise ValueError("Use the month format YYYY-MM, e.g. 2024-03.")

    def totals_by(column: str, which: str) -> dict:
        rows = conn.execute(f"""SELECT {column} AS key, round(sum(total), 2) AS amount, count(*) AS bills
                                FROM transactions WHERE substr(bill_date, 1, 7) = ?
                                GROUP BY {column} ORDER BY amount DESC""", (which,))
        return {r["key"]: {"amount": r["amount"], "bills": r["bills"]} for r in rows}

    by_type = totals_by("transaction_type", month)
    before = totals_by("transaction_type", previous_month(month))
    change = {t: round(v["amount"] - before.get(t, {}).get("amount", 0), 2) for t, v in by_type.items()}
    top_vendors = conn.execute(
        """SELECT vendor_name, round(sum(total), 2) AS amount FROM transactions
           WHERE substr(bill_date, 1, 7) = ? AND transaction_type IN ('purchase', 'expense')
           GROUP BY vendor_name ORDER BY amount DESC LIMIT 5""", (month,))
    return {"month": month, "by_type": by_type, "by_category": totals_by("category", month),
            "change_from_previous_month": change, "previous_month": previous_month(month),
            "top_vendors": [{"vendor": r["vendor_name"], "amount": r["amount"]} for r in top_vendors]}


def supplier_dues(conn: sqlite3.Connection) -> list[dict]:
    """Unpaid balances on purchase bills, per supplier, largest first.

    Note: this sums the balance written on each bill. Recording later payments is a future feature.
    """
    rows = conn.execute(
        """SELECT vendor_name, round(sum(balance_due), 2) AS due, count(*) AS bills, min(bill_date) AS oldest
           FROM transactions WHERE transaction_type = 'purchase' AND balance_due > 0
           GROUP BY vendor_name ORDER BY due DESC""")
    return [{"vendor": r["vendor_name"], "amount_due": r["due"], "bills": r["bills"], "oldest_bill": r["oldest"]}
            for r in rows]
