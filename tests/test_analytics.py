"""Period aggregation (year / half-year / quarter / month) with hand-checkable numbers."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import pandas as pd, numpy as np
import analytics as A

def row(date, company, grade, ccy, tonnes, price, code):
    return dict(date=date, company_en=company, commodity="Coal", grade=grade, currency=ccy, quantity_t=tonnes,
                total_value=tonnes * price, lots=1, product_code=code, deal_price=price)

C = pd.DataFrame([
    row("2025-02-10", "A", "g1", "USD", 100, 50, "1"),
    row("2025-05-10", "A", "g1", "USD", 200, 60, "2"),
    row("2025-08-10", "B", "g1", "USD", 300, 70, "3"),
    row("2025-11-10", "B", "g2", "CNY", 400, 500, "4"),
    row("2026-01-05", "A", "g1", "USD", 100, 80, "5"),
    row("2026-08-20", "A", "g1", "USD", 200, 90, "6"),
    row("2026-09-11", "B", "g1", "USD", 100, 100, "7"),
])
AS_OF = "2026-09-11"

def get(agg, label, group="All"):
    r = agg[(agg.period == label) & (agg.group == group)]
    assert len(r) == 1, (label, group, agg)
    return r.iloc[0]

# ---- year
y_usd = A.sales_by_period(C, "Year", currency="USD", as_of=AS_OF)
r = get(y_usd, "2025"); assert (r.tonnes, r.value, r.contracts) == (600, 100*50 + 200*60 + 300*70, 3) and not r.partial
assert abs(r.avg_price - 38000/600) < 1e-9
r = get(y_usd, "2026"); assert r.partial and r.tonnes == 400
# CNY contract must not leak into USD figures, but tonnes over ALL currencies include it
y_all = A.sales_by_period(C, "Year", currency=None, as_of=AS_OF)
assert get(y_all, "2025").tonnes == 1000

# ---- half-year and quarter boundaries
h = A.sales_by_period(C, "Half-year", currency="USD", as_of=AS_OF)
assert list(h.period) == ["2025 H1", "2025 H2", "2026 H1", "2026 H2"], list(h.period)
assert get(h, "2025 H1").value == 5000 + 12000 and get(h, "2026 H2").partial and not get(h, "2026 H1").partial
q = A.sales_by_period(C, "Quarter", currency="USD", as_of=AS_OF)
assert list(q.period) == ["2025 Q1", "2025 Q2", "2025 Q3", "2026 Q1", "2026 Q3"]
r = get(q, "2026 Q3"); assert r.partial and r.tonnes == 300 and r.value == 200*90 + 100*100
# volume-weighted, NOT the simple mean of the two prices (95)
assert abs(r.avg_price - 28000/300) < 1e-9 and abs(r.avg_price - 95) > 1
assert not get(q, "2025 Q3").partial

# ---- month + splits
m = A.sales_by_period(C, "Month", currency="USD", as_of=AS_OF)
assert "2026-09" in set(m.period) and get(m, "2026-09").partial and not get(m, "2026-08").partial
s = A.sales_by_period(C, "Year", split="Company", currency="USD", as_of=AS_OF)
assert get(s, "2025", "A").value == 5000 + 12000 and get(s, "2025", "B").value == 21000
p = A.sales_by_period(C, "Year", split="Product", currency=None, as_of=AS_OF)
assert get(p, "2025", "g2").tonnes == 400

# ---- missing tonnage must not distort the weighted average
D = C.copy(); D.loc[D.product_code == "2", "quantity_t"] = np.nan
r = get(A.sales_by_period(D, "Year", currency="USD", as_of=AS_OF), "2025")
assert abs(r.avg_price - (5000 + 21000) / (100 + 300)) < 1e-9 and r.value == 38000

# ---- change vs previous period, empty input, bad period
ch = A.add_change(A.sales_by_period(C, "Year", currency="USD", as_of=AS_OF), "value")
assert abs(get(ch, "2026").change_pct - (100*80 + 200*90 + 100*100 - 38000) / 38000 * 100) < 1e-9
assert A.sales_by_period(pd.DataFrame(), "Year").empty
try: A.add_period(C["date"], "Decade"); raise SystemExit("should have failed")
except ValueError: pass
print("analytics tests passed")
