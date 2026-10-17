"""
Column-by-column EDA and data forensics for the CE BI test BNPL extract.

Run:  python3 -I data_forensics.py [path/to/data.csv]
Writes: eda_numbers.json and tables/*.csv next to this script; prints every number.
Default data = the "clean" file (104 out-of-sequence rows removed); raw is used where stated.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
from scipy import optimize, stats

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 40)
pd.set_option("display.max_rows", 200)

HERE = Path(__file__).resolve().parent
DATA = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE.parents[2] / "data.csv"
TAB = HERE / "tables"
TAB.mkdir(exist_ok=True)
NUM = {}


def key(name, value):
    if isinstance(value, (np.floating, np.integer)):
        value = value.item()
    NUM[name] = value
    print(f"  {name} = {value}")


def section(title):
    print("\n" + "=" * 100 + f"\n{title}\n" + "=" * 100)


def poisson_sf(obs, exp):
    return float(stats.poisson.sf(obs - 1, exp))


# ======================================================================================
# 0. LOAD
# ======================================================================================
section("0. LOAD")
raw = pd.read_csv(DATA)
raw["file_row"] = np.arange(len(raw))
raw["seq"] = raw["transaction_id"].str[3:].astype(int)
raw["date"] = pd.to_datetime(raw["trxn_date"])

# out-of-sequence rows: rows whose ID is outside the user's first contiguous ID block
s = raw.sort_values("seq")
blk = (s["user_id"] != s["user_id"].shift()).cumsum()
raw["oos"] = (blk != blk.groupby(s["user_id"]).transform("min")).reindex(raw.index)
key("raw_rows", len(raw))
key("oos_rows", int(raw["oos"].sum()))
key("oos_seq_min", int(raw.loc[raw.oos, "seq"].min()))
key("oos_seq_max", int(raw.loc[raw.oos, "seq"].max()))


def enrich(d):
    d = d.sort_values(["user_id", "seq"]).copy()
    g = d.groupby("user_id")
    d["k"] = g.cumcount()
    d["n_user"] = g["seq"].transform("size")
    d["prev_out"] = g["total_outstanding"].shift()
    d["prev_date"] = g["date"].shift()
    d["gap"] = (d["date"] - d["prev_date"]).dt.days
    d["base"] = d["prev_out"].fillna(0) + d["trxn_amount"]          # balance if nothing was repaid
    d["u"] = d["total_outstanding"] / d["base"]
    d["is_same"] = d["total_outstanding"] == d["base"]
    d["is_capped"] = (d["total_outstanding"] == d["total_limit"]) & (d["base"] > d["total_limit"])
    d["is_rep"] = (d["total_outstanding"] < d["base"]) & ~d["is_capped"]
    d["mon"] = d["date"].dt.to_period("M")
    d["dom"] = d["date"].dt.day
    d["dow"] = d["date"].dt.dayofweek
    d["dim"] = d["date"].dt.days_in_month
    first_mon = g["mon"].transform("min")
    d["age"] = (d["mon"].astype("int64") - first_mon.astype("int64")).astype(int)
    d["la"] = np.log(d["trxn_amount"])
    return d


rawe = enrich(raw)
c = enrich(raw[~raw["oos"]])                    # clean
key("clean_rows", len(c))
USERS = c.groupby("user_id").agg(
    lim=("total_limit", "first"), n_lim=("total_limit", "nunique"), first=("date", "min"), last=("date", "max"),
    n=("seq", "size"), gmv=("trxn_amount", "sum"), first_amt=("trxn_amount", "first"),
    months=("mon", "nunique"), mean_ticket=("trxn_amount", "mean"))
USERS["cohort"] = USERS["first"].dt.to_period("M")
USERS["first_dom"] = USERS["first"].dt.day

# ======================================================================================
# 1. total_outstanding: THE BALANCE RULE
# ======================================================================================
section("1. total_outstanding - balance rule reconstruction")
key("bal_share_same(prev+amt)", float(c.is_same.mean()))
key("bal_share_capped_at_limit", float(c.is_capped.mean()))
key("bal_share_paid_down", float(c.is_rep.mean()))
key("bal_rule_coverage_clean", float((c.is_same | c.is_capped | (c.is_rep & (c.u <= 0.7 + 1000 / c.base + 1e-9))).mean()))
key("bal_rule_violations_clean", int((~(c.is_same | c.is_capped | (c.is_rep & (c.u <= 0.7 + 1000 / c.base + 1e-9)))).sum()))
key("bal_rule_rows_needing_over_500vnd_tolerance", int((c.is_rep & (c.u > 0.7 + 500 / c.base + 1e-9)).sum()))
rr = rawe
key("bal_rule_violations_raw", int((~(rr.is_same | rr.is_capped | (rr.is_rep & (rr.u <= 0.7 + 1000 / rr.base + 1e-9)))).sum()))
p_rep = c.is_rep.mean()
n_rep = len(c)
key("p_paydown", float(p_rep))
key("p_paydown_ci95", [float(p_rep - 1.96 * np.sqrt(p_rep * (1 - p_rep) / n_rep)), float(p_rep + 1.96 * np.sqrt(p_rep * (1 - p_rep) / n_rep))])
key("p_paydown_first_txn", float(c.loc[c.k == 0, "is_rep"].mean()))
key("p_paydown_later_txn", float(c.loc[c.k > 0, "is_rep"].mean()))
rep = c[c.is_rep]
key("paydown_u_KS_vs_U(0,0.7)_p", float(stats.kstest(rep.u.clip(upper=0.7) / 0.7, "uniform").pvalue))
key("paydown_u_max", float(rep.u.max()))
h, edges = np.histogram(rep.u, bins=np.arange(0, 0.75, 0.05))
key("paydown_u_hist_0to0.7_step0.05", h.tolist())
key("balance_zero_rows", int((c.total_outstanding == 0).sum()))
key("balance_zero_expected_if_rounded", float(np.minimum(500 / rep.base / 0.7, 1).sum()))
key("balance_zero_expected_if_floored", float(np.minimum(1000 / rep.base / 0.7, 1).sum()))

later = c[c.k > 0].copy()
tbl = later.groupby(pd.cut(later.gap, [-1, 0, 1, 3, 7, 14, 30, 400]), observed=True)["is_rep"].agg(["mean", "size"])
print(tbl); tbl.to_csv(TAB / "paydown_by_gap_days.csv")
ct = pd.crosstab(pd.cut(later.gap, [-1, 0, 1, 3, 7, 14, 30, 400]), later.is_rep)
key("paydown_vs_gap_chi2_p", float(stats.chi2_contingency(ct)[1]))
later["crossed_month"] = later["mon"] != later["prev_date"].dt.to_period("M")
key("paydown_same_month", float(later.loc[~later.crossed_month, "is_rep"].mean()))
key("paydown_crossed_month_boundary", float(later.loc[later.crossed_month, "is_rep"].mean()))
key("paydown_same_day_as_prev", float(later.loc[later.gap == 0, "is_rep"].mean()))
key("paydown_gap_30plus", float(later.loc[later.gap >= 30, "is_rep"].mean()))
ct = pd.crosstab(later.dom, later.is_rep)
key("paydown_vs_day_of_month_chi2_p", float(stats.chi2_contingency(ct)[1]))
later["prev_rep"] = later.groupby("user_id")["is_rep"].shift()
c["prev_rep"] = c.groupby("user_id")["is_rep"].shift()
key("paydown_given_prev_paydown", float(c.loc[c.prev_rep == True, "is_rep"].mean()))
key("paydown_given_prev_no_paydown", float(c.loc[c.prev_rep == False, "is_rep"].mean()))
uu = c.groupby("user_id")["is_rep"].agg(["sum", "size"])
uu = uu[uu["size"] >= 10]
chi = ((uu["sum"] - uu["size"] * p_rep) ** 2 / (uu["size"] * p_rep * (1 - p_rep))).sum()
key("paydown_user_heterogeneity_dispersion", float(chi / (len(uu) - 1)))
key("paydown_user_heterogeneity_p", float(stats.chi2.sf(chi, len(uu) - 1)))
key("paydown_users_tested(n>=10)", len(uu))
key("paydown_full_prior_balance_cleared_share", float((rep.total_outstanding == rep.trxn_amount).mean()))
key("paydown_amount_mult_10k_share", float(((rep.base - rep.total_outstanding) % 10000 == 0).mean()))
key("rows_balance_below_purchase_amount", int((c.total_outstanding < c.trxn_amount).sum()))
key("rows_balance_below_purchase_amount_share", float((c.total_outstanding < c.trxn_amount).mean()))
key("first_txn_balance_below_amount_share", float((c.loc[c.k == 0, "total_outstanding"] < c.loc[c.k == 0, "trxn_amount"]).mean()))
key("first_txn_balance_above_amount_rows", int((c.loc[c.k == 0, "total_outstanding"] > c.loc[c.k == 0, "trxn_amount"]).sum()))
key("balance_above_limit_rows", int((c.total_outstanding > c.total_limit).sum()))
# limit-related
at = c.total_outstanding == c.total_limit
key("rows_balance_eq_limit", int(at.sum()))
key("users_balance_eq_limit", int(c.loc[at, "user_id"].nunique()))
key("purchases_at_already_full_limit", int((at & (c.prev_out == c.total_limit)).sum()))
key("purchases_exceeding_available_headroom", int((c.base > c.total_limit).sum()))
key("purchases_made_with_zero_headroom", int((c.prev_out == c.total_limit).sum()))
key("over_headroom_purchases_capped_share", float(c.loc[c.base > c.total_limit, "is_capped"].mean()))
key("over_headroom_purchases_paid_down_share", float(c.loc[c.base > c.total_limit, "is_rep"].mean()))
c["head"] = c.total_limit - c.prev_out.fillna(0)
lt = c[c.k > 0]
t = lt.groupby(pd.cut(lt["head"], [-1, 0, 1e5, 2e5, 5e5, 1e6, 1e8]), observed=True)["trxn_amount"].agg(["median", "mean", "size"])
print(t); t.to_csv(TAB / "amount_by_available_headroom.csv")
c["limb"] = pd.cut(c.total_limit, [0, 1e6, 2e6, 3e6, 5e6, 7.5e6, 1e7])
c["util"] = c.total_outstanding / c.total_limit
t = c.groupby("limb", observed=True).agg(median_balance=("total_outstanding", "median"), median_util=("util", "median"))
print(t); t.to_csv(TAB / "balance_and_util_by_limit_band.csv")
key("median_balance_limit_le1m", float(t["median_balance"].iloc[0]))
key("median_balance_limit_gt7.5m", float(t["median_balance"].iloc[-1]))
key("median_util_limit_le1m", float(t["median_util"].iloc[0]))
key("median_util_limit_gt7.5m", float(t["median_util"].iloc[-1]))
uever = at.groupby(c.user_id).any()
t = uever.groupby(pd.cut(USERS.lim, [0, 6e5, 1e6, 1.5e6, 2e6, 3e6, 1e7]), observed=True).mean()
print("share of users ever at limit by limit band\n", t); t.to_csv(TAB / "ever_at_limit_by_limit_band.csv")

# ======================================================================================
# 2. trxn_amount
# ======================================================================================
section("2. trxn_amount")
a = c.trxn_amount
key("amount_unique", int(a.nunique()))
key("amount_min", float(a.min())); key("amount_max", float(a.max()))
key("amount_all_multiples_of_1000", bool((a % 1000 == 0).all()))
vc = a.value_counts().sort_index()
key("amount_rows_at_20000", int(vc.loc[20000])); key("amount_rows_at_21000", int(vc.loc[21000]))
# a second clip: amount never above 60% of the credit limit
key("amount_rows_above_0.6_limit", int((a > 0.6 * c.total_limit).sum()))
key("amount_rows_at_exactly_0.6_limit", int((a == 0.6 * c.total_limit).sum()))
key("amount_users_hitting_0.6_cap", int(c.loc[a == 0.6 * c.total_limit, "user_id"].nunique()))
key("amount_max_over_limit", float((a / c.total_limit).max()))
for f in (0.5, 0.4, 0.3):
    key(f"amount_rows_at_exactly_{f}_limit", int((a == f * c.total_limit).sum()))


# censored lognormal MLE: left-censored at 20k, right-censored at 0.6*limit, 1k rounding ignored
y = c.la.values
lo = np.log(20000)
hi = np.log(0.6 * c.total_limit.values)
L = a.values == 20000
R = a.values == 0.6 * c.total_limit.values
M = ~L & ~R


def nll(p):
    mu, ls = p
    sd = np.exp(ls)
    return -(stats.norm.logpdf(y[M], mu, sd).sum() + stats.norm.logcdf((lo + np.log(20500 / 20000) - mu) / sd) * L.sum()
             + stats.norm.logsf((hi[R] - np.log(1.0 + 500 / (0.6 * c.total_limit.values[R])) - mu) / sd).sum())


res = optimize.minimize(nll, x0=[np.log(133000), np.log(0.7)], method="Nelder-Mead")
MU, SD = res.x[0], float(np.exp(res.x[1]))
key("amount_lognormal_median", float(np.exp(MU))); key("amount_lognormal_sigma", SD)
key("amount_share_at_20k_observed", float((a == 20000).mean()))
key("amount_share_below_20.5k_under_lognormal", float(stats.norm.cdf((np.log(20500) - MU) / SD)))
# pile-up at 0.6*limit vs lognormal tail mass, small limits
t = c.groupby("total_limit").apply(lambda g: pd.Series({
    "rows": len(g), "share_at_0.6_limit": (g.trxn_amount == 0.6 * g.name).mean(),
    "lognormal_mass_above": 1 - stats.norm.cdf((np.log(0.6 * g.name - 500) - MU) / SD)})).head(10)
print(t); t.to_csv(TAB / "amount_pileup_at_60pct_limit.csv")
# goodness of fit on interior bins (log scale)
bins = np.log(np.array([20500, 40000, 60000, 80000, 100000, 130000, 160000, 200000, 250000, 300000, 400000, 600000, 1000000, 5e6]))
obs = np.histogram(c.la[M & (c.total_limit >= 2000000)], bins)[0]
pr = np.diff(stats.norm.cdf((bins - MU) / SD)); exp = pr / pr.sum() * obs.sum()
key("amount_lognormal_bin_ratio_obs_over_exp(limit>=2M)", np.round(obs / exp, 3).tolist())
# round-number heaping
grid = np.arange(20000, 5000001, 1000)
w = stats.lognorm.pdf(grid, s=SD, scale=np.exp(MU)); w /= w.sum()
for m in (10000, 50000, 100000):
    key(f"amount_share_multiple_of_{m}", float((a % m == 0).mean()))
    key(f"amount_share_multiple_of_{m}_expected_smooth", float(w[grid % m == 0].sum()))
for car in ("Telco", "Voucher Selling", "Billing"):
    key(f"amount_share_mult_50k_{car}", float((c.loc[c.carrier == car, "trxn_amount"] % 50000 == 0).mean()))
key("amount_rows_100k", int(vc.loc[100000])); key("amount_rows_99k", int(vc.loc[99000])); key("amount_rows_101k", int(vc.loc[101000]))
key("amount_last_thousand_digit_chi2_p", float(stats.chisquare(np.bincount(((a // 1000) % 10).astype(int), minlength=10)).pvalue))
clip = (a == 20000) | (a == 0.6 * c.total_limit)
key("amount_last_thousand_digit_chi2_p_excl_clipped", float(stats.chisquare(np.bincount(((a[~clip] // 1000) % 10).astype(int), minlength=10)).pvalue))
for m in (10000, 50000, 100000):
    key(f"amount_share_multiple_of_{m}_excl_clipped", float((a[~clip] % m == 0).mean()))
# user effect (ICC) and autocorrelation
g = c.groupby("user_id").la
n_i, m_i = g.size(), g.mean()
k_, N_ = len(n_i), len(c)
msb = (n_i * (m_i - c.la.mean()) ** 2).sum() / (k_ - 1)
msw = ((c.la - c.user_id.map(m_i)) ** 2).sum() / (N_ - k_)
n0 = (N_ - (n_i ** 2).sum() / N_) / (k_ - 1)
key("amount_user_ICC_log", float((msb - msw) / (msb + (n0 - 1) * msw)))
key("amount_user_anova_p", float(stats.f.sf(msb / msw, k_ - 1, N_ - k_)))
c["prev_la"] = c.groupby("user_id")["la"].shift()
key("amount_lag1_corr_within_user", float(c[["la", "prev_la"]].corr().iloc[0, 1]))
key("user_gmv_vs_txn_count_R2", float(np.corrcoef(USERS.n, USERS.gmv)[0, 1] ** 2))

# ======================================================================================
# 3. Dependence screen: amount and pay-down event against every other feature
# ======================================================================================
section("3. Dependence screen")
c["lim_dec"] = pd.qcut(c.total_limit, 10, duplicates="drop").astype(str)
c["uid_dec"] = pd.qcut(c.user_id, 10).astype(str)
c["k_b"] = c.k.clip(upper=20)
c["age_b"] = c.age.clip(upper=12)
c["n_mon"] = c.groupby(["user_id", "mon"])["seq"].transform("size").clip(upper=8)
c["mon_s"] = c["mon"].astype(str)
rows = []
for col in ["package_code", "carrier", "lim_dec", "dow", "dom", "mon_s", "age_b", "k_b", "uid_dec", "n_mon"]:
    groups = [v.values for _, v in c.groupby(col).la]
    H, p = stats.kruskal(*groups)
    gm = c.groupby(col).la.transform("mean")
    eta2 = ((gm - c.la.mean()) ** 2).sum() / ((c.la - c.la.mean()) ** 2).sum()
    med = c.groupby(col).trxn_amount.median()
    ctab = pd.crosstab(c[col], c.is_rep)
    chi2, p2, _, _ = stats.chi2_contingency(ctab)
    rr_ = c.groupby(col).is_rep.mean()
    rows.append((col, c[col].nunique(), eta2, p, med.min(), med.max(), p2, rr_.min(), rr_.max()))
dep = pd.DataFrame(rows, columns=["feature", "levels", "eta2_log_amount", "kruskal_p", "median_amt_min", "median_amt_max",
                                  "paydown_chi2_p", "paydown_rate_min", "paydown_rate_max"])
print(dep.round(5).to_string()); dep.to_csv(TAB / "dependence_screen_amount_paydown.csv", index=False)
key("dep_max_eta2_amount", float(dep.eta2_log_amount.max()))
key("dep_min_p_amount", float(dep.kruskal_p.min()))
key("dep_min_p_paydown", float(dep.paydown_chi2_p.min()))
# user-level Spearman matrix
U = USERS.copy()
U["uid"] = U.index
U["cohort_i"] = U.cohort.astype("int64")
cols = ["uid", "lim", "cohort_i", "first_dom", "n", "months", "gmv", "mean_ticket", "first_amt"]
rho = U[cols].corr(method="spearman")
print(rho.round(3)); rho.round(4).to_csv(TAB / "user_level_spearman.csv")
for a_, b_ in [("lim", "n"), ("lim", "gmv"), ("lim", "mean_ticket"), ("lim", "first_amt"), ("lim", "cohort_i"), ("uid", "cohort_i"),
               ("uid", "lim"), ("mean_ticket", "months"), ("mean_ticket", "n")]:
    r, p = stats.spearmanr(U[a_], U[b_])
    key(f"spearman_{a_}_{b_}", [round(float(r), 4), float(p)])

# ======================================================================================
# 4. total_limit
# ======================================================================================
section("4. total_limit")
key("limit_constant_per_user", bool((USERS.n_lim == 1).all()))
lv = USERS.lim.value_counts().sort_index()
key("limit_levels", int(len(lv)))
key("limit_grid_is_full_100k_grid_0.5_to_9.9m", bool(np.array_equal(lv.index.values, np.arange(500000, 9900001, 100000))))
key("limit_users_per_level_min", int(lv.min())); key("limit_users_per_level_max", int(lv.max()))
key("limit_users_per_level_chi2_uniform_p", float(stats.chisquare(lv.values).pvalue))
key("limit_users_per_level_var_over_mean", float(lv.var() / lv.mean()))
key("limit_mean", float(USERS.lim.mean())); key("limit_median", float(USERS.lim.median()))
key("limit_by_cohort_kruskal_p", float(stats.kruskal(*[g.values for _, g in USERS.groupby("cohort").lim]).pvalue))
cm = USERS.groupby("cohort").lim.mean()
key("limit_cohort_mean_min", float(cm.min())); key("limit_cohort_mean_max", float(cm.max()))
lv.to_csv(TAB / "users_per_limit_level.csv")

# ======================================================================================
# 5. trxn_date
# ======================================================================================
section("5. trxn_date")
alld = pd.date_range(c.date.min(), c.date.max())
key("calendar_days", len(alld)); key("days_with_transactions", int(c.date.nunique()))
key("file_sorted_by_date", bool(raw.date.is_monotonic_increasing))
# 5a. existing users (age>=1): day-of-month exactly uniform?
r1 = c[c.age >= 1]
expd = np.zeros(32)
for Lm, n in r1.groupby("dim").size().items():
    expd[1:Lm + 1] += n / Lm
obsd = np.bincount(r1.dom, minlength=32).astype(float)
chi = ((obsd[1:] - expd[1:]) ** 2 / expd[1:]).sum()
key("dom_uniform_chi2_age1plus", float(chi)); key("dom_uniform_p_age1plus", float(stats.chi2.sf(chi, 30)))
key("dom_ratio_min_age1plus", float((obsd[1:] / expd[1:]).min())); key("dom_ratio_max_age1plus", float((obsd[1:] / expd[1:]).max()))
pd.Series(obsd[1:] / expd[1:], index=range(1, 32), name="obs_over_uniform").to_csv(TAB / "day_of_month_index_age1plus.csv")
daily = r1.groupby("date").size().reindex(alld, fill_value=0)
mexp = daily.groupby(daily.index.to_period("M")).transform("mean")
d2, e2 = daily[daily.index >= "2024-02-01"], mexp[mexp.index >= "2024-02-01"]
chi = ((d2 - e2) ** 2 / e2).sum()
key("daily_count_dispersion_age1plus", float(chi / (len(d2) - 17))); key("daily_count_dispersion_p", float(stats.chi2.sf(chi, len(d2) - 17)))
z = (d2 - e2) / np.sqrt(e2)
key("daily_max_abs_z", float(z.abs().max())); key("daily_max_abs_z_date", str(z.abs().idxmax().date()))
o_ = daily.groupby(daily.index.dayofweek).sum(); e_ = mexp.groupby(mexp.index.dayofweek).sum()
key("dow_ratio_age1plus", (o_ / e_).round(3).tolist())
key("dow_chi2_p_age1plus", float(stats.chisquare(o_, e_ * o_.sum() / e_.sum()).pvalue))
hol = {"Tet 2024 (8-14 Feb)": pd.date_range("2024-02-08", "2024-02-14"), "Tet 2025 (27 Jan-2 Feb)": pd.date_range("2025-01-27", "2025-02-02"),
       "30/4-1/5 2024": pd.date_range("2024-04-30", "2024-05-01"), "30/4-1/5 2025": pd.date_range("2025-04-30", "2025-05-01"),
       "2/9 2024": pd.to_datetime(["2024-09-02"]), "9/9 2024": pd.to_datetime(["2024-09-09"]), "10/10 2024": pd.to_datetime(["2024-10-10"]),
       "11/11 2024": pd.to_datetime(["2024-11-11"]), "12/12 2024": pd.to_datetime(["2024-12-12"]), "Black Friday 29/11/2024": pd.to_datetime(["2024-11-29"]),
       "24-25/12/2024": pd.date_range("2024-12-24", "2024-12-25"), "1/1/2025": pd.to_datetime(["2025-01-01"]), "3/3 2025": pd.to_datetime(["2025-03-03"]),
       "6/6 2025": pd.to_datetime(["2025-06-06"])}
hrows = []
for k_, v in hol.items():
    o, e = daily.loc[v].sum(), mexp.loc[v].sum()
    hrows.append((k_, int(o), round(float(e), 1), round(float(o / e), 3), round(float((o - e) / np.sqrt(e)), 2)))
ht = pd.DataFrame(hrows, columns=["window", "observed", "expected", "ratio", "z"])
print(ht.to_string()); ht.to_csv(TAB / "holiday_effects_age1plus.csv", index=False)
key("holiday_max_abs_z", float(ht.z.abs().max()))
# 5b. first month: is "first transaction day" just the minimum of uniformly placed days?
m0 = c[c.age == 0]
u0 = m0.groupby("user_id").agg(n0=("seq", "size"), fday=("dom", "min"), lday=("dom", "max"), L=("dim", "first"))
rng = np.random.default_rng(7)
mrows = []
for n in range(1, 9):
    s_ = u0[u0.n0 == n]
    em = np.mean([sum(((Lm - d + 1) / Lm) ** n for d in range(1, Lm + 1)) for Lm in s_.L])
    eM = np.mean([sum(1 - ((d - 1) / Lm) ** n for d in range(1, Lm + 1)) for Lm in s_.L])
    F = lambda d, Lm: 1 - ((Lm - d) / Lm) ** n
    lo_ = np.array([F(d - 1, Lm) for d, Lm in zip(s_.fday, s_.L)]); hi_ = np.array([F(d, Lm) for d, Lm in zip(s_.fday, s_.L)])
    pit = lo_ + rng.random(len(s_)) * (hi_ - lo_)
    mrows.append((n, len(s_), s_.fday.mean(), em, s_.lday.mean(), eM, stats.kstest(pit, "uniform").pvalue))
mt = pd.DataFrame(mrows, columns=["n0", "users", "mean_first_day", "model_min_of_n_uniform", "mean_last_day", "model_max_of_n_uniform", "KS_p_first_day"])
print(mt.round(3).to_string()); mt.to_csv(TAB / "first_day_vs_min_of_uniform_model.csv", index=False)
key("first_day_model_KS_p_min", float(mt.KS_p_first_day.min())); key("first_day_model_KS_p_max", float(mt.KS_p_first_day.max()))
key("first_day_n0eq1_mean", float(mt.mean_first_day.iloc[0])); key("first_day_n0eq1_model", float(mt.model_min_of_n_uniform.iloc[0]))
ump = c.groupby(["user_id", "age"]).size().unstack()
b = ump[ump[1].notna() & ump[2].notna()]
key("users_active_M0_M1_M2", len(b))
key("mean_n_M0_M1_M2_same_users", [round(float(b[0].mean()), 3), round(float(b[1].mean()), 3), round(float(b[2].mean()), 3)])
key("wilcoxon_n0_vs_n1_p", float(stats.wilcoxon(b[0], b[1]).pvalue))
b1 = ump[ump[1].notna()]
key("users_active_M0_M1", len(b1)); key("mean_n0_n1_active_M0_M1", [round(float(b1[0].mean()), 3), round(float(b1[1].mean()), 3)])
b1 = b1.assign(fd=USERS.first_dom)
t = b1.groupby(pd.cut(b1.fd, [0, 3, 7, 14, 21, 31]), observed=True)[[0, 1]].mean().round(2)
print("mean n0 and n1 by first-transaction day band (users active M0&M1)\n", t); t.to_csv(TAB / "n0_n1_by_first_day_band.csv")
coh = USERS.cohort.astype(str)
for name, msk in [("2024H1", coh < "2024-07"), ("2024H2", (coh >= "2024-07") & (coh < "2025-01")), ("2025", coh >= "2025-01")]:
    bb = b[b.index.isin(USERS.index[msk])]
    key(f"mean_n_M0_M1_M2_{name}", [round(float(bb[0].mean()), 3), round(float(bb[1].mean()), 3), round(float(bb[2].mean()), 3), len(bb)])
ctb = pd.crosstab(USERS.cohort, pd.cut(USERS.first_dom, [0, 3, 7, 14, 21, 31]))
key("first_day_band_by_cohort_chi2_p", float(stats.chi2_contingency(ctb)[1]))
key("first_day_le3_share", float((USERS.first_dom <= 3).mean()))
key("first_day_le3_share_by_cohort_min_max", [float((ctb.iloc[:, 0] / ctb.sum(1)).min()), float((ctb.iloc[:, 0] / ctb.sum(1)).max())])
# simulate M0 offsets of later transactions from the first one under the model (20 sims)
f_ = m0.groupby("user_id").dom.transform("min")
obs_off = np.bincount((m0.dom - f_)[m0.k > 0], minlength=31)[:31]
sim_off = np.zeros(31)
for it in range(20):
    for (n, Lm), grp in u0.groupby(["n0", "L"]):
        if n < 2:
            continue
        draws = np.sort(rng.integers(1, Lm + 1, size=(len(grp), n)), axis=1)
        sim_off += np.bincount((draws[:, 1:] - draws[:, :1]).ravel(), minlength=31)[:31]
sim_off /= 20
key("m0_offset0_observed", int(obs_off[0])); key("m0_offset0_model", float(sim_off[0]))
key("m0_offset_1to5_observed", obs_off[1:6].tolist()); key("m0_offset_1to5_model", np.round(sim_off[1:6], 0).tolist())
key("m0_offset_chi2_p_vs_model", float(stats.chi2.sf(((obs_off - sim_off) ** 2 / sim_off).sum(), 30)))
# same-day pairs within user-month vs uniform-with-replacement placement
um_n = c.groupby(["user_id", "mon"]).agg(n=("seq", "size"), L=("dim", "first"))
exp_pairs = (um_n.n * (um_n.n - 1) / 2 / um_n.L).sum()
obs_pairs = (c.groupby(["user_id", "date"]).size().pipe(lambda s_: s_ * (s_ - 1) / 2)).sum()
key("same_day_pairs_observed", float(obs_pairs)); key("same_day_pairs_expected_uniform", float(exp_pairs))

# ======================================================================================
# 6. transaction_id and user_id
# ======================================================================================
section("6. transaction_id / user_id")
ins = raw[~raw.oos].sort_values("seq")
key("txn_id_blocks_follow_user_id_order", bool(ins.user_id.is_monotonic_increasing))
key("txn_id_date_decreasing_within_user", int((ins.groupby("user_id").date.diff().dt.days < 0).sum()))
key("user_id_min", int(USERS.index.min())); key("user_id_max", int(USERS.index.max())); key("user_id_count", len(USERS))
r, p = stats.spearmanr(USERS.index, USERS["first"].astype("int64"))
key("spearman_user_id_first_date", [round(float(r), 4), float(p)])
within_date_sorted = raw.groupby("date").seq.apply(lambda x: x.is_monotonic_increasing).mean()
key("share_dates_where_file_order_follows_txn_id", float(within_date_sorted))

# ======================================================================================
# 7. package_code x carrier
# ======================================================================================
section("7. package_code x carrier")
cc = c.copy()
cc["carrier_lbl"] = cc.carrier  # keep 'Other services' (lower case) distinct
cc["pair"] = cc.package_code + " | " + cc.carrier_lbl
pc = cc.pair.value_counts()
key("pairs_clean", int(len(pc))); key("pair_rows_min", int(pc.min())); key("pair_rows_max", int(pc.max()))
key("pair_rows_cv", float(pc.std() / pc.mean()))
pc.to_csv(TAB / "pair_counts.csv")
npairs = cc.groupby("package_code").carrier_lbl.nunique()
pk = pd.DataFrame({"carriers": npairs, "share_if_equal_per_pair": npairs / npairs.sum(),
                   "gmv_share": cc.groupby("package_code").trxn_amount.sum() / cc.trxn_amount.sum()})
print(pk.sort_values("carriers")); pk.to_csv(TAB / "package_share_vs_carrier_count.csv")
key("package_gmv_share_vs_carrier_count_max_abs_diff_pp", float((pk.share_if_equal_per_pair - pk.gmv_share).abs().max() * 100))
key("package_gmv_share_vs_carrier_count_corr", float(np.corrcoef(pk.share_if_equal_per_pair, pk.gmv_share)[0, 1]))
ctp = pd.crosstab(cc.mon, cc.pair)
chi2_, p_, dof_, _ = stats.chi2_contingency(ctp)
key("pair_mix_by_month_cramersV", float(np.sqrt(chi2_ / (ctp.values.sum() * (min(ctp.shape) - 1)))))
key("pair_share_max_monthly_range_pp", float(((ctp.div(ctp.sum(1), axis=0)).max() - ctp.div(ctp.sum(1), axis=0).min()).max() * 100))
cc["prev_pair"] = cc.groupby("user_id").pair.shift()
rp = cc[cc.prev_pair.notna()]
key("p_same_pair_as_previous", float((rp.pair == rp.prev_pair).mean()))
key("p_same_pair_iid_expectation", float((cc.pair.value_counts(normalize=True) ** 2).sum()))
t = rp.assign(same=rp.pair == rp.prev_pair).groupby(pd.cut(rp.gap, [-1, 0, 3, 7, 14, 30, 400]), observed=True).same.mean()
print("P(same pair as previous) by gap\n", t); t.to_csv(TAB / "pair_stickiness_by_gap.csv")
key("p_same_pair_min_over_gap_bands", float(t.min())); key("p_same_pair_max_over_gap_bands", float(t.max()))


def co_usage(a1, a2, n_perm=200):
    rows_ = cc[(cc.package_code == "Channel Partner") & cc.carrier_lbl.isin([a1, a2])][["user_id", "carrier_lbl"]]
    obs_ = int((rows_.groupby("user_id").carrier_lbl.nunique() == 2).sum())
    sims = []
    for _ in range(n_perm):
        s2 = rows_.assign(carrier_lbl=rng.permutation(rows_.carrier_lbl.values))
        sims.append((s2.groupby("user_id").carrier_lbl.nunique() == 2).sum())
    return obs_, float(np.mean(sims)), obs_ / float(np.mean(sims))


crow = []
for a1, a2 in [("Other services", "Other Services"), ("Billing", "FnB"), ("Shopping", "Retail"), ("Game", "Entertainment"), ("Other Services", "Marketplace")]:
    o, e, ratio = co_usage(a1, a2)
    crow.append((a1, a2, o, round(e, 1), round(ratio, 3)))
cu = pd.DataFrame(crow, columns=["label_a", "label_b", "users_with_both", "expected_if_same_merchant(random_label)", "ratio"])
print(cu.to_string()); cu.to_csv(TAB / "other_services_label_co_usage.csv", index=False)
key("lowercase_vs_uppercase_co_usage_ratio", float(cu.ratio.iloc[0]))
key("distinct_carrier_pairs_co_usage_ratio_range", [float(cu.ratio.iloc[1:].min()), float(cu.ratio.iloc[1:].max())])
osr = cc[(cc.package_code == "Channel Partner") & cc.carrier_lbl.isin(["Other services", "Other Services"])]
key("lowercase_months_present", int(osr[osr.carrier_lbl == "Other services"].mon.nunique()))
key("lowercase_rows", int((cc.carrier_lbl == "Other services").sum()))

# ======================================================================================
# 8. The 104 out-of-sequence rows
# ======================================================================================
section("8. The 104 out-of-sequence rows")
o = rawe[rawe.oos].copy()
org = rawe[~rawe.oos]
key("oos_follow_balance_rule_same", int(o.is_same.sum()))
key("oos_follow_any_balance_rule", int((o.is_same | o.is_capped | (o.is_rep & (o.u <= 0.7 + 1000 / o.base + 1e-9))).sum()))
key("oos_violate_balance_rule", int((~(o.is_same | o.is_capped | (o.is_rep & (o.u <= 0.7 + 1000 / o.base + 1e-9)))).sum()))
first4 = org[org.user_id.isin(o.user_id)]
mm = o[["transaction_id", "user_id", "total_outstanding"]].merge(first4[["user_id", "total_outstanding", "k"]], on=["user_id", "total_outstanding"])
key("oos_balance_equals_one_of_users_earlier_balances", int(mm.transaction_id.nunique()))
key("oos_balance_source_position_counts(k=0..3)", mm.k.value_counts().sort_index().tolist())
# baseline: 5th organic transaction vs that user's first 4 balances
f4 = org[org.k < 4]
k4 = org[org.k == 4][["user_id", "total_outstanding", "trxn_amount", "carrier", "package_code"]]
bal_sets = f4.groupby("user_id").total_outstanding.apply(set)
amt_sets = f4.groupby("user_id").trxn_amount.apply(set)
car_sets = f4.groupby("user_id").carrier.apply(set)
pkg_sets = f4.groupby("user_id").package_code.apply(set)
key("baseline_5th_txn_balance_in_first4", float(np.mean([b_ in bal_sets[u_] for u_, b_ in zip(k4.user_id, k4.total_outstanding)])))
key("baseline_5th_txn_amount_in_first4", float(np.mean([b_ in amt_sets[u_] for u_, b_ in zip(k4.user_id, k4.trxn_amount)])))
key("baseline_5th_txn_carrier_in_first4", float(np.mean([b_ in car_sets[u_] for u_, b_ in zip(k4.user_id, k4.carrier)])))
key("baseline_5th_txn_package_in_first4", float(np.mean([b_ in pkg_sets[u_] for u_, b_ in zip(k4.user_id, k4.package_code)])))
ob = first4.groupby("user_id")
key("oos_amount_in_users_earlier_amounts", float(np.mean([b_ in set(ob.get_group(u_).trxn_amount) for u_, b_ in zip(o.user_id, o.trxn_amount)])))
key("oos_carrier_in_users_earlier_carriers", float(np.mean([b_ in set(ob.get_group(u_).carrier) for u_, b_ in zip(o.user_id, o.carrier)])))
key("oos_package_in_users_earlier_packages", float(np.mean([b_ in set(ob.get_group(u_).package_code) for u_, b_ in zip(o.user_id, o.package_code)])))
key("oos_limit_equals_user_limit", float((o.total_limit == o.user_id.map(USERS.lim)).mean()))
key("oos_amount_KS_vs_organic_p", float(stats.ks_2samp(o.trxn_amount, c.trxn_amount).pvalue))
key("oos_gap_days_mean", float(o.gap.mean()))
key("oos_day_of_month_mean", float(o.dom.mean())); key("oos_day_of_month_max", int(o.dom.max()))
# organic comparators: users with exactly 4 txns in M0 who did come back: first M1 transaction
n0 = c[c.age == 0].groupby("user_id").size()
cand = n0[n0 == 4].index
x = c[c.user_id.isin(cand)]
m1first = x[x.age == 1].groupby("user_id").date.min()
l0 = x[x.age == 0].groupby("user_id").date.max()
gap_org = (m1first - l0.reindex(m1first.index)).dt.days
key("organic_comparator_users", len(m1first))
key("organic_comparator_gap_mean", float(gap_org.mean())); key("organic_comparator_first_M1_dom_mean", float(m1first.dt.day.mean()))
key("oos_vs_organic_gap_KS_p", float(stats.ks_2samp(o.gap, gap_org).pvalue))
key("oos_vs_organic_M1_dom_KS_p", float(stats.ks_2samp(o.dom, m1first.dt.day).pvalue))
key("oos_dom_chi2_vs_uniform_1_29_p", float(stats.chisquare(np.bincount(o.dom, minlength=30)[1:30]).pvalue))
# were the 104 users a random subset of the eligible pool (4 txns all in M0, no M1)?
pool = USERS[USERS.index.isin(cand) & (USERS.months == 1) & (USERS.cohort < pd.Period("2025-06", "M"))]
inj = pool.index.isin(o.user_id)
key("eligible_pool_users(4 txns,M0 only)", len(pool)); key("injected_share_of_pool", float(inj.mean()))
key("injected_vs_pool_limit_KS_p", float(stats.ks_2samp(pool.lim[inj], pool.lim[~inj]).pvalue))
key("injected_vs_pool_cohort_KS_p", float(stats.ks_2samp(pool.cohort[inj].astype("int64"), pool.cohort[~inj].astype("int64")).pvalue))
key("injected_vs_pool_first_dom_KS_p", float(stats.ks_2samp(pool.first_dom[inj], pool.first_dom[~inj]).pvalue))
key("oos_file_rows_interleaved_by_date", bool(raw.date.is_monotonic_increasing))
r, p = stats.spearmanr(o.seq, o.user_id)
key("oos_id_order_vs_user_id_spearman", [round(float(r), 3), float(p)])

# ======================================================================================
# 9. Re-checks of existing claims that depend on these features
# ======================================================================================
section("9. Re-checks of existing claims")
# 9a. exact duplicate pair
cols_ = ["user_id", "trxn_date", "trxn_amount", "package_code", "carrier", "total_outstanding", "total_limit"]
dup = raw[raw.duplicated(cols_, keep=False)].sort_values("seq")
print(dup[["transaction_id"] + cols_])
key("exact_dup_amount_over_limit", float((dup.trxn_amount / dup.total_limit).iloc[0]))
key("exact_dup_balance_equals_limit", bool((dup.total_outstanding == dup.total_limit).all()))
# 9b. same user+day+amount: chance expectation with limit-specific amount distributions
kud = c.groupby(["user_id", "date"]).size().rename("kk").reset_index()
kud = kud[kud.kk >= 2]
kud["lim"] = kud.user_id.map(USERS.lim)
pm = c.groupby("total_limit").trxn_amount.apply(lambda s_: (s_.value_counts(normalize=True) ** 2).sum())
glob = (c.trxn_amount.value_counts(normalize=True) ** 2).sum()
exp_lim = float((kud.kk * (kud.kk - 1) / 2 * kud.lim.map(pm)).sum())
exp_glob = float((kud.kk * (kud.kk - 1) / 2).sum() * glob)
obs_sda = int(c.duplicated(["user_id", "date", "trxn_amount"]).sum())
key("same_user_day_amount_pairs", obs_sda); key("expected_global_pmf", exp_glob); key("expected_limit_specific_pmf", exp_lim)
key("p_value_global", poisson_sf(obs_sda, exp_glob)); key("p_value_limit_specific", poisson_sf(obs_sda, exp_lim))
key("same_user_day_amount_carrier_pairs", int(c.duplicated(["user_id", "date", "trxn_amount", "carrier"]).sum()))
# 9c. at-limit and churn (robustness of Appendix C's +0.24 log-odds)
umm = c.sort_values("seq").groupby(["user_id", "mon"]).agg(n=("seq", "size"), out_end=("total_outstanding", "last"),
                                                            lim=("total_limit", "first"), age=("age", "first"), gmv=("trxn_amount", "sum")).reset_index()
umm["mi"] = umm.mon.astype("int64")
umm["churn"] = umm.groupby("user_id").mi.shift(-1).isna().astype(int)
umm = umm[umm.mi < umm.mi.max()].copy()
umm["atlim"] = (umm.out_end == umm.lim).astype(int)
umm["hi80"] = (umm.out_end >= 0.8 * umm.lim).astype(int)
umm["util"] = umm.out_end / umm.lim
umm["nb"] = umm.n.clip(upper=4).astype(str); umm["ab"] = umm.age.clip(upper=8).astype(str)
umm["lb"] = pd.cut(umm.lim, [0, 7e5, 1e6, 1.5e6, 2e6, 3e6, 5e6, 1e7]).astype(str)
base_f = "churn ~ C(nb) + C(ab) + C(lb)"
for var in ["atlim", "hi80", "util"]:
    m_ = smf.logit(f"{base_f} + {var}", umm).fit(disp=0)
    key(f"churn_logit_{var}_coef_p", [round(float(m_.params[var]), 3), float(m_.pvalues[var])])
for name, sub in [("2024", umm[umm.mon < pd.Period("2025-01", "M")]), ("2025", umm[umm.mon >= pd.Period("2025-01", "M")])]:
    m_ = smf.logit(f"{base_f} + atlim", sub).fit(disp=0)
    key(f"churn_logit_atlim_{name}", [round(float(m_.params["atlim"]), 3), float(m_.pvalues["atlim"]), int(sub.atlim.sum())])
# 9d. 'credit-hungry' users (>=80% of limit in Jun-25) are predictable from limit and count alone
j = c[c.mon == pd.Period("2025-06", "M")]
gj = j.groupby("user_id").agg(lim=("total_limit", "first"), n=("seq", "size"), mx=("util", "max"))
gj["hungry"] = (gj.mx >= 0.8).astype(int)
from sklearn.metrics import roc_auc_score  # noqa: E402

mh = smf.logit("hungry ~ np.log(lim) + n", gj).fit(disp=0)
key("hungry_users_jun25", int(gj.hungry.sum()))
key("hungry_auc_from_limit_and_count_only", float(roc_auc_score(gj.hungry, mh.predict(gj))))
# 9e. starting balance: does any user carry a balance into the extract?
key("users_whose_first_balance_exceeds_first_amount", int((c[c.k == 0].total_outstanding > c[c.k == 0].trxn_amount).sum()))

# 9f. does first-transaction day matter for M1 once first-month count (N0) is known?
import statsmodels.api as sm  # noqa: E402

ages = c.groupby("user_id").age.apply(set)
e = USERS[USERS.cohort < pd.Period("2025-06", "M")].copy()
e["m1"] = [int(1 in ages[u_]) for u_ in e.index]
e["n0"] = c[c.age == 0].groupby("user_id").size().reindex(e.index)
e["nb"] = e.n0.clip(upper=8).astype(str)
e["fdb"] = pd.cut(e.first_dom, [0, 3, 7, 14, 21, 31]).astype(str)
m_a = smf.logit("m1 ~ C(nb)", e).fit(disp=0)
m_b = smf.logit("m1 ~ C(nb) + C(fdb)", e).fit(disp=0)
lr = 2 * (m_b.llf - m_a.llf)
key("m1_first_day_band_LR_given_n0", float(lr)); key("m1_first_day_band_p_given_n0", float(stats.chi2.sf(lr, 4)))
key("m1_raw_by_first_day_band", e.groupby("fdb").m1.mean().round(3).to_dict())
key("mean_n0_first_day_1_3", float(e[e.first_dom <= 3].n0.mean())); key("mean_n0_all", float(e.n0.mean()))
# 9g. new users per month: exponential decay + Poisson noise?
nu = USERS.groupby("cohort").size()
dfn = pd.DataFrame({"y": nu.values, "t": np.arange(len(nu))}, index=nu.index.astype(str))
gl = smf.glm("y ~ t", dfn, family=sm.families.Poisson()).fit()
pe = float((gl.resid_pearson ** 2).sum())
key("new_users_exp_monthly_change", float(np.exp(gl.params["t"]) - 1))
key("new_users_pearson_dispersion", pe / gl.df_resid); key("new_users_dispersion_p", float(stats.chi2.sf(pe, gl.df_resid)))
key("new_users_pearson_resid", dict(zip(dfn.index, np.round(gl.resid_pearson.values, 2).tolist())))
gl2 = smf.glm("y ~ t", dfn.drop(index="2024-10"), family=sm.families.Poisson()).fit()
pe2 = float((gl2.resid_pearson ** 2).sum())
key("new_users_dispersion_excl_oct24", pe2 / gl2.df_resid); key("new_users_dispersion_p_excl_oct24", float(stats.chi2.sf(pe2, gl2.df_resid)))
key("new_users_oct24_expected_from_fit_excl_oct24", float(gl2.predict(dfn.loc[["2024-10"]]).iloc[0]))
key("new_users_oct24_observed", int(dfn.loc["2024-10", "y"]))

json.dump(NUM, open(HERE / "eda_numbers.json", "w"), indent=1, default=str)
print(f"\nWrote {len(NUM)} numbers to {HERE / 'eda_numbers.json'} and tables to {TAB}")
