# MSE COMEX dashboard

Scrapes https://comex.mse.mn (Mongolian Stock Exchange mining-products auctions: coal, iron ore,
fluorspar, copper, molybdenum) and shows prices by commodity and by seller company.

```
scraper.py                     fetch + parse comex.mse.mn  ->  data/trades.csv, contracts.csv, notices.csv
analytics.py                   period aggregation (year / half-year / quarter / month) - unit-tested
app.py                         Streamlit dashboard
.github/workflows/update.yml   scheduled scrape every 2h, commits fresh CSVs to the repo
tests/                         parser / update-logic tests
```

## 1. Try it locally (5 minutes)

```bash
pip install -r requirements.txt
python scraper.py --debug      # FIRST: check that page 1 parses (should say "parsed: ~35 trades")
python scraper.py --full       # crawl the whole history (~99 pages, 2-3 min), writes data/trades.csv
streamlit run app.py
```

If `--debug` prints `parsed: 0 trades`, the site's wording/layout differs from what the parser expects.
Paste the printed text to Claude and the regexes in `scraper.py` can be adjusted in minutes.

## 2. Put it online for free (Streamlit Community Cloud + GitHub Actions)

1. Create a GitHub repo and push this folder (commit `data/trades.csv` from step 1 too).
2. Go to https://share.streamlit.io -> **New app** -> pick the repo, branch `main`, main file `app.py` -> Deploy.
3. In the repo's **Actions** tab, enable workflows and press **Run workflow** once on "Update COMEX data".
   From then on GitHub scrapes every 2 hours and commits the new CSV; Streamlit redeploys/reloads from the repo.
   The app *also* refreshes itself when it is opened and the data is older than 3 hours (`STALE_AFTER_HOURS` in `app.py`).

Other free hosts that work the same way: Hugging Face Spaces (Streamlit SDK), Render, Railway.

## Notes

* Please keep the request delay (`REQUEST_DELAY` in `scraper.py`) - it's a public exchange website.
* Check the site's terms of use before redistributing the data.
* Add new commodities / companies / grade translations in the lookup tables at the top of `scraper.py`. Edits apply to already-scraped data automatically (names are re-derived from the raw text on load).
* Note: "Эрдэнэс Тавантолгой ХК" (Erdenes Tavan Tolgoi, state-owned) and "Тавантолгой ХК" (Tavan Tolgoi JSC, MSE-listed) are different companies and are kept separate.
* Failed auctions ("no buyer bid") are kept with status `no_bid` and an empty final price.

## Lots, tonnes and contract value

These come from the exchange's own **daily trading reports** (`/show_trading_infos/YYYY-MM-DD`), one page per day
with one column per executed trade: contract value, lots, tonnes, deal price, number of bidders, seller, quality specs.
The scraper fetches the report for every date that had a sold auction and stores them in `data/contracts.csv`.

* Contract value is the exchange-reported total (deal price x tonnes). It is the sellers' sales value, not profit.
* USD and CNY are never added together.
* Some products (molybdenum) print only the lot count. Tonnes are then implied = contract value / price
  (flagged in the `quantity_source` column).
* Dates with no report page are remembered in `data/contracts_no_page.txt` and not re-requested.
* First run: `python scraper.py --full` fetches every report (about 1 request per trading day).
  Later runs are incremental. If a day parses as 0 contracts, run
  `python scraper.py --debug-contracts 2026-09-11` and send the output so the parser can be adjusted.

## Sales by period (chart tab)

Pick **Year / Half-year / Quarter / Month**, show **Value, Tonnes or Average price**, and optionally split by
company, commodity or product. The sidebar filters (dates, commodity, company) apply.

* Average price = total contract value / total tonnes (volume-weighted), calculated per product. It is never an
  average of prices, and never mixes different products unless you split by company/commodity (the app warns).
* Value and average price are shown in one currency at a time (USD or CNY are never added together);
  what was left out is listed under the chart.
* A period that hasn't finished is labelled "(to date)". Don't compare it with a full quarter or year.
* Contracts are dated by auction day. They are forward contracts, so delivery and payment can fall later.
