"""Parser tests against HTML that mimics the structure seen on comex.mse.mn."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import scraper

def trade(dt, no, company, comm, grade, lines):
    body = "".join(f"<h6>{l}</h6>" if l.startswith("$") else f"<p>{l}</p>" for l in lines)
    return (f"<div><h6><b>{dt}</b> - Арилжааны дугаар {no} {company}</h6>"
            f"<h6>{comm} - {grade}</h6>{body}</div>")

TRADES_HTML = "<html><body><nav><a>Арилжааны мэдээлэл</a></nav>" + "".join([
    trade("2026.09.18 14:00", 2961, "Эрдэнэс Тавантолгой ХК", "Нүүрс", "Дэгдэмхий бодис дунд, коксжих нүүрс",
          ["Худалдан авагч үнийн санал ирүүлээгүй", "$0.00 USD"]),
    trade("2026.09.18 11:00", 2960, "Монголросцветмет ТӨҮГ /Эрдэнэс критикал минералс ТӨҮГ/", "Төмөр", "Fe-52% Төмрийн хүдэр",
          ["65.00 USD", "$68.00 USD", "+3.00<br> (+4.62%)"]),
    trade("2026.09.18 10:00", 2958, "Энержи Ресурс ХХК", "Нүүрс", "Баяжуулсан коксжих нүүрс",
          ["1,150.00 CNY", "$1,255.00 CNY", "+105.00<br> (+9.13%)"]),
    trade("2026.09.11 14:00", 2939, "Тавантолгой ХК", "Нүүрс", "1/3 коксжих нүүрс",
          ["160.00 USD", "$160.00 USD", "+0.00<br> (+0.00%)"]),
    trade("2026.09.10 15:00", 2935, "Эрдэнэт Үйлдвэр ТӨҮГ", "Молибден", "44%-c багагүй молибдены агуулгатай баяжмал",
          ["28,317.90 USD", "$33,767.90 USD", "+5,450.00<br> (+19.25%)"]),
    trade("2026.08.26 15:00", 2890, "Эрдэнэт Үйлдвэр ТӨҮГ", "Зэс", "22.35%-ийн зэсийн агуулгатай баяжмал",
          ["3,288.81 USD", "$3,448.81 USD", "+160.00<br> (+4.86%)"]),
    trade("2025.10.17 10:00", 1987, "Монголросцветмет ТӨҮГ", "Жонш", "CaF2 <55% Хайлуур жоншны хүдэр",
          ["580.00 CNY", "$583.00 CNY", "+3.00<br> (+0.52%)"]),
]) + """<ul><li>‹</li><li>1</li><li><a href="https://comex.mse.mn/show-trades?page=2">2</a></li>
<li><a href="https://comex.mse.mn/show-trades?page=99">99</a></li></ul>
<footer>© Mongolian Stock Exchange.</footer></body></html>"""

def by_id(rows): return {r["trade_id"]: r for r in rows}

def test_trades():
    rows = scraper.parse_trades(TRADES_HTML)
    assert len(rows) == 7, len(rows)
    t = by_id(rows)
    # no-bid
    assert t[2961]["status"] == "no_bid" and t[2961]["final_price"] is None
    assert t[2961]["company"] == "Эрдэнэс Тавантолгой ХК"
    # iron ore + renamed company normalised
    r = t[2960]
    assert (r["start_price"], r["final_price"], r["change"], r["change_pct"]) == (65.0, 68.0, 3.0, 4.62)
    assert r["company_en"].startswith("Mongolrostsvetmet") and r["commodity"] == "Iron ore"
    assert r["trade_time"] == "2026-09-18 11:00" and r["currency"] == "USD"
    # CNY coal, thousands separator
    r = t[2958]; assert (r["start_price"], r["final_price"], r["currency"]) == (1150.0, 1255.0, "CNY")
    # "Тавантолгой ХК" (Tavan Tolgoi JSC) and "Эрдэнэс Тавантолгой ХК" (Erdenes TT) are DIFFERENT companies
    assert t[2939]["company"] == "Тавантолгой ХК" and t[2939]["company_en"] == "Tavan Tolgoi JSC"
    assert t[2961]["company_en"] == "Erdenes Tavan Tolgoi" and t[2939]["change_pct"] == 0.0
    # big numbers with commas + '%' inside grade names must not confuse price parsing
    r = t[2935]; assert (r["start_price"], r["final_price"], r["change"]) == (28317.9, 33767.9, 5450.0)
    assert r["commodity"] == "Molybdenum" and r["grade"].startswith("Molybdenum concentrate")
    r = t[2890]; assert (r["start_price"], r["final_price"]) == (3288.81, 3448.81) and r["commodity"] == "Copper"
    r = t[1987]; assert r["commodity"] == "Fluorspar" and r["currency"] == "CNY" and r["grade_mn"] == "CaF2 <55% Хайлуур жоншны хүдэр"
    assert scraper.last_page_number(TRADES_HTML) == 99

NOTICE_HTML = """<html><body><nav>Хянах самбар</nav><h4>Цахим арилжааны хураангуй зар</h4>
<ul><li>Бүгд</li><li>Нүүрс</li><li>Төмөр</li><li>Жонш</li><li>Зэс</li><li>Молибден</li></ul><span>❮</span><span>❯</span>
<div><h5>Эрдэнэс Тавантолгой ХК/2641-CO</h5><p>Дэгдэмхий бодис дунд, коксжих нүүрс</p><h6>181.5$</h6><p>10 багц / 64000тн / 10:00</p><h4>2026-09-18</h4>
<a href="https://mse.mn/uploads/auction_schedules/mn-2641-CO.pdf">Дэлгэрэнгүй</a></div>
<div><h5>Энержи Ресурс ХХК/ER-26183</h5><p>Баяжуулсан коксжих нүүрс</p><h6>1150¥</h6><p>2 багц / 12800тн / 10:00</p><h4>2026-09-18</h4>
<a href="https://mse.mn/uploads/auction_schedules/mn-890a.pdf">Дэлгэрэнгүй</a></div>
<div><h5>Монголросцветмет ТӨҮГ /Эрдэнэс критикал минералс ТӨҮГ//ECM-26-140</h5><p>Fe-52% Төмрийн хүдэр</p><h6>65$</h6><p>2 багц / 6600тн / 11:00</p><h4>2026-09-18</h4>
<a href="https://mse.mn/uploads/auction_schedules/mn-1394.pdf">Дэлгэрэнгүй</a></div>
<div><h5>Эрдэнэт Үйлдвэр ТӨҮГ/ERD-10-2026</h5><p>44%-c багагүй молибдены агуулгатай баяжмал</p><h6>28317.90$</h6><p>13 багц / 520тн / 15:00</p><h4>2026-09-10</h4>
<a href="https://mse.mn/uploads/auction_schedules/mn-ERD-10-2026.pdf">Дэлгэрэнгүй</a></div>
<div><h5>Эрдэнэт Үйлдвэр ТӨҮГ/ERD-10-2026</h5><p>44%-c багагүй молибдены агуулгатай баяжмал</p><h6>28317.90$</h6><p>13 багц / 520тн / 15:00</p><h4>2026-09-10</h4>
<a href="https://mse.mn/uploads/auction_schedules/mn-ERD-10-2026.pdf">Дэлгэрэнгүй</a></div>
</body></html>"""

def test_notices():
    rows = scraper.parse_notices(NOTICE_HTML)
    assert len(rows) == 4, [r["code"] for r in rows]   # duplicate de-duplicated
    n = {r["code"]: r for r in rows}
    assert n["2641-CO"]["start_price"] == 181.5 and n["2641-CO"]["currency"] == "USD"
    assert n["2641-CO"]["lots"] == 10 and n["2641-CO"]["quantity_t"] == 64000
    assert n["2641-CO"]["company"] == "Эрдэнэс Тавантолгой ХК" and n["2641-CO"]["commodity"] == "Coal"
    assert n["ER-26183"]["currency"] == "CNY" and n["ER-26183"]["start_price"] == 1150
    r = n["ECM-26-140"]
    assert r["company_en"].startswith("Mongolrostsvetmet") and r["commodity"] == "Iron ore" and r["pdf_url"].endswith("mn-1394.pdf")
    assert n["ERD-10-2026"]["commodity"] == "Molybdenum" and n["ERD-10-2026"]["quantity_t"] == 520

if __name__ == "__main__":
    test_trades(); test_notices(); print("all parser tests passed")
