"""Executes app.py top-to-bottom with stubbed streamlit/plotly against sample CSVs."""
import sys, types, pathlib, tempfile, datetime as dt
from unittest.mock import MagicMock
ROOT = pathlib.Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT/"tests"))
import scraper, pandas as pd
from test_parsers import TRADES_HTML, NOTICE_HTML
from test_contracts import D0911, D0910, html_table

tmp = pathlib.Path(tempfile.mkdtemp())
scraper.DATA_DIR, scraper.TRADES_CSV, scraper.NOTICES_CSV = tmp, tmp/"trades.csv", tmp/"notices.csv"
scraper._save(pd.DataFrame(scraper.parse_trades(TRADES_HTML)), scraper.TRADES_CSV, scraper.TRADE_COLUMNS, ["trade_time"])
scraper._save(pd.DataFrame(scraper.parse_notices(NOTICE_HTML)), scraper.NOTICES_CSV, scraper.NOTICE_COLUMNS, ["date"])
scraper.CONTRACTS_CSV = tmp/"contracts.csv"
rows = scraper.parse_contracts(html_table(D0911), "2026-09-11") + scraper.parse_contracts(html_table(D0910), "2026-09-10")
scraper._save(pd.DataFrame(rows), scraper.CONTRACTS_CSV, scraper.CONTRACT_COLUMNS, ["date"])
scraper.update_all = lambda **k: {"new_trades": 0, "notices": 0}   # no network

st = MagicMock()
st.cache_resource = lambda **kw: (lambda f: f)
class _Cache:
    def __call__(self, *a, **kw): return (lambda f: f) if not (a and callable(a[0])) else a[0]
    clear = staticmethod(lambda: None)
st.cache_data = _Cache()
st.columns.side_effect = lambda spec, **kw: [MagicMock() for _ in range(spec if isinstance(spec, int) else len(spec))]
st.tabs.side_effect = lambda names: [MagicMock() for _ in names]
st.date_input.side_effect = lambda *a, **kw: a[1]
st.multiselect.side_effect = lambda label, options, default=None, **kw: default if default is not None else options
import os
CHOICE = {"Period": os.environ.get("SMOKE_PERIOD", "Quarter"), "Show": os.environ.get("SMOKE_METRIC", "Value"),
          "Split by": os.environ.get("SMOKE_SPLIT", "None")}
def _radio(label, options, index=0, **kw): return CHOICE.get(label, list(options)[index])
def _select(label, options, index=0, **kw):
    options = list(options)
    return CHOICE.get(label, options[index] if options else None)
st.selectbox.side_effect = _select
st.radio.side_effect = _radio
st.button.return_value = False; st.checkbox.return_value = True
st.stop.side_effect = SystemExit
sys.modules["streamlit"] = st
sys.modules["plotly"] = MagicMock(); sys.modules["plotly.express"] = MagicMock()
sys.modules["pandas.io.formats.style"] = sys.modules.get("pandas.io.formats.style", MagicMock())

# column widgets return mocks: k1..k5 metrics + c1/c2 in trend tab
src = (ROOT/"app.py").read_text()
# c2.multiselect must behave like the real thing: patch by giving column mocks the same stubs
def mk(): 
    m = MagicMock(); m.selectbox.side_effect = st.selectbox.side_effect; m.radio.side_effect = st.radio.side_effect; m.multiselect.side_effect = st.multiselect.side_effect; return m
st.columns.side_effect = lambda spec, **kw: [mk() for _ in range(spec if isinstance(spec, int) else len(spec))]
exec(compile(src, "app.py", "exec"), {"__name__": "__main__"})
calls = {n: getattr(st, n).call_count for n in ("dataframe", "plotly_chart", "metric", "download_button")}
print("app executed OK:", calls)
print("first snapshot table columns rendered:", list(st.dataframe.call_args_list[0][0][0].columns))

pd.set_option("display.width", 250); pd.set_option("display.max_columns", 30)
snap = st.dataframe.call_args_list[0][0][0]
print(snap[["Company","Product","Currency","Auctions sold","Lots sold","Tonnes sold","Avg lot size (t)","Contract value","Avg bidders"]].to_string(index=False))
print()
for name, call in zip(("by commodity", "by company", "contracts"), st.dataframe.call_args_list[1:4]):
    print("--", name); print(call[0][0].drop(columns=[c for c in call[0][0].columns if c in ("last_auction","commodities","address","quality")], errors="ignore").head(8).to_string(index=False))
print("\nmetrics:", [(c[0][0], c[0][1]) for m in [] for c in m])

for call in st.dataframe.call_args_list:
    d = call[0][0]
    if hasattr(d, "columns") and "Period" in d.columns:
        pd.set_option("display.width", 220)
        print(d.to_string(index=False))
