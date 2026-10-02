"""Update logic: incremental crawl, notices accumulation, daily-report (contracts) fetching."""
import sys, pathlib, tempfile
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import scraper
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from test_parsers import trade

def page(ids, last=3):
    body = "".join(trade(f"2026.09.{20-i%10:02d} 10:00", i, "Энержи Ресурс ХХК", "Нүүрс", "Баяжуулсан коксжих нүүрс",
                        ["1,150.00 CNY", "$1,200.00 CNY", "+50.00 (+4.35%)"]) for i in ids)
    nav = "".join(f'<a href="https://comex.mse.mn/show-trades?page={p}">{p}</a>' for p in range(2, last + 1))
    return f"<html><body>{body}{nav}</body></html>"

tmp = pathlib.Path(tempfile.mkdtemp())
scraper.DATA_DIR, scraper.TRADES_CSV, scraper.NOTICES_CSV = tmp, tmp/"trades.csv", tmp/"notices.csv"
scraper.REQUEST_DELAY = 0

SITE = {1: range(30, 25, -1), 2: range(25, 20, -1), 3: range(20, 15, -1)}
calls = []
def fake_fetch(session, url, retries=3):
    p = int(url.split("page=")[1]) if "page=" in url else 1
    calls.append(p); return page(SITE[p])
scraper.fetch = fake_fetch
from unittest.mock import Mock
scraper.make_session = lambda: Mock(spec=["close"])

n = scraper.update_trades(full=True, log=lambda *_: None)
assert n == 15 and calls == [1, 2, 3], (n, calls)
assert len(scraper.load_trades()) == 15

# new trades appear on page 1 (ids 33..31) and everything shifts down
SITE = {1: range(33, 28, -1), 2: range(28, 23, -1), 3: range(23, 18, -1)}
calls.clear()
n = scraper.update_trades(full=False, log=lambda *_: None)
df = scraper.load_trades()
assert n == 3 + 0 or n >= 3, n
assert set(range(31, 34)) <= set(df.trade_id) and df.trade_id.is_unique
assert calls[:2] == [1, 2], calls          # always re-reads pages 1-2
print("incremental OK: new =", n, "| pages fetched:", calls, "| rows:", len(df))

# nothing new -> stops after page 2
calls.clear(); n = scraper.update_trades(full=False, log=lambda *_: None)
assert n == 0 and calls == [1, 2], (n, calls)
print("no-change run OK: pages fetched:", calls)

# --- old CSV that had the two Tavan Tolgoi companies merged gets fixed on load ---
import pandas as pd
old = pd.DataFrame([{"trade_id": 1, "trade_time": "2026-07-22 10:00", "date": "2026-07-22",
                     "company": "Эрдэнэс Тавантолгой ХК", "company_en": "Erdenes Tavan Tolgoi", "company_raw": "Тавантолгой ХК",
                     "grade_mn": "1/3 коксжих нүүрс", "grade": "1/3 coking coal"},
                    {"trade_id": 2, "trade_time": "2026-07-22 11:00", "date": "2026-07-22",
                     "company": "Эрдэнэс Тавантолгой ХК", "company_en": "Erdenes Tavan Tolgoi", "company_raw": "Эрдэнэс Тавантолгой ХК",
                     "grade_mn": "1/3 коксжих нүүрс", "grade": "1/3 coking coal"}])
old.to_csv(scraper.TRADES_CSV, index=False)
fixed = scraper.load_trades().set_index("trade_id")
assert fixed.loc[1, "company_en"] == "Tavan Tolgoi JSC" and fixed.loc[2, "company_en"] == "Erdenes Tavan Tolgoi"
print("legacy CSV re-normalised OK")

from test_parsers import TRADES_HTML, NOTICE_HTML

# Older pages put a closing slash before the quantity unit and repeat the time.
from notice_fixture import notice_page
for quantity_text in ("4 багц /25,600/ тонн 14:00", "4 Багц/25,600тн/", "4 багц /25,600 тонн/"):
    html = notice_page(code="ER-24165", date="2024-06-26").replace("2 Багц/12800тн/", quantity_text)
    parsed = scraper.parse_notice_archive(html)
    assert len(parsed) == 1 and parsed[0]["lots"] == 4 and parsed[0]["quantity_t"] == 25600
print("legacy notice quantity formats OK")

for text, quantity, lots in [
    ("4 багц 25,600 тонн 14:00", 25600, 4),
    ("4 lots /25,600 tons/ 14:00", 25600, 4),
    ("265 багц /1.696.000 тонн/", 1696000, 265),
    ("2 багц /12.800 тонн/", 12800, 2),
    ("8 багц /51’200 тонн/", 51200, 8),
    ("2 批量/6800 吨/14:00", 6800, 2),
]:
    h = notice_page().replace("2 Багц/12800тн/", text).replace("1,150¥", "$72")
    r = scraper.parse_notice_archive(h)[0]
    assert (r["quantity_t"], r["lots"], r["start_price"], r["currency"]) == (quantity, lots, 72, "USD"), r
