"""Package and carrier checks for retention, churn and the 2024-25 decline.

Run from any directory: python My_solution/segment_mix.py
Uses the delivered CSV (same convention as analysis.py). `Other services` is
merged into `Other Services`. Outputs go to My_solution/outputs/segment_mix/.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import chi2_contingency


ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "My_solution" / "outputs" / "segment_mix"
OUT.mkdir(parents=True, exist_ok=True)
LAST = pd.Period("2025-06", freq="M")
PEAK = pd.Period("2024-10", freq="M")  # MAU peak, as in REPORT.md


def p_value(rows: pd.Series, outcome: pd.Series) -> float:
    return float(chi2_contingency(pd.crosstab(rows, outcome))[1])


tx = pd.read_csv(ROOT / "data.csv", parse_dates=["trxn_date"])
tx["carrier"] = tx.carrier.replace({"Other services": "Other Services"})
tx["month"] = tx.trxn_date.dt.to_period("M")
tx = tx.sort_values(["user_id", "trxn_date", "transaction_id"])
tx["cell"] = tx.package_code + " | " + tx.carrier

first = tx.groupby("user_id").first()
user = pd.DataFrame({"first_month": first.month, "first_package": first.package_code,
                     "first_carrier": first.carrier, "first_cell": first.cell})
um = tx.groupby(["user_id", "month"]).agg(
    transactions=("transaction_id", "size"),
    packages=("package_code", "nunique"),
    main_package=("package_code", lambda s: s.value_counts().index[0]),
    last_cell=("cell", "last"),
).reset_index()
um = um.join(user.first_month, on="user_id")
um["age"] = (um.month.dt.year - um.first_month.dt.year) * 12 + um.month.dt.month - um.first_month.dt.month

# 1. Cohort retention by first package: only cohorts with Mk observed.
retention, tests = [], {}
for k in (1, 2, 3, 6, 12):
    base = user[user.first_month + k <= LAST].copy()
    base["retained"] = base.index.isin(um.loc[um.age == k, "user_id"])
    by_pkg = base.groupby("first_package").retained.agg(users="size", rate="mean")
    by_pkg["age"] = f"M{k}"
    retention.append(by_pkg.reset_index())
    tests[f"first_package_M{k}_p"] = p_value(base.first_package, base.retained)
    tests[f"first_carrier_M{k}_p"] = p_value(base.first_carrier, base.retained)
    tests[f"first_package_M{k}_range_pp"] = float(100 * (by_pkg.rate.max() - by_pkg.rate.min()))
retention = pd.concat(retention)
retention.to_csv(OUT / "retention_by_first_package.csv", index=False, float_format="%.5f")

# 1b. Same check on the 33 package x carrier cells (first purchase's cell).
# The 5 off-hierarchy rows sit in the 104-row tail and are never a first purchase.
cell_retention = {}
for k in (1, 3, 6):
    base = user[user.first_month + k <= LAST].copy()
    base["retained"] = base.index.isin(um.loc[um.age == k, "user_id"])
    by_cell = base.groupby("first_cell").retained.agg(["size", "mean"])
    cell_retention[f"users_M{k}"], cell_retention[f"M{k}"] = by_cell["size"], by_cell["mean"]
    tests[f"first_cell_M{k}_p"] = p_value(base.first_cell, base.retained)
    tests[f"first_cell_M{k}_min"], tests[f"first_cell_M{k}_max"] = map(float, by_cell["mean"].agg(["min", "max"]))
tests["first_cell_count"] = int(user.first_cell.nunique())
cell_retention = pd.DataFrame(cell_retention).sort_values("M1")
cell_retention.to_csv(OUT / "retention_by_first_cell.csv", float_format="%.5f")

# 2. Churners vs stayers: same churn definition as REPORT.md Part 2.
active = pd.MultiIndex.from_frame(um[["user_id", "month"]])
panel = um[um.month < LAST].copy()
panel["churn"] = ~pd.MultiIndex.from_arrays([panel.user_id, panel.month + 1]).isin(active)
mix = (tx[tx.month < LAST].groupby(["user_id", "month"]).package_code
       .value_counts(normalize=True).unstack(fill_value=0))
panel = panel.join(mix, on=["user_id", "month"])
profile = panel.groupby("churn")[list(mix.columns) + ["packages", "transactions"]].mean().T
profile.columns = ["stayed", "churned"]
profile["gap_pp_or_units"] = profile.churned - profile.stayed
profile.loc[mix.columns, ["stayed", "churned", "gap_pp_or_units"]] *= 100
profile.to_csv(OUT / "churn_vs_stay_profile.csv", float_format="%.3f")

panel["frequency_band"] = pd.cut(panel.transactions, [0, 1, 2, 3, 5, np.inf],
                                 labels=["1", "2", "3", "4-5", "6+"])
by_main = panel.pivot_table(index="main_package", columns="frequency_band", values="churn",
                            aggfunc="mean", observed=True)
by_main.to_csv(OUT / "churn_by_main_package_and_frequency.csv", float_format="%.5f")
# Breadth: one vs several packages, holding the month's purchase count fixed.
breadth = panel[panel.transactions.between(2, 5)].assign(several=lambda d: d.packages >= 2)
by_breadth = breadth.groupby(["transactions", "several"]).churn.agg(["size", "mean"]).unstack()
by_breadth.to_csv(OUT / "churn_by_package_breadth_within_frequency.csv", float_format="%.5f")
single = panel[panel.transactions == 1]
tests["churn_single_purchase_months_by_package_p"] = p_value(single.main_package, single.churn)
tests["churn_single_purchase_months_package_range_pp"] = float(
    100 * single.groupby("main_package").churn.mean().agg(np.ptp))
tests["churn_breadth_gap_within_frequency_pp"] = float(
    100 * (by_breadth[("mean", True)] - by_breadth[("mean", False)]).mean())

# 2b. Churn by package x carrier cell of the month's last purchase. Direct
# standardisation to the overall frequency mix, since heavy months churn less.
band_weights = panel.frequency_band.value_counts(normalize=True)
cell_churn = panel.pivot_table(index="last_cell", columns="frequency_band", values="churn",
                               aggfunc="mean", observed=True)
cell_churn = pd.DataFrame({
    "user_months": panel.groupby("last_cell").size(),
    "churn_raw": panel.groupby("last_cell").churn.mean(),
    "churn_frequency_standardised": cell_churn[band_weights.index].mul(band_weights).sum(axis=1),
}).sort_values("churn_frequency_standardised")
cell_churn = cell_churn[cell_churn.user_months >= 100]
cell_churn.to_csv(OUT / "churn_by_last_cell.csv", float_format="%.5f")
tests["churn_cell_p"] = p_value(panel.last_cell, panel.churn)
tests["churn_cell_single_purchase_p"] = p_value(single.last_cell, single.churn)
tests["churn_cell_standardised_min"], tests["churn_cell_standardised_max"] = map(
    float, cell_churn.churn_frequency_standardised.agg(["min", "max"]))

# 3. Decline by package: does any category explain the fall from the MAU peak?
monthly = tx.groupby(["month", "package_code"]).agg(
    gmv_vnd=("trxn_amount", "sum"), users=("user_id", "nunique"),
    transactions=("transaction_id", "size")).reset_index()
mau = tx.groupby("month").user_id.nunique()
monthly["penetration"] = monthly.users / monthly.month.map(mau)
monthly.assign(month=monthly.month.astype(str)).to_csv(
    OUT / "package_monthly.csv", index=False, float_format="%.5f")
wide = monthly.pivot(index="month", columns="package_code")
decline = pd.DataFrame({
    "users_change": wide.users.loc[LAST] / wide.users.loc[PEAK] - 1,
    "gmv_change": wide.gmv_vnd.loc[LAST] / wide.gmv_vnd.loc[PEAK] - 1,
    "penetration_peak": wide.penetration.loc[PEAK],
    "penetration_last": wide.penetration.loc[LAST],
})
decline.to_csv(OUT / "package_decline_peak_to_last.csv", float_format="%.5f")

# Carrier-level share shifts: are quarter-on-quarter moves persistent trends?
tx["quarter"] = tx.trxn_date.dt.to_period("Q")
cell = (tx.package_code + " | " + tx.carrier).rename("package_carrier")
counts = pd.crosstab(cell, tx.quarter)
counts = counts[counts.sum(axis=1) >= 100]  # drops the 5 off-hierarchy rows
share = counts.div(counts.sum(axis=0), axis=1)
share.columns = share.columns.astype(str)
share.to_csv(OUT / "package_carrier_quarterly_share.csv", float_format="%.5f")
moves = share.diff(axis=1).iloc[:, 1:]
persistence = [float(moves.iloc[:, i].corr(moves.iloc[:, i + 1])) for i in range(moves.shape[1] - 1)]

# 4. Where did new users fall? First purchase's package and cell, H1-24 vs H1-25.
user["half"] = np.select([user.first_month <= pd.Period("2024-06", freq="M"),
                          user.first_month <= pd.Period("2024-12", freq="M")],
                         ["H1_2024", "H2_2024"], "H1_2025")
new_pkg = pd.crosstab(user.first_package, user.half)
new_pkg["change_H1_24_to_H1_25"] = new_pkg.H1_2025 / new_pkg.H1_2024 - 1
new_pkg["share_H1_2024"] = new_pkg.H1_2024 / new_pkg.H1_2024.sum()
new_pkg["share_H1_2025"] = new_pkg.H1_2025 / new_pkg.H1_2025.sum()
new_pkg.sort_values("change_H1_24_to_H1_25").to_csv(OUT / "new_users_by_first_package.csv", float_format="%.5f")
new_cell = pd.crosstab(user.first_cell, user.half)
new_cell["change_H1_24_to_H1_25"] = new_cell.H1_2025 / new_cell.H1_2024 - 1
new_cell.sort_values("change_H1_24_to_H1_25").to_csv(OUT / "new_users_by_first_cell.csv", float_format="%.5f")
halves = user[user.half != "H2_2024"]
tests["new_users_change_H1_24_to_H1_25"] = float(new_pkg.H1_2025.sum() / new_pkg.H1_2024.sum() - 1)
tests["new_users_package_mix_p"] = p_value(halves.first_package, halves.half)
tests["new_users_cell_mix_p"] = p_value(halves.first_cell, halves.half)
tests["new_users_package_change_min"], tests["new_users_package_change_max"] = map(
    float, new_pkg.change_H1_24_to_H1_25.agg(["min", "max"]))
tests["new_users_cell_change_min"], tests["new_users_cell_change_max"] = map(
    float, new_cell.change_H1_24_to_H1_25.agg(["min", "max"]))
tests["new_users_package_share_max_shift_pp"] = float(
    100 * (new_pkg.share_H1_2025 - new_pkg.share_H1_2024).abs().max())

summary = {
    **tests,
    "package_users_change_min": float(decline.users_change.min()),
    "package_users_change_max": float(decline.users_change.max()),
    "mau_change": float(mau[LAST] / mau[PEAK] - 1),
    "package_penetration_max_shift_pp": float(
        100 * (decline.penetration_last - decline.penetration_peak).abs().max()),
    "cell_share_min_pct": float(100 * share.min().min()),
    "cell_share_max_pct": float(100 * share.max().max()),
    "cell_share_change_lag1_corr": persistence,
    "package_carrier_cells": int(len(counts)),
}
(OUT / "summary.json").write_text(json.dumps(summary, indent=2))

# Chart: retention, churn, inflow and decline, each split by category.
import matplotlib.dates as mdates

order = decline.sort_values("users_change").index
fig, axes = plt.subplots(2, 2, figsize=(15, 10))
ax = axes[0, 0]
m1 = 100 * cell_retention.M1
overall_m1 = 100 * (cell_retention.M1 * cell_retention.users_M1).sum() / cell_retention.users_M1.sum()
noise = 196 * np.sqrt(overall_m1 / 100 * (1 - overall_m1 / 100) / cell_retention.users_M1.median())
ax.axvspan(overall_m1 - noise, overall_m1 + noise, color="#e2e8f0", label="95% sampling band")
ax.axvline(overall_m1, color="#4a5568", lw=1)
ax.plot(m1, range(len(m1)), "o", color="#2b6cb0", ms=4)
ax.set_yticks(range(len(m1)), m1.index, fontsize=6)
ax.set_xlabel("M1 retention, % of users whose first purchase was in this cell")
ax.set_title(f"M1 by first package x carrier (33 cells): within noise, p = {tests['first_cell_M1_p']:.2f}")
ax.legend(loc="lower right", fontsize=8)
ax = axes[0, 1]
c = 100 * by_main.loc[order]
for band, colour in zip(["1", "2", "4-5", "6+"], ["#c53030", "#dd6b20", "#d69e2e", "#38a169"]):
    ax.plot(c[band], c.index, "o", color=colour, label=f"{band} in month")
ax.set_title("Churn next month is set by purchase count, not by main package")
ax.set_xlabel("% of active user-months with no purchase next month")
ax.set_xlim(right=36)
ax.legend(fontsize=8, loc="lower right", title="Purchases", title_fontsize=8)
ax = axes[1, 0]
quarter = user.first_month.dt.asfreq("Q")
new_q = pd.crosstab(quarter, user.first_package)
for pkg in new_q.columns:
    ax.plot(new_q.index.to_timestamp(), 100 * new_q[pkg] / new_q[pkg].iloc[0], color="#a0aec0", lw=1)
total_q = new_q.sum(axis=1)
ax.plot(total_q.index.to_timestamp(), 100 * total_q / total_q.iloc[0], color="#1a202c", lw=2.5, label="All new users")
ax.set_title("New users fall in every first package (grey = 7 packages, Q1-24 = 100)")
ax.set_ylabel("Index")
ax.legend()
ax = axes[1, 1]
idx = wide.users.div(wide.users.loc[PEAK]) * 100
for pkg in idx.columns:
    ax.plot(idx.index.to_timestamp(), idx[pkg], color="#a0aec0", lw=1)
ax.plot(mau.index.to_timestamp(), 100 * mau / mau[PEAK], color="#1a202c", lw=2.5, label="All MAU")
ax.axhline(100, color="#718096", ls=":", lw=1)
ax.set_title("Active users fall with MAU in every package (Oct-24 = 100)")
ax.legend()
for ax in axes[1]:
    ax.xaxis.set_major_locator(mdates.MonthLocator(bymonth=(1, 4, 7, 10)))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b-%y"))
fig.tight_layout()
fig.savefig(OUT / "segment_mix.png", dpi=150)
print(json.dumps(summary, indent=2))
