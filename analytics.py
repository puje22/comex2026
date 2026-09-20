"""Pure-pandas helpers for the dashboard (no Streamlit here, so they can be unit-tested)."""
from __future__ import annotations

import pandas as pd

PERIODS = ["Year", "Half-year", "Quarter", "Month"]
SPLITS = {"None": None, "Company": "company_en", "Commodity": "commodity", "Product": "grade"}


def add_period(dates: pd.Series, period: str) -> pd.DataFrame:
    """Return period label, period start and period end (inclusive) for every date."""
    d = pd.to_datetime(dates)
    if period == "Year":
        start = pd.to_datetime(dict(year=d.dt.year, month=1, day=1))
        label = d.dt.year.astype(str)
        end = start + pd.DateOffset(years=1) - pd.Timedelta(days=1)
    elif period == "Half-year":
        half = (d.dt.month - 1) // 6 + 1
        start = pd.to_datetime(dict(year=d.dt.year, month=(half - 1) * 6 + 1, day=1))
        label = d.dt.year.astype(str) + " H" + half.astype(str)
        end = start + pd.DateOffset(months=6) - pd.Timedelta(days=1)
    elif period == "Quarter":
        start = d.dt.to_period("Q").dt.start_time
        label = d.dt.year.astype(str) + " Q" + d.dt.quarter.astype(str)
        end = start + pd.DateOffset(months=3) - pd.Timedelta(days=1)
    elif period == "Month":
        start = d.dt.to_period("M").dt.start_time
        label = d.dt.strftime("%Y-%m")
        end = start + pd.DateOffset(months=1) - pd.Timedelta(days=1)
    else:
        raise ValueError(f"unknown period {period!r}")
    return pd.DataFrame({"period": label, "period_start": start, "period_end": end})


def sales_by_period(contracts: pd.DataFrame, period: str, split: str = "None",
                    currency: str | None = None, as_of=None) -> pd.DataFrame:
    """Tonnes, contract value and volume-weighted average price per period (and optional group).

    * currency=None  -> all currencies (only meaningful for tonnes)
    * currency="USD" -> only contracts priced in that currency (value / price can't be mixed across currencies)
    * avg_price = sum(contract value) / sum(tonnes), i.e. weighted by volume, never a mean of prices.
    * partial=True marks a period that hasn't finished yet as of `as_of` (default: latest contract date),
      so a quarter-to-date isn't mistaken for a full quarter.
    """
    cols = ["period", "period_start", "group", "contracts", "tonnes", "lots", "value", "avg_price", "partial"]
    if contracts is None or contracts.empty:
        return pd.DataFrame(columns=cols)
    df = contracts.copy()
    df["date"] = pd.to_datetime(df["date"])
    as_of = pd.Timestamp(as_of) if as_of is not None else df["date"].max()
    if currency:
        df = df[df["currency"] == currency]
        if df.empty:
            return pd.DataFrame(columns=cols)
    df = df.join(add_period(df["date"], period))
    gcol = SPLITS[split]
    df["group"] = df[gcol].fillna("Unknown") if gcol else "All"
    # value and tonnes only from rows that have BOTH, so the weighted average is consistent
    both = df["total_value"].notna() & df["quantity_t"].notna()
    df["_val_both"] = df["total_value"].where(both)
    df["_qty_both"] = df["quantity_t"].where(both)
    g = df.groupby(["period", "period_start", "period_end", "group"], as_index=False).agg(
        contracts=("product_code", "count"), tonnes=("quantity_t", "sum"), lots=("lots", "sum"),
        value=("total_value", "sum"), _v=("_val_both", "sum"), _q=("_qty_both", "sum"))
    g["avg_price"] = (g["_v"] / g["_q"]).where(g["_q"] > 0)
    g["partial"] = g["period_end"] > as_of
    g = g.sort_values(["period_start", "group"]).reset_index(drop=True)
    return g[cols]


def add_change(agg: pd.DataFrame, metric_col: str) -> pd.DataFrame:
    """% change of `metric_col` versus the previous period, within each group."""
    out = agg.sort_values(["group", "period_start"]).copy()
    out["change_pct"] = out.groupby("group")[metric_col].pct_change() * 100
    return out.sort_values(["period_start", "group"]).reset_index(drop=True)
