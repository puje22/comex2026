#!/usr/bin/env python3
"""
Scraper for the Mongolian Stock Exchange COMEX mining-products e-auction site
(https://comex.mse.mn).

Collects
  * every completed / failed auction  -> data/trades.csv   (from /show-trades)
  * recent auction notices            -> data/notices.csv  (from /home)
  * lots / tonnes / contract value    -> data/contracts.csv (from /show_trading_infos/<date>,
                                          one daily report page per trading day)

Usage
  python scraper.py              # incremental update (fast, use this on a schedule)
  python scraper.py --full       # crawl every page of history (first run, ~2-3 min)
  python scraper.py --debug      # print the flattened text of page 1 (to fix parsing)
  python scraper.py --debug-contracts 2026-09-11   # print + parse one daily trading report

The parser works on the *visible text* of the page instead of CSS classes, so it
keeps working if the site's markup or styling changes, as long as the wording
("Арилжааны дугаар", commodity names, etc.) stays the same.
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin

import pandas as pd
import requests
from bs4 import BeautifulSoup

BASE = "https://comex.mse.mn"
DATA_DIR = Path(__file__).parent / "data"
TRADES_CSV = DATA_DIR / "trades.csv"
NOTICES_CSV = DATA_DIR / "notices.csv"
CONTRACTS_CSV = DATA_DIR / "contracts.csv"
CONTRACTS_GONE = DATA_DIR / "contracts_no_page.txt"  # dates that have no daily report page

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; comex-dashboard/1.0; personal research)",
    "Accept-Language": "mn,en;q=0.5",
}
REQUEST_DELAY = 1.0  # seconds between page requests - be polite to the server

# --------------------------------------------------------------------------
# Lookup tables. Add new commodities / companies / grades here.
# --------------------------------------------------------------------------
COMMODITIES = {
    "Нүүрс": "Coal",
    "Төмөр": "Iron ore",
    "Жонш": "Fluorspar",
    "Зэс": "Copper",
    "Молибден": "Molybdenum",
}

# (substring to look for, canonical Mongolian name, English name) - first match wins
COMPANIES = [
    ("Эрдэнэт", "Эрдэнэт Үйлдвэр ТӨҮГ", "Erdenet Mining Corporation"),
    ("Монголросцветмет", "Монголросцветмет ТӨҮГ", "Mongolrostsvetmet (ex-Erdenes Critical Minerals)"),
    ("критикал минералс", "Монголросцветмет ТӨҮГ", "Mongolrostsvetmet (ex-Erdenes Critical Minerals)"),
    ("Эрдэнэс Тавантолгой", "Эрдэнэс Тавантолгой ХК", "Erdenes Tavan Tolgoi"),  # state-owned "big TT"
    ("Тавантолгой", "Тавантолгой ХК", "Tavan Tolgoi JSC"),  # separate, MSE-listed company ("small TT")
    ("Энержи Ресурс", "Энержи Ресурс ХХК", "Energy Resources"),
    ("Хангад", "Хангад Эксплорэйшн ХХК", "Khangad Exploration"),
]

GRADES_EN = {
    "Дэгдэмхий бодис дунд, коксжих нүүрс": "Medium-volatile coking coal",
    "Баяжуулсан коксжих нүүрс": "Washed coking coal",
    "Баяжуулсан сул коксжих нүүрс": "Washed semi-soft coking coal",
    "Баяжуулсан коксжих чанаргүй нүүрс": "Washed non-coking-quality coal",
    "Баяжуулсан дунд зэрэг үнстэй, хагас хатуу коксжих нүүрс": "Washed medium-ash semi-hard coking coal",
    "1/3 коксжих нүүрс": "1/3 coking coal",
    "Эрчим хүчний нүүрс /Битумт, үл барьцалдах нүүрс/": "Thermal coal (bituminous, non-caking)",
    "Эрчим хүчний нүүрс /Саб-битумт, сул барьцалдах нүүрс/": "Thermal coal (sub-bituminous, weakly caking)",
    "Fe-52% Төмрийн хүдэр": "Iron ore Fe 52%",
    "Fe-65% Төмрийн баяжмал": "Iron concentrate Fe 65%",
    "CaF2-95% Хайлуур жоншны баяжмал": "Fluorspar concentrate CaF2 95%",
    "CaF2 <55% Хайлуур жоншны хүдэр": "Fluorspar ore CaF2 <55%",
    "22.35%-ийн зэсийн агуулгатай баяжмал": "Copper concentrate (22.35% Cu)",
    "44%-c багагүй молибдены агуулгатай баяжмал": "Molybdenum concentrate (>=44% Mo)",
}

CURRENCY_SYMBOLS = {"$": "USD", "¥": "CNY", "€": "EUR", "₮": "MNT"}

TRADE_COLUMNS = [
    "trade_id", "trade_time", "date", "company", "company_en", "company_raw",
    "commodity", "commodity_mn", "grade", "grade_mn", "currency",
    "start_price", "final_price", "change", "change_pct", "status",
]
CONTRACT_COLUMNS = [
    "date", "product_code", "registration_no", "company", "company_en", "company_raw",
    "commodity", "commodity_mn", "product_type", "grade", "grade_mn", "contract_type", "bidders",
    "start_price", "deal_price", "currency", "price_unit", "total_value", "premium_pct",
    "lots", "quantity_t", "quantity_source", "quality",
]
NOTICE_COLUMNS = [
    "scraped_at", "date", "time", "company", "company_en", "code", "commodity",
    "grade", "grade_mn", "currency", "start_price", "lots", "quantity_t", "pdf_url",
]

# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
COMMODITY_RE = re.compile(r"(?<!\w)(" + "|".join(map(re.escape, COMMODITIES)) + r")\s+-\s+")
HEADER_RE = re.compile(
    r"(\d{4})\.(\d{2})\.(\d{2})(?:\s+(\d{1,2}:\d{2}))?\s*-\s*Арилжааны\s+дугаар\s+(\d+)"
)
PRICE_RE = re.compile(r"(-?[\d,]+(?:\.\d+)?)\s*(USD|CNY|MNT|EUR|RUB|JPY)\b")
CHANGE_RE = re.compile(r"([+-][\d,]+(?:\.\d+)?)\s*\(\s*([+-]?[\d.,]+)\s*%\s*\)")
NO_BID = "Худалдан авагч үнийн санал ирүүлээгүй"  # "buyer submitted no bid"

NOTICE_RE = re.compile(
    r"(?P<seller>[^\d§]*?)/(?P<code>[A-Za-z0-9][A-Za-z0-9\-_]*)\s+(?P<grade>.+?)\s+"
    r"(?P<price>[\d,]+(?:\.\d+)?)\s*(?P<cur>[$¥€₮])\s+"
    r"(?P<lots>\d+)\s*багц\s*/\s*(?P<qty>[\d,]+(?:\.\d+)?)\s*тн\s*/\s*(?P<time>\d{1,2}:\d{2})\s+"
    r"(?P<date>\d{4}-\d{2}-\d{2})"
)


def _num(s: str) -> float:
    return float(s.replace(",", ""))


def _flatten(soup: BeautifulSoup) -> str:
    return re.sub(r"\s+", " ", soup.get_text(" ", strip=True))


def normalize_company(raw: str) -> tuple[str, str]:
    raw = re.sub(r"\s+", " ", raw).strip(" /")
    for needle, mn, en in COMPANIES:
        if needle in raw:
            return mn, en
    return raw, raw


def grade_en(grade_mn: str) -> str:
    return GRADES_EN.get(grade_mn, grade_mn)


# --------------------------------------------------------------------------
# Parsers (pure functions: HTML string in -> list of dicts out)
# --------------------------------------------------------------------------
def parse_trades(html: str) -> list[dict]:
    text = _flatten(BeautifulSoup(html, "html.parser"))
    heads = list(HEADER_RE.finditer(text))
    rows: list[dict] = []
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        body = text[m.end():end].strip()
        year, month, day, hhmm, trade_id = m.groups()[0], m.groups()[1], m.groups()[2], m.groups()[3], m.groups()[4]

        cm = COMMODITY_RE.search(body)
        if not cm:
            print(f"  ! could not find a known commodity in trade {trade_id}: {body[:80]!r}", file=sys.stderr)
            continue
        company_raw = body[:cm.start()].strip()
        after = body[cm.end():]

        # grade text runs until the "no bid" phrase or the first price
        cut = len(after)
        if NO_BID in after:
            cut = min(cut, after.index(NO_BID))
        pm = PRICE_RE.search(after)
        if pm:
            cut = min(cut, pm.start())
        grade_mn = after[:cut].strip()
        rest = after[cut:]

        prices = PRICE_RE.findall(rest)
        currency = prices[0][1] if prices else None
        start = final = change = change_pct = None

        if NO_BID in rest:
            status = "no_bid"
            if prices and _num(prices[0][0]) > 0:
                start = _num(prices[0][0])
        else:
            if len(prices) >= 2:
                start, final = _num(prices[0][0]), _num(prices[1][0])
            elif len(prices) == 1:
                final = _num(prices[0][0])
            status = "sold" if final and final > 0 else "no_bid"
            if status == "no_bid":
                final = None
            ch = CHANGE_RE.search(rest)
            if ch and status == "sold":
                change, change_pct = _num(ch.group(1)), _num(ch.group(2))
            elif status == "sold" and start:
                change = final - start
                change_pct = change / start * 100

        company_mn, company_en = normalize_company(company_raw)
        rows.append({
            "trade_id": int(trade_id),
            "trade_time": f"{year}-{month}-{day} {hhmm or '00:00'}",
            "date": f"{year}-{month}-{day}",
            "company": company_mn,
            "company_en": company_en,
            "company_raw": company_raw,
            "commodity": COMMODITIES[cm.group(1)],
            "commodity_mn": cm.group(1),
            "grade": grade_en(grade_mn),
            "grade_mn": grade_mn,
            "currency": currency,
            "start_price": start,
            "final_price": final,
            "change": change,
            "change_pct": change_pct,
            "status": status,
        })
    return rows


def parse_notices(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    for a in soup.find_all("a", href=True):
        if "auction_schedules" in a["href"]:
            a.replace_with(f" §{urljoin(BASE, a['href'])}§ ")
    text = _flatten(soup).replace("❮", " ").replace("❯", " ")
    parts = re.split(r"§(\S+?)§", text)  # [chunk, href, chunk, href, ..., tail]
    if len(parts) > 1:
        pairs = []
        for idx in range(0, len(parts) - 1, 2):
            chunk = parts[idx]
            if idx == 0:  # drop menu / tab labels before the first record
                chunk = re.split(r"Зэс\s+Молибден", chunk)[-1]
            pairs.append((NOTICE_RE.search(chunk), parts[idx + 1]))
    else:  # layout without PDF links: scan the whole text
        flat = re.split(r"Зэс\s+Молибден", text.replace("Дэлгэрэнгүй", " "))[-1]
        pairs = [(m, None) for m in NOTICE_RE.finditer(flat)]
    rows, seen = [], set()
    now = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M")
    for m, href in pairs:
        if not m:
            continue
        key = (m["code"], m["date"])
        if key in seen:
            continue
        seen.add(key)
        seller_mn, seller_en = normalize_company(m["seller"])
        grade_mn = m["grade"].strip()
        cm = COMMODITY_RE.search(grade_mn + " - ")
        rows.append({
            "scraped_at": now,
            "date": m["date"],
            "time": m["time"],
            "company": seller_mn,
            "company_en": seller_en,
            "code": m["code"],
            "commodity": _guess_commodity(grade_mn, seller_mn),
            "grade": grade_en(grade_mn),
            "grade_mn": grade_mn,
            "currency": CURRENCY_SYMBOLS.get(m["cur"], m["cur"]),
            "start_price": _num(m["price"]),
            "lots": int(m["lots"]),
            "quantity_t": _num(m["qty"]),
            "pdf_url": href,
        })
    return rows


def _guess_commodity(grade_mn: str, seller_mn: str) -> str:
    g = grade_mn.lower()
    if "нүүрс" in g:
        return "Coal"
    if "төмөр" in g or g.startswith("fe"):
        return "Iron ore"
    if "жонш" in g or "caf2" in g:
        return "Fluorspar"
    if "молибден" in g:
        return "Molybdenum"
    if "зэс" in g:
        return "Copper"
    return "Other"


def last_page_number(html: str) -> int | None:
    nums = [int(n) for n in re.findall(r"show-trades\?page=(\d+)", html)]
    return max(nums) if nums else None


# --------------------------------------------------------------------------
# Daily trading report  (/show_trading_infos/YYYY-MM-DD)
# One column per EXECUTED trade, one row per attribute. Gives the real contract value,
# lots, tonnes and number of bidders that /show-trades does not have.
# --------------------------------------------------------------------------
# (key, label on the page, kind of value)
CONTRACT_LABELS = [
    ("commodity_mn", "Бүтээгдэхүүний нэр", "word"),
    ("product_type", "Бүтээгдэхүүний төрөл", "word"),
    ("grade_mn", "Ангилал", "grade"),
    ("date", "Арилжаа зохион байгуулагдсан огноо", "date"),
    ("bidders", "Арилжаанд оролцсон худалдан авах санал гаргагчдын тоо", "int"),
    ("company_raw", "Худалдагч этгээдийн нэр", "seller"),
    ("address", "Худалдагч этгээдийн албан ёсны хаяг", "skip"),
    ("registration_no", "Захиалгын бүртгэлийн дугаар", "token"),
    ("contract_type", "Гэрээний төрөл", "word"),
    ("product_code", "Бүтээгдэхүүний код", "token"),
    ("start", "Дуудах доод үнэ, валютын төрөл", "price"),
    ("deal", "Хэлцэл хийгдсэн үнэ", "price"),
    ("total", "Гэрээний нийт үнийн дүн", "money"),
    ("premium", "Үнийн өсөлтийн хувь", "pct"),
    ("lots", "Арилжсан бүтээгдэхүүний багцын тоо хэмжээ /тонн/", "lots"),
    ("quality", "Арилжсан бүтээгдэхүүний чанарын үзүүлэлт", "quality"),
]
_FIRST_LABEL = CONTRACT_LABELS[0][1]
_ESSENTIAL = ("commodity_mn", "grade_mn", "date", "company_raw", "product_code", "deal", "total", "lots")
SELLER_NAMES = [
    "Монголросцветмет ТӨҮГ /Эрдэнэс критикал минералс ТӨҮГ/", "Эрдэнэс критикал минералс ТӨҮГ",
    "Монголросцветмет ТӨҮГ", "Эрдэнэс Тавантолгой ХК", "Тавантолгой ХК", "Энержи Ресурс ХХК",
    "Хангад Эксплорэйшн ХХК", "Эрдэнэт Үйлдвэр ТӨҮГ",
]
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
PRICE_UNIT_RE = re.compile(r"([\d,]+(?:\.\d+)?)\s*([A-Z]{3})\s*/\s*(\S+)")
MONEY_RE = re.compile(r"([\d,]+(?:\.\d+)?)\s*([A-Z]{3})")
LOTS_RE = re.compile(r"(\d+)(?:\s*Багц\s*/\s*([\d,.]+)\s*тонн\s*/?)?")


def _split_known(seg: str, n: int, vocab: list[str]) -> list[str] | None:
    """Split a run-together row of n multi-word values, using known values (or exact repetition)."""
    pat = "|".join(re.escape(v) for v in sorted(vocab, key=len, reverse=True))
    found = re.findall(pat, seg)
    if len(found) == n:
        return found
    toks = seg.split()
    if n and len(toks) % n == 0:  # the same value repeated n times
        k = len(toks) // n
        groups = [" ".join(toks[i * k:(i + 1) * k]) for i in range(n)]
        if len(set(groups)) == 1:
            return groups
    return None


def _cells_from_text(kind: str, seg: str, n: int) -> list[str] | None:
    if kind == "skip" or kind == "quality":
        return None
    if kind == "date":
        return DATE_RE.findall(seg)
    if kind == "int":
        return re.findall(r"\d+", seg)
    if kind in ("word", "token"):
        return seg.split()
    if kind == "price":
        return [m.group(0) for m in PRICE_UNIT_RE.finditer(seg)]
    if kind == "money":
        return [m.group(0) for m in MONEY_RE.finditer(seg)]
    if kind == "pct":
        return re.findall(r"[\d.]+\s*%", seg)
    if kind == "lots":
        return [m.group(0) for m in LOTS_RE.finditer(seg)]
    if kind == "grade":
        return _split_known(seg, n, list(GRADES_EN))
    if kind == "seller":
        return _split_known(seg, n, SELLER_NAMES)
    return None


def _text_blocks(text: str) -> list[dict]:
    idx = [m.start() for m in re.finditer(re.escape(_FIRST_LABEL), text)]
    blocks = []
    for a, b in zip(idx, idx[1:] + [len(text)]):
        chunk = text[a:b]
        pos = sorted((chunk.find(lbl), key, lbl) for key, lbl, _ in CONTRACT_LABELS if chunk.find(lbl) >= 0)
        segs = {}
        for j, (i, key, lbl) in enumerate(pos):
            end = pos[j + 1][0] if j + 1 < len(pos) else len(chunk)
            segs[key] = chunk[i + len(lbl):end].strip()
        n = len(DATE_RE.findall(segs.get("date", "")))
        cells = {}
        for key, _, kind in CONTRACT_LABELS:
            if key in segs:
                got = _cells_from_text(kind, segs[key].split("МОНГОЛЫН ХӨРӨНГИЙН БИРЖ")[0], n)
                if got:
                    cells[key] = got
        blocks.append(cells)
    return blocks


def _row_cells(node) -> list[str] | None:
    """Value cells that sit next to the label text node, whatever the markup (table, li/span, div grid)."""
    parent = node.parent
    kids = parent.find_all(recursive=False)
    if kids:                                   # label is bare text inside the row container
        vals = kids
    else:                                      # label is wrapped in its own element: climb to the row
        el = parent
        while el.parent is not None and len(el.parent.find_all(recursive=False)) == 1:
            el = el.parent
        row = el.parent
        if row is None:
            return None
        sibs = row.find_all(recursive=False)
        if el not in sibs:
            return None
        vals = sibs[sibs.index(el) + 1:]
        if len(vals) == 1:                     # values grouped in one wrapper
            sub = vals[0].find_all(recursive=False)
            if len(sub) > 1:
                vals = sub
    return [v.get_text("\n", strip=True) for v in vals] or None


def _dom_blocks(soup: BeautifulSoup) -> list[dict]:
    def find(label):
        return soup.find_all(string=lambda t, L=label: bool(t) and t.strip().rstrip(":").strip() == L)
    first = find(_FIRST_LABEL)
    blocks = [dict() for _ in first]
    for key, label, _ in CONTRACT_LABELS:
        for b, node in enumerate(find(label)[:len(first)]):
            cells = _row_cells(node)
            if cells:
                blocks[b][key] = cells
    return blocks


def _blocks_ok(blocks: list[dict]) -> bool:
    if not blocks:
        return False
    for blk in blocks:
        n = len(blk.get("date", []))
        if n == 0 or any(len(blk.get(k, [])) != n for k in _ESSENTIAL):
            return False
        if not all(DATE_RE.search(c) for c in blk["date"]):
            return False
    return True


def _f(x: str) -> float:
    return float(x.replace(",", ""))


def parse_contracts(html: str, page_date: str | None = None) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    blocks = _dom_blocks(soup)
    if not _blocks_ok(blocks):  # markup not as expected: fall back to reading the visible text
        blocks = _text_blocks(_flatten(soup))
    rows: list[dict] = []
    for blk in blocks:
        n = len(blk.get("date", []))
        if n == 0:
            continue

        def cell(key, i, blk=blk, n=n):
            v = blk.get(key)
            return v[i].strip() if v and len(v) == n else ""

        for i in range(n):
            start, deal = PRICE_UNIT_RE.search(cell("start", i)), PRICE_UNIT_RE.search(cell("deal", i))
            total = MONEY_RE.search(cell("total", i))
            lm = LOTS_RE.search(cell("lots", i))
            pm = re.search(r"[\d.]+", cell("premium", i))
            deal_price = _f(deal.group(1)) if deal else None
            total_value = _f(total.group(1)) if total else None
            lots = int(lm.group(1)) if lm else None
            if lm and lm.group(2):
                qty, qsrc = _f(lm.group(2)), "reported"
            elif deal_price and total_value:  # e.g. molybdenum: only the lot count is printed
                qty, qsrc = round(total_value / deal_price, 3), "implied (total / price)"
            else:
                qty, qsrc = None, None
            company_raw = cell("company_raw", i)
            company_mn, company_en = normalize_company(company_raw)
            commodity_mn = cell("commodity_mn", i)
            grade_mn = cell("grade_mn", i)
            dm = DATE_RE.search(cell("date", i))
            rows.append({
                "date": dm.group(0) if dm else page_date,
                "product_code": cell("product_code", i),
                "registration_no": cell("registration_no", i),
                "company": company_mn, "company_en": company_en, "company_raw": company_raw,
                "commodity": COMMODITIES.get(commodity_mn, commodity_mn), "commodity_mn": commodity_mn,
                "product_type": cell("product_type", i),
                "grade": grade_en(grade_mn), "grade_mn": grade_mn,
                "contract_type": cell("contract_type", i),
                "bidders": int(cell("bidders", i)) if cell("bidders", i).isdigit() else None,
                "start_price": _f(start.group(1)) if start else None,
                "deal_price": deal_price,
                "currency": (deal or start).group(2) if (deal or start) else (total.group(2) if total else None),
                "price_unit": deal.group(3) if deal else None,
                "total_value": total_value,
                "premium_pct": _f(pm.group(0)) if pm else None,
                "lots": lots, "quantity_t": qty, "quantity_source": qsrc,
                "quality": " | ".join(x for x in cell("quality", i).splitlines() if x.strip()),
            })
    return rows


# --------------------------------------------------------------------------
# Network
# --------------------------------------------------------------------------
def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


def fetch(session: requests.Session, url: str, retries: int = 3, allow_404: bool = False) -> str | None:
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            r = session.get(url, timeout=30)
            if allow_404 and r.status_code == 404:
                return None
            r.raise_for_status()
            r.encoding = "utf-8"
            return r.text
        except requests.HTTPError as e:
            code = e.response.status_code if e.response is not None else 0
            if 400 <= code < 500:  # page doesn't exist - retrying won't help
                raise RuntimeError(f"HTTP {code} for {url}") from e
            last_err = e
            time.sleep(2 * (attempt + 1))
        except requests.RequestException as e:  # noqa: PERF203
            last_err = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"Failed to fetch {url}: {last_err}")


# --------------------------------------------------------------------------
# Storage
# --------------------------------------------------------------------------
def load_trades() -> pd.DataFrame:
    if not TRADES_CSV.exists():
        return pd.DataFrame(columns=TRADE_COLUMNS)
    df = pd.read_csv(TRADES_CSV)
    if "company_raw" in df.columns:  # re-apply current alias / translation tables
        norm = df["company_raw"].fillna("").map(normalize_company)
        df["company"] = norm.map(lambda t: t[0])
        df["company_en"] = norm.map(lambda t: t[1])
    if "grade_mn" in df.columns:
        df["grade"] = df["grade_mn"].map(lambda g: grade_en(g) if isinstance(g, str) else g)
    return df


def load_contracts() -> pd.DataFrame:
    if not CONTRACTS_CSV.exists():
        return pd.DataFrame(columns=CONTRACT_COLUMNS)
    df = pd.read_csv(CONTRACTS_CSV)
    if "company_raw" in df.columns:  # re-apply current alias / translation tables
        norm = df["company_raw"].fillna("").map(normalize_company)
        df["company"] = norm.map(lambda t: t[0])
        df["company_en"] = norm.map(lambda t: t[1])
    if "grade_mn" in df.columns:
        df["grade"] = df["grade_mn"].map(lambda g: grade_en(g) if isinstance(g, str) else g)
    return df


def load_notices() -> pd.DataFrame:
    if not NOTICES_CSV.exists():
        return pd.DataFrame(columns=NOTICE_COLUMNS)
    df = pd.read_csv(NOTICES_CSV)
    if "company" in df.columns:
        norm = df["company"].fillna("").map(normalize_company)
        df["company_en"] = norm.map(lambda t: t[1])
    return df


def _save(df: pd.DataFrame, path: Path, columns: list[str], sort_by: list[str]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    df = df.reindex(columns=columns).sort_values(sort_by, ascending=False)
    df.to_csv(path, index=False, encoding="utf-8")


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------
def update_trades(full: bool = False, max_pages: int | None = None, log=print) -> int:
    """Scrape /show-trades and merge into data/trades.csv. Returns number of new trades."""
    session = make_session()
    existing = load_trades()
    known = set(existing["trade_id"].astype(int)) if len(existing) else set()
    fresh: list[dict] = []
    page, last_page = 1, None

    while True:
        url = f"{BASE}/show-trades" + (f"?page={page}" if page > 1 else "")
        html = fetch(session, url)
        if last_page is None:
            last_page = last_page_number(html) or 1
            if max_pages:
                last_page = min(last_page, max_pages)
        rows = parse_trades(html)
        if not rows:
            if page == 1:
                raise RuntimeError(
                    "Parsed 0 trades from page 1 - the site layout may have changed. "
                    "Run `python scraper.py --debug` to inspect the text."
                )
            log(f"  page {page}: no trades found, stopping")
            break
        new_here = [r for r in rows if r["trade_id"] not in known]
        fresh.extend(rows)
        log(f"  page {page}/{last_page}: {len(rows)} trades ({len(new_here)} new)")
        # incremental mode: always re-read pages 1-2, then stop at the first fully known page
        if not full and page >= 2 and not new_here:
            break
        page += 1
        if page > last_page:
            break
        time.sleep(REQUEST_DELAY)

    new_count = len({r["trade_id"] for r in fresh} - known)
    if fresh:
        merged = pd.concat([existing, pd.DataFrame(fresh)], ignore_index=True)
        merged = merged.drop_duplicates("trade_id", keep="last")  # newest scrape wins
        _save(merged, TRADES_CSV, TRADE_COLUMNS, ["trade_time", "trade_id"])
    return new_count


def update_notices(full: bool = False, max_pages: int | None = None, log=print) -> int:
    """Scrape auction notices (lots + tonnage) and ACCUMULATE them in data/notices.csv."""
    session = make_session()
    rows = parse_notices(fetch(session, f"{BASE}/home"))
    log(f"  notices (dashboard): {len(rows)} parsed")

    # Best-effort: the notice archive. Its layout has not been verified, so failures are non-fatal.
    try:
        page, last = 1, None
        limit = (max_pages or 999) if full else 2
        while page <= limit:
            html = fetch(session, f"{BASE}/show-notices" + (f"?page={page}" if page > 1 else ""))
            if last is None:
                nums = [int(n) for n in re.findall(r"show-notices\?page=(\d+)", html)]
                last = max(nums) if nums else 1
            got = parse_notices(html)
            log(f"  notice archive page {page}/{last}: {len(got)} parsed")
            if not got:
                break
            rows += got
            page += 1
            if page > last:
                break
            time.sleep(REQUEST_DELAY)
    except Exception as e:  # noqa: BLE001
        log(f"  notice archive skipped: {e}")

    if rows:
        merged = pd.concat([load_notices(), pd.DataFrame(rows)], ignore_index=True)
        merged = merged.drop_duplicates(["code", "date"], keep="last")
        _save(merged, NOTICES_CSV, NOTICE_COLUMNS, ["date", "time"])
    return len(rows)


def update_contracts(full: bool = False, max_fetch: int = 30, log=print) -> int:
    """Fetch the daily trading report for every date that had a sold auction. Returns contracts parsed."""
    trades = load_trades()
    if trades.empty:
        return 0
    sold_dates = sorted(set(trades.loc[trades["status"] == "sold", "date"].astype(str).str[:10]))
    have = set(load_contracts()["date"].astype(str).str[:10])
    gone = set(CONTRACTS_GONE.read_text().split()) if CONTRACTS_GONE.exists() else set()
    today = pd.Timestamp.now().normalize()
    recent = {d for d in sold_dates if (today - pd.Timestamp(d)).days <= 3}  # reports can be posted late/edited
    todo = [d for d in sold_dates if (d not in have and d not in gone) or d in recent]
    todo = sorted(todo, reverse=True)
    if not full:
        todo = todo[:max_fetch]  # newest first; older gaps are filled on later runs
    session, rows, new_gone = make_session(), [], []
    for d in todo:
        html = fetch(session, f"{BASE}/show_trading_infos/{d}", allow_404=True)
        if html is None:
            log(f"  contracts {d}: no report page")
            if d not in recent:
                new_gone.append(d)
        else:
            got = parse_contracts(html, page_date=d)
            log(f"  contracts {d}: {len(got)} parsed")
            if not got:
                log(f"    ! 0 contracts parsed on {d} - run `python scraper.py --debug-contracts {d}`")
            rows += got
        time.sleep(REQUEST_DELAY)
    if new_gone:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        CONTRACTS_GONE.write_text("\n".join(sorted(gone | set(new_gone))))
    if rows:
        merged = pd.concat([load_contracts(), pd.DataFrame(rows)], ignore_index=True)
        merged = merged.drop_duplicates(["date", "product_code"], keep="last")
        _save(merged, CONTRACTS_CSV, CONTRACT_COLUMNS, ["date", "product_code"])
    return len(rows)


def update_all(full: bool = False, max_pages: int | None = None, log=print) -> dict:
    n_new = update_trades(full=full, max_pages=max_pages, log=log)
    try:
        n_notices = update_notices(full=full, max_pages=max_pages, log=log)
    except Exception as e:  # notices are nice-to-have; never fail the whole run
        log(f"  notices failed: {e}")
        n_notices = 0
    errors = []
    try:
        n_contracts = update_contracts(full=full, log=log)
    except Exception as e:  # keep prices working if the daily reports break, but SAY so
        log(f"  contracts failed: {e}")
        errors.append(f"contracts: {e}")
        n_contracts = 0
    return {"new_trades": n_new, "notices": n_notices, "contracts": n_contracts, "errors": errors}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--full", action="store_true", help="crawl all pages of history")
    ap.add_argument("--max-pages", type=int, help="limit pages (for testing)")
    ap.add_argument("--debug", action="store_true", help="print flattened text of page 1 and exit")
    ap.add_argument("--debug-contracts", metavar="YYYY-MM-DD", help="print + parse one daily trading report and exit")
    args = ap.parse_args()

    if args.debug:
        html = fetch(make_session(), f"{BASE}/show-trades")
        print(_flatten(BeautifulSoup(html, "html.parser"))[:4000])
        print("\nparsed:", len(parse_trades(html)), "trades")
        return 0

    if args.debug_contracts:
        html = fetch(make_session(), f"{BASE}/show_trading_infos/{args.debug_contracts}")
        print(_flatten(BeautifulSoup(html, "html.parser"))[:3000])
        for r in parse_contracts(html, page_date=args.debug_contracts):
            print({k: r[k] for k in ("product_code", "company_en", "commodity", "grade", "deal_price", "currency", "lots", "quantity_t", "total_value", "bidders")})
        return 0

    print("Updating COMEX data ...")
    result = update_all(full=args.full, max_pages=args.max_pages)
    total = len(load_trades())
    print(f"Done. {result['new_trades']} new trades ({total} total), {len(load_contracts())} contracts "
          f"in {CONTRACTS_CSV.name}")
    for err in result["errors"]:
        print("WARNING:", err)
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
