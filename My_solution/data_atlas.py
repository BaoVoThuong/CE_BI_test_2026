"""Profile every supplied field and relationships that affect interpretation.

Run: python My_solution/data_atlas.py
Outputs are descriptive. Rare combinations and regular patterns are flags for
source-system review, not automatic proof of bad transactions.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "My_solution" / "outputs" / "data_atlas"
OUT.mkdir(parents=True, exist_ok=True)
tx = pd.read_csv(ROOT / "data.csv", parse_dates=["trxn_date"])
tx["month"] = tx.trxn_date.dt.to_period("M")
tx["seq"] = tx.transaction_id.str.removeprefix("TXN").astype(int)
assert tx.transaction_id.is_unique

columns = pd.DataFrame({
    "column": [c for c in tx if c not in ("month", "seq")],
    "missing": [int(tx[c].isna().sum()) for c in tx if c not in ("month", "seq")],
    "distinct": [int(tx[c].nunique()) for c in tx if c not in ("month", "seq")],
})
columns.to_csv(OUT / "field_profile.csv", index=False)

package_carrier = tx.groupby(["package_code", "carrier"]).agg(
    transactions=("transaction_id", "size"),
    mean_ticket_vnd=("trxn_amount", "mean"),
    gmv_vnd=("trxn_amount", "sum"),
).reset_index().sort_values(["transactions", "package_code"])
package_carrier.to_csv(OUT / "package_carrier_pairs.csv", index=False, float_format="%.2f")
rare_pairs = package_carrier[package_carrier.transactions < 10]
rare_pair_keys = set(zip(rare_pairs.package_code, rare_pairs.carrier))
rare_pair_rows = tx[["package_code", "carrier"]].apply(tuple, axis=1).isin(rare_pair_keys)

package_month = pd.crosstab(tx.month, tx.package_code, normalize="index")
package_month.to_csv(OUT / "package_mix_by_month.csv", float_format="%.5f")
package_ticket = tx.groupby("package_code").trxn_amount.agg(
    transactions="size", mean_ticket_vnd="mean", median_ticket_vnd="median"
)
package_ticket.to_csv(OUT / "package_ticket.csv", float_format="%.2f")

# Export/ID structure.
sorted_by_id = tx.sort_values("seq")
blocks = (sorted_by_id.user_id != sorted_by_id.user_id.shift()).cumsum()
block_count_by_user = blocks.groupby(sorted_by_id.user_id).nunique()
first_block_end = len(tx) - int((block_count_by_user > 1).sum())
tail = sorted_by_id.iloc[first_block_end:]

# Temporal regularity and activation waves.
first_date = tx.groupby("user_id").trxn_date.min()
new_by_month = first_date.dt.to_period("M").value_counts().sort_index()
timeline = np.arange(len(new_by_month))
log_new = np.log(new_by_month.values)
trend = np.polyfit(timeline, log_new, 1)
fitted = np.polyval(trend, timeline)
loglinear_r2 = 1 - float(((log_new - fitted) ** 2).sum() / ((log_new - log_new.mean()) ** 2).sum())
daily = tx.groupby("trxn_date").size()
weekday_index = daily.groupby(daily.index.dayofweek).mean() / daily.mean()
daily_month = daily.groupby(daily.index.to_period("M"))
within_month_cv = daily_month.std() / daily_month.mean()
daily_summary = pd.DataFrame({
    "daily_mean": daily_month.mean(), "daily_cv": within_month_cv,
    "poisson_cv_at_same_mean": 1 / np.sqrt(daily_month.mean()),
})
daily_summary.to_csv(OUT / "daily_regularity_by_month.csv", float_format="%.5f")
weekday_index.rename("volume_vs_daily_mean").to_csv(OUT / "weekday_index.csv")

# Balance semantics. Previous means previous recorded transaction, with
# same-day ordering by transaction ID; the source has no balance timestamp.
ordered = tx.sort_values(["user_id", "trxn_date", "transaction_id"])
previous = ordered.groupby("user_id").total_outstanding.shift()
at_limit = ordered.total_outstanding == ordered.total_limit
last_in_user_month = ordered.groupby(["user_id", "month"]).last()
util_last = last_in_user_month.total_outstanding / last_in_user_month.total_limit
balance_metrics = {
    "first_transaction_balance_below_purchase_share": float(
        (ordered.loc[previous.isna(), "total_outstanding"]
         < ordered.loc[previous.isna(), "trxn_amount"]).mean()
    ),
    "transactions_at_limit": int(at_limit.sum()),
    "transactions_at_limit_with_prior_recorded_balance_at_limit": int(
        ((previous == ordered.total_limit) & at_limit).sum()
    ),
    "transactions_above_limit": int((ordered.total_outstanding > ordered.total_limit).sum()),
    "users_with_multiple_limit_values": int((tx.groupby("user_id").total_limit.nunique() > 1).sum()),
    "median_last_recorded_utilisation_per_user_month": float(util_last.median()),
    "user_months_at_or_above_80pct_limit_share": float((util_last >= .8).mean()),
}

# Anomaly table without declaring a transaction invalid.
anomalies = pd.DataFrame([
    {"check": "Rare package/carrier pairs (<10 records)", "count": int(rare_pairs.transactions.sum()),
     "meaning": "Source mapping needed; rarity alone is not an error"},
    {"check": "Rows appended after contiguous per-user ID blocks", "count": len(tail),
     "meaning": "Could be backfill or an injected batch; confirm source"},
    {"check": "First balance below first purchase", "count": int((ordered.loc[previous.isna(), "total_outstanding"]
                                                                  < ordered.loc[previous.isna(), "trxn_amount"]).sum()),
     "meaning": "Balance timestamp/definition is unknown"},
    {"check": "Purchase when prior and current recorded balances equal limit",
     "count": balance_metrics["transactions_at_limit_with_prior_recorded_balance_at_limit"],
     "meaning": "Balance may be capped or transaction/balance times may differ"},
])
anomalies.to_csv(OUT / "anomaly_register.csv", index=False)

summary = {
    "rows": len(tx), "users": tx.user_id.nunique(),
    "date_range": [str(tx.trxn_date.min().date()), str(tx.trxn_date.max().date())],
    "months": tx.month.nunique(), "null_cells": int(tx.isna().sum().sum()),
    "duplicate_transaction_ids": int(tx.transaction_id.duplicated().sum()),
    "user_ids_complete_range": bool(
        tx.user_id.nunique() == tx.user_id.max() - tx.user_id.min() + 1
    ),
    "transaction_ids_complete_range": bool(
        tx.seq.nunique() == tx.seq.max() - tx.seq.min() + 1
    ),
    "users_with_one_contiguous_id_block": int((block_count_by_user == 1).sum()),
    "users_with_two_id_blocks": int((block_count_by_user == 2).sum()),
    "first_block_user_ids_monotonic": bool(sorted_by_id.iloc[:first_block_end].user_id.is_monotonic_increasing),
    "appended_rows": len(tail),
    "appended_id_range": [tail.transaction_id.min(), tail.transaction_id.max()],
    "new_user_loglinear_monthly_change": float(np.exp(trend[0]) - 1),
    "new_user_loglinear_r_squared": loglinear_r2,
    "first_purchases_days_1_to_3_share": float((first_date.dt.day <= 3).mean()),
    "all_transactions_days_1_to_3_share": float((tx.trxn_date.dt.day <= 3).mean()),
    "weekday_index_range": [float(weekday_index.min()), float(weekday_index.max())],
    "median_within_month_daily_cv": float(within_month_cv.median()),
    "median_poisson_cv_at_same_daily_mean": float((1 / np.sqrt(daily_month.mean())).median()),
    "amounts_multiple_of_1000_share": float((tx.trxn_amount % 1000 == 0).mean()),
    "limits_multiple_of_100000_share": float((tx.total_limit % 100000 == 0).mean()),
    "package_count": int(tx.package_code.nunique()),
    "carrier_labels": int(tx.carrier.nunique()),
    "package_carrier_pairs": len(package_carrier),
    "rare_pair_rows": int(rare_pairs.transactions.sum()),
    "rare_pair_rows_in_appended_tail": int(rare_pair_rows[tx.seq >= tail.seq.min()].sum()),
    "carrier_lowercase_other_services_rows": int((tx.carrier == "Other services").sum()),
    "duplicate_rows_except_transaction_id": int(tx.duplicated(
        ["user_id", "trxn_date", "trxn_amount", "package_code", "carrier",
         "total_outstanding", "total_limit"]
    ).sum()),
    "package_mean_ticket_min_vnd": float(package_ticket.mean_ticket_vnd.min()),
    "package_mean_ticket_max_vnd": float(package_ticket.mean_ticket_vnd.max()),
    "largest_package_share_range_pp": float(100 * (package_month.max() - package_month.min()).max()),
    "balance": balance_metrics,
}
(OUT / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
print(json.dumps(summary, indent=2))
