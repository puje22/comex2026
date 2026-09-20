"""Daily trading report parser, tested with the real values from comex.mse.mn/show_trading_infos/2026-09-10 and -11,
rendered in three different markups (the real markup isn't known)."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import scraper

L = {k: lbl for k, lbl, _ in scraper.CONTRACT_LABELS}
D0911 = {
 "commodity_mn": ["Нүүрс"]*4, "product_type": ["Боловсруулаагүй"]*3 + ["Баяжуулсан"],
 "grade_mn": ["1/3 коксжих нүүрс", "Дэгдэмхий бодис дунд, коксжих нүүрс", "Дэгдэмхий бодис дунд, коксжих нүүрс", "Баяжуулсан коксжих нүүрс"],
 "date": ["2026-09-11"]*4, "bidders": ["3", "6", "4", "5"],
 "company_raw": ["Тавантолгой ХК"]*3 + ["Энержи Ресурс ХХК"],
 "address": ["Өмнөговь аймаг Цогтцэций сум Цагаан-Овоо баг Тавантолгой Хувьцаат Компани"]*3 + ["16 давхар, Сэнтрал Тауэр, 1-р хороо, Сүхбаатар дүүрэг, Улаанбаатар хот, 14200, Монгол улс"],
 "registration_no": ["TTOA-2026-043", "TTOA-2026-042", "TTOA-2026-041", "ER-26179"], "contract_type": ["Форвард"]*4,
 "product_code": ["C04-2026091104", "C03-2026091103", "C03-2026091102", "C01-2026091101"],
 "start": ["160 USD /тонн", "180 USD /тонн", "180 USD /тонн", "1150 CNY /тонн"],
 "deal": ["160 USD /тонн", "191 USD /тонн", "191 USD /тонн", "1445 CNY /тонн"],
 "total": ["16,384,000 USD", "19,558,400 USD", "19,558,400 USD", "18,496,000 CNY"],
 "premium": ["0%", "6.11%", "6.11%", "25.65%"],
 "lots": ["16 Багц/102400 тонн/", "16 Багц/102400 тонн/", "16 Багц/102400 тонн/", "2 Багц/12800 тонн/"],
 "quality": ["Ash (db): 18.9 (-4.0, +6.0)\nVolatile (daf): 29.1", "Ash (db): 15.64\nG-index (5:1): 76.0", "Ash (db): 15.64\nG-index (5:1): 76.0", "Ash (dry, %) ≤ 11.0%\nG index ≥ 75"],
}
D0910 = {
 "commodity_mn": ["Молибден", "Нүүрс", "Нүүрс", "Төмөр"], "product_type": ["Баяжмал", "Баяжуулсан", "Баяжуулсан", "Хүдэр"],
 "grade_mn": ["44%-c багагүй молибдены агуулгатай баяжмал", "Баяжуулсан коксжих чанаргүй нүүрс", "Баяжуулсан сул коксжих нүүрс", "Fe-52% Төмрийн хүдэр"],
 "date": ["2026-09-10"]*4, "bidders": ["3"]*4,
 "company_raw": ["Эрдэнэт Үйлдвэр ТӨҮГ", "Тавантолгой ХК", "Тавантолгой ХК", "Монголросцветмет ТӨҮГ /Эрдэнэс критикал минералс ТӨҮГ/"],
 "address": ["Монгол Улс, Орхон аймаг, Баян-Өндөр сум, Найрамдал талбай", "Өмнөговь аймаг Цогтцэций сум", "Өмнөговь аймаг Цогтцэций сум", "Улаанбаатар хот, Баянзүрх дүүрэг"],
 "registration_no": ["ERD-10-2026", "TTOA-2026-040", "TTOA-2026-039", "ECM-26-137"], "contract_type": ["Форвард"]*4,
 "product_code": ["MO01-2026091001", "C10-2026091003", "C02-2026091002", "FE03-2026091001"],
 "start": ["28317.9 USD /тонн", "63 USD /тонн", "120 USD /тонн", "65 USD /тонн"],
 "deal": ["33767.9 USD /тонн", "70 USD /тонн", "120.5 USD /тонн", "66.5 USD /тонн"],
 "total": ["15,803,377 USD", "4,480,000 USD", "24,678,400 USD", "438,900 USD"],
 "premium": ["19.25%", "11.11%", "0.42%", "2.31%"],
 "lots": ["13", "10 Багц/64000 тонн/", "32 Багц/204800 тонн/", "2 Багц/6600 тонн/"],
 "quality": ["Молибден /Мо/ >44%\nЗэс /Cu/ <3%", "Ash (db): 30.0 (-5, +5)", "Ash (db): ≤12", "H2O 0.5-1.0%\nFe <52%"],
}
SIDEBAR = '<h6><a href="https://comex.mse.mn/show_trading_infos/2026-09-18">09-Р САРЫН 18 ӨДРИЙН УУЛ УУРХАЙН БҮТЭЭГДЭХҮҮНИЙ АРИЛЖААНЫ МЭДЭЭ</a></h6>'

def html_li_span(d):
    rows = "".join(f'<li><span class="k">{L[k]}</span>' + "".join(f"<span>{v.replace(chr(10), '<br>')}</span>" for v in d[k]) + "</li>" for k in L)
    return f"<html><body><nav><a>Арилжааны мэдээлэл</a></nav><ul><li>Арилжигдсан уул уурхайн бүтээгдэхүүний мэдээлэл</li>{rows}</ul>{SIDEBAR}</body></html>"

def html_table(d):
    rows = "".join(f"<tr><th>{L[k]}</th>" + "".join(f"<td>{v.replace(chr(10), '<br>')}</td>" for v in d[k]) + "</tr>" for k in L)
    return f"<html><body><table>{rows}</table>{SIDEBAR}</body></html>"

def html_bare_text(d):   # label + all values as one run of text (what a text-only rendering looks like)
    rows = "".join(f"<li>{L[k]} " + " ".join(d[k]) + "</li>" for k in L if k != "quality")
    return f"<html><body><ul>{rows}</ul>МОНГОЛЫН ХӨРӨНГИЙН БИРЖ {SIDEBAR}</body></html>"

def check_0911(rows):
    assert len(rows) == 4, len(rows)
    r = {x["product_code"]: x for x in rows}
    a = r["C04-2026091104"]
    assert (a["company_en"], a["grade"], a["commodity"]) == ("Tavan Tolgoi JSC", "1/3 coking coal", "Coal")
    assert (a["lots"], a["quantity_t"], a["quantity_source"], a["total_value"], a["currency"], a["bidders"]) == (16, 102400, "reported", 16384000, "USD", 3)
    assert a["price_unit"] == "тонн" and a["start_price"] == 160 and a["deal_price"] == 160 and a["premium_pct"] == 0
    b = r["C03-2026091103"]; assert (b["deal_price"], b["total_value"], b["bidders"], b["premium_pct"]) == (191, 19558400, 6, 6.11)
    e = r["C01-2026091101"]
    assert (e["company_en"], e["currency"], e["deal_price"], e["lots"], e["quantity_t"], e["total_value"]) == ("Energy Resources", "CNY", 1445, 2, 12800, 18496000)
    for x in rows:  # internal consistency: total = price x tonnes
        assert abs(x["deal_price"] * x["quantity_t"] - x["total_value"]) < 1, x["product_code"]

def check_0910(rows):
    assert len(rows) == 4, len(rows)
    r = {x["product_code"]: x for x in rows}
    mo = r["MO01-2026091001"]                      # only the lot count is printed -> tonnes implied from value / price
    assert mo["commodity"] == "Molybdenum" and mo["lots"] == 13 and mo["total_value"] == 15803377
    assert mo["quantity_source"].startswith("implied") and abs(mo["quantity_t"] - 468) < 0.01, mo["quantity_t"]
    assert mo["company_en"] == "Erdenet Mining Corporation"
    fe = r["FE03-2026091001"]
    assert (fe["commodity"], fe["lots"], fe["quantity_t"], fe["total_value"]) == ("Iron ore", 2, 6600, 438900)
    assert fe["company_en"].startswith("Mongolrostsvetmet") and fe["grade"] == "Iron ore Fe 52%"
    c = r["C02-2026091002"]; assert (c["lots"], c["quantity_t"], c["total_value"], c["grade"]) == (32, 204800, 24678400, "Washed semi-soft coking coal")
    assert r["C10-2026091003"]["company_en"] == "Tavan Tolgoi JSC"

def test_all_markups():
    for name, fn in [("li/span", html_li_span), ("table", html_table), ("bare text", html_bare_text)]:
        check_0911(scraper.parse_contracts(fn(D0911), "2026-09-11"))
        check_0910(scraper.parse_contracts(fn(D0910), "2026-09-10"))
        print("contracts parsed OK with markup:", name)

def test_quality_kept_when_dom_available():
    rows = scraper.parse_contracts(html_table(D0910), "2026-09-10")
    mo = next(x for x in rows if x["product_code"].startswith("MO01"))
    assert "Молибден /Мо/ >44%" in mo["quality"] and "Зэс /Cu/ <3%" in mo["quality"]

def test_two_tables_one_page():
    both = html_table(D0911).replace("</body>", "") + html_table(D0910).split("<body>")[1]
    rows = scraper.parse_contracts(both)
    assert len(rows) == 8

if __name__ == "__main__":
    test_all_markups(); test_quality_kept_when_dom_available(); test_two_tables_one_page(); print("contract parser tests passed")
