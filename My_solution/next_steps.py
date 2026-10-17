"""Extra BI angles and an offline dry-run of a day-14 retention pilot.

Run: python My_solution/next_steps.py [--cohort-month YYYY-MM]
No users are contacted. The assignment CSV is a historical planning artifact.
The product/Risk eligibility join and the actual send step are outside this file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import chi2_contingency, norm


HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "data.csv"
OUT = HERE / "outputs" / "next_steps"
OUT.mkdir(parents=True, exist_ok=True)


def sample_size_per_arm(p0: float, lift: float, alpha: float = .05, power: float = .8) -> int:
    """Normal-approximation sizing for a two-sided, two-arm proportion test."""
    p1 = p0 + lift
    pbar = (p0 + p1) / 2
    z_alpha = norm.ppf(1 - alpha / 2)
    z_power = norm.ppf(power)
    n = (
        z_alpha * math.sqrt(2 * pbar * (1 - pbar))
        + z_power * math.sqrt(p0 * (1 - p0) + p1 * (1 - p1))
    ) ** 2 / lift**2
    return math.ceil(n)


def arm_for_user(user_id: int) -> str:
    # Stable at rerun; assignment is at user level, never at transaction level.
    digest = hashlib.blake2b(f"bnpl_day14_v1|{user_id}".encode(), digest_size=8).digest()
    return "prompt" if int.from_bytes(digest, "big") % 2 else "holdout"


parser = argparse.ArgumentParser()
parser.add_argument("--cohort-month", help="Month of first purchase for historical dry-run, YYYY-MM")
args = parser.parse_args()

tx = pd.read_csv(DATA, parse_dates=["trxn_date"])
assert tx.transaction_id.is_unique and not tx.isna().any().any()
end = tx.trxn_date.max()
tx["month"] = tx.trxn_date.dt.to_period("M")
first = tx.groupby("user_id").trxn_date.min()
tx["first_date"] = tx.user_id.map(first)
tx["day"] = (tx.trxn_date - tx.first_date).dt.days
tx["cohort"] = tx.first_date.dt.to_period("M")
tx["carrier_normalized"] = tx.carrier.replace({"Other services": "Other Services"})

# Equal 60-day observation for all historical signal estimates.
mature_ids = first[first <= end - pd.Timedelta(days=59)].index
mature = tx[tx.user_id.isin(mature_ids)]
outcome_ids = set(mature.loc[mature.day.between(30, 59), "user_id"])
n30 = mature[mature.day < 30].groupby("user_id").size()

early_rows = []
for day in (3, 7, 14, 21, 30):
    counts = mature[mature.day < day].groupby("user_id").size().reindex(mature_ids)
    assert counts.notna().all()
    for group, chosen in (("exactly_1", counts[counts == 1].index),
                          ("at_least_2", counts[counts >= 2].index)):
        active = pd.Index(chosen).isin(outcome_ids)
        natural_repeat = (n30.loc[chosen] >= 2).mean() if group == "exactly_1" else np.nan
        early_rows.append({"day": day, "purchases_at_trigger": group, "users": len(chosen),
                           "share_of_mature_users": len(chosen) / len(mature_ids),
                           "active_days_30_59": int(active.sum()), "rate_days_30_59": active.mean(),
                           "natural_second_purchase_by_day30": natural_repeat})
early = pd.DataFrame(early_rows)
early.to_csv(OUT / "early_trigger_tradeoff.csv", index=False, float_format="%.5f")

# Same mature cohort base for each month in the fixed M0-M6 horizon.
last_month = tx.month.max()
fixed_ids = first[first.dt.to_period("M") <= last_month - 6].index
fixed = tx[tx.user_id.isin(fixed_ids)].copy()
fixed["age"] = (
    (fixed.month.dt.year - fixed.cohort.dt.year) * 12
    + fixed.month.dt.month - fixed.cohort.dt.month
)
fixed_rows = []
for age in range(7):
    part = fixed[fixed.age == age]
    fixed_rows.append({"age": age, "base_users": len(fixed_ids),
                       "active_users": part.user_id.nunique(),
                       "retention": part.user_id.nunique() / len(fixed_ids),
                       "gmv_vnd_per_new_user": part.trxn_amount.sum() / len(fixed_ids)})
fixed_horizon = pd.DataFrame(fixed_rows)
fixed_horizon.to_csv(OUT / "fixed_M0_M6_value.csv", index=False, float_format="%.5f")

# Merchant breadth: compare like transaction-count bands to avoid attributing
# the whole raw breadth gap to browsing across categories.
activity30 = mature[mature.day < 30].groupby("user_id").agg(
    n=("transaction_id", "size"), carriers=("carrier_normalized", "nunique")
)
activity30 = activity30[activity30.n >= 2].copy()
activity30["active_next_30"] = activity30.index.isin(outcome_ids)
activity30["frequency_band"] = pd.cut(activity30.n, [1, 2, 3, 5, np.inf],
                                        labels=["2", "3", "4-5", "6+"])
activity30["multiple_carriers"] = activity30.carriers >= 2
breadth = activity30.groupby(["frequency_band", "multiple_carriers"], observed=True)[
    "active_next_30"
].agg(users="size", rate="mean").reset_index()
breadth.to_csv(OUT / "merchant_breadth_within_frequency.csv", index=False, float_format="%.5f")
mix_weights = activity30.frequency_band.value_counts(normalize=True).sort_index()
rates = breadth.pivot(index="frequency_band", columns="multiple_carriers", values="rate")
adjusted_breadth_gap = float(((rates[True] - rates[False]) * mix_weights).sum())
raw_breadth_gap = float(
    activity30.groupby("multiple_carriers").active_next_30.mean().diff().iloc[-1]
)

# Acquisition quality: use equal 60-day windows, not raw M1 for late joiners.
first_record = tx.sort_values(["user_id", "trxn_date", "transaction_id"]).groupby("user_id").first()
quality = pd.DataFrame(index=mature_ids)
quality["cohort_quarter"] = first.loc[mature_ids].dt.to_period("Q")
quality["n30"] = n30.loc[mature_ids]
quality["active_days_30_59"] = quality.index.isin(outcome_ids)
quality["first_ticket_vnd"] = first_record.loc[mature_ids, "trxn_amount"]
quality["credit_limit_vnd"] = first_record.loc[mature_ids, "total_limit"]
quality_quarter = quality.groupby("cohort_quarter").agg(
    users=("n30", "size"), n30_mean=("n30", "mean"),
    active_days_30_59=("active_days_30_59", "mean"),
    first_ticket_mean_vnd=("first_ticket_vnd", "mean"),
    credit_limit_mean_vnd=("credit_limit_vnd", "mean"),
)
quality_quarter.to_csv(OUT / "new_user_quality_by_quarter.csv", float_format="%.5f")

# An in-sample cohort reweighting, not a forecast: hold the Nov-Jun number
# of first-time purchasers at October's level, preserving each cohort's
# actually observed June retention fraction.
cohorts = first.dt.to_period("M")
final_active = set(tx.loc[tx.month == last_month, "user_id"])
first_month_counts = cohorts.value_counts().sort_index()
reference_month = pd.Period("2024-10", freq="M")
reference_inflow = int(first_month_counts.loc[reference_month])
counterfactual_rows = []
for c in pd.period_range(reference_month + 1, last_month, freq="M"):
    ids = cohorts[cohorts == c].index
    retained_to_final = pd.Index(ids).isin(final_active).mean()
    counterfactual_rows.append({
        "cohort": str(c), "observed_new_users": len(ids),
        "observed_retention_to_final_month": retained_to_final,
        "extra_final_mau_at_reference_inflow": (reference_inflow - len(ids)) * retained_to_final,
    })
counterfactual = pd.DataFrame(counterfactual_rows)
counterfactual.to_csv(OUT / "inflow_cohort_reweighting.csv", index=False, float_format="%.5f")
actual_final_mau = len(final_active)
counterfactual_final_mau = actual_final_mau + counterfactual.extra_final_mau_at_reference_inflow.sum()

# Tenure composition versus within-tenure changes in observed monthly churn.
user_month = tx.groupby(["user_id", "month"]).size().rename("transactions").reset_index()
user_month["cohort"] = user_month.user_id.map(cohorts)
user_month["age"] = (
    (user_month.month.dt.year - user_month.cohort.dt.year) * 12
    + user_month.month.dt.month - user_month.cohort.dt.month
)
seen = set(zip(user_month.user_id, user_month.month))
user_month = user_month[user_month.month < last_month].copy()
user_month["churn"] = [(uid, month + 1) not in seen
                       for uid, month in zip(user_month.user_id, user_month.month)]
user_month["age_band"] = pd.cut(user_month.age, [-1, 0, 1, 3, np.inf],
                                 labels=["M0", "M1", "M2-3", "M4+"])
start_churn_month = pd.Period("2024-10", freq="M")
end_churn_month = last_month - 1
churn_start = user_month[user_month.month == start_churn_month]
churn_end = user_month[user_month.month == end_churn_month]
w_start = churn_start.age_band.value_counts(normalize=True).sort_index()
w_end = churn_end.age_band.value_counts(normalize=True).sort_index()
r_start = churn_start.groupby("age_band", observed=True).churn.mean()
r_end = churn_end.groupby("age_band", observed=True).churn.mean()
churn_decomp = pd.DataFrame({
    "weight_start": w_start, "weight_end": w_end,
    "churn_start": r_start, "churn_end": r_end,
})
churn_decomp["composition_contribution"] = (churn_decomp.weight_end - churn_decomp.weight_start) * churn_decomp.churn_start
churn_decomp["within_band_contribution"] = churn_decomp.weight_end * (churn_decomp.churn_end - churn_decomp.churn_start)
churn_decomp.to_csv(OUT / "churn_tenure_decomposition.csv", float_format="%.6f")

# Activation timing and second-purchase lag. All second-purchase shares use
# the 60-day mature base, avoiding right-censoring near the end of the file.
second = mature.sort_values(["user_id", "trxn_date", "transaction_id"]).groupby("user_id").nth(1).reset_index()
second_lag = (second.trxn_date - second.user_id.map(first)).dt.days
second_timing = pd.DataFrame([
    {"by_day_exclusive": d, "mature_users": len(mature_ids),
     "second_purchase_users": int((second_lag < d).sum()),
     "share": float((second_lag < d).sum() / len(mature_ids))}
    for d in (3, 7, 14, 21, 30, 60)
])
second_timing.to_csv(OUT / "second_purchase_timing.csv", index=False, float_format="%.5f")
day_of_month = pd.DataFrame({
    "first_purchase_users": first.dt.day.value_counts().sort_index(),
    "all_transactions": tx.trxn_date.dt.day.value_counts().sort_index(),
}).fillna(0)
day_of_month.to_csv(OUT / "day_of_month_pattern.csv", float_format="%.0f")

# Screen obvious segmentation ideas, retaining the global test to avoid
# choosing a category solely because it tops a 22-way ranking by chance.
eligible_m1 = cohorts[cohorts < last_month].to_frame("cohort")
eligible_m1["m1"] = [
    (uid, c + 1) in seen for uid, c in zip(eligible_m1.index, eligible_m1.cohort)
]
eligible_m1["first_carrier"] = first_record.loc[eligible_m1.index, "carrier_normalized"]
eligible_m1["first_ticket"] = first_record.loc[eligible_m1.index, "trxn_amount"]
eligible_m1["credit_limit"] = first_record.loc[eligible_m1.index, "total_limit"]
carrier = eligible_m1.groupby("first_carrier").m1.agg(users="size", rate="mean")
carrier.to_csv(OUT / "first_carrier_M1_screen.csv", float_format="%.5f")
carrier_global_p = float(chi2_contingency(pd.crosstab(eligible_m1.first_carrier, eligible_m1.m1))[1])
for field in ("first_ticket", "credit_limit"):
    bins = pd.qcut(eligible_m1[field], 4, duplicates="drop")
    eligible_m1.groupby(bins, observed=True).m1.agg(users="size", rate="mean").to_csv(
        OUT / f"{field}_quartile_M1.csv", float_format="%.5f"
    )

# Credit-field semantics and value concentration checks.
ordered = tx.sort_values(["user_id", "trxn_date", "transaction_id"])
prior_balance = ordered.groupby("user_id").total_outstanding.shift()
at_limit = ordered.total_outstanding == ordered.total_limit
balance_first_below_purchase = float((ordered.loc[prior_balance.isna(), "total_outstanding"]
                                     < ordered.loc[prior_balance.isna(), "trxn_amount"]).mean())
user_month_gmv = tx.groupby(["user_id", "month"]).trxn_amount.sum().sort_values(ascending=False)
top_10pct_user_month_gmv_share = float(
    user_month_gmv.iloc[:math.ceil(.1 * len(user_month_gmv))].sum() / user_month_gmv.sum()
)

# Historical dry-run: use a fully observed first-purchase month. The CSV is
# only a deterministic assignment example, not evidence of an intervention.
cohort_month = pd.Period(args.cohort_month, freq="M") if args.cohort_month else last_month - 1
assert cohort_month <= last_month - 1
cohort_users = first[first.dt.to_period("M") == cohort_month]
assert len(cohort_users) > 0
assert cohort_users.max() + pd.Timedelta(days=14) <= end, "Day-14 trigger is not fully observed"
count14 = tx[(tx.user_id.isin(cohort_users.index)) & (tx.day < 14)].groupby("user_id").size()
assert len(count14) == len(cohort_users)
eligible_ids = count14[count14 == 1].index
pilot = pd.DataFrame({
    "user_id": eligible_ids,
    "first_purchase_date": cohort_users.loc[eligible_ids].values,
    "trigger_date": (cohort_users.loc[eligible_ids] + pd.Timedelta(days=14)).values,
    "arm": [arm_for_user(int(i)) for i in eligible_ids],
    "simulation_only": True,
}).sort_values("user_id")
pilot.to_csv(OUT / f"pilot_dry_run_{cohort_month}.csv", index=False)

day14_one = early[(early.day == 14) & (early.purchases_at_trigger == "exactly_1")].iloc[0]
p0 = float(day14_one.rate_days_30_59)
current_inflow = int(first.dt.to_period("M").value_counts().loc[last_month])
eligible_per_month = current_inflow * float(day14_one.share_of_mature_users)
power_rows = []
for lift in (.05, .10):
    n = sample_size_per_arm(p0, lift)
    power_rows.append({"absolute_lift_pp": 100 * lift, "baseline": p0,
                       "users_per_arm": n, "total_eligible": 2 * n,
                       "estimated_months_at_current_inflow": math.ceil(2 * n / eligible_per_month)})
pd.DataFrame(power_rows).to_csv(OUT / "pilot_sample_size.csv", index=False, float_format="%.4f")

summary = {
    "mature_users_60_day_followup": len(mature_ids),
    "day14_eligible_share": float(day14_one.share_of_mature_users),
    "day14_eligible_outcome_rate": p0,
    "day14_natural_second_by_day30": float(day14_one.natural_second_purchase_by_day30),
    "same_cohort_M0_M6_users": len(fixed_ids),
    "active_user_months_M0_M6_per_new_user": float(fixed_horizon.retention.sum()),
    "gmv_M0_M6_vnd_per_new_user": float(fixed_horizon.gmv_vnd_per_new_user.sum()),
    "merchant_breadth_raw_gap_pp": 100 * raw_breadth_gap,
    "merchant_breadth_frequency_adjusted_gap_pp": 100 * adjusted_breadth_gap,
    "reference_month": str(reference_month),
    "reference_first_time_users": reference_inflow,
    "actual_final_mau": actual_final_mau,
    "counterfactual_final_mau_same_cohort_rates": counterfactual_final_mau,
    "churn_start_month": str(start_churn_month),
    "churn_end_month": str(end_churn_month),
    "churn_start": float(churn_start.churn.mean()),
    "churn_end": float(churn_end.churn.mean()),
    "churn_change_composition_pp": float(100 * churn_decomp.composition_contribution.sum()),
    "churn_change_within_tenure_pp": float(100 * churn_decomp.within_band_contribution.sum()),
    "first_purchase_by_day3_share": float((first.dt.day <= 3).mean()),
    "all_transactions_by_day3_share": float((tx.trxn_date.dt.day <= 3).mean()),
    "second_purchase_by_day7_share_mature": float(second_timing.loc[second_timing.by_day_exclusive == 7, "share"].iloc[0]),
    "second_purchase_by_day14_share_mature": float(second_timing.loc[second_timing.by_day_exclusive == 14, "share"].iloc[0]),
    "second_purchase_by_day30_share_mature": float(second_timing.loc[second_timing.by_day_exclusive == 30, "share"].iloc[0]),
    "median_second_purchase_lag_days_among_repeaters": float(second_lag.median()),
    "first_carrier_global_M1_p": carrier_global_p,
    "first_carrier_count": len(carrier),
    "balance_at_limit_transactions": int(at_limit.sum()),
    "transactions_with_prior_balance_at_limit_and_current_at_limit": int(((prior_balance == ordered.total_limit) & at_limit).sum()),
    "first_purchase_balance_below_purchase_share": balance_first_below_purchase,
    "user_month_balance_at_or_above_80pct_share": float(
        (ordered.groupby(["user_id", "month"]).last().total_outstanding
         / ordered.groupby(["user_id", "month"]).last().total_limit >= .8).mean()
    ),
    "top_10pct_user_month_gmv_share": top_10pct_user_month_gmv_share,
    "pilot_dry_run_cohort": str(cohort_month),
    "pilot_dry_run_eligible": len(pilot),
    "pilot_dry_run_arm_counts": pilot.arm.value_counts().to_dict(),
    "current_inflow_for_sizing": current_inflow,
    "estimated_day14_eligible_per_month": eligible_per_month,
    "sample_size": power_rows,
}
(OUT / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")

# A compact visual summary of four decision-relevant comparisons.
fig, axes = plt.subplots(2, 2, figsize=(12, 8.5))
fig.suptitle("BNPL follow-on findings | Jan 2024–Jun 2025 extract", fontsize=15, fontweight="bold")
new_month = first.dt.to_period("M").value_counts().sort_index()
ax = axes[0, 0]
ax.bar(range(len(new_month)), new_month.values, color="#315da7")
ax.axhline(reference_inflow, color="#d65f34", ls="--", lw=1.5,
           label=f"Oct 2024: {reference_inflow:,}")
ax.set_xticks(range(0, len(new_month), 3),
              [str(m) for m in new_month.index[::3]], rotation=35, ha="right")
ax.set_title("Fewer first-time purchasers each month")
ax.set_ylabel("Users")
ax.legend(frameon=False)

ax = axes[0, 1]
bars = ax.bar(["Observed", "Same inflow as Oct 2024"],
              [actual_final_mau, counterfactual_final_mau],
              color=["#315da7", "#e7a345"])
for bar in bars:
    ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 45,
            f"{bar.get_height():,.0f}", ha="center")
ax.set_ylim(0, 5000)
ax.set_title("Jun 2025 MAU: cohort reweighting only")
ax.set_ylabel("Users; scenario, not forecast")

ax = axes[1, 0]
timing = early[(early.purchases_at_trigger == "exactly_1") & early.day.isin([7, 14, 21])]
for field, label, color in [
    ("share_of_mature_users", "One purchase at trigger", "#315da7"),
    ("rate_days_30_59", "Active on days 30–59", "#d65f34"),
    ("natural_second_purchase_by_day30", "Second purchase naturally by day 30", "#319b77"),
]:
    ax.plot(timing.day, timing[field] * 100, "o-", label=label, color=color)
ax.set_xticks([7, 14, 21])
ax.set_ylim(0, 80)
ax.set_ylabel("Percent of relevant users")
ax.set_xlabel("Days after first purchase")
ax.set_title("A later trigger trades reach for precision")
ax.legend(frameon=False, fontsize=8)

ax = axes[1, 1]
bars = ax.bar(["Raw", "Same frequency mix"],
              [100 * raw_breadth_gap, 100 * adjusted_breadth_gap],
              color=["#d65f34", "#315da7"])
for bar in bars:
    ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + .12,
            f"{bar.get_height():.1f}pp", ha="center")
ax.set_ylim(0, 8)
ax.set_ylabel("Gap in days 30–59 activity")
ax.set_title("Multi-carrier gap shrinks after frequency adjustment")
fig.tight_layout(rect=(0, .04, 1, .96))
fig.text(.02, .012,
         "Source: delivered transaction CSV. Same-inflow bar preserves each cohort's observed Jun-2025 retention; all associations are observational.",
         fontsize=8, color="#555555")
fig.savefig(OUT / "additional_insights.png", dpi=160)
plt.close(fig)
print(json.dumps(summary, indent=2))