h = notice_page().replace("2 Багц/12800тн/", "3,000 НМТ /нойтон метр тонн/ 2,718 ХМТ /хуурай метр тонн/")
h = h.replace("1,150¥", "2,267.43 ам.дол/ХМТ")
r = scraper.parse_notice_archive(h)[0]
assert r["lots"] is None and r["quantity_wet_t"] == 3000 and r["quantity_dry_t"] == 2718
assert r["start_price"] == 2267.43 and r["currency"] == "USD" and r["price_unit"] == "ХМТ"
h = notice_page(code="0").replace("2026-09-18 10:00:00", "2026-09-18 00:00:00").replace("2 Багц/12800тн/", "2 Багц/12800тн/ 14:00")
r = scraper.parse_notice_archive(h)[0]
assert r["code"].startswith("archive-") and r["time"] == "14:00"
assert scraper.parse_notice_archive(h.replace("mn-0.pdf", "mn-another.pdf"))[0]["code"] != r["code"]
print("historical numbers, languages, currency, wet/dry tonnes and missing codes OK")

# --- archive pagination, accumulation, amendments and failure preservation ---
from notice_fixture import notice_page
from urllib.parse import urlparse, parse_qs
archive_calls = []
archive_pages = {
    1: notice_page(last=3),
    2: notice_page(code="ECM-26-140", page=2, last=3),
    3: notice_page(code="ERD-10-2026", page=3, last=3),
}
def fake_fetch2(session, url, retries=3):
    assert urlparse(url).path == "/show-notices", url
    p = int(parse_qs(urlparse(url).query).get("page", ["1"])[0])
    archive_calls.append(p)
    return archive_pages[p]
scraper.fetch = fake_fetch2
if scraper.NOTICES_CSV.exists(): scraper.NOTICES_CSV.unlink()
assert scraper.update_notices(log=lambda *_: None) == 3
assert archive_calls == [1, 2, 3], archive_calls
assert len(scraper.load_notices()) == 3
r = scraper.load_notices().set_index("code").loc["ER-26183"]
assert r["currency"] == "CNY" and r["start_price"] == 1150
assert r["pdf_url"].endswith("mn-ER-26183.pdf")
assert r["lab_pdf_url"].endswith("lab-ER-26183.pdf")
assert r["price_type"] == "Тогтмол үнэтэй"
# Preserve history, add a notice, and refresh an older amended record.
archive_pages[1] = notice_page(code="ER-99999", date="2026-09-19", last=3)
archive_pages[3] = notice_page(code="ERD-10-2026", quantity=19200, page=3, last=3)
archive_calls.clear()
scraper.update_notices(log=lambda *_: None)
assert archive_calls == [1, 2, 3]
assert len(scraper.load_notices()) == 4
assert scraper.load_notices().set_index("code").loc["ERD-10-2026", "quantity_t"] == 19200
scraper.update_notices(log=lambda *_: None)
assert len(scraper.load_notices()) == 4
print("notice archive pagination, accumulation, amendment and deduplication OK")
before = scraper.NOTICES_CSV.read_bytes()
archive_pages[2] = "<html>broken layout</html>"
try:
    scraper.update_notices(log=lambda *_: None)
except RuntimeError as e:
    assert "table missing" in str(e), e
else:
    raise AssertionError("Incomplete archive scan must raise")
assert scraper.NOTICES_CSV.read_bytes() == before
print("notice archive failure preserves existing CSV OK")

# --- parser fallback when a page has no PDF links ---
no_pdf = NOTICE_HTML.replace('<a href="', '<a data-x="')
rows = scraper.parse_notices(no_pdf)
assert {r["code"] for r in rows} >= {"2641-CO", "ER-26183", "ECM-26-140", "ERD-10-2026"}, [r["code"] for r in rows]
assert next(r for r in rows if r["code"] == "ECM-26-140")["company_en"].startswith("Mongolrostsvetmet")
print("no-PDF-link fallback OK")


# --- daily trading reports -> contracts.csv ---
from test_contracts import D0911, D0910, html_table
scraper.CONTRACTS_CSV, scraper.CONTRACTS_GONE = scraper.DATA_DIR / "contracts.csv", scraper.DATA_DIR / "contracts_no_page.txt"
tr = pd.DataFrame([
    {"trade_id": 1, "trade_time": "2026-09-11 10:00", "date": "2026-09-11", "status": "sold"},
    {"trade_id": 2, "trade_time": "2026-09-10 10:00", "date": "2026-09-10", "status": "sold"},
    {"trade_id": 3, "trade_time": "2026-09-09 10:00", "date": "2026-09-09", "status": "sold"},      # report page does not exist
    {"trade_id": 4, "trade_time": "2026-09-08 10:00", "date": "2026-09-08", "status": "no_bid"},   # no sold auction -> never fetched
])
tr.to_csv(scraper.TRADES_CSV, index=False)
fetched = []
def fake_fetch3(session, url, retries=3, allow_404=False):
    d = url.rsplit("/", 1)[1]; fetched.append(d)
    return {"2026-09-11": html_table(D0911), "2026-09-10": html_table(D0910)}.get(d)   # None = 404
scraper.fetch = fake_fetch3
n = scraper.update_contracts(full=True, log=lambda *_: None)
c = scraper.load_contracts()
assert n == 8 and len(c) == 8 and sorted(fetched) == ["2026-09-09", "2026-09-10", "2026-09-11"], (n, fetched)
assert c["total_value"].sum() == 16384000 + 19558400*2 + 18496000 + 15803377 + 4480000 + 24678400 + 438900
assert "2026-09-09" in scraper.CONTRACTS_GONE.read_text()
# second run: known dates are not re-fetched (they are older than 3 days), the missing page is remembered
fetched.clear(); n = scraper.update_contracts(full=False, log=lambda *_: None)
assert fetched == [] and len(scraper.load_contracts()) == 8, fetched
print("contracts update OK: 8 contracts, missing page remembered, no re-fetch")
