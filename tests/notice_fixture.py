"""Offline archive-table fixtures matching /show-notices column order."""
from html import escape


def notice_page(code="ER-26183", date="2026-09-18", quantity=12800, page=1, last=1):
    values = [str(page), "Нүүрс", "Баяжуулсан коксжих нүүрс", "Энержи Ресурс ХХК",
              f"{date} 10:00:00", f"2 Багц/{quantity}тн/", "1,150¥",
              "Тогтмол үнэтэй", code]
    row = "".join(f"<td>{escape(value)}</td>" for value in values)
    row += f'<td><a href="/uploads/auction_schedules/lab-{escape(code)}.pdf">Харах</a></td>'
    row += f'<td><a href="/uploads/auction_schedules/mn-{escape(code)}.pdf">Дэлгэрэнгүй</a></td>'
    nav = "".join(f'<a href="/show-notices?page={p}">{p}</a>' for p in range(1, last + 1))
    return ('<table><thead><tr><th>Худалдагч</th><th>Захиалгын дугаар</th></tr></thead>'
            f'<tbody><tr>{row}</tr></tbody></table>{nav}')
