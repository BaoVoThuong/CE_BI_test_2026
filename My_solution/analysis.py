"""Independent, reproducible analysis of the BNPL take-home dataset.

Run from any directory: python My_solution/analysis.py
The delivered CSV is the primary dataset. A flagged 104-row tail is analysed as
a sensitivity case; the script does not silently discard records.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "My_solution" / "outputs"
OUT.mkdir(parents=True, exist_ok=True)
LAST = pd.Period("2025-06", freq="M")


def wilson(successes: int, total: int) -> tuple[float, float]:
    p = successes / total
    z = 1.96
    denominator = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denominator
    radius = z * np.sqrt(p * (1 - p) / total + z * z / (4 * total**2)) / denominator
    return centre - radius, centre + radius


def make_tables(tx: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    user = tx.groupby("user_id").agg(
        first_date=("trxn_date", "min"),
        first_month=("month", "min"),
        last_month=("month", "max"),
    )
    user_month = tx.groupby(["user_id", "month"]).agg(
        transactions=("transaction_id", "size"),
        gmv_vnd=("trxn_amount", "sum"),
    ).reset_index()
    user_month = user_month.join(user["first_month"], on="user_id")
    user_month["age"] = (
        (user_month["month"].dt.year - user_month["first_month"].dt.year) * 12
        + user_month["month"].dt.month - user_month["first_month"].dt.month
    )
    observed = pd.MultiIndex.from_frame(user_month[["user_id", "month"]])
    following = pd.MultiIndex.from_frame(
        user_month.assign(month=user_month["month"] + 1)[["user_id", "month"]]
    )
    user_month["next_active"] = following.isin(observed)
    user["m0_transactions"] = user_month[user_month.age == 0].set_index("user_id")["transactions"]
    user["m1_active"] = user.index.isin(user_month[user_month.age == 1].user_id)
    return user, user_month


tx = pd.read_csv(ROOT / "data.csv", parse_dates=["trxn_date"])
assert tx.transaction_id.is_unique
assert not tx.isna().any().any()
tx["month"] = tx.trxn_date.dt.to_period("M")
assert tx.month.min() == pd.Period("2024-01", freq="M")
assert tx.month.max() == LAST
tx["tail_104"] = tx.transaction_id.str[3:].astype(int).between(204591, 204694)
assert tx.tail_104.sum() == 104

raw_user, raw_um = make_tables(tx)
sens_user, _ = make_tables(tx[~tx.tail_104])
eligible = raw_user[raw_user.first_month < LAST]
eligible_sens = sens_user[sens_user.first_month < LAST]

# Cohort matrix: blank means follow-up has not yet been observed.
cohort_rows = []
for cohort, group in raw_user.groupby("first_month"):
    row: dict[str, object] = {"cohort": str(cohort), "users": len(group)}
    active = raw_um[raw_um.first_month == cohort].groupby("age").size()
    for age in range(18):
        row[f"M{age}"] = active.get(age, 0) / len(group) if cohort + age <= LAST else np.nan
    cohort_rows.append(row)
cohorts = pd.DataFrame(cohort_rows)
cohorts.to_csv(OUT / "cohort_retention_raw.csv", index=False, float_format="%.5f")

# Weighted retention: only cohorts with a fully observed M-k enter each denominator.
retention = []
for age in (1, 2, 3, 6, 9, 12):
    base = raw_user[raw_user.first_month + age <= LAST]
    retained_ids = set(raw_um.loc[raw_um.age == age, "user_id"])
    yes = int(base.index.isin(retained_ids).sum())
    lo, hi = wilson(yes, len(base))
    retention.append({"age": age, "cohorts": base.first_month.nunique(),
                      "users": len(base), "retained": yes, "rate": yes / len(base),
                      "ci_low": lo, "ci_high": hi})
pd.DataFrame(retention).to_csv(OUT / "weighted_retention_raw.csv", index=False, float_format="%.5f")

# First-calendar-month transaction counts and M1 retention, raw plus sensitivity.
def frequency_table(users: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for n, group in users.groupby(users.m0_transactions.clip(upper=9)):
        yes = int(group.m1_active.sum())
        lo, hi = wilson(yes, len(group))
        rows.append({"N": f"{int(n)}" if n < 9 else "9+", "users": len(group),
                     "retained": yes, "rate": yes / len(group), "ci_low": lo, "ci_high": hi})
    return pd.DataFrame(rows)


q_raw = frequency_table(eligible)
q_sens = frequency_table(eligible_sens)
q1c = q_raw.merge(q_sens[["N", "retained", "rate"]], on="N", suffixes=("_raw", "_without_tail"))
q1c.to_csv(OUT / "first_month_frequency.csv", index=False, float_format="%.5f")

thresholds = []
for label, users in (("raw", eligible), ("without_tail", eligible_sens)):
    for n in range(2, 9):
        high = users[users.m0_transactions >= n].m1_active
        low = users[users.m0_transactions < n].m1_active
        thresholds.append({"dataset": label, "N": n, "users_ge_N": len(high),
                           "m1_ge_N": high.mean(), "m1_lt_N": low.mean(),
                           "gap_pp": 100 * (high.mean() - low.mean())})
pd.DataFrame(thresholds).to_csv(OUT / "threshold_sensitivity.csv", index=False, float_format="%.5f")

# Equal opportunity window: 0-29 days of exposure, then activity in days 30-59.
first_date = raw_user.first_date
tx["days_from_first"] = (tx.trxn_date - tx.user_id.map(first_date)).dt.days
rolling_eligible = raw_user[raw_user.first_date <= tx.trxn_date.max() - pd.Timedelta(days=59)].copy()
within_30 = tx[tx.days_from_first.between(0, 29)].groupby("user_id").size()
return_30_59 = set(tx.loc[tx.days_from_first.between(30, 59), "user_id"])
rolling_eligible["n30"] = within_30
rolling_eligible["next30"] = rolling_eligible.index.isin(return_30_59)
rolling_rows = []
for n, group in rolling_eligible.groupby(rolling_eligible.n30.clip(upper=9)):
    yes = int(group.next30.sum())
    lo, hi = wilson(yes, len(group))
    rolling_rows.append({"N": f"{int(n)}" if n < 9 else "9+", "users": len(group),
                         "active_days_30_59": yes, "rate": yes / len(group),
                         "ci_low": lo, "ci_high": hi})
rolling = pd.DataFrame(rolling_rows)
rolling.to_csv(OUT / "equal_30_day_windows.csv", index=False, float_format="%.5f")

# Monthly dynamics and prospective churn: each user-month contributes only if
# the next month is inside the extract.
month = raw_um.groupby("month").agg(mau=("user_id", "size"), gmv_vnd=("gmv_vnd", "sum"))
month["new_users"] = raw_user.groupby("first_month").size()
month["returning_users"] = month.mau - month.new_users
churn_panel = raw_um[raw_um.month < LAST].copy()
churn_panel["churn"] = ~churn_panel.next_active
month["churn_to_next_month"] = churn_panel.groupby("month").churn.mean()
month.index = month.index.astype(str)
month.to_csv(OUT / "monthly_dynamics_raw.csv", float_format="%.5f")

churn_panel["frequency_group"] = pd.cut(churn_panel.transactions, [0, 1, 3, np.inf],
                                         labels=["1", "2-3", "4+"])
churn_panel["tenure_group"] = pd.cut(churn_panel.age, [-1, 0, 1, 3, np.inf],
                                      labels=["M0", "M1", "M2-3", "M4+"])
churn_rates = churn_panel.groupby("frequency_group", observed=True).churn.agg(["size", "sum", "mean"])
churn_rates.to_csv(OUT / "churn_by_frequency_raw.csv", float_format="%.5f")
strata = churn_panel.groupby(["tenure_group", "frequency_group"], observed=True).churn.agg(["size", "mean"])
strata.to_csv(OUT / "churn_by_tenure_and_frequency.csv", float_format="%.5f")

# Direct standardisation over tenure to reduce the tenure-mix difference
# between light and heavy user-months. This remains observational.
weights = churn_panel.tenure_group.value_counts(normalize=True).sort_index()
standardised = {
    str(freq): float(sum(weights.loc[age] * strata.loc[(age, freq), "mean"] for age in weights.index))
    for freq in churn_panel.frequency_group.cat.categories
}

# Check whether a fully inactive month is followed by later activity.
sorted_um = raw_um.sort_values(["user_id", "month"])
gap_months = (
    (sorted_um.month.dt.year * 12 + sorted_um.month.dt.month)
    .groupby(sorted_um.user_id).diff()
)
users_with_reactivation = int(sorted_um.loc[gap_months > 1, "user_id"].nunique())

# Exactly how many of the 104 records change M1; no assumption about validity.
tail_users = tx.loc[tx.tail_104, "user_id"]
tail_with_four_m0 = int((sens_user.loc[tail_users, "m0_transactions"] == 4).sum())
tail_m1_added = int((~eligible_sens.loc[tail_users, "m1_active"] & eligible.loc[tail_users, "m1_active"]).sum())

summary = {
    "rows": len(tx), "users": len(raw_user), "months": tx.month.nunique(),
    "period": [str(tx.month.min()), str(tx.month.max())],
    "eligible_m1_users": len(eligible),
    "m1_raw": float(eligible.m1_active.mean()),
    "m1_without_tail": float(eligible_sens.m1_active.mean()),
    "tail_rows": int(tx.tail_104.sum()),
    "tail_users_with_four_m0_transactions": tail_with_four_m0,
    "tail_m1_added": tail_m1_added,
    "retention": retention,
    "peak_mau_month": str(month.mau.idxmax()), "peak_mau": int(month.mau.max()),
    "final_mau": int(month.mau.iloc[-1]),
    "new_users_q1_2024_mean": float(month.new_users.iloc[:3].mean()),
    "new_users_final": int(month.new_users.iloc[-1]),
    "churn_rate_all": float(churn_panel.churn.mean()),
    "churn_rate_recent_6m": float(churn_panel[churn_panel.month >= pd.Period("2024-12")].churn.mean()),
    "churn_standardised_by_tenure": standardised,
    "users_with_reactivation": users_with_reactivation,
    "lapsed_with_two_months_to_return": int((raw_user.last_month <= LAST - 2).sum()),
    "one_txn_churn": float(churn_rates.loc["1", "mean"]),
    "four_plus_churn": float(churn_rates.loc["4+", "mean"]),
    "n1_rolling_rate": float(rolling.loc[rolling.N == "1", "rate"].iloc[0]),
    "n2_rolling_rate": float(rolling.loc[rolling.N == "2", "rate"].iloc[0]),
}
(OUT / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")

# Three simple figures, with labels and source scope embedded in the graphic.
plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False})
fig, ax = plt.subplots(figsize=(9, 4.2))
xx = np.arange(len(month))
ax.bar(xx, month.returning_users, color="#2557a7", label="Returning")
ax.bar(xx, month.new_users, bottom=month.returning_users, color="#f19837", label="First transaction")
ax.set_xticks(xx[::2], month.index[::2], rotation=45, ha="right")
ax.set_ylabel("Monthly active users")
ax.set_title("The active base declines as first-time users arrive more slowly")
ax.legend(frameon=False)
fig.tight_layout()
fig.savefig(OUT / "active_users.png", dpi=160)
plt.close(fig)

fig, ax = plt.subplots(figsize=(8, 4.2))
for _, row in cohorts.iloc[:12].iterrows():
    y = row[[f"M{i}" for i in range(13)]].astype(float).to_numpy()
    ax.plot(range(13), y, alpha=.23, color="#2557a7")
ax.plot([x["age"] for x in retention], [x["rate"] for x in retention],
        "o-", color="#c95035", lw=2, label="Weighted, observable cohorts")
ax.set_xlim(0, 12)
ax.set_ylim(0, .85)
ax.set_xlabel("Months after first transaction month")
ax.set_ylabel("Share with ≥1 transaction")
ax.set_title("Retention declines steadily across cohorts")
ax.legend(frameon=False)
fig.tight_layout()
fig.savefig(OUT / "cohort_retention.png", dpi=160)
plt.close(fig)

fig, axes = plt.subplots(1, 2, figsize=(10, 4.2), sharey=True)
ns = np.arange(1, 9)
axes[0].plot(ns, q_raw.rate.iloc[:8], "o-", color="#c95035", label="As delivered")
axes[0].plot(ns, q_sens.rate.iloc[:8], "o--", color="#2557a7", label="Excluding 104 appended rows")
axes[0].set_title("First calendar month → M1")
axes[0].legend(frameon=False, fontsize=9)
axes[1].plot(ns, rolling.rate.iloc[:8], "o-", color="#2557a7")
axes[1].set_title("Days 0–29 → activity in days 30–59")
for ax in axes:
    ax.set_xticks(ns)
    ax.set_xlabel("Transactions in initial window")
    ax.set_ylim(.4, .9)
axes[0].set_ylabel("Next-window active share")
fig.tight_layout()
fig.savefig(OUT / "early_frequency.png", dpi=160)
plt.close(fig)

print(json.dumps(summary, indent=2))
