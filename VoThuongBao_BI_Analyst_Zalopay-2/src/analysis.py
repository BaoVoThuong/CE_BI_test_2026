"""
Zalopay BI Credit Enablement - take-home test: end-to-end analysis.

Run:  python3 src/analysis.py
Input:  ../Input/data.csv (relative to this file)
Output: src/outputs/{tables/*.csv, charts/*.png, key_numbers.json}

Every number quoted in the report is written to outputs/key_numbers.json by this
script, so the report can be audited against the code.

Conventions
- "Clean" data = raw data minus 104 out-of-sequence rows (see section 1).
  All analysis uses clean data unless a result is explicitly labelled "raw".
- Cohort = calendar month of a user's first transaction in the dataset.
- Age k (M0, M1, ...) = calendar months since the cohort month.
- Active in a month = at least one transaction in that calendar month.
- Monthly churn (hazard) = share of users active in month t with no transaction in t+1.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
from matplotlib.colors import LinearSegmentedColormap
from scipy import stats
from sklearn.metrics import roc_auc_score

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "Input" / "data.csv"
OUT = HERE / "outputs"
TAB = OUT / "tables"
FIG = OUT / "charts"
for p in (TAB, FIG):
    p.mkdir(parents=True, exist_ok=True)

KEY: dict = {}  # every number the report cites


def key(name, value):
    """Store a number for the report (converts numpy types to plain Python)."""
    if isinstance(value, (np.integer,)):
        value = int(value)
    elif isinstance(value, (np.floating,)):
        value = float(value)
    KEY[name] = value
    return value


def save(df: pd.DataFrame, name: str, index=True):
    df.to_csv(TAB / f"{name}.csv", index=index)


# --------------------------------------------------------------------------
# Chart style (validated palette: blue, orange, aqua, yellow; light surface)
# --------------------------------------------------------------------------
SURFACE, INK, INK2, MUTED = "#fcfcfb", "#0b0b0b", "#52514e", "#898781"
GRID, BASE = "#e1e0d9", "#c3c2b7"
BLUE, ORANGE, AQUA, YELLOW = "#2a78d6", "#eb6834", "#1baf7a", "#eda100"
GRAY = "#c3c2b7"
BLUE_RAMP = ["#f4f8fd", "#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]

plt.rcParams.update({
    "font.family": ["Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"],
    "font.size": 10,
    "axes.facecolor": SURFACE,
    "figure.facecolor": SURFACE,
    "axes.edgecolor": BASE,
    "axes.labelcolor": INK2,
    "axes.titlecolor": INK,
    "axes.titlesize": 12,
    "axes.titleweight": "semibold",
    "axes.titlelocation": "left",
    "axes.titlepad": 12,
    "xtick.color": MUTED,
    "ytick.color": MUTED,
    "axes.grid": True,
    "grid.color": GRID,
    "grid.linewidth": 0.8,
    "grid.linestyle": "-",
    "axes.axisbelow": True,
    "legend.frameon": False,
    "lines.linewidth": 2,
    "lines.solid_capstyle": "round",
    "savefig.dpi": 170,
    "savefig.bbox": "tight",
})


def tidy(ax, ygrid=True):
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(BASE)
    ax.grid(axis="x", visible=False)
    ax.grid(axis="y", visible=ygrid)
    ax.tick_params(length=0)


def pct_axis(ax, lo=0, hi=1):
    ax.set_ylim(lo, hi)
    ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0, decimals=0))


def caption(fig, text):
    fig.text(0.0, -0.02, text, ha="left", va="top", fontsize=8.5, color=MUTED, wrap=True)


def bump_text(fig):
    """Wide charts are shown ~7in wide on an A4 page or in the report column: scale their text up so it stays readable."""
    f = min(1.35, max(1.0, fig.get_figwidth() / 9))
    if f == 1.0:
        return
    tick_labels = set()
    for ax in fig.axes:
        for axis, name in ((ax.xaxis, "x"), (ax.yaxis, "y")):
            ticks = axis.get_major_ticks() + axis.get_minor_ticks()
            tick_labels.update(t for tk in ticks for t in (tk.label1, tk.label2))
            if ticks:
                ax.tick_params(axis=name, which="both", labelsize=ticks[0].label1.get_fontsize() * f)
    for t in fig.findobj(matplotlib.text.Text):
        if t not in tick_labels:
            t.set_fontsize(t.get_fontsize() * f)


def save_fig(fig, name, relayout=False):
    bump_text(fig)
    if relayout:
        fig.tight_layout()
    fig.savefig(FIG / name)


def wilson(k, n, z=1.96):
    p = k / n
    d = 1 + z**2 / n
    c = (p + z**2 / (2 * n)) / d
    h = z * np.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / d
    return c - h, c + h


def month_index(s: pd.Series) -> pd.Series:
    return s.dt.year * 12 + s.dt.month - 1


def mi_to_label(mi) -> str:
    return f"{int(mi) // 12}-{int(mi) % 12 + 1:02d}"


# ==========================================================================
# 1. LOAD + DATA QUALITY
# ==========================================================================
raw = pd.read_csv(DATA, parse_dates=["trxn_date"])
raw["txn_seq"] = raw["transaction_id"].str[3:].astype(int)
raw["mi"] = month_index(raw["trxn_date"])
LAST_MI = int(raw["mi"].max())

key("raw_rows", len(raw))
key("raw_users", raw["user_id"].nunique())
key("date_min", str(raw["trxn_date"].min().date()))
key("date_max", str(raw["trxn_date"].max().date()))
key("months_covered", raw["mi"].nunique())
key("null_cells", int(raw.isna().sum().sum()))
key("dup_transaction_ids", int(raw["transaction_id"].duplicated().sum()))

# 1a. Out-of-sequence rows.
# transaction_id is a global sequence 1..204,694 in which each user's transactions
# form one contiguous, date-ordered block. 104 rows sit outside their user's block,
# all at the very end of the ID range.
s = raw.sort_values("txn_seq")
block_id = (s["user_id"] != s["user_id"].shift()).cumsum()
first_block = block_id.groupby(s["user_id"]).transform("min")
raw["out_of_sequence"] = (block_id != first_block).reindex(raw.index)
oos = raw[raw["out_of_sequence"]].copy()
key("oos_rows", len(oos))
key("oos_users", oos["user_id"].nunique())
key("oos_id_min", oos["transaction_id"].min())
key("oos_id_max", oos["transaction_id"].max())

# What do these users look like without the out-of-sequence row?
ins = raw[~raw["out_of_sequence"]]
u_first_mi = ins.groupby("user_id")["mi"].min()
oos["age_of_row"] = oos["mi"] - oos["user_id"].map(u_first_mi)
in_seq_aff = ins[ins["user_id"].isin(oos["user_id"])]
aff_profile = in_seq_aff.groupby("user_id").agg(n_txn=("txn_seq", "size"), n_months=("mi", "nunique"))
key("oos_users_with_exactly_4_txn_all_in_M0",
    int(((aff_profile["n_txn"] == 4) & (aff_profile["n_months"] == 1)).sum()))
key("oos_rows_in_M1", int((oos["age_of_row"] == 1).sum()))
oos["days_after_last_in_seq_txn"] = (oos["trxn_date"] - oos["user_id"].map(ins.groupby("user_id")["trxn_date"].max())).dt.days
key("oos_days_after_last_min", int(oos["days_after_last_in_seq_txn"].min()))
key("oos_days_after_last_max", int(oos["days_after_last_in_seq_txn"].max()))

# 1b. Package -> carrier hierarchy: valid pairs have thousands of rows; violations are tiny cells.
pair_n = raw.groupby(["package_code", "carrier"])["txn_seq"].transform("size")
raw["hierarchy_violation"] = pair_n < 10
key("hierarchy_violations", int(raw["hierarchy_violation"].sum()))
key("hierarchy_violations_in_oos", int((raw["hierarchy_violation"] & raw["out_of_sequence"]).sum()))

# 1c. Balance consistency: outstanding should never rise by more than the transaction amount.
t = raw.sort_values(["user_id", "txn_seq"]).copy()
t["prev_out"] = t.groupby("user_id")["total_outstanding"].shift()
t["implied_repayment"] = t["prev_out"] + t["trxn_amount"] - t["total_outstanding"]
neg = t["implied_repayment"] < 0
key("negative_implied_repayment_rows", int(neg.sum()))
key("negative_implied_repayment_in_oos", int((neg & t["out_of_sequence"]).sum()))
first_txn = t[t["prev_out"].isna()]
key("first_txn_outstanding_below_amount_share",
    float((first_txn["total_outstanding"] < first_txn["trxn_amount"]).mean()))

# 1d. Other checks
key("carrier_other_services_lowercase_rows", int((raw["carrier"] == "Other services").sum()))
key("limit_constant_per_user_share", float((raw.groupby("user_id")["total_limit"].nunique() == 1).mean()))
key("outstanding_above_limit_rows", int((raw["total_outstanding"] > raw["total_limit"]).sum()))
same_day_amt_pairs = int(raw.duplicated(["user_id", "trxn_date", "trxn_amount"]).sum())
pmf = raw["trxn_amount"].value_counts(normalize=True)
k_ud = raw.groupby(["user_id", "trxn_date"]).size()
expected_pairs = float((k_ud * (k_ud - 1) / 2).sum() * (pmf**2).sum())
key("same_user_day_amount_pairs", same_day_amt_pairs)
key("same_user_day_amount_pairs_expected_by_chance", round(expected_pairs, 1))
key("exact_duplicates_except_id", int(raw.duplicated([c for c in raw.columns if c not in ("transaction_id", "txn_seq")]).sum()))
at_limit = t["total_outstanding"] == t["total_limit"]
key("rows_balance_at_limit", int(at_limit.sum()))
key("users_balance_at_limit", int(t.loc[at_limit, "user_id"].nunique()))
key("purchases_while_already_at_limit", int((at_limit & (t["prev_out"] == t["total_limit"])).sum()))

# Extra evidence on the out-of-sequence rows: compare their balance behaviour with organic rows
t["gap_days"] = (t["trxn_date"] - t.groupby("user_id")["trxn_date"].shift()).dt.days
org = t[~t["out_of_sequence"] & t["prev_out"].notna() & t["gap_days"].between(4, 41)]   # same gap range as the 104
oos_t = t[t["out_of_sequence"]]
key("oos_share_balance_below_previous", float((oos_t["total_outstanding"] < oos_t["prev_out"]).mean()))
key("organic_share_balance_below_previous", float((org["total_outstanding"] < org["prev_out"]).mean()))

oos_out = oos.merge(
    t[["transaction_id", "implied_repayment"]], on="transaction_id", how="left"
)[["transaction_id", "user_id", "trxn_date", "trxn_amount", "package_code", "carrier",
   "total_outstanding", "total_limit", "age_of_row", "implied_repayment"]]
oos_out["hierarchy_violation"] = oos_out["transaction_id"].isin(raw.loc[raw["hierarchy_violation"], "transaction_id"])
save(oos_out.sort_values("transaction_id"), "dq_out_of_sequence_rows", index=False)


# Clean dataset
df = raw[~raw["out_of_sequence"]].copy()
df["carrier"] = df["carrier"].replace({"Other services": "Other Services"})
key("clean_rows", len(df))

# ==========================================================================
# 2. USER + USER-MONTH TABLES
# ==========================================================================


def build(d: pd.DataFrame):
    d = d.sort_values(["user_id", "txn_seq"]).copy()
    d["util"] = d["total_outstanding"] / d["total_limit"]
    users = d.groupby("user_id").agg(
        first_date=("trxn_date", "min"), cohort=("mi", "min"), last_mi=("mi", "max"),
        n_txn=("txn_seq", "size"), gmv=("trxn_amount", "sum"), limit=("total_limit", "first"),
    )
    d = d.join(users[["first_date", "cohort"]], on="user_id")
    d["age"] = d["mi"] - d["cohort"]
    d["days_since_first"] = (d["trxn_date"] - d["first_date"]).dt.days
    um = d.groupby(["user_id", "mi"]).agg(
        n=("txn_seq", "size"), gmv=("trxn_amount", "sum"), avg_ticket=("trxn_amount", "mean"),
        n_categories=("carrier", "nunique"), util_end=("util", "last"), out_end=("total_outstanding", "last"),
        last_day=("trxn_date", lambda x: x.max().day), age=("age", "first"), limit=("total_limit", "first"),
        cohort=("cohort", "first"),
    ).reset_index().sort_values(["user_id", "mi"])
    um["next_mi"] = um.groupby("user_id")["mi"].shift(-1)
    um["churn_next"] = um["next_mi"].isna()
    um["prev_n"] = um.groupby("user_id")["n"].shift(1)
    users["n_months"] = um.groupby("user_id").size()
    users["n0"] = um[um["age"] == 0].set_index("user_id")["n"]
    users["m1"] = um[um["age"] == 1].groupby("user_id").size().reindex(users.index).fillna(0) > 0
    users["n30"] = d[d["days_since_first"] < 30].groupby("user_id").size()
    users["r30_60"] = d[(d["days_since_first"] >= 30) & (d["days_since_first"] < 60)].groupby("user_id").size().reindex(users.index).fillna(0) > 0
    users["join_day"] = users["first_date"].dt.day
    return d, users, um


df, users, um = build(df)
raw_b, users_raw, um_raw = build(raw)

# Reactivation check: any user with a gap between active months?
gaps = um.groupby("user_id")["mi"].apply(lambda x: (x.diff().dropna() > 1).any())
key("users_with_reactivation", int(gaps.sum()))
key("users_who_lapsed_observably", int((users["last_mi"] < LAST_MI).sum()))
# a lapsed user could only have been seen returning if at least one month followed their first empty month
key("lapsed_users_with_a_chance_to_return", int((users["last_mi"] <= LAST_MI - 2).sum()))
key("first_txn_on_day1_share", float((users["join_day"] == 1).mean()))
key("first_txn_by_day15_share", float((users["join_day"] <= 15).mean()))
key("first_txn_by_day3_share", float((users["join_day"] <= 3).mean()))

dq = pd.DataFrame([
    ("Rows / users", f"{len(raw):,} rows, {raw.user_id.nunique():,} users", "-"),
    ("Date range", f"{KEY['date_min']} to {KEY['date_max']} ({KEY['months_covered']} months; brief says 6)", "Used all 18 months"),
    ("Nulls / duplicate transaction_id", f"{KEY['null_cells']} / {KEY['dup_transaction_ids']}", "-"),
    ("Out-of-sequence rows (IDs outside the user's block)",
     f"{KEY['oos_rows']} rows ({KEY['oos_id_min']}-{KEY['oos_id_max']}), 1 per user; every user had exactly 4 txns, all in M0; every row lands in M1",
     "Quarantined (excluded) - see Q1c"),
    ("Package->carrier hierarchy violations", f"{KEY['hierarchy_violations']} rows, all {KEY['hierarchy_violations_in_oos']} inside the out-of-sequence rows", "Removed with them"),
    ("Outstanding rises by more than the txn amount", f"{KEY['negative_implied_repayment_rows']} rows, all {KEY['negative_implied_repayment_in_oos']} inside the out-of-sequence rows", "Removed with them"),
    ("'Other services' vs 'Other Services' label", f"{KEY['carrier_other_services_lowercase_rows']:,} rows (all Channel Partner)", "Merged for category counts"),
    ("First-ever txn has outstanding < txn amount", f"{KEY['first_txn_outstanding_below_amount_share']:.0%} of users", "Use outstanding only directionally; confirm snapshot timing"),
    ("Same user + day + amount", f"{same_day_amt_pairs} pairs vs ~{expected_pairs:.0f} expected by chance", "Kept (mostly different merchants, balances add up)"),
    ("total_limit changes over time", f"Never ({KEY['limit_constant_per_user_share']:.0%} of users have one value)", "Treated as static attribute"),
    ("Balance capped at the limit", f"{KEY['rows_balance_at_limit']:,} rows ({KEY['users_balance_at_limit']} users); {KEY['purchases_while_already_at_limit']:,} purchases made at an already-full limit", "Kept; flagged"),
    ("Exact duplicates (all fields except ID)", f"{KEY['exact_duplicates_except_id']} pair", "Kept (immaterial)"),
    ("Users who return after a fully inactive month", f"0 of {KEY['lapsed_users_with_a_chance_to_return']:,} who had a later month to return in", "Key finding - see Q1b"),
], columns=["Check", "Result", "Treatment"])
save(dq, "dq_checks", index=False)

# ==========================================================================
# 3. Q1b - COHORT RETENTION
# ==========================================================================
ct = um.groupby(["cohort", "age"])["user_id"].nunique().unstack()
size = ct[0]
ret = ct.div(size, axis=0)
for c in ret.index:  # mask unobservable cells
    ret.loc[c, [a for a in ret.columns if c + a > LAST_MI]] = np.nan
ret.index = [mi_to_label(c) for c in ret.index]
ret_out = ret.copy()
ret_out.insert(0, "cohort_size", size.values)
save(ret_out.round(4), "q1b_cohort_retention_users")

gmv_ct = um.groupby(["cohort", "age"])["gmv"].sum().unstack()
gmv_ret = gmv_ct.div(gmv_ct[0], axis=0)
for c in gmv_ret.index:
    gmv_ret.loc[c, [a for a in gmv_ret.columns if c + a > LAST_MI]] = np.nan
gmv_ret.index = [mi_to_label(c) for c in gmv_ret.index]
save(gmv_ret.round(4), "q1b_cohort_retention_gmv")

# weighted average curves (only cohorts that can observe age k)
avg = []
for k in range(0, 18):
    elig = [c for c in ct.index if c + k <= LAST_MI]
    if not elig:
        break
    users_k = ct.loc[elig, k].fillna(0).sum() if k in ct.columns else 0
    gmv_k = gmv_ct.loc[elig, k].fillna(0).sum() if k in gmv_ct.columns else 0
    avg.append(dict(age=k, cohorts=len(elig), base_users=size.loc[elig].sum(), retained=users_k,
                    user_retention=users_k / size.loc[elig].sum(),
                    gmv_retention=gmv_k / gmv_ct.loc[elig, 0].sum()))
avg = pd.DataFrame(avg).set_index("age")
# conditional month-on-month survival (hazard) by tenure, from the panel
haz = um[um["mi"] < LAST_MI].groupby("age")["churn_next"].agg(["size", "mean"]).rename(columns={"size": "user_months", "mean": "churn_next_month"})
avg = avg.join(haz)
save(avg.round(4), "q1b_average_retention_curve")
for k in (1, 2, 3, 6, 9, 12):
    key(f"avg_user_retention_M{k}", float(avg.loc[k, "user_retention"]))
    key(f"avg_gmv_retention_M{k}", float(avg.loc[k, "gmv_retention"]))
key("cohorts_with_observable_m1", int(ret[1].notna().sum()))
key("m1_range_min", float(ret[1].min()))
key("m1_range_max", float(ret[1].max()))
key("m3_range_min", float(ret[3].min()))
key("m3_range_max", float(ret[3].max()))
key("hazard_age0", float(haz.loc[0, "churn_next_month"]))
key("hazard_age1", float(haz.loc[1, "churn_next_month"]))
key("hazard_age2_to_8_mean", float(um[(um["mi"] < LAST_MI) & um["age"].between(2, 8)]["churn_next"].mean()))
key("overall_monthly_churn", float(um[um["mi"] < LAST_MI]["churn_next"].mean()))

# Homogeneity across cohorts (chi-square)
for k in (1, 3, 6):
    rows = []
    for c in ct.index:
        if c + k <= LAST_MI:
            r = ct.loc[c, k] if not np.isnan(ct.loc[c, k]) else 0
            rows.append([r, size.loc[c] - r])
    chi = stats.chi2_contingency(np.array(rows))
    key(f"chi2_cohort_homogeneity_M{k}_p", float(chi[1]))

# Lifetime: mean active months for cohorts with >= 12 months follow-up (Jan-Jun 2024)
mature = users[users["cohort"] <= 2024 * 12 + 5]
key("mean_active_months_mature_cohorts", float(mature["n_months"].mean()))
key("share_one_month_users", float((users[users["cohort"] < LAST_MI]["n_months"] == 1).mean()))
key("share_single_txn_users", float((users["n_txn"] == 1).mean()))

# Monthly business dynamics
mau = um.groupby("mi").agg(mau=("user_id", "size"), gmv=("gmv", "sum"), txn=("n", "sum"))
mau["new"] = users.groupby("cohort").size()
mau["returning"] = mau["mau"] - mau["new"]
mau["churn_next"] = um.groupby("mi")["churn_next"].mean()
mau.loc[LAST_MI, "churn_next"] = np.nan
mau["txn_per_user"] = mau["txn"] / mau["mau"]
mau["gmv_per_user"] = mau["gmv"] / mau["mau"]
mau.index = [mi_to_label(m) for m in mau.index]
save(mau.round(4), "q1b_monthly_dynamics")
key("mau_peak", int(mau["mau"].max()))
key("mau_peak_month", mau["mau"].idxmax())
key("mau_last", int(mau["mau"].iloc[-1]))
key("mau_change_from_peak", float(mau["mau"].iloc[-1] / mau["mau"].max() - 1))
key("new_users_first_month", int(mau["new"].iloc[0]))
key("new_users_q1_2024_avg", float(mau["new"].iloc[0:3].mean()))
key("new_users_2024_avg", float(mau["new"].iloc[0:12].mean()))
key("new_users_last", int(mau["new"].iloc[-1]))
key("new_users_change_mar24_to_jun25", float(mau["new"].iloc[-1] / mau["new"].loc["2024-03"] - 1))
cmgr12 = (mau["new"].iloc[-1] / mau["new"].iloc[-13]) ** (1 / 12) - 1
key("new_users_cmgr_12m", float(cmgr12))
key("gmv_peak_month", mau["gmv"].idxmax())
key("gmv_last_vs_peak", float(mau["gmv"].iloc[-1] / mau["gmv"].max() - 1))
key("churn_rate_jan24", float(mau["churn_next"].iloc[0]))            # every user brand new that month
key("churn_rate_range_min_from_feb24", float(mau["churn_next"].iloc[1:-1].min()))
key("churn_rate_range_max_from_feb24", float(mau["churn_next"].iloc[1:-1].max()))
key("new_users_change_q1_2024_avg_to_jun25", float(mau["new"].iloc[-1] / mau["new"].iloc[0:3].mean() - 1))
key("mau_jul_oct24_min", int(mau["mau"].loc["2024-07":"2024-10"].min()))
key("mau_jul_oct24_max", int(mau["mau"].loc["2024-07":"2024-10"].max()))
key("users_lost_may_to_jun25", int(round(mau["mau"].loc["2025-05"] * mau["churn_next"].loc["2025-05"])))
# Oct-24 new-user bump vs a log-linear trend fitted on Feb-24..Jun-25 without Oct-24
nu = mau["new"].iloc[1:].copy()
xs = np.arange(1, len(mau))
fit_mask = nu.index != "2024-10"
coef_tr = np.polyfit(xs[fit_mask], np.log(nu[fit_mask].values), 1)
oct_pos = list(mau.index).index("2024-10")
key("new_users_oct24", int(mau["new"].loc["2024-10"]))
key("new_users_oct24_trend", float(np.exp(np.polyval(coef_tr, oct_pos))))
key("txn_per_active_user_first", float(mau["txn_per_user"].iloc[0]))
key("txn_per_active_user_last", float(mau["txn_per_user"].iloc[-1]))
key("txn_per_user_by_age_0", float(um[um["age"] == 0]["n"].mean()))
key("txn_per_user_by_age_10plus", float(um[um["age"] >= 10]["n"].mean()))

# Does usage deepen with tenure, or do light users just leave first? Follow fixed groups of users.
um["lifetime"] = um["user_id"].map(users["n_months"])
wu = {f"users active >= {L} months": um[(um["lifetime"] >= L) & (um["age"] < L)].groupby("age")["n"].mean()
      for L in (3, 6, 9)}
wu = pd.DataFrame(wu)
wu.index = [f"M{a}" for a in wu.index]
save(wu.round(2), "q1b_within_user_frequency_by_tenure")
key("within_user_freq_9m_M0", float(wu.loc["M0", "users active >= 9 months"]))
key("within_user_freq_9m_M8", float(wu.loc["M8", "users active >= 9 months"]))
key("within_user_freq_3m_M0", float(wu.loc["M0", "users active >= 3 months"]))

# Are newer cohorts different users? (limit, first ticket, category mix by cohort)
first_row = df.sort_values("txn_seq").groupby("user_id").first()
first_row["cohort"] = users["cohort"]
coh_prof = first_row.groupby("cohort").agg(users=("total_limit", "size"), avg_limit=("total_limit", "mean"),
                                          first_ticket=("trxn_amount", "mean"))
coh_prof.index = [mi_to_label(c) for c in coh_prof.index]
save(coh_prof.round(0), "q1b_cohort_profile")
key("cohort_avg_limit_min_m", float(coh_prof["avg_limit"].min() / 1e6))
key("cohort_avg_limit_max_m", float(coh_prof["avg_limit"].max() / 1e6))
key("cohort_first_ticket_min_k", float(coh_prof["first_ticket"].min() / 1e3))
key("cohort_first_ticket_max_k", float(coh_prof["first_ticket"].max() / 1e3))
car_mix = pd.crosstab(df["mi"], df["carrier"], normalize="index")
key("carrier_share_max_shift_pp", float((car_mix.iloc[-3:].mean() - car_mix.iloc[:3].mean()).abs().max() * 100))
key("gmv_total_bn_vnd", float(df["trxn_amount"].sum() / 1e9))

# Raw vs clean M1 by cohort - the 104 rows are invisible at cohort level
m1_raw = users_raw[users_raw["cohort"] < LAST_MI].groupby("cohort")["m1"].mean()
m1_cln = users[users["cohort"] < LAST_MI].groupby("cohort")["m1"].mean()
key("max_cohort_m1_diff_raw_vs_clean_pp", float((m1_raw - m1_cln).abs().max() * 100))

# ==========================================================================
# 4. Q1c - FIRST-MONTH TRANSACTIONS (N) vs M1 RETENTION
# ==========================================================================


def m1_by_n(u: pd.DataFrame, col="n0", target="m1", cap=10):
    x = u.copy()
    x["N"] = x[col].clip(upper=cap)
    g = x.groupby("N")[target].agg(users="size", retained="sum")
    g["rate"] = g["retained"] / g["users"]
    lo, hi = wilson(g["retained"], g["users"])
    g["ci_low"], g["ci_high"] = lo, hi
    return g


elig = users[users["cohort"] < LAST_MI]            # M1 observable
elig_raw = users_raw[users_raw["cohort"] < LAST_MI]
q_clean = m1_by_n(elig)
q_raw = m1_by_n(elig_raw)
q = q_raw[["users", "rate"]].rename(columns={"rate": "m1_raw", "users": "users"}).join(
    q_clean[["rate", "ci_low", "ci_high"]].rename(columns={"rate": "m1_clean"}))
q["share_of_new_users"] = q["users"] / q["users"].sum()
save(q.round(4), "q1c_m1_by_first_month_txns")
for n in range(1, 9):
    key(f"q1c_m1_raw_N{n}", float(q_raw.loc[n, "rate"]))
    key(f"q1c_m1_clean_N{n}", float(q_clean.loc[n, "rate"]))
    key(f"q1c_users_N{n}", int(q_clean.loc[n, "users"]))
key("q1c_eligible_users", len(elig))
key("q1c_users_N9plus", int((elig["n0"] >= 9).sum()))
key("q1c_m1_clean_N9plus", float(elig[elig["n0"] >= 9]["m1"].mean()))
key("q1c_m1_clean_N4to8_min", float(q_clean.loc[4:8, "rate"].min()))
key("q1c_m1_clean_N4to8_max", float(q_clean.loc[4:8, "rate"].max()))

# threshold scan: >= N vs < N
scan = []
for label, u in (("raw", elig_raw), ("clean", elig)):
    for N in range(2, 11):
        a, b = u[u["n0"] >= N]["m1"], u[u["n0"] < N]["m1"]
        _, p = stats.chi2_contingency([[a.sum(), len(a) - a.sum()], [b.sum(), len(b) - b.sum()]])[:2]
        scan.append(dict(data=label, N=N, share_ge_N=len(a) / len(u), m1_ge_N=a.mean(), m1_lt_N=b.mean(),
                         lift_pp=(a.mean() - b.mean()) * 100, p_value=p))
scan = pd.DataFrame(scan)
save(scan.round(5), "q1c_threshold_scan", index=False)
for label in ("raw", "clean"):
    s_ = scan[scan["data"] == label].set_index("N")
    key(f"q1c_{label}_best_N", int(s_["lift_pp"].idxmax()))
    key(f"q1c_{label}_best_lift_pp", float(s_["lift_pp"].max()))
    key(f"q1c_{label}_lift_N4_pp", float(s_.loc[4, "lift_pp"]))
    key(f"q1c_{label}_ge4", float(s_.loc[4, "m1_ge_N"]))
    key(f"q1c_{label}_lt4", float(s_.loc[4, "m1_lt_N"]))
s_c = scan[(scan["data"] == "clean") & scan["N"].between(2, 8)]
key("q1c_clean_lift_range_N2_8_min", float(s_c["lift_pp"].min()))
key("q1c_clean_lift_range_N2_8_max", float(s_c["lift_pp"].max()))
share_ge4 = (elig["n0"] >= 4).mean()
key("q1c_share_new_users_ge4", float(share_ge4))

# what the 104 rows do to the N = 4 cell
n4_raw = elig_raw[elig_raw["n0"] == 4]
n4_cln = elig[elig["n0"] == 4]
key("q1c_n4_users", len(n4_cln))
key("q1c_n4_retained_raw", int(n4_raw["m1"].sum()))
key("q1c_n4_retained_clean", int(n4_cln["m1"].sum()))
# in clean data, how many "exactly 4 txns in M0" users did NOT come back - the pool the 104 rows convert
key("q1c_n4_not_retained_clean", int(len(n4_cln) - n4_cln["m1"].sum()))

# step tests on clean data: 3 vs 4 and 4 vs 5+
def two_prop(a, b):
    tbl = [[a.sum(), len(a) - a.sum()], [b.sum(), len(b) - b.sum()]]
    return stats.chi2_contingency(tbl)[1]


key("q1c_clean_p_3_vs_4", float(two_prop(elig[elig["n0"] == 3]["m1"], elig[elig["n0"] == 4]["m1"])))
key("q1c_clean_p_4_vs_5to8", float(two_prop(elig[elig["n0"] == 4]["m1"], elig[elig["n0"].between(5, 8)]["m1"])))
key("q1c_raw_p_4_vs_5to8", float(two_prop(elig_raw[elig_raw["n0"] == 4]["m1"], elig_raw[elig_raw["n0"].between(5, 8)]["m1"])))
key("q1c_clean_m1_5to8", float(elig[elig["n0"].between(5, 8)]["m1"].mean()))

# robustness 1: join timing (partial first month)
elig = elig.assign(join_half=np.where(elig["join_day"] <= 15, "joined day 1-15", "joined day 16-31"))
jt = elig.assign(N=elig["n0"].clip(upper=6)).pivot_table(index="N", columns="join_half", values="m1", aggfunc=["mean", "size"])
save(jt.round(4), "q1c_by_join_timing")
key("q1c_share_late_joiners_reaching_4", float((elig[elig["join_day"] > 15]["n0"] >= 4).mean()))
key("q1c_share_early_joiners_reaching_4", float((elig[elig["join_day"] <= 15]["n0"] >= 4).mean()))

# robustness 2: rolling 30-day definition (equal exposure for every user)
elig30 = users[users["first_date"] <= raw["trxn_date"].max() - pd.Timedelta(days=59)]
elig30_raw = users_raw[users_raw["first_date"] <= raw["trxn_date"].max() - pd.Timedelta(days=59)]
r30 = m1_by_n(elig30, col="n30", target="r30_60")
r30_raw = m1_by_n(elig30_raw, col="n30", target="r30_60")
r30_tab = r30[["users", "rate", "ci_low", "ci_high"]].rename(columns={"rate": "d30_60_clean"}).join(r30_raw[["rate"]].rename(columns={"rate": "d30_60_raw"}))
save(r30_tab.round(4), "q1c_rolling_30d_definition")
for n in range(1, 9):
    key(f"q1c_d30_clean_N{n}", float(r30.loc[n, "rate"]))
key("q1c_d30_share_single_txn", float((elig30["n30"] == 1).mean()))
key("q1c_d30_overall", float(elig30["r30_60"].mean()))

# robustness 2b: users with a full first calendar month (first transaction on day 1-3).
# Churn happens at calendar-month boundaries, so this is the cleanest like-for-like view.
full = elig[elig["join_day"] <= 3]
q_full = m1_by_n(full, cap=6)
save(q_full.round(4), "q1c_full_first_month")
for n in range(1, 7):
    key(f"q1c_full_month_m1_N{n}", float(q_full.loc[n, "rate"]))
key("q1c_full_month_users", len(full))
key("q1c_share_n0_eq1", float((elig["n0"] == 1).mean()))
# the 30-day view by join timing: late joiners with 1 txn in 30 days have usually already missed a month boundary
e30 = elig30.assign(join_band=pd.cut(elig30["join_day"], [0, 3, 10, 20, 31], labels=["day 1-3", "day 4-10", "day 11-20", "day 21-31"]))
jb = e30.pivot_table(index=e30["n30"].clip(upper=5), columns="join_band", values="r30_60", aggfunc="mean", observed=True)
save(jb.round(4), "q1c_rolling_30d_by_join_day")
key("q1c_d30_N1_join_day1_3", float(jb.loc[1, "day 1-3"]))
key("q1c_d30_N1_join_day21_31", float(jb.loc[1, "day 21-31"]))
key("q1c_d30_N2_join_day21_31", float(jb.loc[2, "day 21-31"]))
jd_act = e30.groupby("join_band", observed=True)["r30_60"].mean()
key("d30_activity_join_day1_3", float(jd_act["day 1-3"]))
key("d30_activity_join_day21_31", float(jd_act["day 21-31"]))

# robustness 3: logistic regression with cohort + join-day controls (clean)
lr = elig.assign(Nb=elig["n0"].clip(upper=8).astype(str), cohort_s=elig["cohort"].astype(str),
                 jd=pd.cut(elig["join_day"], [0, 7, 14, 21, 31]).astype(str), m1i=elig["m1"].astype(int))
m_q1c = smf.logit("m1i ~ C(Nb) + C(jd) + C(cohort_s)", data=lr).fit(disp=0)
coef = m_q1c.summary2().tables[1]
coef = coef[coef.index.str.startswith("C(Nb)")]
save(coef.round(4), "q1c_logit_controls")
key("q1c_logit_coef_N4", float(coef.loc["C(Nb)[T.4]", "Coef."]))
key("q1c_logit_coef_N5", float(coef.loc["C(Nb)[T.5]", "Coef."]))

# value of early engagement: cohorts with >= 12 months follow-up
mat = users[users["cohort"] <= 2024 * 12 + 5].copy()
mat["N_group"] = pd.cut(mat["n0"], [0, 1, 2, 3, 4, 100], labels=["1", "2", "3", "4", "5+"])
ltv = mat.groupby("N_group", observed=True).agg(users=("n_months", "size"), active_months=("n_months", "mean"),
                                               txns=("n_txn", "sum"), gmv=("gmv", "mean"))
ltv["txns"] = ltv["txns"] / ltv["users"]
save(ltv.round(1), "q1c_lifetime_value_by_first_month_txns")
key("ltv_gmv_N1", float(ltv.loc["1", "gmv"]))
key("ltv_gmv_N5plus", float(ltv.loc["5+", "gmv"]))
key("ltv_months_N1", float(ltv.loc["1", "active_months"]))
key("ltv_months_N5plus", float(ltv.loc["5+", "active_months"]))

# ==========================================================================
# 5. PART 2 - CHURN DEEP-DIVE
# ==========================================================================
panel = um[um["mi"] < LAST_MI].copy()       # rows whose next month is observable
panel["churn"] = panel["churn_next"].astype(int)
key("churned_users", int((users["last_mi"] < LAST_MI).sum()))
key("active_users_last_month", int((users["last_mi"] == LAST_MI).sum()))


def hazard(col, bins=None, labels=None):
    x = panel[col] if bins is None else pd.cut(panel[col], bins, labels=labels)
    g = panel.groupby(x, observed=True)["churn"].agg(user_months="size", churn_rate="mean")
    g.index = g.index.astype(str)
    return g


h_n = hazard("n", [0, 1, 2, 3, 4, 5, 6, 8, 100], ["1", "2", "3", "4", "5", "6", "7-8", "9+"])
h_prev = hazard("prev_n", [0, 1, 2, 3, 100], ["1", "2", "3", "4+"])
h_age = hazard("age", [-1, 0, 1, 2, 3, 5, 8, 17], ["M0", "M1", "M2", "M3", "M4-5", "M6-8", "M9+"])
h_cat = hazard("n_categories", [0, 1, 2, 3, 100], ["1", "2", "3", "4+"])
h_tk = hazard("avg_ticket", [0, 50e3, 100e3, 150e3, 200e3, 300e3, 5e6], ["<50K", "50-100K", "100-150K", "150-200K", "200-300K", "300K+"])
panel["util_band"] = np.select(
    [panel["util_end"] >= 1, panel["util_end"] >= 0.5, panel["util_end"] >= 0.2, panel["util_end"] >= 0.05],
    ["At limit", "50-99%", "20-50%", "5-20%"], "<5%")
h_util = panel.groupby("util_band")["churn"].agg(user_months="size", churn_rate="mean").loc[
    ["<5%", "5-20%", "20-50%", "50-99%", "At limit"]]
h_lim = hazard("limit", [0, 2e6, 4e6, 6e6, 8e6, 1e7], ["<=2M", "2-4M", "4-6M", "6-8M", "8-10M"])
hz_all = pd.concat({"txns_this_month": h_n, "txns_prev_month": h_prev, "tenure": h_age,
                    "merchant_categories": h_cat, "avg_ticket": h_tk, "utilisation_end_month": h_util,
                    "credit_limit": h_lim})
save(hz_all.round(4), "p2_churn_rate_by_feature")
key("churn_n1", float(h_n.loc["1", "churn_rate"]))
key("churn_n2", float(h_n.loc["2", "churn_rate"]))
key("churn_n3", float(h_n.loc["3", "churn_rate"]))
key("churn_n4plus", float(panel[panel["n"] >= 4]["churn"].mean()))
key("churn_n1_to_3", float(panel[panel["n"] <= 3]["churn"].mean()))
key("share_user_months_le3", float((panel["n"] <= 3).mean()))
key("share_user_months_1txn", float((panel["n"] == 1).mean()))
key("churn_limit_min", float(h_lim["churn_rate"].min()))
key("churn_limit_max", float(h_lim["churn_rate"].max()))
key("churn_util_below_limit_min", float(h_util["churn_rate"].iloc[:-1].min()))
key("churn_util_below_limit_max", float(h_util["churn_rate"].iloc[:-1].max()))

# Multivariate: which signals survive controls?
# Pb = 0 marks a user's first month (no previous month). Tenure therefore starts at 1:
# a separate M0 tenure level would be perfectly collinear with Pb = 0.
pm = panel.assign(
    Nb=panel["n"].clip(upper=6).astype(str),
    Pb=panel["prev_n"].fillna(0).clip(upper=4).astype(int).astype(str),
    Ab=panel["age"].clip(lower=1, upper=6).astype(str),
    Cb=panel["n_categories"].clip(upper=4).astype(str),
    Tb=pd.cut(panel["avg_ticket"], [0, 100e3, 150e3, 200e3, 300e3, 5e6], labels=["<100K", "100-150K", "150-200K", "200-300K", "300K+"]).astype(str),
    log_limit=np.log(panel["limit"]),
)
pm["at_limit"] = (pm["util_end"] >= 1).astype(int)
formula = ("churn ~ C(Nb) + C(Pb) + C(Ab) + C(Cb) + C(Tb, Treatment('150-200K')) + util_end + at_limit + log_limit + last_day")
m_full = smf.logit(formula, data=pm).fit(disp=0)
tbl = m_full.summary2().tables[1]
tbl["odds_ratio"] = np.exp(tbl["Coef."])
save(tbl.round(4), "p2_logit_churn_drivers")
key("logit_pseudo_r2", float(m_full.prsquared))
key("logit_coef_at_limit", float(tbl.loc["at_limit", "Coef."]))
key("logit_p_at_limit", float(tbl.loc["at_limit", "P>|z|"]))


def lr_test(restricted_formula):
    """Likelihood-ratio test of the full model against a model without some terms."""
    m_r = smf.logit(restricted_formula, data=pm).fit(disp=0)
    stat = 2 * (m_full.llf - m_r.llf)
    dof = m_full.df_model - m_r.df_model
    return float(stats.chi2.sf(stat, dof))


base_terms = "churn ~ C(Nb) + C(Pb) + C(Ab)"
key("lr_p_non_frequency_excl_at_limit", lr_test(base_terms + " + at_limit"))
key("lr_p_all_non_frequency_incl_at_limit", lr_test(base_terms))
key("lr_p_categories", lr_test(formula.replace(" + C(Cb)", "")))
key("lr_p_ticket", lr_test(formula.replace(" + C(Tb, Treatment('150-200K'))", "")))
key("lr_p_util_limit_lastday", lr_test(base_terms + " + C(Cb) + C(Tb, Treatment('150-200K')) + at_limit"))
cap = panel.assign(at_limit=panel["util_end"] >= 1)
key("at_limit_user_months", int(cap["at_limit"].sum()))
key("at_limit_share_user_months", float(cap["at_limit"].mean()))
key("churn_at_limit", float(cap[cap["at_limit"]]["churn"].mean()))
key("churn_not_at_limit", float(cap[~cap["at_limit"]]["churn"].mean()))
ever_cap = df.groupby("user_id")["util"].max() >= 1
key("ever_at_limit_share_limit_le1m", float(ever_cap[users["limit"] <= 1e6].mean()))
key("ever_at_limit_share_limit_gt3m", float(ever_cap[users["limit"] > 3e6].mean()))
key("logit_p_util", float(tbl.loc["util_end", "P>|z|"]))
key("logit_p_limit", float(tbl.loc["log_limit", "P>|z|"]))
key("logit_p_lastday", float(tbl.loc["last_day", "P>|z|"]))
key("logit_min_p_categories", float(tbl[tbl.index.str.startswith("C(Cb)")]["P>|z|"].min()))
key("logit_min_p_ticket", float(tbl[tbl.index.str.startswith("C(Tb")]["P>|z|"].min()))

# Momentum: previous-month x current-month frequency
fb = lambda s: pd.cut(s, [0, 1, 3, 100], labels=["1", "2-3", "4+"])
mom_src = panel[panel["prev_n"].notna()]
mom = mom_src.groupby([fb(mom_src["prev_n"]).rename("prev_month_txns"), fb(mom_src["n"]).rename("this_month_txns")],
                      observed=True)["churn"].agg(user_months="size", churn_rate="mean")
save(mom.round(4), "p2_churn_by_prev_and_current_freq")
key("churn_1_then_1", float(mom.loc[("1", "1"), "churn_rate"]))
key("churn_4p_then_4p", float(mom.loc[("4+", "4+"), "churn_rate"]))

# Out-of-time validation: train on months <= Dec-2024, test on Jan-May 2025
cut = 2024 * 12 + 11
train, test = pm[pm["mi"] <= cut], pm[pm["mi"] > cut]
m_oot = smf.logit(formula, data=train).fit(disp=0)
test = test.assign(score=m_oot.predict(test))
auc = roc_auc_score(test["churn"], test["score"])
key("oot_auc", float(auc))
test["decile"] = pd.qcut(test["score"].rank(method="first"), 10, labels=list(range(10, 0, -1))).astype(int)
dec = test.groupby("decile").agg(user_months=("churn", "size"), churn_rate=("churn", "mean"), churners=("churn", "sum")).sort_index()
dec["capture_cum"] = dec["churners"].cumsum() / dec["churners"].sum()
save(dec.round(4), "p2_out_of_time_deciles")
key("oot_top_decile_churn", float(dec.loc[1, "churn_rate"]))
key("oot_bottom_decile_churn", float(dec.loc[10, "churn_rate"]))
key("oot_top20_capture", float(dec.loc[2, "capture_cum"]))
key("oot_base_churn", float(test["churn"].mean()))

# Churned vs stayed - (a) month before leaving vs months followed by more activity
prof = panel.assign(one_txn=panel["n"] == 1, four_plus=panel["n"] >= 4).groupby("churn").agg(
    user_months=("n", "size"), avg_txns=("n", "mean"), share_1_txn=("one_txn", "mean"),
    share_4plus_txn=("four_plus", "mean"), avg_ticket=("avg_ticket", "mean"),
    merchant_categories=("n_categories", "mean"), util_end=("util_end", "median"),
    credit_limit=("limit", "mean"), tenure_months=("age", "mean"))
prof.index = ["Stayed (active next month)", "Churned (no txn next month)"]
save(prof.T.round(3), "p2_profile_month_level")

# (b) user level: churned vs still active in the last month
ul = users.copy()
ul["status"] = np.where(ul["last_mi"] == LAST_MI, "Active in Jun-2025", "Churned")
ul["avg_txn_per_month"] = ul["n_txn"] / ul["n_months"]
# only users with a full 30-day window can be judged on "2nd txn within 30 days"
full30 = ul["first_date"] <= raw["trxn_date"].max() - pd.Timedelta(days=29)
ul["second_txn_30d"] = np.where(full30, ul["n30"] >= 2, np.nan)
last_txn = df.sort_values(["user_id", "txn_seq"]).groupby("user_id").tail(1).set_index("user_id")
ul["out_at_last_txn"] = last_txn["total_outstanding"]
prof_u = ul.groupby("status").agg(
    users=("n_txn", "size"), first_month_txns=("n0", "mean"), share_2plus_txn_first_30d=("second_txn_30d", "mean"),
    avg_txn_per_active_month=("avg_txn_per_month", "mean"), active_months=("n_months", "mean"),
    avg_ticket=("gmv", "sum"), credit_limit=("limit", "mean"))
prof_u["avg_ticket"] = ul.groupby("status")["gmv"].sum() / ul.groupby("status")["n_txn"].sum()
save(prof_u.T.round(3), "p2_profile_user_level")
key("profile_churned_2plus_30d", float(prof_u.loc["Churned", "share_2plus_txn_first_30d"]))
key("profile_active_2plus_30d", float(prof_u.loc["Active in Jun-2025", "share_2plus_txn_first_30d"]))
key("profile_churned_txn_per_month", float(prof_u.loc["Churned", "avg_txn_per_active_month"]))
key("profile_active_txn_per_month", float(prof_u.loc["Active in Jun-2025", "avg_txn_per_active_month"]))

# Exposure at churn (balance at last observed transaction)
ch = ul[ul["status"] == "Churned"]
key("churned_with_balance_share", float((ch["out_at_last_txn"] > 0).mean()))
key("churned_balance_total_bn_vnd", float(ch["out_at_last_txn"].sum() / 1e9))
key("churned_balance_mean_k_vnd", float(ch["out_at_last_txn"].mean() / 1e3))
# Same measure for months followed by more activity (balance after the month's last purchase)
stay_rows = panel[panel["churn"] == 0]
key("stayer_months_with_balance_share", float((stay_rows["out_end"] > 0).mean()))
key("stayer_months_balance_mean_k_vnd", float(stay_rows["out_end"].mean() / 1e3))

# Intra-month lapse signal: if a user active in month t has not transacted by day d of t+1,
# how likely are they to transact later in t+1?
first_day_next = df.groupby(["user_id", "mi"])["trxn_date"].min().dt.day.rename("first_day").reset_index()
first_day_next["mi"] -= 1                       # align to the previous month
lapse = panel[["user_id", "mi"]].merge(first_day_next, on=["user_id", "mi"], how="left")
lapse_rows = []
for d in (5, 7, 10, 15, 20, 25):
    silent = lapse[lapse["first_day"].isna() | (lapse["first_day"] > d)]
    lapse_rows.append(dict(day=d, share_silent=len(silent) / len(lapse),
                           p_transacts_later=silent["first_day"].notna().mean(),
                           p_lost_for_good=silent["first_day"].isna().mean()))
lapse_tab = pd.DataFrame(lapse_rows).set_index("day")
save(lapse_tab.round(4), "p2_lapse_signal")
for d in (7, 10, 15, 20):
    key(f"lapse_share_silent_day{d}", float(lapse_tab.loc[d, "share_silent"]))
    key(f"lapse_p_lost_day{d}", float(lapse_tab.loc[d, "p_lost_for_good"]))
key("current_base_share_le3_txn", float((um[um["mi"] == LAST_MI]["n"] <= 3).mean()))

# Risk tiers for the current base (users active in Jun-2025), using historical hazards
cur = um[um["mi"] == LAST_MI].copy()
tier_of = lambda n: "High (1 txn)" if n == 1 else ("Medium (2-3 txns)" if n <= 3 else "Low (4+ txns)")
cur["tier"] = cur["n"].map(tier_of)
panel["tier"] = panel["n"].map(tier_of)
hist = panel.groupby("tier")["churn"].mean()
tiers = cur.groupby("tier").agg(users=("user_id", "size"))
tiers["hist_churn_rate"] = hist
tiers["expected_churners_next_month"] = tiers["users"] * tiers["hist_churn_rate"]
tiers = tiers.loc[["High (1 txn)", "Medium (2-3 txns)", "Low (4+ txns)"]]
save(tiers.round(3), "p2_current_base_risk_tiers")
for tname, kname in (("High (1 txn)", "high"), ("Medium (2-3 txns)", "medium"), ("Low (4+ txns)", "low")):
    key(f"tier_{kname}_users", int(tiers.loc[tname, "users"]))
    key(f"tier_{kname}_churn", float(tiers.loc[tname, "hist_churn_rate"]))
key("tier_expected_churners_total", float(tiers["expected_churners_next_month"].sum()))

# ==========================================================================
# 6. SCENARIOS - stock-flow model of MAU
#    MAU[t+1] = MAU[t] * (1 - churn) + New[t+1]
# ==========================================================================
mau_mi = um.groupby("mi").agg(mau=("user_id", "size"))
mau_mi["new"] = users.groupby("cohort").size()
recent = panel[panel["mi"] >= LAST_MI - 6]                       # Dec-24 .. May-25
churn_recent = float(recent["churn"].mean())
key("scenario_churn_base", churn_recent)

# In-sample check: drive the model with actual new users from Jan-2024 at the same constant churn.
# With zero reactivation the model is an accounting identity, so this only tests that churn was stable.
bt = [float(mau_mi["mau"].iloc[0])]
for i in range(1, len(mau_mi)):
    bt.append(bt[-1] * (1 - churn_recent) + float(mau_mi["new"].iloc[i]))
mape = float(np.mean(np.abs(np.array(bt) - mau_mi["mau"].values) / mau_mi["mau"].values))
key("scenario_backtest_mape", mape)

H = 12
mau_last = float(mau_mi["mau"].iloc[-1])
new_last = float(mau_mi["new"].iloc[-1])
new_2024 = float(mau_mi["new"].iloc[0:12].mean())
# illustrative frequency programme: every 1-3 txn user churns like a 4+ txn user (same window); an assumption, not a proven bound
churn_freq = float(recent[recent["n"] >= 4]["churn"].mean())
key("scenario_churn_if_all_low_freq_behave_like_4plus", churn_freq)
key("users_lost_per_month_recent", churn_recent * mau_last)
key("new_users_needed_to_hold_mau", churn_recent * mau_last)
key("churn_needed_to_hold_mau", new_last / mau_last)


def project(new_fn, churn):
    m = [mau_last]
    for h in range(1, H + 1):
        m.append(m[-1] * (1 - churn) + new_fn(h))
    return m[1:]


ramp = lambda h: new_last + (new_2024 - new_last) * min(h, 3) / 3   # back to 2024 average over 3 months
key("scenario_D_ramp_m1", ramp(1))
key("scenario_D_ramp_m2", ramp(2))
scen = {
    "A. New users keep falling ~5%/month": project(lambda h: new_last * (1 + cmgr12) ** h, churn_recent),
    "B. New users stop falling (596/month)": project(lambda h: new_last, churn_recent),
    "C. B + every light user churns like a heavy user (assumption)": project(lambda h: new_last, churn_freq),
    "D. New users back to 2024 average (%s/month)" % f"{new_2024:,.0f}": project(ramp, churn_recent),
}
fut_idx = [mi_to_label(LAST_MI + h) for h in range(1, H + 1)]
scen_df = pd.DataFrame(scen, index=fut_idx)
scen_df["E. D + C combined (not plotted)"] = project(ramp, churn_freq)
save(scen_df.round(0), "p2_mau_scenarios")
for i, col in enumerate(scen_df.columns):
    key(f"scenario_{'ABCDE'[i]}_mau_jun26", float(scen_df[col].iloc[-1]))

# Sensitivity: tenure-aware projection (new users churn faster than tenured ones), scenarios B and D
haz_age = um[um["mi"] < LAST_MI].groupby(um["age"].clip(upper=8))["churn_next"].mean()
base_by_age = um[um["mi"] == LAST_MI].groupby(um["age"].clip(upper=8)).size().reindex(range(9), fill_value=0).astype(float)


def project_tenure(new_fn):
    s_ = base_by_age.copy()
    for h in range(1, H + 1):
        nxt = pd.Series(0.0, index=s_.index)
        for a in s_.index:
            nxt[min(a + 1, 8)] += s_[a] * (1 - haz_age[a])
        nxt[0] += new_fn(h)
        s_ = nxt
    return float(s_.sum())


key("scenario_B_tenure_aware_gap", project_tenure(lambda h: new_last) / scen_df.iloc[-1, 1] - 1)
key("scenario_D_tenure_aware_gap", project_tenure(ramp) / scen_df.iloc[-1, 3] - 1)
key("new_users_2024_avg_rounded", round(new_2024))
key("steady_state_mau_flat_acq", new_last / churn_recent)
key("dormant_users", int((users["last_mi"] < LAST_MI).sum()))

# Size every action in one unit: extra active users in Jun-26 vs scenario B (new users flat)
B_end = scen_df.iloc[-1, 1]
one_done_share = float((elig["n0"] == 1).mean())
uplift_2nd = float(q_clean.loc[2, "rate"] - q_clean.loc[1, "rate"])  # all-user calendar step 1->2 (unadjusted)
extra_kept_2nd = new_last * one_done_share * uplift_2nd          # if every one-transaction new user made a 2nd purchase
recent_cap = recent.assign(cap=recent["util_end"] >= 1)
cap_churn_cut = float(recent_cap["cap"].mean()) * (KEY["churn_at_limit"] - KEY["churn_not_at_limit"])
sizing = pd.DataFrame([
    ("Recover new users to the 2024 average", "inflow 596 -> 1,144/month over 3 months", scen_df.iloc[-1, 3] - B_end),
    ("Frequency rewards for light users", "assumption: every 1-3 txn user churns like a 4+ user", scen_df.iloc[-1, 2] - B_end),
    ("Mid-month reminder to silent users", "assumption: saves 1 in 10 of the users who would otherwise be lost (churn x 0.9)", project(lambda h: new_last, churn_recent * 0.9)[-1] - B_end),
    ("Win-back of dormant users (illustration)", "assumption: 1% of dormant users return each month (0% observed so far)", project(lambda h: new_last + 0.01 * KEY["dormant_users"], churn_recent)[-1] - B_end),
    ("Second-purchase offer for new users", "assumption: every 1-transaction new user makes a 2nd purchase (+3pp M1 each)", project(lambda h: new_last + extra_kept_2nd, churn_recent)[-1] - B_end),
    ("Raise limits for users who hit their limit", "assumption: capped users churn like everyone else", project(lambda h: new_last, churn_recent - cap_churn_cut)[-1] - B_end),
], columns=["action", "assumption", "extra_active_users_jun26"])
save(sizing.round(0), "p2_action_sizing", index=False)
for i, r in sizing.iterrows():
    key(f"sizing_{i}_{r['action'].split()[0].lower()}", float(r["extra_active_users_jun26"]))
key("one_txn_first_month_share", one_done_share)
key("uplift_2nd_all_users", uplift_2nd)
key("uplift_2nd_full_month", float(q_full.loc[2, "rate"] - q_full.loc[1, "rate"]))
key("extra_kept_per_month_2nd_purchase", extra_kept_2nd)

# ==========================================================================
# 7. BONUS - limits, utilisation, seasonality
# ==========================================================================
lim_q = um.assign(limit_q=pd.qcut(um["limit"], 5)).groupby("limit_q", observed=True).agg(
    txns_per_month=("n", "mean"), gmv_per_month=("gmv", "mean"), median_util=("util_end", "median"))
lim_q["m1_retention"] = elig.groupby(pd.qcut(elig["limit"], 5), observed=True)["m1"].mean().values
lim_q.index = lim_q.index.astype(str)
save(lim_q.round(4), "bonus_credit_limit_quintiles")
key("median_util_end_month", float(um["util_end"].median()))
key("share_user_months_util_gt_80", float((um.groupby(["user_id", "mi"])["util_end"].max() > 0.8).mean()))
key("avg_limit_m_vnd", float(users["limit"].mean() / 1e6))
key("avg_gmv_per_active_month_k", float(um["gmv"].mean() / 1e3))
key("txn_per_month_lowest_limit_q", float(lim_q["txns_per_month"].iloc[0]))
key("txn_per_month_highest_limit_q", float(lim_q["txns_per_month"].iloc[-1]))
dow = df.groupby(df["trxn_date"].dt.dayofweek).size()
key("dow_max_over_min", float(dow.max() / dow.min()))
# day-of-month and payday: each day's volume relative to its own month's daily average (removes the trend)
daily = df.groupby(df["trxn_date"].dt.normalize()).size()
rel = daily / daily.groupby(daily.index.to_period("M")).transform("mean")
dom_rel = rel.groupby(rel.index.day).mean()
key("dom_index_max", float(dom_rel.max()))
key("dom_index_min", float(dom_rel.min()))
key("payday_days_index", float(rel[(rel.index.day <= 5) | (rel.index.day >= 25)].mean()))
# Tet 2025 (29 Jan): Tet week vs the 28 days before
tet_week = daily.loc["2025-01-27":"2025-02-02"].mean()
pre_tet = daily.loc["2024-12-30":"2025-01-26"].mean()
key("tet2025_week_vs_prior_4w", float(tet_week / pre_tet))
save(dom_rel.rename("volume_vs_month_avg").round(4).to_frame(), "bonus_day_of_month_index")
mix = pd.crosstab(df["trxn_date"].dt.to_period("M"), df["package_code"], normalize="index")
key("package_share_max_range_pp", float((mix.max() - mix.min()).max() * 100))
save(mix.round(4), "bonus_package_mix_by_month")
key("avg_ticket_k", float(df["trxn_amount"].mean() / 1e3))
key("median_ticket_k", float(df["trxn_amount"].median() / 1e3))

# ==========================================================================
# 7b. EXTENDED FINDINGS (beyond the brief)
# ==========================================================================
from scipy.optimize import minimize
from scipy.special import betaln

seg_of = lambda n: np.where(n == 1, "Light (1)", np.where(n <= 3, "Medium (2-3)", "Heavy (4+)"))
SEGS = ["Light (1)", "Medium (2-3)", "Heavy (4+)"]
um["seg"] = seg_of(um["n"])

# E1. Segment dynamics: where does each segment go next month?
nxt = um[["user_id", "mi", "n"]].assign(mi=lambda x: x["mi"] - 1).rename(columns={"n": "n_next"})
tr = um[um["mi"] < LAST_MI].merge(nxt, on=["user_id", "mi"], how="left")
tr["next_state"] = np.where(tr["n_next"].isna(), "Churned", seg_of(tr["n_next"].fillna(0)))
trans = pd.crosstab(tr["seg"], tr["next_state"], normalize="index").loc[SEGS, SEGS + ["Churned"]]
save(trans.round(4), "x1_segment_transitions")
key("x_trans_heavy_stay", float(trans.loc["Heavy (4+)", "Heavy (4+)"]))
key("x_trans_heavy_to_light", float(trans.loc["Heavy (4+)", "Light (1)"]))
key("x_trans_light_to_heavy", float(trans.loc["Light (1)", "Heavy (4+)"]))
key("x_trans_medium_to_heavy", float(trans.loc["Medium (2-3)", "Heavy (4+)"]))
key("x_trans_light_stay", float(trans.loc["Light (1)", "Light (1)"]))

# E2. Where GMV comes from
r6 = um[um["mi"] >= LAST_MI - 5]
segv = r6.groupby("seg").agg(user_months=("n", "size"), gmv=("gmv", "sum"), gmv_per_user_month=("gmv", "mean")).loc[SEGS]
segv["share_user_months"] = segv["user_months"] / segv["user_months"].sum()
segv["share_gmv"] = segv["gmv"] / segv["gmv"].sum()
save(segv.round(4), "x2_segment_value_last6m")
key("x_heavy_share_user_months", float(segv.loc["Heavy (4+)", "share_user_months"]))
key("x_heavy_share_gmv", float(segv.loc["Heavy (4+)", "share_gmv"]))
key("x_light_share_user_months", float(segv.loc["Light (1)", "share_user_months"]))
key("x_light_share_gmv", float(segv.loc["Light (1)", "share_gmv"]))
for sg, kk in zip(SEGS, ("light", "medium", "heavy")):
    key(f"x_gmv_per_user_month_{kk}_k", float(segv.loc[sg, "gmv_per_user_month"] / 1e3))
ug = df.groupby("user_id")["trxn_amount"].sum().sort_values(ascending=False)
cum = ug.cumsum() / ug.sum()
for q_ in (0.01, 0.1, 0.2):
    key(f"x_top{int(q_*100)}pct_users_gmv_share", float(cum.iloc[int(len(ug) * q_) - 1]))
mix = pd.crosstab(um["mi"], um["seg"], normalize="index")
key("x_heavy_share_mau_first", float(mix["Heavy (4+)"].iloc[0]))
key("x_heavy_share_mau_last", float(mix["Heavy (4+)"].iloc[-1]))
cur_seg = um[um["mi"] == LAST_MI]
gpm = segv["gmv_per_user_month"]
upl_mh = (cur_seg["seg"] == "Medium (2-3)").sum() * 0.10 * (gpm["Heavy (4+)"] - gpm["Medium (2-3)"])
upl_lm = (cur_seg["seg"] == "Light (1)").sum() * 0.10 * (gpm["Medium (2-3)"] - gpm["Light (1)"])
key("x_uplift_10pct_medium_to_heavy_pct_gmv", float(upl_mh / cur_seg["gmv"].sum()))
key("x_uplift_10pct_light_to_medium_pct_gmv", float(upl_lm / cur_seg["gmv"].sum()))

# E3. Timing of the second purchase
ds = df.sort_values(["user_id", "txn_seq"]).copy()
ds["gap_days"] = ds.groupby("user_id")["trxn_date"].diff().dt.days
second = ds[ds.groupby("user_id").cumcount() == 1]["gap_days"]
key("x_days_to_2nd_median", float(second.median()))
for d_ in (7, 14, 30):
    key(f"x_2nd_within_{d_}d_share", float((second <= d_).mean()))
key("x_gap_between_txns_median", float(ds["gap_days"].median()))

# E4. Observed repayment does not predict churn (once frequency is controlled)
ds["prev_out"] = ds.groupby("user_id")["total_outstanding"].shift()
ds["repaid"] = ds["prev_out"] + ds["trxn_amount"] - ds["total_outstanding"]
rp = ds.groupby(["user_id", "mi"]).agg(repay_obs=("repaid", lambda x: x.notna().sum()), repay_events=("repaid", lambda x: (x > 0).sum())).reset_index()
pr = pm.merge(rp, on=["user_id", "mi"])
pr = pr[pr["repay_obs"] > 0].assign(any_repay=lambda x: (x["repay_events"] > 0).astype(int))
m_rep = smf.logit("churn ~ C(Nb) + C(Pb) + C(Ab) + any_repay", data=pr).fit(disp=0)
key("x_repay_coef", float(m_rep.params["any_repay"]))
key("x_repay_p", float(m_rep.pvalues["any_repay"]))
key("x_churn_no_repay_raw", float(pr[pr["any_repay"] == 0]["churn"].mean()))
key("x_churn_repay_raw", float(pr[pr["any_repay"] == 1]["churn"].mean()))

# E5. No "fading" before churn: this month vs the user's own past average
fd = panel.copy()
fd["own_avg"] = fd.groupby("user_id")["n"].transform(lambda x: x.shift().expanding().mean())
fd = fd[fd["age"] >= 2]
fd["ratio_band"] = pd.cut(fd["n"] / fd["own_avg"], [0, 0.5, 0.8, 1.2, 2, 100], labels=["<50%", "50-80%", "80-120%", "120-200%", ">200%"])
fade = fd.groupby("ratio_band", observed=True)["churn"].agg(user_months="size", churn_rate="mean")
save(fade.round(4), "x5_churn_vs_own_usual_frequency")
key("x_fade_churn_min", float(fade["churn_rate"].min()))
key("x_fade_churn_max", float(fade["churn_rate"].max()))
key("x_fade_churn_below_half", float(fade.loc["<50%", "churn_rate"]))

# E6. Categories: identical tickets, strong personal loyalty, no gateway or exit category
cat = df.groupby("package_code").agg(txns=("txn_seq", "size"), gmv=("trxn_amount", "sum"), users=("user_id", "nunique"),
                                     avg_ticket=("trxn_amount", "mean"), median_ticket=("trxn_amount", "median"))
cat["share_gmv"] = cat["gmv"] / cat["gmv"].sum()
cat["user_reach"] = cat["users"] / df["user_id"].nunique()
cat = cat.sort_values("gmv", ascending=False)
save(cat.round(4), "x6_category_economics")
car_t = df.groupby("carrier")["trxn_amount"].mean()
key("x_carrier_avg_ticket_min_k", float(car_t.min() / 1e3))
key("x_carrier_avg_ticket_max_k", float(car_t.max() / 1e3))
key("x_top2_package_gmv_share", float(cat["share_gmv"].iloc[:2].sum()))
dom = df.groupby(["user_id", "package_code"]).size().groupby(level=0).max() / df.groupby("user_id").size()
key("x_dominant_package_share_median", float(dom[users["n_txn"] >= 5].median()))
pop = df["package_code"].value_counts(normalize=True).values
rng = np.random.default_rng(0)
upk = df.groupby("user_id")["package_code"].nunique()
for k_ in (5, 10):
    key(f"x_distinct_packages_n{k_}_observed", float(upk[users["n_txn"] == k_].mean()))
    key(f"x_distinct_packages_n{k_}_random", float(np.mean([len(set(rng.choice(len(pop), k_, p=pop))) for _ in range(4000)])))
fpk = df.sort_values("txn_seq").groupby("user_id")["package_code"].first()
matu = users[users["cohort"] <= 2024 * 12 + 5].assign(first_pkg=fpk)
fp = matu.groupby("first_pkg").agg(users=("n_months", "size"), active_months=("n_months", "mean"), lifetime_gmv=("gmv", "mean"))
save(fp.round(1), "x6_first_category_vs_lifetime")
key("x_first_pkg_months_min", float(fp["active_months"].min()))
key("x_first_pkg_months_max", float(fp["active_months"].max()))
lastrow = df.sort_values("txn_seq").groupby("user_id").tail(1)
lastrow = lastrow[lastrow["mi"] < LAST_MI]
key("x_exit_category_max_dev_pp", float((lastrow["package_code"].value_counts(normalize=True) - df["package_code"].value_counts(normalize=True)).abs().max() * 100))

# E7. Trying a new category is not a loyalty signal
pk = df.groupby(["user_id", "mi"])["package_code"].apply(set).reset_index()
seen = []
for _, g_ in pk.groupby("user_id"):
    acc = set()
    for st in g_["package_code"]:
        seen.append(bool(acc) and len(st - acc) > 0)
        acc |= st
pk["new_cat"] = seen
nc = pm.merge(pk[["user_id", "mi", "new_cat"]], on=["user_id", "mi"])
nc = nc[nc["age"] >= 1].assign(new_cat=lambda x: x["new_cat"].astype(int))
m_nc = smf.logit("churn ~ C(Nb) + C(Pb) + C(Ab) + new_cat", data=nc).fit(disp=0)
key("x_newcat_coef", float(m_nc.params["new_cat"]))
key("x_newcat_p", float(m_nc.pvalues["new_cat"]))
key("x_newcat_share_months", float(nc["new_cat"].mean()))

# E8. Survival model: shifted-beta-geometric (heterogeneous churn) vs constant churn
life_t = (users["last_mi"] - users["cohort"] + 1).values
still = (users["last_mi"] == LAST_MI).values


def nll_sbg(par):
    a_, b_ = np.exp(par)
    return -np.where(still, betaln(a_, b_ + life_t - 1), betaln(a_ + 1, b_ + life_t - 1)).sum() + len(life_t) * betaln(a_, b_)


def nll_geo(par):
    q_ = 1 / (1 + np.exp(-par[0]))
    return -np.where(still, (life_t - 1) * np.log(1 - q_), (life_t - 1) * np.log(1 - q_) + np.log(q_)).sum()


fit_s = minimize(nll_sbg, [0.0, 0.0], method="Nelder-Mead", options={"maxiter": 4000})
fit_g = minimize(nll_geo, [0.0], method="Nelder-Mead")
A_, B_ = np.exp(fit_s.x)
Qg = 1 / (1 + np.exp(-fit_g.x[0]))
S_ = lambda k: float(np.exp(betaln(A_, B_ + k) - betaln(A_, B_)))
surv = pd.DataFrame({"observed": avg["user_retention"].loc[0:12], "sbg_model": [S_(k) for k in range(13)],
                     "constant_churn_model": [(1 - Qg) ** k for k in range(13)]})
save(surv.round(4), "x8_survival_model_fit")
key("x_sbg_alpha", float(A_)); key("x_sbg_beta", float(B_))
key("x_sbg_mean_churn", float(A_ / (A_ + B_)))
key("x_sbg_sd_churn", float(np.sqrt(A_ * B_ / ((A_ + B_) ** 2 * (A_ + B_ + 1)))))
key("x_sbg_lr_vs_constant", float(2 * (fit_g.fun - fit_s.fun)))
key("x_sbg_share_churn_below_10pct", float(stats.beta.cdf(0.10, A_, B_)))
key("x_sbg_share_churn_below_15pct", float(stats.beta.cdf(0.15, A_, B_)))
key("x_sbg_M12", S_(12)); key("x_sbg_M24", S_(24))
key("x_expected_active_months", float(sum(S_(k) for k in range(600))))
gmv_age = um.groupby(um["age"].clip(upper=12))["gmv"].mean()
key("x_lifetime_gmv_per_new_user_m", float(sum(S_(k) * gmv_age.loc[min(k, 12)] for k in range(600)) / 1e6))

# E9. Credit-hungry users: engaged users pressing against small limits
peak = df[df["mi"] == LAST_MI].groupby("user_id")["util"].max()
cur_seg = cur_seg.set_index("user_id").assign(peak_util=peak)
hungry = cur_seg[cur_seg["peak_util"] >= 0.8]
key("x_hungry_users_jun25", len(hungry))
key("x_hungry_avg_limit_m", float(hungry["limit"].mean() / 1e6))
key("x_hungry_avg_txns", float(hungry["n"].mean()))
key("x_all_avg_txns_jun25", float(cur_seg["n"].mean()))
key("x_hungry_share_limit_le2m", float((hungry["limit"] <= 2e6).mean()))
small = um[um["limit"] <= 1e6].copy()
small["next_gmv"] = small.groupby("user_id")["gmv"].shift(-1)
key("x_small_limit_next_gmv_after_capped_k", float(small[small["util_end"] >= 1]["next_gmv"].mean() / 1e3))
key("x_small_limit_next_gmv_not_capped_k", float(small[small["util_end"] < 1]["next_gmv"].mean() / 1e3))

# E10. Cohort value stays the same: 3-month GMV per new user
c3 = df[df["age"] < 3].groupby("cohort")["trxn_amount"].sum() / users.groupby("cohort").size()
c3 = c3[c3.index <= LAST_MI - 2]
key("x_cohort_3m_gmv_per_user_min_k", float(c3.min() / 1e3))
key("x_cohort_3m_gmv_per_user_max_k", float(c3.max() / 1e3))

# E11. Usage looks random around a personal rate; no weekend effect; few same-day bursts
lng = um[um["user_id"].isin(users[users["n_months"] >= 6].index)].groupby("user_id")["n"].agg(["mean", "var"])
key("x_within_user_var_to_mean", float((lng["var"] / lng["mean"]).mean()))
key("x_weekend_share", float((df["trxn_date"].dt.dayofweek >= 5).mean()))
key("x_same_day_multi_share", float((df.groupby(["user_id", "trxn_date"]).size() >= 2).mean()))

# E12. No "buy big and leave" pattern
bb = panel.merge(df.groupby(["user_id", "mi"])["trxn_amount"].max().rename("max_amt").reset_index(), on=["user_id", "mi"])
bb["max_rel"] = pd.cut(bb["max_amt"] / bb["limit"], [0, 0.05, 0.2, 0.5, 1.01], labels=["<5%", "5-20%", "20-50%", "50-100%"])
big = bb.groupby("max_rel", observed=True)["churn"].agg(user_months="size", churn_rate="mean")
save(big.round(4), "x12_churn_vs_biggest_purchase")
key("x_big_purchase_churn_50_100", float(big.loc["50-100%", "churn_rate"]))
key("x_big_purchase_churn_lt5", float(big.loc["<5%", "churn_rate"]))

# Corrections after QC: fairer baselines and controls
key("x_heavy_share_mau_jun24", float(mix["Heavy (4+)"].loc[2024 * 12 + 5]))
key("x_txn_per_user_oct24", float(mau.loc["2024-10", "txn_per_user"]))
key("x_txn_per_user_jun25", float(mau["txn_per_user"].iloc[-1]))
med_now = cur_seg[cur_seg["seg"] == "Medium (2-3)"]
avg_ticket_all = float(df["trxn_amount"].mean())
upl_m4 = len(med_now) * 0.10 * (4 - med_now["n"].mean()) * avg_ticket_all          # move just to 4 txns
light_now = cur_seg[cur_seg["seg"] == "Light (1)"]
upl_l2 = len(light_now) * 0.10 * (2 - 1) * avg_ticket_all                         # move just to 2 txns
key("x_uplift_10pct_medium_to_4_pct_gmv", float(upl_m4 / cur_seg["gmv"].sum()))
key("x_uplift_10pct_light_to_2_pct_gmv", float(upl_l2 / cur_seg["gmv"].sum()))
cap_now = um[um["util_end"] >= 1]
key("x_capped_month_gmv_k", float(cap_now["gmv"].mean() / 1e3))
key("x_not_capped_month_gmv_k", float(um[um["util_end"] < 1]["gmv"].mean() / 1e3))
bbm = pm.merge(bb[["user_id", "mi", "max_amt"]], on=["user_id", "mi"])
bbm["big50"] = (bbm["max_amt"] / bbm["limit"] >= 0.5).astype(int)
m_big = smf.logit("churn ~ C(Nb) + C(Pb) + C(Ab) + big50", data=bbm).fit(disp=0)
key("x_big_purchase_p_controlled", float(m_big.pvalues["big50"]))
key("q1c_full_month_share_n1", float((full["n0"] == 1).mean()))
key("q1c_full_month_share_of_users", float(len(full) / len(elig)))
ci_full = q_full.loc[[1, 2], ["ci_low", "ci_high"]]
key("q1c_full_month_step_1_2_ci_halfwidth", float(1.96 * np.sqrt(sum(q_full.loc[k, "rate"] * (1 - q_full.loc[k, "rate"]) / q_full.loc[k, "users"] for k in (1, 2)))))
key("q1c_logit_coef_N2", float(coef.loc["C(Nb)[T.2]", "Coef."]))
key("q1c_logit_coef_N3", float(coef.loc["C(Nb)[T.3]", "Coef."]))
key("lastday_p_in_churn_model", KEY["logit_p_lastday"])

# E13. First-transaction day of month (onboarding waves)
key("x_first_txn_day1_3_share", float((users["join_day"] <= 3).mean()))
fday = users["join_day"].value_counts(normalize=True).sort_index()
save(fday.rename("share_of_first_transactions").round(4).to_frame(), "x13_first_transaction_day_of_month")

# ==========================================================================
# 7c. MERGED ANGLES (adopted from the independent second solution, recomputed here)
# ==========================================================================
import math
from scipy.stats import norm

# M1. Every headline on the delivered file vs with the 104 rows quarantined
def headline(users_, um_, label):
    el = users_[users_["cohort"] < LAST_MI]
    w_m1 = el["m1"].mean()
    mau_ = um_.groupby("mi").size()
    p_ = um_[um_["mi"] < LAST_MI]
    ch = p_["churn_next"]
    n4 = el[el["n0"] == 4]["m1"].mean()
    ge4 = el[el["n0"] >= 4]["m1"].mean() - el[el["n0"] < 4]["m1"].mean()
    m30 = users_[users_["first_date"] <= raw["trxn_date"].max() - pd.Timedelta(days=59)]
    return {"data": label, "transactions": int(um_["n"].sum()), "M1 retention (weighted)": w_m1,
            "MAU peak": int(mau_.max()), "MAU Jun-25": int(mau_.iloc[-1]), "New users Jun-25": int((users_["cohort"] == LAST_MI).sum()),
            "Monthly churn": ch.mean(), "Churn after 1-txn month": p_[p_["n"] == 1]["churn_next"].mean(),
            "Churn after 4+ month": p_[p_["n"] >= 4]["churn_next"].mean(), "M1 at exactly N=4": n4,
            "Gap >=4 vs <4 (pp)": ge4 * 100, "Days 30-59 active, 1 vs 2 txns in 30d (pp)": (m30[m30["n30"] == 2]["r30_60"].mean() - m30[m30["n30"] == 1]["r30_60"].mean()) * 100,
            "Users who returned after a blank month": int(um_.groupby("user_id")["mi"].apply(lambda x: (x.diff().dropna() > 1).any()).sum())}


hd = pd.DataFrame([headline(users_raw, um_raw, "Delivered file"), headline(users, um, "104 rows quarantined")]).set_index("data").T
save(hd, "m1_delivered_vs_quarantined")
key("m_raw_weighted_m1", float(hd.loc["M1 retention (weighted)", "Delivered file"]))
key("m_raw_mau_peak", int(hd.loc["MAU peak", "Delivered file"]))
key("m_raw_mau_last", int(hd.loc["MAU Jun-25", "Delivered file"]))
key("m_raw_churn", float(hd.loc["Monthly churn", "Delivered file"]))
key("m_raw_churn_n1", float(hd.loc["Churn after 1-txn month", "Delivered file"]))
key("m_raw_churn_4plus", float(hd.loc["Churn after 4+ month", "Delivered file"]))

# M2. In-sample inflow reweighting: what June MAU would have been had later cohorts been as large as a reference month
final_active = set(um[um["mi"] == LAST_MI]["user_id"])
rw = []
for c_ in range(2024 * 12 + 10, LAST_MI + 1):                   # cohorts Nov-24 .. Jun-25
    ids = users.index[users["cohort"] == c_]
    rw.append(dict(cohort=mi_to_label(c_), new_users=len(ids), share_active_jun25=float(pd.Index(ids).isin(final_active).mean())))
rw = pd.DataFrame(rw)
for ref_name, ref_val in (("oct24", float(mau["new"].loc["2024-10"])), ("2024avg", new_2024)):
    rw[f"extra_mau_at_{ref_name}"] = (ref_val - rw["new_users"]) * rw["share_active_jun25"]
    key(f"m_reweight_mau_jun25_{ref_name}", float(len(final_active) + rw[f"extra_mau_at_{ref_name}"].sum()))
save(rw.round(4), "m2_inflow_reweighting")

# M3/M4. Early-trigger trade-off and second-purchase timing (users with 60 days of follow-up)
mat_ids = users.index[users["first_date"] <= raw["trxn_date"].max() - pd.Timedelta(days=59)]
mt = df[df["user_id"].isin(mat_ids)]
act3059 = set(mt.loc[mt["days_since_first"].between(30, 59), "user_id"])
n30_m = users.loc[mat_ids, "n30"]
trig = []
for d_ in (7, 14, 21):
    cnt = mt[mt["days_since_first"] < d_].groupby("user_id").size().reindex(mat_ids)
    one = cnt[cnt == 1].index
    trig.append(dict(trigger_day=d_, share_with_one_purchase=len(one) / len(mat_ids),
                     active_days_30_59=float(pd.Index(one).isin(act3059).mean()),
                     second_purchase_anyway_by_day30=float((n30_m.loc[one] >= 2).mean())))
trig = pd.DataFrame(trig).set_index("trigger_day")
save(trig.round(4), "m3_early_trigger_tradeoff")
for d_ in (7, 14, 21):
    key(f"m_trigger{d_}_share", float(trig.loc[d_, "share_with_one_purchase"]))
    key(f"m_trigger{d_}_active3059", float(trig.loc[d_, "active_days_30_59"]))
    key(f"m_trigger{d_}_natural_2nd", float(trig.loc[d_, "second_purchase_anyway_by_day30"]))
cnt14 = mt[mt["days_since_first"] < 14].groupby("user_id").size().reindex(mat_ids)
one14 = users.loc[cnt14[cnt14 == 1].index]
jb14 = one14.assign(band=pd.cut(one14["join_day"], [0, 3, 10, 20, 31], labels=["day 1-3", "day 4-10", "day 11-20", "day 21-31"])) \
    .assign(active=lambda x: x.index.isin(act3059)).groupby("band", observed=True)["active"].agg(users="size", active_days_30_59="mean")
save(jb14.round(4), "m3_day14_trigger_by_join_day")
key("m_trigger14_active_join1_3", float(jb14.loc["day 1-3", "active_days_30_59"]))
key("m_trigger14_active_join21_31", float(jb14.loc["day 21-31", "active_days_30_59"]))
sec_lag = mt.sort_values(["user_id", "txn_seq"]).groupby("user_id").nth(1).set_index("user_id")["days_since_first"]
for d_ in (7, 14, 30):
    key(f"m_second_purchase_by_day{d_}_all_users", float((sec_lag < d_).sum() / len(mat_ids)))

# M5. Fixed-horizon value (same users observed for the whole window)
def fixed_value(max_age):
    ids = users.index[users["cohort"] <= LAST_MI - max_age]
    sub = um[um["user_id"].isin(ids) & (um["age"] <= max_age)]
    return len(ids), len(sub) / len(ids), sub["gmv"].sum() / len(ids)
for h_ in (6, 11):
    n_, am_, g_ = fixed_value(h_)
    key(f"m_fixed_M0_M{h_}_users", n_); key(f"m_fixed_M0_M{h_}_active_months", am_); key(f"m_fixed_M0_M{h_}_gmv_m", g_ / 1e6)
f12 = um[um["user_id"].isin(users.index[users["cohort"] <= LAST_MI - 11]) & (um["age"] <= 11)].groupby("user_id")["gmv"].sum()
n0g = users.loc[f12.index, "n0"]
key("m_fixed12_gmv_n1_m", float(f12[n0g == 1].mean() / 1e6))
key("m_fixed12_gmv_n5plus_m", float(f12[n0g >= 5].mean() / 1e6))
a12 = um[um["user_id"].isin(f12.index) & (um["age"] <= 11)].groupby("user_id").size()
key("m_fixed12_active_months_n1", float(a12[n0g == 1].mean()))
key("m_fixed12_active_months_n5plus", float(a12[n0g >= 5].mean()))

# M6. Recent churn change: tenure mix vs within-tenure
def churn_month(m_):
    x = panel[panel["mi"] == m_].assign(band=lambda d: pd.cut(d["age"], [-1, 0, 1, 3, 100], labels=["M0", "M1", "M2-3", "M4+"]))
    return x["band"].value_counts(normalize=True).sort_index(), x.groupby("band", observed=True)["churn"].mean(), x["churn"].mean()
w0, r0, c0 = churn_month(2024 * 12 + 9); w1, r1, c1 = churn_month(LAST_MI - 1)
dec = pd.DataFrame({"weight_oct24": w0, "weight_may25": w1, "churn_oct24": r0, "churn_may25": r1})
dec["mix_effect"] = (dec["weight_may25"] - dec["weight_oct24"]) * dec["churn_oct24"]
dec["within_tenure_effect"] = dec["weight_may25"] * (dec["churn_may25"] - dec["churn_oct24"])
save(dec.round(5), "m6_churn_change_decomposition")
key("m_churn_oct24", float(c0)); key("m_churn_may25", float(c1))
key("m_churn_change_mix_pp", float(dec["mix_effect"].sum() * 100)); key("m_churn_change_within_pp", float(dec["within_tenure_effect"].sum() * 100))

# M7. New-user quality by quarter (equal 30-day windows)
qq = users.loc[mat_ids].assign(q=lambda d: pd.PeriodIndex([pd.Period(year=int(c_) // 12, month=int(c_) % 12 + 1, freq="M") for c_ in d["cohort"]]).asfreq("Q").astype(str))
qq = qq.join(first_row[["trxn_amount"]].rename(columns={"trxn_amount": "first_ticket"}))
qual = qq.groupby("q").agg(users=("n30", "size"), txns_first_30d=("n30", "mean"), active_days_30_59=("r30_60", "mean"),
                           first_ticket=("first_ticket", "mean"), credit_limit=("limit", "mean"))
save(qual.round(3), "m7_new_user_quality_by_quarter")
key("m_quality_q1_24_n30", float(qual.iloc[0]["txns_first_30d"])); key("m_quality_q1_25_n30", float(qual.loc["2025Q1", "txns_first_30d"]))
key("m_quality_q1_24_r30", float(qual.iloc[0]["active_days_30_59"])); key("m_quality_q1_25_r30", float(qual.loc["2025Q1", "active_days_30_59"]))

# M8. Merchant breadth within the same frequency band
a30 = mt[mt["days_since_first"] < 30].groupby("user_id").agg(n=("txn_seq", "size"), car=("carrier", "nunique"))
a30 = a30[a30["n"] >= 2].assign(active=lambda d: d.index.isin(act3059), multi=lambda d: d["car"] >= 2,
                                 band=lambda d: pd.cut(d["n"], [1, 2, 3, 5, 1000], labels=["2", "3", "4-5", "6+"]))
br = a30.groupby(["band", "multi"], observed=True)["active"].mean().unstack()
wts = a30["band"].value_counts(normalize=True).sort_index()
key("m_breadth_raw_gap_pp", float((a30[a30["multi"]]["active"].mean() - a30[~a30["multi"]]["active"].mean()) * 100))
key("m_breadth_adjusted_gap_pp", float(((br[True] - br[False]) * wts).sum() * 100))

# M9. Screens of first carrier, first ticket and limit against M1
fc = df.sort_values("txn_seq").groupby("user_id")["carrier"].first()
e1 = elig.assign(first_car=fc, first_ticket=first_row["trxn_amount"])
key("m_first_carrier_m1_p", float(stats.chi2_contingency(pd.crosstab(e1["first_car"], e1["m1"]))[1]))
for f_ in ("first_ticket", "limit"):
    r_ = e1.groupby(pd.qcut(e1[f_], 4, duplicates="drop"), observed=True)["m1"].mean()
    key(f"m_{f_}_quartile_m1_min", float(r_.min())); key(f"m_{f_}_quartile_m1_max", float(r_.max()))

# M10. Data-generation fingerprints
nu_all = mau["new"].values.astype(float)
sl, ic, rv, _, _ = stats.linregress(np.arange(len(nu_all)), np.log(nu_all))
key("m_new_users_loglinear_monthly_change", float(np.exp(sl) - 1)); key("m_new_users_loglinear_r2", float(rv ** 2))
dd = df.groupby(df["trxn_date"].dt.normalize()).size()
cv = dd.groupby(dd.index.to_period("M")).agg(lambda x: x.std() / x.mean())
pois = dd.groupby(dd.index.to_period("M")).agg(lambda x: 1 / np.sqrt(x.mean()))
key("m_daily_cv_median", float(cv.median())); key("m_daily_cv_poisson_median", float(pois.median()))
key("m_limit_levels", int(raw["total_limit"].nunique()))
key("m_package_carrier_pairs", int(raw.groupby(["package_code", "carrier"]).ngroups))

# M11. Pilot sizing for the two proposed tests
def n_per_arm(p0, lift, alpha=0.05, power=0.8):
    p1 = p0 + lift; pb = (p0 + p1) / 2
    return math.ceil((norm.ppf(1 - alpha / 2) * math.sqrt(2 * pb * (1 - pb)) + norm.ppf(power) * math.sqrt(p0 * (1 - p0) + p1 * (1 - p1))) ** 2 / lift ** 2)
p0_a = float(trig.loc[14, "active_days_30_59"])
elig_a = new_last * float(trig.loc[14, "share_with_one_purchase"])
p0_b = float(lapse_tab.loc[15, "p_transacts_later"])
elig_b = mau_last * float(lapse_tab.loc[15, "share_silent"])
pil = []
for name, p0_, el_ in (("A. Second-purchase nudge (day 14, one purchase so far)", p0_a, elig_a),
                       ("B. Mid-month reminder (no purchase by day 15)", p0_b, elig_b)):
    for lift in (0.02, 0.05, 0.10):
        n_ = n_per_arm(p0_, lift)
        pil.append(dict(test=name, baseline=p0_, absolute_lift_pp=lift * 100, users_per_arm=n_,
                        eligible_per_month=el_, months_to_recruit=math.ceil(2 * n_ / el_)))
pil = pd.DataFrame(pil)
save(pil.round(3), "m11_pilot_sample_size")
for i, r_ in pil.iterrows():
    key(f"m_pilot_{'A' if r_['test'].startswith('A') else 'B'}_{int(r_['absolute_lift_pp'])}pp_n", int(r_["users_per_arm"]))
    key(f"m_pilot_{'A' if r_['test'].startswith('A') else 'B'}_{int(r_['absolute_lift_pp'])}pp_months", int(r_["months_to_recruit"]))
key("m_pilot_A_eligible_per_month", elig_a); key("m_pilot_B_eligible_per_month", elig_b)

# ==========================================================================
# 7d. OPTION B - GROWTH DEEP-DIVE
# ==========================================================================
# G1. Which segment is growing? Users and GMV by frequency segment, Jun-24 vs Oct-24 vs Jun-25
seg_t = um.groupby(["mi", "seg"]).agg(users=("n", "size"), gmv=("gmv", "sum")).unstack()
g1 = []
for sg in SEGS:
    a_, b_, c_ = (2024 * 12 + 5, 2024 * 12 + 9, LAST_MI)
    g1.append(dict(segment=sg, users_jun24=seg_t.loc[a_, ("users", sg)], users_oct24=seg_t.loc[b_, ("users", sg)], users_jun25=seg_t.loc[c_, ("users", sg)],
                   gmv_jun24_m=seg_t.loc[a_, ("gmv", sg)] / 1e6, gmv_jun25_m=seg_t.loc[c_, ("gmv", sg)] / 1e6))
g1 = pd.DataFrame(g1).set_index("segment")
g1["users_change"] = g1["users_jun25"] / g1["users_jun24"] - 1
g1["gmv_change"] = g1["gmv_jun25_m"] / g1["gmv_jun24_m"] - 1
save(g1.round(3), "g1_segment_growth")
for sg, kk in zip(SEGS, ("light", "medium", "heavy")):
    key(f"g_users_change_{kk}", float(g1.loc[sg, "users_change"]))
    key(f"g_gmv_change_{kk}", float(g1.loc[sg, "gmv_change"]))

# G2. Does a bigger intake dilute quality? Cohort size vs early quality (cohorts with full observation)
coh_q = users[users["cohort"] <= LAST_MI - 2].groupby("cohort").agg(cohort_size=("m1", "size"), m1=("m1", "mean"))
coh_q["gmv_first_3m"] = df[df["age"] < 3].groupby("cohort")["trxn_amount"].sum() / users.groupby("cohort").size()
mq = users.loc[mat_ids]
coh_q = coh_q.join(mq.groupby("cohort").agg(txns_first_30d=("n30", "mean"), active_days_30_59=("r30_60", "mean")))
coh_q.index = [mi_to_label(c_) for c_ in coh_q.index]
save(coh_q.round(4), "g2_cohort_size_vs_quality")
for col in ("m1", "gmv_first_3m", "txns_first_30d", "active_days_30_59"):
    r_, p_ = stats.pearsonr(coh_q["cohort_size"], coh_q[col])
    key(f"g_size_vs_{col}_r", float(r_)); key(f"g_size_vs_{col}_p", float(p_))
key("g_cohort_size_min", int(coh_q["cohort_size"].min())); key("g_cohort_size_max", int(coh_q["cohort_size"].max()))
# Bound the effect instead of reading "not significant" as "zero": slope of M1 on cohort size, and the test's power
sl_m1 = stats.linregress(coh_q["cohort_size"], coh_q["m1"])
key("g_m1_change_at_2024_volume_pp", float(sl_m1.slope * (KEY["new_users_q1_2024_avg"] - new_last) * 100))
key("g_m1_change_ci_low_pp", float((sl_m1.slope - 1.96 * sl_m1.stderr) * (KEY["new_users_q1_2024_avg"] - new_last) * 100))
key("g_m1_change_ci_high_pp", float((sl_m1.slope + 1.96 * sl_m1.stderr) * (KEY["new_users_q1_2024_avg"] - new_last) * 100))
zr = np.arctanh(0.3) * np.sqrt(len(coh_q) - 3)
key("g_power_detect_r03", float(norm.sf(1.96 - zr) + norm.cdf(-1.96 - zr)))
key("g_cohorts_compared", len(coh_q))

# G3. Growth levers in one unit: extra monthly GMV in Jun-26 vs scenario B (new users flat). Illustrations.
gmv_active = float(um[um["mi"] >= LAST_MI - 5]["gmv"].mean())          # recent GMV per active user-month
gmv_young = gmv_active   # one basis for every lever: recent first-year users spend ~564K, close to the 568K average
month_gmv = float(um[um["mi"] >= LAST_MI - 5].groupby("mi")["gmv"].sum().mean())
key("g_gmv_per_active_k", gmv_active / 1e3); key("g_gmv_per_young_active_k", gmv_young / 1e3); key("g_monthly_gmv_b", month_gmv / 1e9)
plus100 = project(lambda h: new_last + 100, churn_recent)[-1] - B_end
lev = pd.DataFrame([
    ("Recover new users to the 2024 average (+548/month)", "inflow 596 -> 1,144 over 3 months", (scen_df.iloc[-1, 3] - B_end) * gmv_young),
    ("+100 new users a month", "same quality as today's cohorts", plus100 * gmv_young),
    ("Retention: every 1-3 txn user churns like a 4+ user", "assumption", (scen_df.iloc[-1, 2] - B_end) * gmv_active),
    ("Upgrade 10% of medium users to 4 txns a month", "habit sticks; ~+260K VND each", KEY["x_uplift_10pct_medium_to_4_pct_gmv"] * cur_seg["gmv"].sum()),
    ("Upgrade 10% of light users to 2 txns a month", "habit sticks; +1 purchase each", KEY["x_uplift_10pct_light_to_2_pct_gmv"] * cur_seg["gmv"].sum()),
], columns=["lever", "assumption", "extra_monthly_gmv_jun26"])
lev["share_of_monthly_gmv"] = lev["extra_monthly_gmv_jun26"] / month_gmv
save(lev.round(3), "g3_growth_levers_gmv")
for i, r_ in lev.iterrows():
    key(f"g_lever_{i}_m", float(r_["extra_monthly_gmv_jun26"] / 1e6)); key(f"g_lever_{i}_share", float(r_["share_of_monthly_gmv"]))
key("g_plus100_mau", float(plus100))
key("g_winback_illustration_m", float(KEY["sizing_3_win-back"] * gmv_active / 1e6))
# Monthly GMV in Jun-26 under the main paths (MAU x recent GMV per active user; illustration)
for i, nm in enumerate("ABCD"):
    key(f"g_gmv_jun26_{nm}_b", float(scen_df.iloc[-1, i] * gmv_active / 1e9))

# ==========================================================================
# 7e. DEEP EDA - what the data-generating rules explain, and what is real
#     (column-level forensics and behaviour checks; these numbers feed the Bonus chapter)
# ==========================================================================
import statsmodels.api as sm

f_ = df.sort_values(["user_id", "txn_seq"]).copy()
f_["prev_out"] = f_.groupby("user_id")["total_outstanding"].shift().fillna(0)
f_["gap"] = f_.groupby("user_id")["trxn_date"].diff().dt.days
pre_ = f_["prev_out"] + f_["trxn_amount"]
rule_add = (f_["total_outstanding"] - pre_).abs() <= 1000
rule_cap = ~rule_add & (pre_ > f_["total_limit"]) & ((f_["total_outstanding"] - f_["total_limit"]).abs() <= 1000)
f_["paydown"] = ~rule_add & ~rule_cap
pd_frac = (f_.loc[f_["paydown"], "total_outstanding"] / pre_[f_["paydown"]])
key("f_balance_rule_add_share", float(rule_add.mean()))
key("f_balance_rule_cap_share", float(rule_cap.mean()))
key("f_balance_paydown_share", float(f_["paydown"].mean()))
key("f_paydown_fraction_max", float(pd_frac.max()))
key("f_paydown_fraction_ks_p", float(stats.kstest(pd_frac.clip(0, 0.7) / 0.7, "uniform").pvalue))
gap_band = pd.cut(f_["gap"], [-1, 0, 6, 13, 29, 10_000], labels=["same day", "1–6", "7–13", "14–29", "30+"])
pd_by_gap = f_[f_["gap"].notna()].groupby(gap_band, observed=True)["paydown"].agg(["mean", "size"])
save(pd_by_gap, "f_paydown_by_days_since_previous")
key("f_paydown_same_day", float(pd_by_gap.loc["same day", "mean"]))
key("f_paydown_gap_30plus", float(pd_by_gap.loc["30+", "mean"]))
key("f_paydown_first_purchase", float(f_.loc[f_["gap"].isna(), "paydown"].mean()))
key("f_paydown_after_paydown", float(f_.loc[f_.groupby("user_id")["paydown"].shift() == True, "paydown"].mean()))
key("f_paydown_after_no_paydown", float(f_.loc[f_.groupby("user_id")["paydown"].shift() == False, "paydown"].mean()))

# Purchase amounts: capped at 60% of the limit, never checked against available credit
amt_ratio = f_["trxn_amount"] / f_["total_limit"]
at60 = (f_["trxn_amount"] - 0.6 * f_["total_limit"]).abs() < 1
headroom = f_["total_limit"] - f_["prev_out"]
key("f_amount_max_share_of_limit", float(amt_ratio.max()))
key("f_rows_amount_exactly_60pct_limit", int(at60.sum()))
key("f_users_amount_exactly_60pct_limit", int(f_.loc[at60, "user_id"].nunique()))
key("f_purchases_above_headroom", int((f_["trxn_amount"] > headroom + 1).sum()))
key("f_purchases_at_zero_headroom", int((headroom <= 0).sum()))
key("f_rows_amount_20k_floor", int((f_["trxn_amount"] == 20_000).sum()))
key("f_rows_amount_21k", int((f_["trxn_amount"] == 21_000).sum()))
# ticket size is not a user trait: one-way ICC of log amount, users with 5+ purchases
g5 = f_.groupby("user_id")["txn_seq"].transform("size") >= 5
la_ = pd.DataFrame({"u": f_.loc[g5, "user_id"], "y": np.log(f_.loc[g5, "trxn_amount"])})
grp_ = la_.groupby("u")["y"]
k_, m_, gm_ = grp_.size(), grp_.mean(), la_["y"].mean()
msb = float((k_ * (m_ - gm_) ** 2).sum() / (len(k_) - 1))
msw = float(((la_["y"] - la_["u"].map(m_)) ** 2).sum() / (len(la_) - len(k_)))
k0_ = (len(la_) - (k_ ** 2).sum() / len(la_)) / (len(k_) - 1)
key("f_ticket_icc", (msb - msw) / (msb + (k0_ - 1) * msw))
key("f_ticket_icc_p", float(stats.f.sf(msb / msw, len(k_) - 1, len(la_) - len(k_))))

# Merchant mix: equal-sized package x carrier cells (raw labels, clean rows)
rc_ = raw[~raw["out_of_sequence"]]
cells_ = rc_.groupby(["package_code", "carrier"]).size()
cells_ = cells_[cells_ >= 10]
key("f_merchant_cells", len(cells_))
key("f_merchant_cell_rows_min", int(cells_.min()))
key("f_merchant_cell_rows_max", int(cells_.max()))
pk_ = rc_.groupby("package_code").agg(gmv=("trxn_amount", "sum"), carriers=("carrier", "nunique"))
pk_["gmv_share"] = pk_["gmv"] / pk_["gmv"].sum()
pk_["carrier_share"] = pk_["carriers"] / len(cells_)
save(pk_, "f_package_gmv_share_vs_carrier_count")
key("f_package_share_vs_carrier_share_r", float(np.corrcoef(pk_["gmv_share"], pk_["carrier_share"])[0, 1]))
key("f_package_share_vs_carrier_share_maxdiff_pp", float((pk_["gmv_share"] - pk_["carrier_share"]).abs().max() * 100))
key("f_other_services_lowercase_users", int(rc_.loc[rc_["carrier"] == "Other services", "user_id"].nunique()))

# Credit limits: a flat random draw over a 100K grid, unrelated to behaviour
lv_ = users["limit"].value_counts()
key("f_limit_levels", len(lv_))
key("f_limit_grid_complete_0_5m_to_9_9m", bool(set(lv_.index) == set(range(500_000, 9_900_001, 100_000))))
key("f_limit_users_per_level_min", int(lv_.min()))
key("f_limit_users_per_level_max", int(lv_.max()))
key("f_limit_vs_monthly_frequency_rho", float(stats.spearmanr(users["limit"], users["n_txn"] / users["n_months"]).correlation))

# The first month is a full month, and the "early-month" first purchase is an order statistic
w_ = um.pivot_table(index="user_id", columns="age", values="n")
both_ = w_[[0, 1, 2]].dropna()
key("f_same_users_txn_m0", float(both_[0].mean()))
key("f_same_users_txn_m1", float(both_[1].mean()))
key("f_same_users_txn_m2", float(both_[2].mean()))
key("f_same_users_n", len(both_))
key("f_m0_vs_m1_wilcoxon_p", float(stats.wilcoxon(both_[0], both_[1]).pvalue))
L_ = users["first_date"].dt.days_in_month
n0_ = users["n0"]
days_ = np.arange(1, 32)
exp_first = np.array([(((L_ - d + 1).clip(lower=0) / L_) ** n0_ - ((L_ - d).clip(lower=0) / L_) ** n0_).mean() for d in days_])
obs_first = users["join_day"].value_counts(normalize=True).reindex(days_, fill_value=0).values
first_day_tbl = pd.DataFrame({"observed": obs_first, "expected_earliest_of_uniform_days": exp_first}, index=days_)
save(first_day_tbl, "f_first_purchase_day_observed_vs_model")
key("f_first_day_1_3_observed", float(obs_first[:3].sum()))
key("f_first_day_1_3_expected", float(exp_first[:3].sum()))
key("f_first_day_by15_observed", float(obs_first[:15].sum()))
key("f_first_day_by15_expected", float(exp_first[:15].sum()))
first_day_um = df.groupby(["user_id", "mi"])["trxn_date"].min().dt.day
cont_ = um.set_index(["user_id", "mi"])
cont_ = cont_[cont_["age"] >= 1]
Lc_ = pd.Series([pd.Period(year=int(m) // 12, month=int(m) % 12 + 1, freq="M").days_in_month for m in cont_.index.get_level_values(1)], index=cont_.index)
key("f_continuing_first_day_1_3_observed", float((first_day_um.reindex(cont_.index) <= 3).mean()))
key("f_continuing_first_day_1_3_expected", float((1 - ((Lc_ - 3) / Lc_) ** cont_["n"]).mean()))
key("f_day13_users_mean_n0", float(users.loc[users["join_day"] <= 3, "n0"].mean()))
key("f_all_users_mean_n0", float(users["n0"].mean()))

# New-user inflow: a smooth exponential decline plus Poisson noise, except Oct-24
nu_ = users.groupby("cohort").size()
X_ = sm.add_constant(np.arange(len(nu_), dtype=float))
glm_ = sm.GLM(nu_.values, X_, family=sm.families.Poisson()).fit()
pred_ = glm_.predict(X_)
z_ = (nu_.values - pred_) / np.sqrt(pred_)
oct_i = list(nu_.index).index(2024 * 12 + 9)
key("f_inflow_monthly_change", float(np.exp(glm_.params[1]) - 1))
key("f_oct24_expected", float(pred_[oct_i]))
key("f_oct24_z", float(z_[oct_i]))
key("f_inflow_max_abs_z_other_months", float(np.abs(np.delete(z_, oct_i)).max()))
mask_ = np.arange(len(nu_)) != oct_i
glm2_ = sm.GLM(nu_.values[mask_], X_[mask_], family=sm.families.Poisson()).fit()
key("f_inflow_dispersion_without_oct24", float(glm2_.pearson_chi2 / glm2_.df_resid))

# The 104 suspect rows: balance copied from one of the user's own earlier rows
own_bal = df.groupby("user_id")["total_outstanding"].apply(set)
key("f_oos_balance_copied_from_own_rows", int(sum(r.total_outstanding in own_bal[r.user_id] for r in oos.itertuples())))

# --- Behaviour: churn follows a user's usual frequency, not this month's ---
bh = um.copy()
bh["n1"] = bh.groupby("user_id")["n"].shift(1)
bh["n2"] = bh.groupby("user_id")["n"].shift(2)
bh = bh[(bh["mi"] < LAST_MI) & (bh["age"] >= 3)].copy()       # this month and two earlier months after M0
bh["avg3"] = (bh["n"] + bh["n1"] + bh["n2"]) / 3
bins_ = [0, 1, 2, 3, 4, 5, 6, np.inf]
lab_ = ["≤1", "1–2", "2–3", "3–4", "4–5", "5–6", ">6"]
by_avg = bh.groupby(pd.cut(bh["avg3"], bins_, labels=lab_), observed=True)["churn_next"].agg(["mean", "size"])
by_now = bh.groupby(pd.cut(bh["n"], bins_, labels=lab_), observed=True)["churn_next"].agg(["mean", "size"])
save(pd.concat({"by_3_month_average": by_avg, "by_this_month": by_now}, axis=1), "b_churn_by_usual_vs_this_month")
key("b_sample_user_months", len(bh))
key("b_churn_avg3_low", float(by_avg["mean"].iloc[0]))
key("b_churn_avg3_high", float(by_avg["mean"].iloc[-1]))
key("b_churn_this_month_low", float(by_now["mean"].iloc[0]))
key("b_churn_this_month_high", float(by_now["mean"].iloc[-1]))
bh["c"] = bh["churn_next"].astype(int)
bh["la"] = np.log(bh["avg3"])
bh["dev"] = np.log(bh["n"] / bh["avg3"])
lg_ = smf.logit("c ~ la + dev + age", bh).fit(disp=0, cov_type="cluster", cov_kwds={"groups": bh["user_id"]})
key("b_dev_coef", float(lg_.params["dev"]))
key("b_dev_ci_low", float(lg_.conf_int().loc["dev", 0]))
key("b_dev_ci_high", float(lg_.conf_int().loc["dev", 1]))
key("b_dev_p", float(lg_.pvalues["dev"]))
key("b_tenure_p_given_usual_frequency", float(lg_.pvalues["age"]))
key("b_avg3_coef_p", float(lg_.pvalues["la"]))
# reliability of one month's count as a read of the user's rate (one-way ICC, Spearman-Brown)
r_ = um[um.groupby("user_id")["mi"].transform("size") >= 3]
gr_ = r_.groupby("user_id")["n"]
kk_, mm_, gg_ = gr_.size(), gr_.mean(), r_["n"].mean()
msb2 = float((kk_ * (mm_ - gg_) ** 2).sum() / (len(kk_) - 1))
msw2 = float(((r_["n"] - r_["user_id"].map(mm_)) ** 2).sum() / (len(r_) - len(kk_)))
k02 = (len(r_) - (kk_ ** 2).sum() / len(r_)) / (len(kk_) - 1)
icc_n = (msb2 - msw2) / (msb2 + (k02 - 1) * msw2)
key("b_reliability_1_month", float(icc_n))
key("b_reliability_3_months", float(3 * icc_n / (1 + 2 * icc_n)))
# within a user, frequency does not change with tenure (user fixed effects)
fe_ = um[um.groupby("user_id")["mi"].transform("size") >= 3].copy()
fe_["yd"] = fe_["n"] - fe_.groupby("user_id")["n"].transform("mean")
fe_["xd"] = fe_["age"] - fe_.groupby("user_id")["age"].transform("mean")
ols_ = smf.ols("yd ~ xd - 1", fe_).fit(cov_type="cluster", cov_kwds={"groups": fe_["user_id"]})
key("b_within_user_frequency_slope_per_month", float(ols_.params["xd"]))
key("b_within_user_frequency_slope_ci_half", float(1.96 * ols_.bse["xd"]))
# silence trigger by usual-frequency band
day_ = df["trxn_date"].dt.day
sil = {}
for d_ in (10, 15):
    early_ = set(zip(df.loc[day_ <= d_, "user_id"], df.loc[day_ <= d_, "mi"]))
    bh[f"silent{d_}"] = [(u, m + 1) not in early_ for u, m in zip(bh["user_id"], bh["mi"])]
band4 = pd.cut(bh["avg3"], [0, 1.5, 3, 5, np.inf], labels=["≤1.5", "1.5–3", "3–5", ">5"])
sil_tbl = pd.DataFrame({
    "lost_if_silent_day10": bh[bh["silent10"]].groupby(band4[bh["silent10"]], observed=True)["churn_next"].mean(),
    "lost_if_silent_day15": bh[bh["silent15"]].groupby(band4[bh["silent15"]], observed=True)["churn_next"].mean(),
    "share_of_churners": bh[bh["churn_next"]].groupby(band4[bh["churn_next"]], observed=True).size() / bh["churn_next"].sum(),
    "share_of_churners_gmv": bh[bh["churn_next"]].groupby(band4[bh["churn_next"]], observed=True)["gmv"].sum() / bh.loc[bh["churn_next"], "gmv"].sum(),
})
save(sil_tbl, "b_silence_and_churn_by_usual_frequency")
key("b_heavy_lost_if_silent_day10", float(sil_tbl.loc[">5", "lost_if_silent_day10"]))
key("b_heavy_lost_if_silent_day15", float(sil_tbl.loc[">5", "lost_if_silent_day15"]))
key("b_heavy_share_of_churners", float(sil_tbl.loc[">5", "share_of_churners"]))
key("b_heavy_share_of_churned_gmv", float(sil_tbl.loc[">5", "share_of_churners_gmv"]))
key("b_all_lost_if_silent_day10", float(bh.loc[bh["silent10"], "churn_next"].mean()))
# realised next-6-month GMV per Dec-24 active user, by usual-frequency band
dec_ = um[(um["mi"] == 2024 * 12 + 11)].copy()
dec_["n1"] = dec_["user_id"].map(um[um["mi"] == 2024 * 12 + 10].set_index("user_id")["n"])
dec_["n2"] = dec_["user_id"].map(um[um["mi"] == 2024 * 12 + 9].set_index("user_id")["n"])
dec_ = dec_.dropna(subset=["n1", "n2"])
dec_["avg3"] = (dec_["n"] + dec_["n1"] + dec_["n2"]) / 3
fut_ = um[um["mi"].between(2025 * 12, 2025 * 12 + 5)].groupby("user_id")["gmv"].sum()
dec_["gmv_next6"] = dec_["user_id"].map(fut_).fillna(0)
real_ = dec_.groupby(pd.cut(dec_["avg3"], [0, 1.5, 3, 5, np.inf], labels=["≤1.5", "1.5–3", "3–5", ">5"]), observed=True)["gmv_next6"].agg(["mean", "size"])
save(real_, "b_realised_next6m_gmv_by_usual_frequency")
key("b_realised_gmv_next6_low_m", float(real_["mean"].iloc[0] / 1e6))
key("b_realised_gmv_next6_high_m", float(real_["mean"].iloc[-1] / 1e6))
# category choice is memoryless: next package vs the user's own mix
cs_ = df.sort_values(["user_id", "txn_seq"])[["user_id", "package_code"]].copy()
cs_["prev"] = cs_.groupby("user_id")["package_code"].shift()
nn_ = cs_.groupby("user_id")["package_code"].transform("size")
cc_ = cs_[(nn_ >= 6) & cs_["prev"].notna()]
mix_ = cs_[nn_ >= 6].groupby(["user_id", "package_code"]).size()
pairs_ = cc_.groupby("user_id").size()
key("b_same_package_as_previous_observed", float((cc_["package_code"] == cc_["prev"]).mean()))
# unbiased per-user estimate of sum(p_k^2) = sum c_k (c_k - 1) / (n (n - 1))
tot_ = mix_.groupby(level=0).sum()
same_u = (mix_ * (mix_ - 1)).groupby(level=0).sum() / (tot_ * (tot_ - 1))
key("b_same_package_as_previous_expected", float((same_u.reindex(pairs_.index) * pairs_).sum() / pairs_.sum()))

# ==========================================================================
# 8. CHARTS
# ==========================================================================
months = list(mau.index)
xm = np.arange(len(months))
short = [pd.Period(m).strftime("%b\n%y") if i % 3 == 0 else "" for i, m in enumerate(months)]

# Fig 1 - MAU: new vs returning (stacked columns)
fig, ax = plt.subplots(figsize=(9, 4.2))
ax.bar(xm, mau["returning"], width=0.7, color=BLUE, label="Returning users", edgecolor=SURFACE, linewidth=1)
ax.bar(xm, mau["new"], bottom=mau["returning"], width=0.7, color=ORANGE, label="New users (first transaction)", edgecolor=SURFACE, linewidth=1)
ip = int(np.argmax(mau["mau"].values))
ax.annotate(f"Peak {mau['mau'].iloc[ip]:,}", (ip, mau["mau"].iloc[ip]),
            xytext=(0, 6), textcoords="offset points", ha="center", color=INK, fontsize=9)
ax.annotate(f"{mau['mau'].iloc[-1]:,}", (xm[-1], mau["mau"].iloc[-1]), xytext=(0, 6), textcoords="offset points", ha="center", color=INK, fontsize=9)
ax.text(len(xm) - 0.5, 4700, f"New users/month: ~{mau['new'].iloc[0:3].mean():,.0f} (Q1-24 avg) → {int(mau['new'].iloc[-1]):,} (Jun-25)",
        ha="right", va="center", fontsize=9, color=INK2)
ax.set_xticks(xm, short)
ax.set_ylim(0, 5000)
ax.yaxis.set_major_formatter(matplotlib.ticker.StrMethodFormatter("{x:,.0f}"))
ax.set_title("Active users plateaued Jul–Oct 2024 and have fallen since, as fewer new users arrive each month")
ax.legend(loc="upper left", ncol=1, fontsize=9)
tidy(ax)
caption(fig, "Active user = at least one BNPL transaction in the month. Clean data (104 out-of-sequence rows removed).")
save_fig(fig, "fig1_mau_new_vs_returning.png")
plt.close(fig)

# Fig 2 - cohort heatmap
R = ret.iloc[:, :18].values
fig, ax = plt.subplots(figsize=(11, 6.4))
cmap = LinearSegmentedColormap.from_list("blues", BLUE_RAMP)
cmap.set_bad(SURFACE)
show = np.ma.masked_invalid(np.where(np.arange(R.shape[1]) == 0, np.nan, R))
im = ax.imshow(show, cmap=cmap, vmin=0, vmax=0.8, aspect="auto")
for i in range(R.shape[0]):
    for j in range(1, R.shape[1]):
        v = R[i, j]
        if np.isnan(v):
            continue
        ax.text(j, i, f"{v*100:.0f}", ha="center", va="center", fontsize=7.5,
                color="white" if v > 0.42 else INK)
    ax.text(0, i, f"{int(size.iloc[i]):,}", ha="center", va="center", fontsize=7.5, color=INK2)
ax.set_xticks(range(R.shape[1]), ["Users"] + [f"M{j}" for j in range(1, R.shape[1])])
ax.set_yticks(range(R.shape[0]), [pd.Period(c).strftime("%b %y") for c in ret.index])
ax.xaxis.tick_top()
ax.grid(False)
for s_ in ax.spines.values():
    s_.set_visible(False)
ax.tick_params(length=0)
ax.set_title("Cohort retention (% of cohort transacting in month k) - every cohort decays in a very similar way", pad=28)
cb = fig.colorbar(im, ax=ax, fraction=0.025, pad=0.01)
cb.outline.set_visible(False)
cb.ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0, decimals=0))
cb.ax.tick_params(length=0, colors=MUTED)
caption(fig, "Cohort = month of first transaction. 'Users' = cohort size (note the steady decline). Blank = not yet observable.")
save_fig(fig, "fig2_cohort_heatmap.png")
plt.close(fig)

# Fig 3 - retention curves + hazard
fig, axes = plt.subplots(1, 2, figsize=(11, 4.2), gridspec_kw={"width_ratios": [1.35, 1]})
ax = axes[0]
for c in ret.index:
    y = ret.loc[c].dropna().values
    ax.plot(range(len(y)), y, color=GRAY, linewidth=0.9, alpha=0.8)
ax.plot(avg.index, avg["user_retention"], color=BLUE, linewidth=2.4, label="User retention (weighted)")
ax.plot(avg.index, avg["gmv_retention"], color=ORANGE, linewidth=2, label="GMV retention (weighted)")
for k in (1, 3, 6, 12):
    ax.plot(k, avg.loc[k, "user_retention"], "o", color=BLUE, markersize=6, markeredgecolor=SURFACE, markeredgewidth=1.5)
    ax.annotate(f"M{k}: {avg.loc[k, 'user_retention']*100:.0f}%", (k, avg.loc[k, "user_retention"]), xytext=(6, 6),
                textcoords="offset points", fontsize=8.5, color=INK)
pct_axis(ax, 0, 1.05)
ax.set_xlim(-0.3, 17.5)
ax.set_xlabel("Months since first transaction")
ax.set_title("No plateau: retention keeps falling ~25% per month")
ax.legend(loc="upper right")
tidy(ax)
ax = axes[1]
hz = haz.loc[0:12, "churn_next_month"]
ax.bar(hz.index, hz.values, width=0.6, color=BLUE)
ax.axhline(KEY["overall_monthly_churn"], color=INK2, linewidth=1)
ax.annotate(f"average {KEY['overall_monthly_churn']*100:.1f}%", (12.4, KEY["overall_monthly_churn"]), xytext=(0, 4),
            textcoords="offset points", ha="right", fontsize=8.5, color=INK2)
pct_axis(ax, 0, 0.35)
ax.set_xticks(range(0, 13), [f"M{k}" for k in range(0, 13)], fontsize=8)
ax.set_title("Monthly churn by tenure: ~1 in 4, barely improves")
ax.set_xlabel("Tenure month (share not returning next month)")
tidy(ax)
caption(fig, "Grey lines = individual cohorts. GMV retention = cohort GMV in month k / cohort GMV in M0. Hazard from user-month panel, Jan-24 to May-25.")
save_fig(fig, "fig3_retention_curves_and_hazard.png", relayout=True)
plt.close(fig)

# Fig 4 - Q1c
fig, ax = plt.subplots(figsize=(7.6, 4.3))
Ns = np.arange(1, 9)
ax.plot(Ns, q_raw.loc[1:8, "rate"], color=ORANGE, marker="o", markersize=6, markeredgecolor=SURFACE, markeredgewidth=1.5, label="Raw data (as delivered)")
ax.fill_between(Ns, q_clean.loc[1:8, "ci_low"], q_clean.loc[1:8, "ci_high"], color=BLUE, alpha=0.10, linewidth=0)
ax.plot(Ns, q_clean.loc[1:8, "rate"], color=BLUE, marker="o", markersize=6, markeredgecolor=SURFACE, markeredgewidth=1.5, label="Clean (104 suspect rows removed), 95% CI")
ax.annotate(f"{q_raw.loc[4,'rate']*100:.1f}%\nspike created by\n104 suspect rows", (4, q_raw.loc[4, "rate"]),
            xytext=(4.6, 0.835), fontsize=8.5, color=INK, arrowprops=dict(arrowstyle="-", color=MUTED, lw=0.8))
ax.annotate(f"{q_clean.loc[4,'rate']*100:.1f}%", (4, q_clean.loc[4, "rate"]), xytext=(4.15, 0.742), fontsize=8.5, color=INK)
pct_axis(ax, 0.6, 0.9)
ax.set_xticks(Ns, ["1", "2", "3", "4", "5", "6", "7", "8"])
ax.set_xlabel("Transactions in first calendar month (N)")
ax.set_ylabel("Active in next calendar month (M1)")
ax.set_title("A gradual rise with no threshold once the suspect rows are removed")
ax.legend(loc="lower right", fontsize=8.5)
tidy(ax)
caption(fig, "Users from the Jan-24 to May-25 cohorts. Shaded band = 95% Wilson CI. The first calendar month behaves like a full month "
        "in this file (same purchases per user as M1), so no join-day adjustment is needed.")
save_fig(fig, "fig4_q1c_first_month_txns_vs_m1.png", relayout=True)
plt.close(fig)

# Fig 5 - churn drivers small multiples (same y-scale so flat really looks flat)
panels = [("Transactions this month", h_n, "all"), ("Tenure: falls only because light users leave first", h_age, "none"),
          ("Utilisation at month end: balance field is synthetic", h_util, "none"),
          ("Credit limit (VND): no detectable effect", h_lim, "none"),
          ("Average ticket (VND): gap gone once frequency is controlled", h_tk, "none"),
          ("Merchant categories used: gap gone once frequency is controlled", h_cat, "none")]
fig, axes = plt.subplots(2, 3, figsize=(13, 6.6), sharey=True)
for ax, (title, h, signal) in zip(axes.flat, panels):
    xs = np.arange(len(h))
    colors = [BLUE if signal == "all" or (signal == "last" and i == len(h) - 1) else GRAY for i in range(len(h))]
    ax.bar(xs, h["churn_rate"], width=0.62, color=colors)
    ax.axhline(KEY["overall_monthly_churn"], color=INK2, linewidth=0.8)
    ax.set_xticks(xs, h.index, fontsize=8)
    ax.set_title(title, fontsize=9.5)
    pct_axis(ax, 0, 0.34)
    tidy(ax)
    for xi, v in zip(xs, h["churn_rate"]):
        ax.text(xi, v + 0.006, f"{v*100:.0f}", ha="center", fontsize=7.5, color=INK2)
fig.suptitle("Share of active users who do not come back next month: purchase frequency is the only robust signal",
             x=0.0, ha="left", fontsize=12, fontweight="semibold", color=INK)
caption(fig, "Line = average monthly churn (24.9%). Blue = survives once a user's usual (3-month average) frequency is controlled. "
        "Grey = no detectable effect once frequency is controlled: tenure only reflects light users leaving first, and the balance behind "
        "utilisation follows a mechanical rule (Chapter 8), so its small at-limit gap is not a reliable signal.")
save_fig(fig, "fig5_churn_drivers.png", relayout=True)
plt.close(fig)

# Fig 6 - scenarios
r50 = lambda v: round(v / 50) * 50
fig, ax = plt.subplots(figsize=(10, 4.6))
hist_x = np.arange(len(months))
ax.plot(hist_x, mau["mau"].values, color=INK2, linewidth=2, label="Actual")
fx = np.arange(len(months) - 1, len(months) + H)
cols = [ORANGE, BLUE, AQUA, YELLOW]
for (name, vals), col in zip(scen.items(), cols):
    y = [mau["mau"].iloc[-1]] + list(vals)
    ax.plot(fx, y, color=col, linewidth=2, label=name)
    ax.annotate(f"{name.split('.')[0]}: ~{r50(vals[-1]):,}", (fx[-1], y[-1]), xytext=(6, 0), textcoords="offset points",
                va="center", fontsize=8.5, color=INK)
ax.axvline(len(months) - 1, color=BASE, linewidth=1)
ax.text(len(months) - 0.7, 5250, "scenarios", fontsize=8.5, color=MUTED)
lbls = months + fut_idx
ax.set_xticks(range(0, len(lbls), 3), [pd.Period(lbls[i]).strftime("%b %y") for i in range(0, len(lbls), 3)])
ax.set_ylim(0, 5500)
ax.set_xlim(-0.5, len(lbls) + 2.5)
ax.yaxis.set_major_formatter(matplotlib.ticker.StrMethodFormatter("{x:,.0f}"))
ax.set_title("Monthly active users: a recovery in new users is the biggest lever")
ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.09), ncol=2, fontsize=8.5)
tidy(ax)
fig.text(0.0, -0.17, f"Stock-flow model: MAU[t+1] = MAU[t] x (1 - churn) + new users, with churn {churn_recent*100:.1f}% (Dec-24 to May-25 average). "
         f"In-sample check on 2024-25: {mape*100:.1f}% mean error.\nD ramps new users up over 3 months (~{ramp(1):,.0f}, ~{ramp(2):,.0f}, then {new_2024:,.0f}). "
         "C is an assumption, not a proven bound. Scenarios from Jun 2025, not forecasts.",
         ha="left", va="top", fontsize=8.5, color=MUTED)
save_fig(fig, "fig6_mau_scenarios.png")
plt.close(fig)

# Fig 7 - simplified scenario chart for the one-pager (3 paths, direct labels only)
fig, ax = plt.subplots(figsize=(7.2, 3.3))
ax.plot(hist_x, mau["mau"].values, color=INK2, linewidth=2)
ax.annotate("Actual", (ip, mau["mau"].iloc[ip]), xytext=(0, 8), textcoords="offset points", ha="center", fontsize=9, color=INK2)
simple = [(list(scen.values())[3], BLUE, "New users back to 2024 level"), (list(scen.values())[1], AQUA, "New users stop falling"),
          (list(scen.values())[0], ORANGE, "New users keep falling")]
for vals, col, lab in simple:
    y = [mau["mau"].iloc[-1]] + list(vals)
    ax.plot(fx, y, color=col, linewidth=2.2)
    ax.plot(fx[-1], y[-1], "o", color=col, markersize=6, markeredgecolor=SURFACE, markeredgewidth=1.5)
    ax.annotate(f"{lab}: ~{r50(vals[-1]):,}", (fx[-1], y[-1]), xytext=(8, 0), textcoords="offset points", va="center", fontsize=9, color=INK)
ax.axvline(len(months) - 1, color=BASE, linewidth=1)
ax.text(len(months) - 0.6, 5150, "next 12 months", fontsize=8.5, color=MUTED)
ax.set_xticks([0, 6, 12, 18, 24, 29], ["Jan 24", "Jul 24", "Jan 25", "Jul 25", "Jan 26", "Jun 26"])
ax.set_ylim(0, 5400)
ax.set_yticks([1000, 2000, 3000, 4000, 5000])
ax.set_xlim(-1, len(lbls) + 8)
ax.yaxis.set_major_formatter(matplotlib.ticker.StrMethodFormatter("{x:,.0f}"))
ax.set_title("Monthly active BNPL users", fontsize=11)
tidy(ax)
save_fig(fig, "fig7_onepager_mau_paths.png")
plt.close(fig)

# Fig 8 - segment dynamics and where GMV comes from
fig, axes = plt.subplots(1, 2, figsize=(12, 4.2), gridspec_kw={"width_ratios": [1.45, 1]})
ax = axes[0]
states = [("Churned", ORANGE), ("Heavy (4+)", BLUE), ("Medium (2-3)", AQUA), ("Light (1)", YELLOW)]
rows = SEGS[::-1]
left = np.zeros(len(rows))
for st, col in states:
    vals = trans.loc[rows, st].values
    ax.barh(range(len(rows)), vals, left=left, height=0.55, color=col, edgecolor=SURFACE, linewidth=2, label=st)
    for yi, (l_, v_) in enumerate(zip(left, vals)):
        if v_ >= 0.07:
            ax.text(l_ + v_ / 2, yi, f"{v_*100:.0f}%", ha="center", va="center", fontsize=8.5,
                    color="white" if col in (ORANGE, BLUE) else INK)
    left += vals
ax.set_yticks(range(len(rows)), [f"{r_}\nthis month" for r_ in rows], fontsize=9)
ax.set_xlim(0, 1)
ax.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0, decimals=0))
ax.set_title("Next month, users move between segments a lot")
ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.1), ncol=4, fontsize=8.5, title="State next month", title_fontsize=8.5)
for s_ in ("top", "right", "left"):
    ax.spines[s_].set_visible(False)
ax.grid(False)
ax.tick_params(length=0)
ax = axes[1]
xs = np.arange(3)
w = 0.34
ax.bar(xs - w / 2 - 0.01, segv["share_user_months"].values, width=w, color=GRAY, label="Share of active users")
ax.bar(xs + w / 2 + 0.01, segv["share_gmv"].values, width=w, color=BLUE, label="Share of GMV")
for xi, (a1, a2) in enumerate(zip(segv["share_user_months"].values, segv["share_gmv"].values)):
    ax.text(xi - w / 2 - 0.01, a1 + 0.01, f"{a1*100:.0f}%", ha="center", fontsize=8.5, color=INK2)
    ax.text(xi + w / 2 + 0.01, a2 + 0.01, f"{a2*100:.0f}%", ha="center", fontsize=8.5, color=INK2)
ax.set_xticks(xs, SEGS, fontsize=9)
pct_axis(ax, 0, 0.75)
ax.set_title("Heavy users are 38% of the base but 65% of GMV")
ax.legend(loc="upper left", fontsize=8.5)
tidy(ax)
caption(fig, "Segments by transactions in the month. Left: all user-months Jan-24 to May-25. Right: last 6 months (Jan-Jun 2025).")
save_fig(fig, "fig8_segments_dynamics_value.png", relayout=True)
plt.close(fig)

# Fig 9 - survival model: no loyal core
fig, axes = plt.subplots(1, 2, figsize=(12, 4.2))
ax = axes[0]
kk = np.arange(13)
ax.plot(kk, surv["observed"], "o", color=INK2, markersize=6, markeredgecolor=SURFACE, markeredgewidth=1.5, label="Observed (weighted cohorts)")
ax.plot(kk, surv["sbg_model"], color=BLUE, label="Model: users differ in churn propensity")
ax.plot(kk, surv["constant_churn_model"], color=ORANGE, label="Model: everyone has the same churn")
ax.set_yscale("log")
ax.set_ylim(0.02, 1.1)
ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v*100:.0f}%" if v >= 0.05 else f"{v*100:.0f}%"))
ax.set_yticks([0.03, 0.05, 0.1, 0.2, 0.5, 1.0])
ax.set_xlabel("Months since first transaction")
ax.set_title("Log scale: a near-straight line = no plateau")
ax.legend(loc="lower left", fontsize=8.5)
tidy(ax)
ax = axes[1]
xg = np.linspace(0, 0.6, 400)
ax.fill_between(xg, stats.beta.pdf(xg, A_, B_), color=BLUE, alpha=0.10, linewidth=0)
ax.plot(xg, stats.beta.pdf(xg, A_, B_), color=BLUE)
ax.axvline(A_ / (A_ + B_), color=INK2, linewidth=1)
ax.set_ylim(0, stats.beta.pdf(A_ / (A_ + B_), A_, B_) * 1.15)
ax.text(A_ / (A_ + B_) + 0.01, stats.beta.pdf(A_ / (A_ + B_), A_, B_) * 1.06, f"average {A_/(A_+B_)*100:.0f}% a month", fontsize=8.5, color=INK2)
ax.text(0.005, stats.beta.pdf(A_ / (A_ + B_), A_, B_) * 0.5, f"only {KEY['x_sbg_share_churn_below_10pct']*100:.1f}% of users\nbelow 10% a month", fontsize=8.5, color=INK)
ax.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0, decimals=0))
ax.set_yticks([])
ax.set_xlabel("A user's chance of leaving in any given month")
ax.set_title("Model-implied churn propensity: no loyal core")
tidy(ax, ygrid=False)
caption(fig, f"Shifted-beta-geometric model fitted to 18,000 user lifetimes (right-censored for active users): Beta({A_:.1f}, {B_:.1f}). "
        f"Fits observed retention far better than constant churn (likelihood-ratio {KEY['x_sbg_lr_vs_constant']:.0f}).")
save_fig(fig, "fig9_survival_no_loyal_core.png", relayout=True)
plt.close(fig)

# Fig 10 - the "early-month" first purchase is an order statistic, and M0 is a full month
fig, axes = plt.subplots(1, 2, figsize=(12, 4.0), gridspec_kw={"width_ratios": [1.6, 1]})
ax = axes[0]
ax.bar(first_day_tbl.index, first_day_tbl["observed"], width=0.7, color=BLUE, label="Observed: day of a new user's first purchase")
ax.plot(first_day_tbl.index, first_day_tbl["expected_earliest_of_uniform_days"], color=ORANGE, linewidth=2,
        label="Model: earliest of the user's first-month purchases,\nplaced at random across the whole month")
ax.set_xlim(0, 32)
ax.set_xticks([1, 5, 10, 15, 20, 25, 31])
ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0, decimals=0))
ax.set_xlabel("Day of month")
ax.set_title(f"No onboarding waves: {KEY['f_first_day_1_3_observed']*100:.1f}% on days 1–3 vs {KEY['f_first_day_1_3_expected']*100:.1f}% by chance")
ax.legend(loc="upper right", fontsize=8.5)
tidy(ax)
ax = axes[1]
vals_ = [KEY["f_same_users_txn_m0"], KEY["f_same_users_txn_m1"], KEY["f_same_users_txn_m2"]]
ax.bar(range(3), vals_, width=0.55, color=BLUE)
for xi, v_ in enumerate(vals_):
    ax.text(xi, v_ + 0.05, f"{v_:.2f}", ha="center", fontsize=9, color=INK)
ax.set_xticks(range(3), ["First month (M0)", "M1", "M2"])
ax.set_ylim(0, 4)
ax.set_yticks([1, 2, 3, 4])
ax.set_title("The first month is a full month")
ax.set_ylabel("Purchases per user")
tidy(ax)
caption(fig, f"Right: the same {KEY['f_same_users_n']:,} users, active in M0, M1 and M2 (Wilcoxon M0 vs M1 p = {KEY['f_m0_vs_m1_wilcoxon_p']:.2f}). "
        "A late first purchase is what a user with few purchases looks like, not a late sign-up.")
save_fig(fig, "fig10_first_purchase_day_is_an_artefact.png", relayout=True)
plt.close(fig)

# Fig 12 - the balance field follows a rule
fig, axes = plt.subplots(1, 2, figsize=(12, 3.9), gridspec_kw={"width_ratios": [1, 1.2]})
ax = axes[0]
ax.bar(range(len(pd_by_gap)), pd_by_gap["mean"], width=0.6, color=BLUE)
for xi, v_ in enumerate(pd_by_gap["mean"]):
    ax.text(xi, v_ + 0.012, f"{v_*100:.1f}%", ha="center", fontsize=8.5, color=INK)
ax.set_xticks(range(len(pd_by_gap)), [str(i) for i in pd_by_gap.index])
pct_axis(ax, 0, 0.5)
ax.set_xlabel("Days since the previous purchase")
ax.set_title("Balance falls on ~35% of purchases, whatever the gap")
tidy(ax)
ax = axes[1]
ax.hist(pd_frac, bins=np.arange(0, 0.75, 0.025), color=BLUE, edgecolor=SURFACE, linewidth=0.5)
ax.set_xlim(0, 0.75)
ax.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0, decimals=0))
ax.set_xlabel("Balance after the purchase ÷ (previous balance + purchase)")
ax.set_title("When it falls, the share kept is a flat random draw from 0% to 70%")
tidy(ax)
caption(fig, f"Every clean row follows one of three rules: balance = previous + purchase ({KEY['f_balance_rule_add_share']*100:.1f}%), "
        f"= the limit when that would exceed it ({KEY['f_balance_rule_cap_share']*100:.1f}%), or a random pay-down ({KEY['f_balance_paydown_share']*100:.1f}%). "
        "Real repayments would cluster after statement and due dates and grow with time since purchase.")
save_fig(fig, "fig12_balance_field_rules.png", relayout=True)
plt.close(fig)

# Fig 13 - churn follows a user's usual frequency; heavy users can be reached earlier
fig, axes = plt.subplots(1, 2, figsize=(12, 4.0))
ax = axes[0]
xs_ = np.arange(len(by_avg))
ax.plot(xs_, by_avg["mean"], color=BLUE, marker="o", markersize=6, markeredgecolor=SURFACE, markeredgewidth=1.5, label="By usual frequency (3-month average)")
ax.plot(xs_, by_now["mean"].reindex(by_avg.index), color=GRAY, marker="o", markersize=6, markeredgecolor=SURFACE, markeredgewidth=1.5, label="By this month's purchases only")
ax.set_xticks(xs_, ["≤1", "2", "3", "4", "5", "6", ">6"])
pct_axis(ax, 0.15, 0.35)
ax.set_yticks([0.15, 0.20, 0.25, 0.30, 0.35])
ax.set_xlabel("Purchases per month (band)")
ax.set_title("Churn follows a user's usual frequency, not one month")
ax.legend(loc="upper right", fontsize=8.5)
tidy(ax)
ax = axes[1]
xb_ = np.arange(len(sil_tbl))
ax.bar(xb_ - 0.18, sil_tbl["lost_if_silent_day10"], width=0.34, color=BLUE, label="Silent by day 10")
ax.bar(xb_ + 0.18, sil_tbl["lost_if_silent_day15"], width=0.34, color=GRAY, label="Silent by day 15")
for xi, (v10, v15) in enumerate(zip(sil_tbl["lost_if_silent_day10"], sil_tbl["lost_if_silent_day15"])):
    ax.text(xi - 0.18, v10 + 0.015, f"{v10*100:.0f}", ha="center", fontsize=8, color=INK)
    ax.text(xi + 0.18, v15 + 0.015, f"{v15*100:.0f}", ha="center", fontsize=8, color=INK2)
ax.set_xticks(xb_, list(sil_tbl.index))
pct_axis(ax, 0, 1)
ax.set_xlabel("Usual purchases per month (3-month average)")
ax.set_title("Share lost if still silent: frequent users can be reached by day 10")
ax.legend(loc="upper left", fontsize=8.5)
tidy(ax)
caption(fig, f"User-months with three observed months after M0 (n = {KEY['b_sample_user_months']:,}). For this month's purchases the bands are 1, 2, …, 7+. "
        f"Given the 3-month average, this month's deviation adds nothing (log-odds {KEY['b_dev_coef']:+.2f}, 95% CI {KEY['b_dev_ci_low']:+.2f} to {KEY['b_dev_ci_high']:+.2f}).")
save_fig(fig, "fig13_churn_follows_usual_frequency.png", relayout=True)
plt.close(fig)

# Fig 11 - Option B: volume does not dilute quality; levers in one unit
fig, axes = plt.subplots(1, 2, figsize=(12.5, 4.4), gridspec_kw={"width_ratios": [1, 1.35]})
ax = axes[0]
ax.plot(coh_q["cohort_size"], coh_q["m1"], "o", color=BLUE, markersize=7, markeredgecolor=SURFACE, markeredgewidth=1.5)
for lab_, row_ in coh_q.iloc[[0, -1]].iterrows():
    ax.annotate(pd.Period(lab_).strftime("%b %y"), (row_["cohort_size"], row_["m1"]), xytext=(6, 4), textcoords="offset points", fontsize=8.5, color=INK2)
pct_axis(ax, 0.6, 0.85)
ax.set_xlabel("New users in the cohort")
ax.set_ylabel("M1 retention")
ax.set_title(f"Cohort size vs M1: weak, non-significant link (r = {KEY['g_size_vs_m1_r']:.2f}, p = {KEY['g_size_vs_m1_p']:.2f})", fontsize=11)
tidy(ax)
ax = axes[1]
lv = lev.iloc[::-1]
cols_ = [BLUE if "new users" in l_.lower() else AQUA for l_ in lv["lever"]]
ax.barh(range(len(lv)), lv["extra_monthly_gmv_jun26"] / 1e6, height=0.55, color=cols_)
for yi, v_ in enumerate(lv["extra_monthly_gmv_jun26"] / 1e6):
    ax.text(v_ + 15, yi, f"+{v_:,.0f}M VND ({v_*1e6/month_gmv*100:.1f}%)", va="center", fontsize=8.5, color=INK2)
ax.set_yticks(range(len(lv)), list(lv["lever"]), fontsize=8.5)
ax.set_xlim(0, lv["extra_monthly_gmv_jun26"].max() / 1e6 * 1.45)
ax.set_xlabel("Extra GMV per month by Jun-26 (vs new users holding flat)")
ax.set_title("Growth levers in one unit: new-user volume dominates")
ax.grid(axis="x", visible=True); ax.grid(axis="y", visible=False)
for s_ in ("top", "right", "left"):
    ax.spines[s_].set_visible(False)
ax.tick_params(length=0)
caption(fig, f"Left: cohorts Jan-24 to Apr-25 (size falls with calendar time, so this also tests quality over time). Right: illustrations under stated assumptions, "
        f"before incentive cost and credit losses; % of today's average monthly GMV (~{month_gmv/1e9:.2f}B VND). Blue = acquisition, aqua = existing users.")
save_fig(fig, "fig11_growth_option_b.png", relayout=True)
plt.close(fig)

# ==========================================================================
# 9. SAVE KEY NUMBERS
# ==========================================================================
with open(OUT / "key_numbers.json", "w") as f:
    json.dump(KEY, f, indent=2, default=str)
print(f"Done. {len(KEY)} key numbers, tables in {TAB}, charts in {FIG}")
