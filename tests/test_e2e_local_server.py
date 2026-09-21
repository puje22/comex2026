"""End-to-end: real fetch()/requests against a local HTTP server that mimics comex.mse.mn."""
import sys, threading, tempfile, pathlib, http.server, socketserver
ROOT = pathlib.Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT/"tests"))
import scraper, pandas as pd
from test_parsers import TRADES_HTML, NOTICE_HTML
from test_contracts import D0911, D0910, html_table

PAGES = {"/show-trades": TRADES_HTML, "/home": NOTICE_HTML,
         "/show_trading_infos/2026-09-11": html_table(D0911), "/show_trading_infos/2026-09-10": html_table(D0910)}
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?")[0]
        if path in PAGES:
            body = PAGES[path].encode("utf-8"); self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=UTF-8"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
        else:
            self.send_response(404); self.end_headers()
    def log_message(self, *a): pass

srv = socketserver.TCPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
tmp = pathlib.Path(tempfile.mkdtemp())
scraper.BASE = f"http://127.0.0.1:{srv.server_address[1]}"; scraper.REQUEST_DELAY = 0
scraper.DATA_DIR = tmp
scraper.TRADES_CSV, scraper.NOTICES_CSV, scraper.CONTRACTS_CSV, scraper.CONTRACTS_GONE = tmp/"trades.csv", tmp/"notices.csv", tmp/"contracts.csv", tmp/"gone.txt"

def reset():
    for f in tmp.glob("*"): f.unlink()

def run(full):
    logs = []
    res = scraper.update_all(full=full, log=logs.append)
    return res, logs

# 1) full crawl through update_all()  (this is what `python scraper.py --full` does)
res, logs = run(full=True)
c = scraper.load_contracts()
assert res["errors"] == [], res["errors"]
assert len(c) == 8 and sorted(set(c["date"])) == ["2026-09-10", "2026-09-11"], (res, len(c))
assert c["total_value"].sum() == 16384000 + 19558400*2 + 18496000 + 15803377 + 4480000 + 24678400 + 438900
tt = c[c["company_en"] == "Tavan Tolgoi JSC"]
assert len(tt) == 5 and tt["quantity_t"].sum() == 102400*3 + 64000 + 204800
print("full crawl OK:", res["contracts"], "contracts parsed; Tavan Tolgoi JSC tonnes =", tt["quantity_t"].sum())

# 2) what the Streamlit app does: trades.csv already exists, contracts.csv does not -> incremental refresh
scraper.CONTRACTS_CSV.unlink(); scraper.CONTRACTS_GONE.unlink(missing_ok=True)
res, logs = run(full=False)
assert res["errors"] == [] and len(scraper.load_contracts()) == 8, (res, logs[-4:])
print("incremental refresh with no contracts.csv OK")

# 3) main() exit code + summary line
import io, contextlib
scraper.CONTRACTS_CSV.unlink()
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    sys.argv = ["scraper.py"]; rc = scraper.main()
assert rc == 0 and "8 contracts" in buf.getvalue(), buf.getvalue()[-200:]
print("main() OK:", buf.getvalue().strip().splitlines()[-1])

# 4) a failing contracts step must be reported, not swallowed
orig = scraper.update_contracts
scraper.update_contracts = lambda **k: (_ for _ in ()).throw(RuntimeError("boom"))
res, _ = run(full=False)
assert res["errors"] and "boom" in res["errors"][0]
scraper.update_contracts = orig
print("errors are surfaced OK")
