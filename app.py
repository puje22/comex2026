"""
MSE COMEX mining-products dashboard (Streamlit).

Run locally:   streamlit run app.py
Data comes from data/trades.csv, which is refreshed
  * by the GitHub Action (.github/workflows/update.yml) on a schedule, and
  * by this app itself when the data is older than STALE_AFTER_HOURS.
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd
import plotly.express as px
import streamlit as st

import analytics
import scraper

STALE_AFTER_HOURS = 3

st.set_page_config(page_title="MSE COMEX Dashboard", page_icon="⛏️", layout="wide")


# ---------------------------------------------------------------- data loading
@st.cache_resource(ttl=STALE_AFTER_HOURS * 3600, show_spinner="Checking COMEX for new auctions…")
def auto_refresh() -> dict:
    """Runs at most once per STALE_AFTER_HOURS per server process (shared by all visitors)."""
    try:
        first_run = not scraper.TRADES_CSV.exists()
        result = scraper.update_all(full=first_run, log=lambda *_: None)
        return {"ok": True, "at": datetime.now(), "error": None, **result}
    except Exception as e:  # keep serving the last good CSV
        return {"ok": False, "at": datetime.now(), "error": str(e)}


@st.cache_data(show_spinner=False)
def load_trades(file_mtime: float) -> pd.DataFrame:  # file_mtime busts the cache on update
    df = scraper.load_trades()
    if df.empty:
        return df
    df["trade_time"] = pd.to_datetime(df["trade_time"])
    df["date"] = pd.to_datetime(df["date"])
    df["month"] = df["date"].dt.to_period("M").dt.to_timestamp()
    df["premium_pct"] = (df["final_price"] / df["start_price"] - 1) * 100
    df["label"] = df["grade"] + " (" + df["currency"].fillna("?") + ")"
    return df.sort_values("trade_time")


@st.cache_data(show_spinner=False)
def load_contracts(file_mtime: float) -> pd.DataFrame:
    df = scraper.load_contracts()
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
    return df


@st.cache_data(show_spinner=False)
def load_notices(file_mtime: float) -> pd.DataFrame:
    df = scraper.load_notices()
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
    return df


def mtime(path) -> float:
    return path.stat().st_mtime if path.exists() else 0.0


def contract_summary(c: pd.DataFrame, by: str) -> pd.DataFrame:
    """Executed contracts: count, lots, tonnes, average bidders and contract value (one column per currency)."""
    if c.empty:
        return pd.DataFrame({by: []})
    g = c.groupby(by).agg(contracts=("product_code", "count"), lots=("lots", "sum"),
                          tonnes=("quantity_t", "sum"), avg_bidders=("bidders", "mean"))
    val = c.pivot_table(index=by, columns="currency", values="total_value", aggfunc="sum")
    val.columns = [f"Contract value {x}" for x in val.columns]
    return g.join(val).reset_index()


def contract_cols(table: pd.DataFrame) -> dict:
    cfg = {"contracts": st.column_config.NumberColumn("Contracts", format="%.0f"),
           "lots": st.column_config.NumberColumn("Lots", format="%.0f"),
           "tonnes": st.column_config.NumberColumn("Tonnes", format="%.0f"),
           "avg_bidders": st.column_config.NumberColumn("Avg bidders", format="%.1f")}
    for c in table.columns:
        if c.startswith("Contract value"):
            cfg[c] = st.column_config.NumberColumn(format="%.0f")
    return cfg


status = auto_refresh()
trades_all = load_trades(mtime(scraper.TRADES_CSV))
contracts_all = load_contracts(mtime(scraper.CONTRACTS_CSV))
notices = load_notices(mtime(scraper.NOTICES_CSV))

st.title("⛏️ MSE COMEX – Mining Products Auctions")
if trades_all.empty:
    st.error("No data yet. Run `python scraper.py --full` once, or check the error below.")
    if status.get("error"):
        st.code(status["error"])
    st.stop()

# -------------------------------------------------------------------- sidebar
with st.sidebar:
    st.header("Filters")
    dmin, dmax = trades_all["date"].min().date(), trades_all["date"].max().date()
    default_start = max(dmin, (trades_all["date"].max() - pd.Timedelta(days=365)).date())
    date_range = st.date_input("Date range", (default_start, dmax), min_value=dmin, max_value=dmax)
    if isinstance(date_range, tuple) and len(date_range) == 2:
        d_from, d_to = date_range
    else:
        d_from, d_to = dmin, dmax

    commodities = sorted(trades_all["commodity"].dropna().unique())
    sel_comm = st.multiselect("Commodity", commodities, default=commodities)
    companies = sorted(trades_all["company_en"].dropna().unique())
    sel_comp = st.multiselect("Company", companies, default=companies)

    st.divider()
    if st.button("🔄 Refresh now", use_container_width=True):
        with st.spinner("Scraping COMEX…"):
            try:
                scraper.update_all(log=lambda *_: None)
                st.cache_data.clear()
                st.rerun()
            except Exception as e:
                st.error(f"Refresh failed: {e}")
    last_scrape = datetime.fromtimestamp(mtime(scraper.TRADES_CSV)).strftime("%Y-%m-%d %H:%M")
    st.caption(f"Data file updated: {last_scrape}")
    if not status["ok"]:
        st.warning(f"Last auto-refresh failed – showing saved data.\n\n{status['error']}")
    for err in status.get("errors", []):
        st.warning(f"Refresh problem – {err}")
    n_c = len(contracts_all)
    st.caption(f"Contracts loaded: {n_c:,}" + (f" ({contracts_all['date'].min():%Y-%m-%d} → {contracts_all['date'].max():%Y-%m-%d})" if n_c else ""))

mask = (
    (trades_all["date"].dt.date >= d_from) & (trades_all["date"].dt.date <= d_to)
    & trades_all["commodity"].isin(sel_comm) & trades_all["company_en"].isin(sel_comp)
)
df = trades_all[mask].copy()
sold = df[df["status"] == "sold"]

if df.empty:
    st.info("No trades match the current filters.")
    st.stop()

# ----------------------------------------------------------------------- KPIs
k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Auctions", f"{len(df):,}")
k2.metric("Sold", f"{len(sold):,}")
k3.metric("No-bid rate", f"{(df['status'] == 'no_bid').mean() * 100:.0f}%")
k4.metric("Avg premium over start", f"{sold['premium_pct'].mean():.1f}%" if len(sold) else "–")
k5.metric("Latest auction", df["trade_time"].max().strftime("%Y-%m-%d"))

if contracts_all.empty:
    cf = contracts_all
else:
    cf = contracts_all[
        (contracts_all["date"].dt.date >= d_from) & (contracts_all["date"].dt.date <= d_to)
        & contracts_all["commodity"].isin(sel_comm) & contracts_all["company_en"].isin(sel_comp)
    ].copy()
val_by_ccy = cf.groupby("currency")["total_value"].sum() if len(cf) else pd.Series(dtype=float)
v1, v2, v3, v4, v5 = st.columns(5)
v1.metric("Tonnes traded", f"{cf['quantity_t'].sum():,.0f}" if len(cf) else "–")
v2.metric("Contract value USD", f"${val_by_ccy.get('USD', 0):,.0f}")
v3.metric("Contract value CNY", f"¥{val_by_ccy.get('CNY', 0):,.0f}")
v4.metric("Avg bidders / auction", f"{cf['bidders'].mean():.1f}" if len(cf) and cf["bidders"].notna().any() else "–")
v5.metric("Contract data coverage", f"{len(cf)} of {len(sold)} sold")
st.caption("Contract value, lots and tonnes come from the exchange's own daily trading reports (total contract value "
           "= deal price × tonnes). It is the sellers' sales value, not profit. USD and CNY are never added together. "
           + ("" if len(cf) >= len(sold) else
              ("No daily reports are loaded yet (see the Contracts tab). " if contracts_all.empty else
               "Some sold auctions have no daily report loaded yet, so totals may be understated.")))

tab_snap, tab_period, tab_trend, tab_comm, tab_comp, tab_contracts, tab_raw, tab_notice = st.tabs(
    ["📊 Latest prices", "📆 Sales by period", "📈 Price trends", "🪨 By commodity", "🏢 By company",
     "📑 Contracts", "🧾 All trades", "📅 Auction notices"]
)

# ------------------------------------------------------------- latest prices
with tab_snap:
    st.subheader("Latest sold price per product")
    if sold.empty:
        st.info("No sold auctions in this selection.")
    else:
        rows = []
        for (comm, comp, label), g in sold.groupby(["commodity", "company_en", "label"]):
            g = g.sort_values("trade_time")
            last = g.iloc[-1]
            prev = g.iloc[-2]["final_price"] if len(g) > 1 else None
            cg = cf[(cf["commodity"] == comm) & (cf["company_en"] == comp)
                    & (cf["grade"] == last["grade"]) & (cf["currency"] == last["currency"])] if len(cf) else cf
            tot_lots = cg["lots"].sum() if len(cg) else 0
            rows.append({
                "Commodity": comm, "Company": comp, "Product": last["grade"], "Currency": last["currency"],
                "Last price": last["final_price"], "Start price": last["start_price"],
                "Previous sold": prev,
                "Δ vs previous %": (last["final_price"] / prev - 1) * 100 if prev else None,
                "Last sold on": last["trade_time"].strftime("%Y-%m-%d"),
                "Auctions sold": len(g),
                "Lots sold": tot_lots if len(cg) else None,
                "Tonnes sold": cg["quantity_t"].sum() if len(cg) else None,
                "Avg lot size (t)": cg["quantity_t"].sum() / tot_lots if tot_lots else None,
                "Contract value": cg["total_value"].sum() if len(cg) else None,
                "Avg bidders": cg["bidders"].mean() if len(cg) else None,
            })
        snap = pd.DataFrame(rows).sort_values(["Commodity", "Last sold on"], ascending=[True, False])
        st.dataframe(
            snap, hide_index=True, use_container_width=True,
            column_config={
                "Last price": st.column_config.NumberColumn(format="%.2f"),
                "Start price": st.column_config.NumberColumn(format="%.2f"),
                "Previous sold": st.column_config.NumberColumn(format="%.2f"),
                "Δ vs previous %": st.column_config.NumberColumn(format="%+.2f%%"),
                "Lots sold": st.column_config.NumberColumn(format="%.0f"),
                "Tonnes sold": st.column_config.NumberColumn(format="%.0f"),
                "Avg lot size (t)": st.column_config.NumberColumn(format="%.0f"),
                "Contract value": st.column_config.NumberColumn(format="%.0f", help="In the product's currency"),
                "Avg bidders": st.column_config.NumberColumn(format="%.1f"),
            },
        )
        st.caption("Prices are in each product's auction currency (coal from some sellers is quoted in CNY). "
                   "Auctions with no buyer bid are excluded here. 'Auctions sold' counts auctions; lots, tonnes and "
                   "contract value are the exchange-reported totals for those auctions.")

# --------------------------------------------------------------- price trends
# ------------------------------------------------------------ sales by period
with tab_period:
    st.subheader("Sales by year / half-year / quarter")
    if cf.empty:
        st.info("No contract data for the current filters – see the Contracts tab for why.")
    else:
        c1, c2, c3, c4 = st.columns([1.4, 1.4, 1, 1])
        period = c1.radio("Period", analytics.PERIODS, index=2, horizontal=True)
        metric = c2.radio("Show", ["Value", "Tonnes", "Average price"], horizontal=True)
        split_label = c3.selectbox("Split by", list(analytics.SPLITS), index=0)
        needs_ccy = metric != "Tonnes"
        ccys = sorted(cf["currency"].dropna().unique())
        currency = c4.selectbox("Currency", ccys, index=ccys.index("USD") if "USD" in ccys else 0,
                                disabled=not needs_ccy)
        products = sorted(cf["grade"].dropna().unique())
        with st.expander(f"Products included ({len(products)})"):
            sel_products = st.multiselect("Products", products, default=products, label_visibility="collapsed")
        scope = cf[cf["grade"].isin(sel_products)]

        if metric == "Average price" and split_label == "None":
            split_label = "Product"
            st.caption("Average price is shown per product, because prices of different products "
                       "(e.g. coking coal at $190/t vs iron ore at $65/t) can't be averaged together.")
        elif metric == "Average price" and split_label in ("Company", "Commodity"):
            st.caption(f"Note: splitting by {split_label.lower()} mixes different grades; use “Product” for like-for-like prices.")

        agg = analytics.sales_by_period(scope, period, split_label, currency if needs_ccy else None,
                                        as_of=contracts_all["date"].max())
        if agg.empty:
            st.info("Nothing to show for this selection.")
        else:
            agg["label"] = agg["period"] + agg["partial"].map({True: " (to date)", False: ""})
            order = agg.drop_duplicates("period").sort_values("period_start")["label"].tolist()
            ycol, ytitle = {
                "Value": ("value", f"Contract value ({currency})"),
                "Tonnes": ("tonnes", "Tonnes"),
                "Average price": ("avg_price", f"Average price ({currency} per tonne, volume-weighted)"),
            }[metric]
            labels = {"label": "", ycol: ytitle, "group": split_label if split_label != "None" else ""}
            if metric == "Average price":
                fig = px.line(agg, x="label", y=ycol, color="group", markers=True, labels=labels,
                              category_orders={"label": order}, hover_data={"contracts": True, "tonnes": ":,.0f"})
            else:
                fig = px.bar(agg, x="label", y=ycol, color="group", labels=labels,
                             barmode="stack" if split_label != "None" else "group",
                             category_orders={"label": order}, hover_data={"contracts": True})
            fig.update_layout(height=470, legend_title_text="", margin=dict(t=20),
                              showlegend=split_label != "None" or metric == "Average price")
            fig.update_yaxes(tickformat=",.0f" if metric != "Average price" else ",.2f")
            st.plotly_chart(fig, use_container_width=True)

            tbl = analytics.add_change(agg, ycol)
            tbl = tbl.sort_values(["period_start", "group"], ascending=False)
            tbl["Period"] = tbl["label"]
            show = tbl[["Period", "group", "contracts", "tonnes", "lots", "value", "avg_price", "change_pct"]]
            show = show.rename(columns={"group": split_label if split_label != "None" else "Group"})
            st.dataframe(show, hide_index=True, use_container_width=True, column_config={
                "contracts": st.column_config.NumberColumn("Contracts", format="%.0f"),
                "tonnes": st.column_config.NumberColumn("Tonnes", format="%.0f"),
                "lots": st.column_config.NumberColumn("Lots", format="%.0f"),
                "value": st.column_config.NumberColumn(f"Value{f' ({currency})' if needs_ccy else ''}", format="%.0f"),
                "avg_price": st.column_config.NumberColumn(f"Avg price{f' ({currency}/t)' if needs_ccy else ''}", format="%.2f"),
                "change_pct": st.column_config.NumberColumn(f"Δ {ytitle.split(' (')[0].lower()} vs previous period", format="%+.1f%%"),
            })
            st.download_button("⬇️ Download this table (CSV)", show.to_csv(index=False).encode("utf-8-sig"),
                               file_name=f"comex_sales_by_{period.lower()}.csv", mime="text/csv")

            notes = [f"Based on {len(scope):,} contracts from {scope['date'].min():%Y-%m-%d} to {scope['date'].max():%Y-%m-%d} "
                     "(the auction date; forward contracts, so delivery and payment can fall in a later period)."]
            if agg["partial"].any():
                notes.append("Periods marked “(to date)” are not finished yet – don't compare them with full periods.")
            if needs_ccy:
                other = scope[scope["currency"] != currency]
                if len(other):
                    tot = other.groupby("currency")["total_value"].sum()
                    notes.append("Not included (different currency): " + ", ".join(f"{v:,.0f} {c}" for c, v in tot.items()) + ".")
            if (scope["quantity_source"].fillna("").str.startswith("implied")).any():
                notes.append("Molybdenum tonnes are implied from contract value ÷ price.")
            st.caption(" ".join(notes))

with tab_trend:
    c1, c2 = st.columns([1, 2])
    comm = c1.selectbox("Commodity", sorted(sold["commodity"].unique()) if len(sold) else [])
    sub = sold[sold["commodity"] == comm] if comm else sold.iloc[0:0]
    labels = sorted(sub["label"].unique())
    pick = c2.multiselect("Products", labels, default=labels[: min(3, len(labels))])
    show_start = st.checkbox("Also show starting (reserve) price", value=False)
    sub = sub[sub["label"].isin(pick)]
    if sub.empty:
        st.info("Nothing to plot for this selection.")
    else:
        fig = px.line(sub, x="trade_time", y="final_price", color="label", markers=True,
                      labels={"trade_time": "", "final_price": "Final price", "label": "Product"},
                      hover_data={"company_en": True, "start_price": ":.2f", "premium_pct": ":.2f"})
        if show_start:
            for lab, g in sub.groupby("label"):
                fig.add_scatter(x=g["trade_time"], y=g["start_price"], mode="lines",
                                line=dict(dash="dot"), name=f"{lab} – start", opacity=0.6)
        fig.update_layout(height=480, legend_title_text="", margin=dict(t=20))
        st.plotly_chart(fig, use_container_width=True)

# ---------------------------------------------------------------- by commodity
with tab_comm:
    g = df.groupby("commodity").agg(
        auctions=("trade_id", "count"),
        sold=("status", lambda s: (s == "sold").sum()),
        avg_premium_pct=("premium_pct", "mean"),
        last_auction=("trade_time", "max"),
    )
    g["no_bid_rate_%"] = (1 - g["sold"] / g["auctions"]) * 100
    tbl = g.reset_index().merge(contract_summary(cf, "commodity"), on="commodity", how="left").rename(columns={"commodity": "Commodity"})
    st.dataframe(tbl, hide_index=True, use_container_width=True,
                 column_config={"avg_premium_pct": st.column_config.NumberColumn("Avg premium %", format="%.2f"),
                                "no_bid_rate_%": st.column_config.NumberColumn("No-bid rate %", format="%.0f"),
                                **contract_cols(tbl)})
    monthly = df.groupby(["month", "commodity", "status"]).size().reset_index(name="auctions")
    fig = px.bar(monthly, x="month", y="auctions", color="commodity", pattern_shape="status",
                 labels={"month": "", "auctions": "Auctions"}, title="Auctions per month (hatched = no bid)")
    fig.update_layout(height=420)
    st.plotly_chart(fig, use_container_width=True)

# ------------------------------------------------------------------ by company
with tab_comp:
    g = df.groupby("company_en").agg(
        auctions=("trade_id", "count"),
        sold=("status", lambda s: (s == "sold").sum()),
        avg_premium_pct=("premium_pct", "mean"),
        commodities=("commodity", lambda s: ", ".join(sorted(set(s)))),
        last_auction=("trade_time", "max"),
    ).sort_values("auctions", ascending=False)
    g["no_bid_rate_%"] = (1 - g["sold"] / g["auctions"]) * 100
    tbl = g.reset_index().merge(contract_summary(cf, "company_en"), on="company_en", how="left").rename(columns={"company_en": "Company"})
    st.dataframe(tbl, hide_index=True, use_container_width=True,
                 column_config={"avg_premium_pct": st.column_config.NumberColumn("Avg premium %", format="%.2f"),
                                "no_bid_rate_%": st.column_config.NumberColumn("No-bid rate %", format="%.0f"),
                                **contract_cols(tbl)})
    by_status = df.groupby(["company_en", "status"]).size().reset_index(name="auctions")
    fig = px.bar(by_status, x="auctions", y="company_en", color="status", orientation="h",
                 labels={"company_en": "", "auctions": "Auctions"}, title="Auctions by company")
    fig.update_layout(height=380, yaxis={"categoryorder": "total ascending"})
    st.plotly_chart(fig, use_container_width=True)

    st.subheader("Company drill-down")
    who = st.selectbox("Company", list(g.index))
    cs = sold[sold["company_en"] == who]
    if cs.empty:
        st.info("No sold auctions for this company in the selected range.")
    else:
        fig = px.line(cs, x="trade_time", y="final_price", color="label", markers=True,
                      labels={"trade_time": "", "final_price": "Final price", "label": "Product"})
        fig.update_layout(height=420, legend_title_text="")
        st.plotly_chart(fig, use_container_width=True)

# ------------------------------------------------------------------ contracts
with tab_contracts:
    if cf.empty and contracts_all.empty:
        st.warning("`data/contracts.csv` is missing or empty, so no daily trading reports have been loaded at all. "
                   "Run `python scraper.py --full` (look for the line 'Done … N contracts'; any 'contracts failed' or "
                   "'0 contracts parsed' message tells you what went wrong). On Streamlit Cloud the file must be committed "
                   "to the repo – the GitHub Action does this on its first run.")
    elif cf.empty:
        st.info(f"{len(contracts_all):,} contracts are loaded ({contracts_all['date'].min():%Y-%m-%d} → "
                f"{contracts_all['date'].max():%Y-%m-%d}) but none match the current date / commodity / company filters.")
    else:
        ct = cf.sort_values(["date", "product_code"], ascending=False)
        cols = ["date", "product_code", "registration_no", "company_en", "commodity", "grade", "bidders", "currency",
                "start_price", "deal_price", "premium_pct", "lots", "quantity_t", "total_value", "quantity_source", "quality"]
        st.dataframe(ct[cols], hide_index=True, use_container_width=True, column_config={
            "date": st.column_config.DateColumn("Date"),
            "total_value": st.column_config.NumberColumn("Contract value", format="%.0f"),
            "quantity_t": st.column_config.NumberColumn("Tonnes", format="%.0f"),
            "premium_pct": st.column_config.NumberColumn("Premium %", format="%.2f"),
            "quantity_source": "Tonnes source",
        })
        implied = (ct["quantity_source"].fillna("").str.startswith("implied")).sum()
        if implied:
            st.caption(f"{implied} contract(s) (e.g. molybdenum) only print the lot count, so tonnes = contract value ÷ price.")
        st.download_button("⬇️ Download contracts (CSV)", ct[cols].to_csv(index=False).encode("utf-8-sig"),
                           file_name="comex_contracts.csv", mime="text/csv")

# ------------------------------------------------------------------- raw data
with tab_raw:
    show_cols = ["trade_time", "trade_id", "company_en", "commodity", "grade", "currency",
                 "start_price", "final_price", "change", "change_pct", "status"]
    table = df.sort_values("trade_time", ascending=False)[show_cols]
    st.dataframe(table, hide_index=True, use_container_width=True)
    st.download_button("⬇️ Download filtered trades (CSV)", table.to_csv(index=False).encode("utf-8-sig"),
                       file_name="comex_trades.csv", mime="text/csv")

# -------------------------------------------------------------------- notices
with tab_notice:
    if notices.empty:
        st.info("No auction notices scraped yet.")
    else:
        nt = notices.sort_values(["date", "time"], ascending=False)
        st.dataframe(
            nt[["date", "time", "company_en", "code", "commodity", "grade", "currency",
                "start_price", "lots", "quantity_t", "pdf_url"]],
            hide_index=True, use_container_width=True,
            column_config={"pdf_url": st.column_config.LinkColumn("Schedule PDF", display_text="open"),
                           "date": st.column_config.DateColumn("Date")},
        )
        st.caption("Recent notices as shown on the COMEX dashboard (start price, number of lots, tonnage).")

st.divider()
st.caption("Source: comex.mse.mn (Mongolian Stock Exchange). Unofficial dashboard – verify important figures "
           "on the official site.")
