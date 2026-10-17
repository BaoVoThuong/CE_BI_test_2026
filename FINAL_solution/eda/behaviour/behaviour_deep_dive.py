"""
Behavioural & business EDA of the BNPL extract (Zalopay BI take-home, Credit Enablement).

Scope: how users behave over time, how they use credit, and which segments/patterns matter.
Verifies the existing Bonus findings (A1-A4, B1-B4, C1, D1-D2, E1, E3-E5) of
FINAL_solution/REPORT.md and adds new findings.

Run:   python3 eda_behaviour.py            (about 2-3 minutes)
Out:   outputs/eda_numbers.json  (every number quoted in EDA_BEHAVIOUR_REPORT.md)
       outputs/*.csv             (supporting tables)

Conventions (same as FINAL_solution/analysis.py):
  * clean data = drop transaction_id TXN00204591-TXN00204694 (104 out-of-sequence rows)
  * 'Other services' merged into 'Other Services'
  * cohort = calendar month of first transaction; M_k = calendar month cohort + k
  * churn after month t = active in t, no transaction in t+1 (no user ever returns)
  * light / medium / heavy = 1 / 2-3 / 4+ transactions in the month
  * all logits on user-month panels use standard errors clustered by user
"""
import json
import os
import warnings

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
from scipy import stats
from scipy.optimize import minimize
from scipy.special import betaln
from sklearn.metrics import roc_auc_score

warnings.filterwarnings("ignore")
pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 40)

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "..", "..", "data.csv")
OUT = os.path.join(HERE, "outputs")
os.makedirs(OUT, exist_ok=True)

K = {}


def key(name, value):
    if isinstance(value, (np.floating, float)):
        value = float(value)
    elif isinstance(value, (np.integer,)):
        value = int(value)
    K[name] = value
    print(f"  {name} = {value}")


def save(df, name, index=True):
    df.to_csv(os.path.join(OUT, f"{name}.csv"), index=index)


def wilson(k, n, z=1.96):
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return c - h, c + h


def logit_cl(formula, data):
    """Logit with user-clustered standard errors."""
    return smf.logit(formula, data=data).fit(disp=0, cov_type="cluster", cov_kwds={"groups": data["user_id"]})


def section(t):
    print("\n" + "=" * 80 + "\n" + t + "\n" + "=" * 80)


# =============================================================================
# 0. LOAD + BUILD
# =============================================================================
section("0. LOAD")
raw = pd.read_csv(DATA, parse_dates=["trxn_date"])
raw["txn_seq"] = raw["transaction_id"].str[3:].astype(int)
df = raw[~raw["txn_seq"].between(204591, 204694)].copy()
df["carrier"] = df["carrier"].replace({"Other services": "Other Services"})
df["mi"] = df["trxn_date"].dt.year * 12 + df["trxn_date"].dt.month - 1
df = df.sort_values(["user_id", "txn_seq"]).reset_index(drop=True)
LAST = int(df["mi"].max())
key("clean_rows", len(df))
key("users", df["user_id"].nunique())
key("seq_order_equals_date_order", bool((df.groupby("user_id")["trxn_date"].diff().dt.days.dropna() >= 0).all()))

d = df.copy()
d["prev_out"] = d.groupby("user_id")["total_outstanding"].shift()
d["gap"] = d.groupby("user_id")["trxn_date"].diff().dt.days
d["pre"] = d["prev_out"] + d["trxn_amount"]
d["repay"] = d["pre"] - d["total_outstanding"]
d["util"] = d["total_outstanding"] / d["total_limit"]
d["dom"] = d["trxn_date"].dt.day
d["dim"] = d["trxn_date"].dt.days_in_month
users = d.groupby("user_id").agg(first_date=("trxn_date", "min"), cohort=("mi", "min"), last_mi=("mi", "max"),
                                 n_txn=("txn_seq", "size"), gmv=("trxn_amount", "sum"), limit=("total_limit", "first"))
d = d.join(users[["first_date", "cohort"]], on="user_id")
d["age"] = d["mi"] - d["cohort"]
d["pos"] = d.groupby("user_id").cumcount()
d["dsf"] = (d["trxn_date"] - d["first_date"]).dt.days
um = d.groupby(["user_id", "mi"]).agg(
    n=("txn_seq", "size"), gmv=("trxn_amount", "sum"), avg_ticket=("trxn_amount", "mean"),
    n_car=("carrier", "nunique"), n_pkg=("package_code", "nunique"), out_end=("total_outstanding", "last"),
    util_end=("util", "last"), first_dom=("dom", "min"), last_dom=("dom", "max"), dim=("dim", "first"),
    age=("age", "first"), limit=("total_limit", "first"), cohort=("cohort", "first")).reset_index()
um["churn_next"] = um.groupby("user_id")["mi"].shift(-1).isna()
um["prev_n"] = um.groupby("user_id")["n"].shift(1)
um["prev2_n"] = um.groupby("user_id")["n"].shift(2)
users["n_months"] = um.groupby("user_id").size()
users["join_day"] = users["first_date"].dt.day
users["n0"] = um[um["age"] == 0].set_index("user_id")["n"]
users["m1"] = users.index.isin(um.loc[um["age"] == 1, "user_id"])
seg_of = lambda n: np.where(n == 1, "Light (1)", np.where(n <= 3, "Medium (2-3)", "Heavy (4+)"))
SEGS = ["Light (1)", "Medium (2-3)", "Heavy (4+)"]
um["seg"] = seg_of(um["n"])

panel = um[um["mi"] < LAST].copy()          # next month observable
panel["churn"] = panel["churn_next"].astype(int)
# running (expanding) average frequency over FULL months (age >= 1) up to and including t
full = panel[panel["age"] >= 1].copy()
full["cum_avg"] = full.groupby("user_id")["n"].transform(lambda s: s.expanding().mean())
full["age_c"] = full["age"].clip(upper=9)

# =============================================================================
# PART 1. VERIFICATION OF EXISTING BONUS FINDINGS
# =============================================================================
section("A1. Heavy users 38% of base, 65% of GMV (last 6 months)")
r6 = um[um["mi"] >= LAST - 5]
sv = r6.groupby("seg").agg(um_=("n", "size"), gmv=("gmv", "sum"), gpm=("gmv", "mean")).loc[SEGS]
sv["share_um"] = sv["um_"] / sv["um_"].sum()
sv["share_gmv"] = sv["gmv"] / sv["gmv"].sum()
save(sv.round(4), "v_a1_segment_value_last6m")
key("a1_heavy_share_user_months", sv.loc["Heavy (4+)", "share_um"])
key("a1_heavy_share_gmv", sv.loc["Heavy (4+)", "share_gmv"])
key("a1_light_share_user_months", sv.loc["Light (1)", "share_um"])
key("a1_light_share_gmv", sv.loc["Light (1)", "share_gmv"])
for s_, k_ in zip(SEGS, ("light", "medium", "heavy")):
    key(f"a1_gmv_per_um_{k_}_k", sv.loc[s_, "gpm"] / 1e3)
ug = users["gmv"].sort_values(ascending=False)
cs = ug.cumsum() / ug.sum()
key("a1_top10_share_all", cs.iloc[int(0.1 * len(ug)) - 1])
key("a1_top20_share_all", cs.iloc[int(0.2 * len(ug)) - 1])
# complete lifetimes only (churned users), to remove right-censoring
cu = users[users["last_mi"] < LAST]
ugc = cu["gmv"].sort_values(ascending=False)
csc = ugc.cumsum() / ugc.sum()
key("a1_top10_share_complete", csc.iloc[int(0.1 * len(ugc)) - 1])
key("a1_top20_share_complete", csc.iloc[int(0.2 * len(ugc)) - 1])


def gini(x):
    x = np.sort(np.asarray(x, dtype=float))
    n = len(x)
    return (2 * np.arange(1, n + 1) - n - 1).dot(x) / (n * x.sum())


key("a1_gini_lifetime_gmv_all", gini(users["gmv"]))
key("a1_gini_lifetime_gmv_complete", gini(cu["gmv"]))
# Heavy is a monthly state: what share of users are heavy in >=2/3 of their months?
um_full = um[um["age"] >= 1]
heavy_share_u = um_full.groupby("user_id")["n"].apply(lambda s: (s >= 4).mean())
nm_full = um_full.groupby("user_id").size()
key("a1_users_heavy_in_2of3_months_share_among_3plus_full_months", (heavy_share_u[nm_full >= 3] >= 2 / 3).mean())

section("A2. Base getting heavier as it shrinks")
mix = pd.crosstab(um["mi"], um["seg"], normalize="index")
key("a2_heavy_share_jun24", mix.loc[2024 * 12 + 5, "Heavy (4+)"])
key("a2_heavy_share_jun25", mix.loc[LAST, "Heavy (4+)"])
tpu = um.groupby("mi")["n"].mean()
key("a2_txn_per_user_oct24", tpu.loc[2024 * 12 + 9])
key("a2_txn_per_user_jun25", tpu.loc[LAST])
# Decompose Oct-24 -> Jun-25 change in txns per active user: tenure mix vs within-tenure
def tenure_band(a):
    return pd.cut(a, [-1, 0, 1, 3, 6, 100], labels=["M0", "M1", "M2-3", "M4-6", "M7+"])


a_, b_ = um[um["mi"] == 2024 * 12 + 9], um[um["mi"] == LAST]
wa = tenure_band(a_["age"]).value_counts(normalize=True).sort_index()
wb = tenure_band(b_["age"]).value_counts(normalize=True).sort_index()
ra = a_.groupby(tenure_band(a_["age"]), observed=True)["n"].mean()
rb = b_.groupby(tenure_band(b_["age"]), observed=True)["n"].mean()
dec = pd.DataFrame({"w_oct24": wa, "w_jun25": wb, "n_oct24": ra, "n_jun25": rb})
dec["mix"] = (dec["w_jun25"] - dec["w_oct24"]) * dec["n_oct24"]
dec["within"] = dec["w_jun25"] * (dec["n_jun25"] - dec["n_oct24"])
save(dec.round(4), "v_a2_txn_per_user_decomposition")
key("a2_change_total", tpu.loc[LAST] - tpu.loc[2024 * 12 + 9])
key("a2_change_mix", dec["mix"].sum())
key("a2_change_within", dec["within"].sum())
key("a2_m0_share_oct24", wa.loc["M0"])
key("a2_m0_share_jun25", wb.loc["M0"])
# finer: exact tenure month (0..17)
wa_e = a_["age"].value_counts(normalize=True); wb_e = b_["age"].value_counts(normalize=True)
ra_e = a_.groupby("age")["n"].mean(); rb_e = b_.groupby("age")["n"].mean()
ages_e = wb_e.index
mix_e = sum((wb_e.get(k, 0) - wa_e.get(k, 0)) * ra_e.get(k, um[um["age"] == k]["n"].mean()) for k in ages_e.union(wa_e.index))
key("a2_change_mix_exact_age", mix_e)
key("a2_change_within_exact_age", (tpu.loc[LAST] - tpu.loc[2024 * 12 + 9]) - mix_e)
# calendar trend in frequency within exact tenure (user-month OLS, user-clustered SE), Jul-24..Jun-25
ct = um[um["mi"] >= 2024 * 12 + 6].assign(t=lambda x: x["mi"] - (2024 * 12 + 6))
ctm = smf.ols("n ~ t + C(age)", data=ct).fit(cov_type="cluster", cov_kwds={"groups": ct["user_id"]})
key("a2_calendar_trend_per_month_within_age", ctm.params["t"])
key("a2_calendar_trend_ci_lo", ctm.conf_int().loc["t", 0]); key("a2_calendar_trend_ci_hi", ctm.conf_int().loc["t", 1])
key("a2_calendar_trend_p", ctm.pvalues["t"])
ct0 = smf.ols("n ~ t", data=ct).fit(cov_type="cluster", cov_kwds={"groups": ct["user_id"]})
key("a2_calendar_trend_raw_per_month", ct0.params["t"]); key("a2_calendar_trend_raw_p", ct0.pvalues["t"])

section("A4. Lifetime value ~2.3M VND (sBG) / 1.85M VND fixed 7-month window")
life_t = (users["last_mi"] - users["cohort"] + 1).values
still = (users["last_mi"] == LAST).values


def nll_sbg(par):
    a, b = np.exp(par)
    return -np.where(still, betaln(a, b + life_t - 1), betaln(a + 1, b + life_t - 1)).sum() + len(life_t) * betaln(a, b)


fs = minimize(nll_sbg, [0.0, 0.0], method="Nelder-Mead", options={"maxiter": 4000})
A_, B_ = np.exp(fs.x)
S_ = lambda k: float(np.exp(betaln(A_, B_ + k) - betaln(A_, B_)))
gmv_age = um.groupby(um["age"].clip(upper=12))["gmv"].mean()
key("a4_sbg_expected_active_months", sum(S_(k) for k in range(600)))
key("a4_sbg_lifetime_gmv_m", sum(S_(k) * gmv_age.loc[min(k, 12)] for k in range(600)) / 1e6)
for h in (6, 11):
    ids = users.index[users["cohort"] <= LAST - h]
    sub = um[um["user_id"].isin(ids) & (um["age"] <= h)]
    key(f"a4_fixed_M0_M{h}_users", len(ids))
    key(f"a4_fixed_M0_M{h}_gmv_m", sub["gmv"].sum() / len(ids) / 1e6)
    key(f"a4_fixed_M0_M{h}_active_months", len(sub) / len(ids))

section("B1. Monthly frequency is noisy; classify on a 2-3 month average")
nx = um[["user_id", "mi", "n"]].assign(mi=lambda x: x["mi"] - 1).rename(columns={"n": "n_next"})
tr = um[um["mi"] < LAST].merge(nx, on=["user_id", "mi"], how="left")
tr["next_state"] = np.where(tr["n_next"].isna(), "Churned", seg_of(tr["n_next"].fillna(0)))
trans = pd.crosstab(tr["seg"], tr["next_state"], normalize="index").loc[SEGS, SEGS + ["Churned"]]
save(trans.round(4), "v_b1_transitions")
key("b1_light_to_heavy", trans.loc["Light (1)", "Heavy (4+)"])
key("b1_heavy_to_light", trans.loc["Heavy (4+)", "Light (1)"])
key("b1_heavy_stay", trans.loc["Heavy (4+)", "Heavy (4+)"])
lng = um[um["user_id"].isin(users[users["n_months"] >= 6].index)].groupby("user_id")["n"].agg(["mean", "var"])
key("b1_var_to_mean", (lng["var"] / lng["mean"]).mean())
# Reliability of the monthly count as a measure of a user's personal rate (full months, users with >=4 of them)
f4 = um_full[um_full["user_id"].isin(nm_full[nm_full >= 4].index)].copy()
g = f4.groupby("user_id")["n"]
kk = g.size()
N, a = len(f4), len(kk)
msb = (kk * (g.mean() - f4["n"].mean()) ** 2).sum() / (a - 1)
msw = ((f4["n"] - g.transform("mean")) ** 2).sum() / (N - a)
n0_ = (N - (kk ** 2).sum() / N) / (a - 1)
icc1 = (msb - msw) / (msb + (n0_ - 1) * msw)
key("b1_icc_single_month_count", icc1)
for m_ in (1, 2, 3, 6):
    key(f"b1_reliability_{m_}_month_avg", m_ * icc1 / (1 + (m_ - 1) * icc1))
f4["h"] = f4.groupby("user_id").cumcount() % 2
hh = f4.pivot_table(index="user_id", columns="h", values="n", aggfunc="mean")
key("b1_split_half_corr_monthly_count", hh.corr().iloc[0, 1])
key("b1_split_half_users", len(hh))

section("B2/N1. No fading; churn follows a stable personal rate, not this month's dip")
q = panel[panel["age"] >= 3].copy()        # n_t, n_t-1, n_t-2 all full months
q["avg3"] = (q["n"] + q["prev_n"] + q["prev2_n"]) / 3
q["dev"] = np.log(q["n"]) - np.log(q["avg3"])
q["age_c"] = q["age"].clip(upper=9)
key("n1_panel_user_months", len(q))
m_lag = logit_cl("churn ~ np.log(n) + np.log(prev_n) + np.log(prev2_n) + C(age_c)", q)
for t_, nm in (("np.log(n)", "t"), ("np.log(prev_n)", "t1"), ("np.log(prev2_n)", "t2")):
    key(f"n1_coef_logn_{nm}", m_lag.params[t_])
    key(f"n1_coef_logn_{nm}_lo", m_lag.conf_int().loc[t_, 0])
    key(f"n1_coef_logn_{nm}_hi", m_lag.conf_int().loc[t_, 1])
key("n1_wald_p_t_eq_t1", float(m_lag.wald_test("np.log(n) = np.log(prev_n)", scalar=True).pvalue))
key("n1_wald_p_t_eq_t2", float(m_lag.wald_test("np.log(n) = np.log(prev2_n)", scalar=True).pvalue))
m_dev = logit_cl("churn ~ np.log(avg3) + dev + C(age_c)", q)
key("n1_coef_log_avg3", m_dev.params["np.log(avg3)"])
key("n1_p_log_avg3", m_dev.pvalues["np.log(avg3)"])
key("n1_coef_dev", m_dev.params["dev"])
key("n1_coef_dev_lo", m_dev.conf_int().loc["dev", 0])
key("n1_coef_dev_hi", m_dev.conf_int().loc["dev", 1])
key("n1_p_dev", m_dev.pvalues["dev"])
key("n1_auc_this_month", roc_auc_score(q["churn"], -q["n"]))
key("n1_auc_avg3", roc_auc_score(q["churn"], -q["avg3"]))
bands = lambda s: pd.cut(s, [0, 1, 2, 3, 4, 6, 100], labels=["<=1", "1-2", "2-3", "3-4", "4-6", "6+"])
ch_avg = q.groupby(bands(q["avg3"]), observed=True)["churn"].agg(user_months="size", churn="mean")
ch_cur = q.groupby(bands(q["n"]), observed=True)["churn"].agg(user_months="size", churn="mean")
save(pd.concat({"by_3m_avg": ch_avg, "by_this_month": ch_cur}).round(4), "n1_churn_by_avg3_vs_this_month")
key("n1_churn_avg3_le1", ch_avg.loc["<=1", "churn"])
key("n1_churn_avg3_6plus", ch_avg.loc["6+", "churn"])
key("n1_churn_this_month_le1", ch_cur.loc["<=1", "churn"])
key("n1_churn_this_month_6plus", ch_cur.loc["6+", "churn"])
q["nb"] = pd.cut(q["n"], [0, 1, 3, 100], labels=["this month 1", "this month 2-3", "this month 4+"])
q["ab"] = pd.cut(q["avg3"], [0, 2, 10 / 3, 100], labels=["3m avg <=2", "3m avg 2-3.3", "3m avg >3.3"])
xt = q.pivot_table(index="nb", columns="ab", values="churn", aggfunc=["mean", "size"], observed=True)
save(xt.round(4), "n1_churn_this_month_x_avg3")
mid = q[q["ab"] == "3m avg 2-3.3"].groupby("nb", observed=True)["churn"].agg(["sum", "size", "mean"])
for lab, nm in (("this month 1", "1"), ("this month 2-3", "2_3"), ("this month 4+", "4p")):
    key(f"n1_mid_avg_band_churn_{nm}", mid.loc[lab, "mean"])
    key(f"n1_mid_avg_band_n_{nm}", int(mid.loc[lab, "size"]))
# Within-user: churners' final month vs their own other full months; placebo = still-active users' Jun-25
fu = um_full.copy()
fu["is_last"] = fu.groupby("user_id")["mi"].transform("max") == fu["mi"]
u4 = users[users["n_months"] >= 4]


def paired(ids):
    g_ = fu[fu["user_id"].isin(ids)]
    last = g_[g_["is_last"]].set_index("user_id")["n"]
    oth = g_[~g_["is_last"]].groupby("user_id")["n"].mean()
    dlt = (last - oth).dropna()
    return dlt.mean(), 1.96 * dlt.std() / np.sqrt(len(dlt)), len(dlt), stats.wilcoxon(dlt).pvalue


m_, h_, n_, p_ = paired(u4[u4["last_mi"] < LAST].index)
key("n1_churners_last_minus_own_avg", m_); key("n1_churners_last_minus_own_avg_ci", h_)
key("n1_churners_paired_n", n_); key("n1_churners_paired_p", p_)
m_, h_, n_, p_ = paired(u4[u4["last_mi"] == LAST].index)
key("n1_placebo_last_minus_own_avg", m_); key("n1_placebo_paired_p", p_)
# B2 replication (ratio to own past average)
fd = panel.copy()
fd["own_avg"] = fd.groupby("user_id")["n"].transform(lambda x: x.shift().expanding().mean())
fd = fd[fd["age"] >= 2]
fd["rb"] = pd.cut(fd["n"] / fd["own_avg"], [0, 0.5, 0.8, 1.2, 2, 100], labels=["<50%", "50-80%", "80-120%", "120-200%", ">200%"])
fade = fd.groupby("rb", observed=True)["churn"].agg(["size", "mean"])
save(fade.round(4), "v_b2_churn_vs_own_usual")
key("b2_churn_below_half", fade.loc["<50%", "mean"])
key("b2_churn_80_120", fade.loc["80-120%", "mean"])

section("C1/N2. No loyal core: tenure has no effect once the personal rate is known")
key("c1_sbg_mean_churn", A_ / (A_ + B_))
key("c1_sbg_sd_churn", np.sqrt(A_ * B_ / ((A_ + B_) ** 2 * (A_ + B_ + 1))))
haz = full.groupby(pd.cut(full["age"], [0, 1, 2, 3, 5, 8, 17], labels=["M1", "M2", "M3", "M4-5", "M6-8", "M9+"]), observed=True)["churn"].mean()
key("c1_hazard_M1", haz.loc["M1"]); key("c1_hazard_M9plus", haz.loc["M9+"])
t0 = logit_cl("churn ~ age12", full.assign(age12=full["age"].clip(upper=12)))
t1 = logit_cl("churn ~ age12 + np.log(cum_avg)", full.assign(age12=full["age"].clip(upper=12)))
key("n2_age_coef_raw", t0.params["age12"]); key("n2_age_p_raw", t0.pvalues["age12"])
key("n2_age_coef_ctrl", t1.params["age12"]); key("n2_age_p_ctrl", t1.pvalues["age12"])
key("n2_age_coef_ctrl_lo", t1.conf_int().loc["age12", 0]); key("n2_age_coef_ctrl_hi", t1.conf_int().loc["age12", 1])
key("n2_logcum_coef", t1.params["np.log(cum_avg)"]); key("n2_logcum_p", t1.pvalues["np.log(cum_avg)"])
full["fb"] = pd.cut(full["cum_avg"], [0, 1.5, 2.5, 3.5, 5, 100], labels=["<=1.5", "1.5-2.5", "2.5-3.5", "3.5-5", "5+"])
full["ab"] = pd.cut(full["age"], [0, 1, 2, 3, 5, 8, 17], labels=["M1", "M2", "M3", "M4-5", "M6-8", "M9+"])
hz = full.pivot_table(index="fb", columns="ab", values="churn", aggfunc="mean", observed=True)
save(hz.round(4), "n2_churn_by_running_freq_x_tenure")
save(full.groupby("ab", observed=True)["cum_avg"].mean().round(3).to_frame(), "n2_running_freq_by_tenure")
key("n2_running_freq_M1", full[full["ab"] == "M1"]["cum_avg"].mean())
key("n2_running_freq_M9plus", full[full["ab"] == "M9+"]["cum_avg"].mean())
# Within-user trend of frequency with tenure (user fixed effects), full months, users with >=3 of them
ff = um_full[um_full["user_id"].isin(nm_full[nm_full >= 3].index)].copy()
ff["n_dm"] = ff["n"] - ff.groupby("user_id")["n"].transform("mean")
ff["a_dm"] = ff["age"] - ff.groupby("user_id")["age"].transform("mean")
fe = smf.ols("n_dm ~ a_dm - 1", data=ff).fit(cov_type="cluster", cov_kwds={"groups": ff["user_id"]})
key("n2_within_user_freq_slope_per_month", fe.params["a_dm"])
key("n2_within_user_freq_slope_ci_lo", fe.conf_int().loc["a_dm", 0])
key("n2_within_user_freq_slope_ci_hi", fe.conf_int().loc["a_dm", 1])
key("n2_ticket_vs_age_spearman", stats.spearmanr(d["age"], d["trxn_amount"])[0])
key("n2_ticket_vs_age_p", stats.spearmanr(d["age"], d["trxn_amount"])[1])
pk_age = pd.crosstab(d["age"].clip(upper=9), d["package_code"], normalize="index")
save(pk_age.round(4), "n2_category_mix_by_tenure")
key("n2_category_mix_max_dev_pp_by_tenure", (pk_age - d["package_code"].value_counts(normalize=True)).abs().max().max() * 100)
key("n2_category_mix_chi2_p_by_tenure_naive", stats.chi2_contingency(pd.crosstab(d["age"].clip(upper=9), d["package_code"]))[1])
# naive chi2 ignores clustering by user (personal mixes + survivor selection); permute tenure labels WITHIN user
rng = np.random.default_rng(7)
pk_codes = d["package_code"].astype("category").cat.codes.values
age_c9 = d["age"].clip(upper=9).values
uid = d["user_id"].values
order = np.argsort(uid, kind="stable")
bounds = np.flatnonzero(np.r_[True, uid[order][1:] != uid[order][:-1], True])


def chi2_stat(ages):
    tab = pd.crosstab(ages, pk_codes).values
    return stats.chi2_contingency(tab)[0]


obs_chi = chi2_stat(age_c9)
perm = []
for _ in range(200):
    a_perm = age_c9.copy()
    for i in range(len(bounds) - 1):
        idx = order[bounds[i]:bounds[i + 1]]
        if len(idx) > 1:
            a_perm[idx] = rng.permutation(a_perm[idx])
    perm.append(chi2_stat(a_perm))
key("n2_category_mix_within_user_perm_p", (1 + np.sum(np.array(perm) >= obs_chi)) / 201)

section("N3. Value = tenure x frequency; ticket size is not a user trait")
x5 = d[d["user_id"].isin(users[users["n_txn"] >= 5].index)].copy()
x5["la"] = np.log(x5["trxn_amount"])
g = x5.groupby("user_id")["la"]
kk = g.size(); N, a = len(x5), len(kk)
msb = (kk * (g.mean() - x5["la"].mean()) ** 2).sum() / (a - 1)
msw = ((x5["la"] - g.transform("mean")) ** 2).sum() / (N - a)
n0_ = (N - (kk ** 2).sum() / N) / (a - 1)
key("n3_ticket_icc", (msb - msw) / (msb + (n0_ - 1) * msw))
key("n3_ticket_anova_F", msb / msw)
key("n3_ticket_anova_p", stats.f.sf(msb / msw, a - 1, N - a))
x5["h"] = x5.groupby("user_id").cumcount() % 2
hh = x5.pivot_table(index="user_id", columns="h", values="la", aggfunc="mean")
key("n3_ticket_split_half_corr", hh.corr().iloc[0, 1])
c = cu.copy()
c["lm"] = np.log(c["n_months"]); c["lf"] = np.log(c["n_txn"] / c["n_months"])
c["lt"] = np.log(c["gmv"] / c["n_txn"]); c["lg"] = np.log(c["gmv"])
for comp, nm in (("lm", "months"), ("lf", "freq"), ("lt", "ticket")):
    key(f"n3_var_share_{nm}", np.cov(c[comp], c["lg"])[0, 1] / c["lg"].var())
top = c["gmv"] >= c["gmv"].quantile(0.9)
key("n3_top10_months", c[top]["n_months"].mean()); key("n3_rest_months", c[~top]["n_months"].mean())
key("n3_top10_freq", (c[top]["n_txn"] / c[top]["n_months"]).mean()); key("n3_rest_freq", (c[~top]["n_txn"] / c[~top]["n_months"]).mean())
key("n3_top10_ticket_k", (c[top]["gmv"] / c[top]["n_txn"]).mean() / 1e3); key("n3_rest_ticket_k", (c[~top]["gmv"] / c[~top]["n_txn"]).mean() / 1e3)
key("n3_top10_limit_m", c[top]["limit"].mean() / 1e6); key("n3_rest_limit_m", c[~top]["limit"].mean() / 1e6)
# Monetary vs frequency at user-month level
key("n3_corr_month_gmv_vs_n", stats.pearsonr(um["gmv"], um["n"])[0])

section("N4. Early value: the first full month predicts future value; first-purchase attributes don't")
u12 = users[users["cohort"] <= LAST - 11].copy()
fr = d[d["pos"] == 0].set_index("user_id")
u12["first_amt"] = fr["trxn_amount"]; u12["first_pkg"] = fr["package_code"]; u12["first_car"] = fr["carrier"]
u12["llim"] = np.log(u12["limit"])
u12["n1"] = um[um["age"] == 1].set_index("user_id")["n"].reindex(u12.index).fillna(0)
u12["jb"] = pd.cut(u12["join_day"], [0, 3, 10, 20, 31]).astype(str)
fut = um[(um["age"] >= 2) & (um["age"] <= 11)].groupby("user_id").agg(g_fut=("gmv", "sum"), m_fut=("n", "size"))
u12 = u12.join(fut).fillna({"g_fut": 0, "m_fut": 0})
ret1 = u12[u12["n1"] > 0].copy()            # users still active in M1; predict months 2-11
key("n4_users_active_m1_cohorts_le_jun24", len(ret1))
r_fp = smf.ols("np.log1p(g_fut) ~ np.log(first_amt) + C(first_pkg) + llim + C(jb)", data=ret1).fit()
r_ct = smf.ols("np.log1p(g_fut) ~ C(n0.clip(upper=8)) + C(n1.clip(upper=8))", data=ret1).fit()
r_fp_m = smf.ols("m_fut ~ np.log(first_amt) + C(first_pkg) + llim + C(jb)", data=ret1).fit()
r_ct_m = smf.ols("m_fut ~ C(n0.clip(upper=8)) + C(n1.clip(upper=8))", data=ret1).fit()
key("n4_r2_first_purchase_attrs_future_gmv", r_fp.rsquared)
key("n4_r2_m0_m1_counts_future_gmv", r_ct.rsquared)
key("n4_r2_first_purchase_attrs_future_months", r_fp_m.rsquared)
key("n4_r2_m0_m1_counts_future_months", r_ct_m.rsquared)
key("n4_p_first_amt_future_months", r_fp_m.pvalues["np.log(first_amt)"])
key("n4_p_limit_future_months", r_fp_m.pvalues["llim"])
pk_terms = [t_ for t_ in r_fp_m.params.index if t_.startswith("C(first_pkg)")]
key("n4_p_first_pkg_future_months", float(r_fp_m.f_test(", ".join(f"{t_} = 0" for t_ in pk_terms)).pvalue))
ev = ret1.groupby(pd.cut(ret1["n1"], [0, 1, 3, 100], labels=["M1: 1 txn", "M1: 2-3", "M1: 4+"]), observed=True).agg(
    users=("g_fut", "size"), future_gmv_m2_m11=("g_fut", "mean"), future_active_months=("m_fut", "mean"))
save(ev.round(1), "n4_future_value_by_m1_frequency")
key("n4_future_gmv_m1_1txn_k", ev.loc["M1: 1 txn", "future_gmv_m2_m11"] / 1e3)
key("n4_future_gmv_m1_4p_k", ev.loc["M1: 4+", "future_gmv_m2_m11"] / 1e3)
key("n4_future_months_m1_1txn", ev.loc["M1: 1 txn", "future_active_months"])
key("n4_future_months_m1_4p", ev.loc["M1: 4+", "future_active_months"])
key("n4_share_m1_1txn", ev.loc["M1: 1 txn", "users"] / ev["users"].sum())
key("n4_share_m1_4p", ev.loc["M1: 4+", "users"] / ev["users"].sum())

section("B3/B4/N5. Within-month timing: purchases fall uniformly; 'join day' is the earliest of them")
# day-of-month of the first purchase of a month, M0 vs continuing months, by count
rows = []
for n_ in (1, 2, 3, 4, 5, 6):
    a0 = um[(um["age"] == 0) & (um["n"] == n_)]["first_dom"]
    a1 = um[(um["age"] >= 1) & (um["n"] == n_)]["first_dom"]
    rows.append(dict(n=n_, m0_mean_first_day=a0.mean(), continuing_mean_first_day=a1.mean(),
                     uniform_expectation=float(np.mean(31 / (n_ + 1))), ks_p=stats.ks_2samp(a0, a1).pvalue,
                     m0_months=len(a0), continuing_months=len(a1)))
fdt = pd.DataFrame(rows).set_index("n")
save(fdt.round(4), "n5_first_day_m0_vs_continuing")
key("n5_ks_p_min", fdt["ks_p"].min())
m0 = um[um["age"] == 0]
cont = um[um["age"] >= 1]
key("n5_join_day_le3_obs", (m0["first_dom"] <= 3).mean())
key("n5_join_day_le3_exp_min_uniform", (1 - (1 - 3 / m0["dim"]) ** m0["n"]).mean())
key("n5_join_day_le15_obs", (m0["first_dom"] <= 15).mean())
key("n5_join_day_le15_exp_min_uniform", (1 - (1 - 15 / m0["dim"]) ** m0["n"]).mean())
key("n5_cont_first_day_le3_obs", (cont["first_dom"] <= 3).mean())
key("n5_cont_first_day_le3_exp", (1 - (1 - 3 / cont["dim"]) ** cont["n"]).mean())
both = um[um["age"] <= 1].pivot_table(index="user_id", columns="age", values="n").dropna()
key("n5_mean_n0_users_active_m0_m1", both[0].mean())
key("n5_mean_n1_users_active_m0_m1", both[1].mean())
key("n5_paired_p_n0_vs_n1", stats.ttest_rel(both[0], both[1]).pvalue)
late = users.loc[both.index, "join_day"] > 20
key("n5_late_joiners_mean_n0", both[late][0].mean()); key("n5_late_joiners_mean_n1", both[late][1].mean())
key("n5_early_joiners_mean_n0", both[~late][0].mean()); key("n5_early_joiners_mean_n1", both[~late][1].mean())
# distinct purchase days vs uniform-random expectation (same-day 'bursts')
u2 = d[d["age"] >= 1].groupby(["user_id", "mi"]).agg(n=("dom", "size"), nd=("dom", "nunique"), dim=("dim", "first"))
u2["exp_nd"] = u2["dim"] * (1 - (1 - 1 / u2["dim"]) ** u2["n"])
key("n5_same_day_obs_extra_txns", (u2["n"] - u2["nd"]).sum())
key("n5_same_day_exp_extra_txns", (u2["n"] - u2["exp_nd"]).sum())
key("n5_same_day_user_day_share", (d.groupby(["user_id", "trxn_date"]).size() >= 2).mean())
# Join day and churn: raw vs controlling for M0 count and running frequency
fj = full.join(users[["join_day", "n0"]], on="user_id")
fj["jmid"] = fj["join_day"].between(11, 20).astype(int); fj["jlate"] = (fj["join_day"] > 20).astype(int)
j0 = logit_cl("churn ~ jmid + jlate + C(age_c)", fj)
j1 = logit_cl("churn ~ jmid + jlate + np.log(cum_avg) + np.log(n0) + C(age_c)", fj)
key("n5_join_late_coef_raw", j0.params["jlate"]); key("n5_join_late_p_raw", j0.pvalues["jlate"])
key("n5_join_late_coef_ctrl", j1.params["jlate"]); key("n5_join_late_p_ctrl", j1.pvalues["jlate"])
key("n5_join_joint_p_ctrl", float(j1.wald_test("jmid = 0, jlate = 0", scalar=True).pvalue))
hz_j = fj[fj["age"].between(1, 3)].groupby(pd.cut(fj["join_day"], [0, 10, 20, 31]), observed=True)["churn"].mean()
key("n5_churn_M1_M3_join_le10", hz_j.iloc[0]); key("n5_churn_M1_M3_join_gt20", hz_j.iloc[2])
ue = users[users["cohort"] < LAST].copy()
ue["jmid"] = ue["join_day"].between(11, 20).astype(int); ue["jlate"] = (ue["join_day"] > 20).astype(int)
ue["m1i"] = ue["m1"].astype(int)
mm0 = smf.logit("m1i ~ jmid + jlate + C(cohort)", data=ue).fit(disp=0)
mm1 = smf.logit("m1i ~ jmid + jlate + C(n0.clip(upper=8)) + C(cohort)", data=ue).fit(disp=0)
key("n5_m1_join_late_coef_raw", mm0.params["jlate"]); key("n5_m1_join_late_p_raw", mm0.pvalues["jlate"])
key("n5_m1_join_late_coef_ctrl_n0", mm1.params["jlate"]); key("n5_m1_join_late_p_ctrl_n0", mm1.pvalues["jlate"])
key("n5_m1_join_joint_p_ctrl_n0", float(mm1.wald_test("jmid = 0, jlate = 0", scalar=True).pvalue))
key("n5_share_n0_ge4_join_le15", (ue[ue["join_day"] <= 15]["n0"] >= 4).mean())
key("n5_share_n0_ge4_join_gt15", (ue[ue["join_day"] > 15]["n0"] >= 4).mean())
key("n5_mean_n0_join_le3", ue[ue["join_day"] <= 3]["n0"].mean())
key("n5_mean_n0_all", ue["n0"].mean())
# 30-59-day window (B3) by join day within the same M0 count
last_date = d["trxn_date"].max()
mat = users[users["first_date"] <= last_date - pd.Timedelta(days=59)].copy()
act = set(d[d["user_id"].isin(mat.index) & d["dsf"].between(30, 59)]["user_id"])
mat["r"] = mat.index.isin(act)
w = mat.pivot_table(index=mat["n0"].clip(upper=4), columns=pd.cut(mat["join_day"], [0, 3, 10, 20, 31]), values="r", aggfunc="mean", observed=True)
save(w.round(4), "v_b3_active_30_59_by_join_day_x_n0")
key("b3_r3059_join_le3", mat[mat["join_day"] <= 3]["r"].mean())
key("b3_r3059_join_gt20", mat[mat["join_day"] > 20]["r"].mean())
key("b3_r3059_n0eq1_join_le3", w.iloc[0, 0]); key("b3_r3059_n0eq1_join_gt20", w.iloc[0, 3])
# B3: churn vs day of the last purchase, given the count
lp = logit_cl("churn ~ last_dom + C(nb) + C(age_c)", panel.assign(nb=panel["n"].clip(upper=6), age_c=panel["age"].clip(upper=9)))
key("b3_last_day_coef", lp.params["last_dom"]); key("b3_last_day_p", lp.pvalues["last_dom"])
# B4: second purchase timing (users with 60 days follow-up)
sec = d[d["pos"] == 1].set_index("user_id")["dsf"].reindex(mat.index)
for dd_ in (7, 14, 30):
    key(f"b4_second_within_{dd_}d_all_new", (sec < dd_).mean())
key("b4_median_gap_to_second_among_who_do", sec.dropna().median())

section("N6. Silence trigger personalised by the user's usual frequency")
nxt = um[["user_id", "mi", "first_dom"]].copy()
nxt["mi"] -= 1
pp = panel.merge(nxt.rename(columns={"first_dom": "fd_next"}), on=["user_id", "mi"], how="left")
pp["avg3"] = pp.groupby("user_id")["n"].transform(lambda s: s.rolling(3, min_periods=1).mean())
pp["band"] = pd.cut(pp["avg3"], [0, 1.5, 3, 5, 100], labels=["avg <=1.5", "avg 1.5-3", "avg 3-5", "avg >5"])
rows = []
for b, g_ in pp.groupby("band", observed=True):
    for day in (5, 7, 10, 12, 15, 20):
        sil = g_[g_["fd_next"].isna() | (g_["fd_next"] > day)]
        lo, hi = wilson(sil["fd_next"].isna().sum(), len(sil))
        rows.append(dict(band=b, day=day, user_months=len(g_), share_silent=len(sil) / len(g_),
                         p_lost=sil["fd_next"].isna().mean(), ci_lo=lo, ci_hi=hi, avg_gmv=g_["gmv"].mean()))
for day in (10, 15):
    sil = pp[pp["fd_next"].isna() | (pp["fd_next"] > day)]
    rows.append(dict(band="all", day=day, user_months=len(pp), share_silent=len(sil) / len(pp), p_lost=sil["fd_next"].isna().mean(),
                     ci_lo=wilson(sil["fd_next"].isna().sum(), len(sil))[0], ci_hi=wilson(sil["fd_next"].isna().sum(), len(sil))[1],
                     avg_gmv=pp["gmv"].mean()))
sl = pd.DataFrame(rows)
save(sl.round(4), "n6_silence_precision_by_band")
gt = lambda b, day, col: float(sl[(sl["band"] == b) & (sl["day"] == day)][col].iloc[0])
key("n6_all_day15_p_lost", gt("all", 15, "p_lost"))
key("n6_all_day10_p_lost", gt("all", 10, "p_lost"))
key("n6_heavy_day10_p_lost", gt("avg >5", 10, "p_lost"))
key("n6_heavy_day10_ci_lo", gt("avg >5", 10, "ci_lo")); key("n6_heavy_day10_ci_hi", gt("avg >5", 10, "ci_hi"))
key("n6_heavy_day12_p_lost", gt("avg >5", 12, "p_lost"))
key("n6_heavy_day15_p_lost", gt("avg >5", 15, "p_lost"))
key("n6_light_day15_p_lost", gt("avg <=1.5", 15, "p_lost"))
key("n6_light_day20_p_lost", gt("avg <=1.5", 20, "p_lost"))
key("n6_mid_day15_p_lost", gt("avg 1.5-3", 15, "p_lost"))
key("n6_heavy_share_silent_day10", gt("avg >5", 10, "share_silent"))
key("n6_heavy_avg_gmv_k", gt("avg >5", 10, "avg_gmv") / 1e3)
key("n6_light_avg_gmv_k", gt("avg <=1.5", 10, "avg_gmv") / 1e3)
# Heavy users in the current base
cur = um[um["mi"] == LAST].copy()
cur["avg3"] = um[um["mi"] >= LAST - 2].groupby("user_id")["n"].mean().reindex(cur["user_id"]).values  # avg over active months in last 3
key("n6_heavy_avg_gt5_users_jun25", int((cur["avg3"] > 5).sum()))

# GMV at risk: churn events weighted by the churner's recent monthly GMV (3-month average)
pp["gmv3"] = pp.groupby("user_id")["gmv"].transform(lambda s_: s_.rolling(3, min_periods=1).mean())
ce = pp[pp["churn"] == 1]
risk = pd.DataFrame({"share_of_churners": ce["band"].value_counts(normalize=True),
                     "share_of_churned_gmv": ce.groupby("band", observed=True)["gmv3"].sum() / ce["gmv3"].sum(),
                     "churn_rate": pp.groupby("band", observed=True)["churn"].mean(),
                     "share_of_active": pp["band"].value_counts(normalize=True)})
save(risk.round(4), "n6_gmv_at_risk_by_band")
key("n6_heavy5_share_churners", risk.loc["avg >5", "share_of_churners"])
key("n6_heavy5_share_churned_gmv", risk.loc["avg >5", "share_of_churned_gmv"])
key("n6_light_share_churners", risk.loc["avg <=1.5", "share_of_churners"])
key("n6_light_share_churned_gmv", risk.loc["avg <=1.5", "share_of_churned_gmv"])
key("n6_3to5_share_churned_gmv", risk.loc["avg 3-5", "share_of_churned_gmv"])
key("n6_3to5_share_churners", risk.loc["avg 3-5", "share_of_churners"])

# Remaining value by band. N2 shows hazard is flat in tenure within a frequency band, so a geometric
# lifetime per band is a fair first approximation: expected future GMV after this month = gmv * (1-c)/c.
hist_c = pp.groupby("band", observed=True)["churn"].agg(["sum", "size", "mean"])
hist_g = pp[pp["mi"] >= LAST - 6].groupby("band", observed=True)["gmv3"].mean()
cb_ = um[um["mi"] == LAST][["user_id", "n", "gmv"]].copy()
last3 = um[um["mi"] >= LAST - 2]
cb_["avg3"] = last3.groupby("user_id")["n"].mean().reindex(cb_["user_id"]).values
cb_["band"] = pd.cut(cb_["avg3"], [0, 1.5, 3, 5, 100], labels=["avg <=1.5", "avg 1.5-3", "avg 3-5", "avg >5"])
rv = pd.DataFrame({"users_jun25": cb_["band"].value_counts(), "hist_monthly_churn": hist_c["mean"],
                   "churn_ci_lo": [wilson(r["sum"], r["size"])[0] for _, r in hist_c.iterrows()],
                   "churn_ci_hi": [wilson(r["sum"], r["size"])[1] for _, r in hist_c.iterrows()],
                   "recent_monthly_gmv": hist_g})
rv["expected_future_months"] = (1 - rv["hist_monthly_churn"]) / rv["hist_monthly_churn"]
rv["expected_future_gmv"] = rv["recent_monthly_gmv"] * rv["expected_future_months"]
rv["share_of_base"] = rv["users_jun25"] / rv["users_jun25"].sum()
rv["share_of_future_gmv"] = rv["users_jun25"] * rv["expected_future_gmv"] / (rv["users_jun25"] * rv["expected_future_gmv"]).sum()
save(rv.round(4), "n6_remaining_value_by_band_jun25")
print(rv)
key("n6b_future_gmv_heavy5_m", rv.loc["avg >5", "expected_future_gmv"] / 1e6)
key("n6b_future_gmv_light_m", rv.loc["avg <=1.5", "expected_future_gmv"] / 1e6)
key("n6b_future_gmv_ratio_heavy_light", rv.loc["avg >5", "expected_future_gmv"] / rv.loc["avg <=1.5", "expected_future_gmv"])
key("n6b_heavy5_share_base", rv.loc["avg >5", "share_of_base"]); key("n6b_heavy5_share_future_gmv", rv.loc["avg >5", "share_of_future_gmv"])
key("n6b_3to5_share_base", rv.loc["avg 3-5", "share_of_base"]); key("n6b_3to5_share_future_gmv", rv.loc["avg 3-5", "share_of_future_gmv"])
key("n6b_light_share_base", rv.loc["avg <=1.5", "share_of_base"]); key("n6b_light_share_future_gmv", rv.loc["avg <=1.5", "share_of_future_gmv"])
key("n6b_heavy5_users_jun25", int(rv.loc["avg >5", "users_jun25"]))
for b_ in rv.index:
    key(f"n6b_churn_{b_.replace(' ', '').replace('<=', 'le').replace('.', 'p').replace('-', '_').replace('+', 'plus')}", rv.loc[b_, "hist_monthly_churn"])
# Out-of-sample check of the geometric lifetime: Dec-24 active users, predicted vs realised GMV Jan-Jun 25 by band
dec_ = pp[pp["mi"] == 2024 * 12 + 11][["user_id", "band", "gmv3"]]
real = um[(um["mi"] > 2024 * 12 + 11)].groupby("user_id")["gmv"].sum()
dec_["real6"] = dec_["user_id"].map(real).fillna(0)
hc_tr = pp[pp["mi"] < 2024 * 12 + 11].groupby("band", observed=True)["churn"].mean()
cc = dec_["band"].map(hc_tr).astype(float)
dec_["pred6"] = dec_["gmv3"] * sum((1 - cc) ** k for k in range(1, 7))
oos = dec_.groupby("band", observed=True)[["pred6", "real6"]].mean()
save(oos.round(0), "n6_geometric_value_out_of_time_check")
print(oos)
key("n6b_oot_pred_real_ratio_heavy5", oos.loc["avg >5", "pred6"] / oos.loc["avg >5", "real6"])
key("n6b_oot_pred_real_ratio_light", oos.loc["avg <=1.5", "pred6"] / oos.loc["avg <=1.5", "real6"])
key("n6b_oot_pred_real_ratio_all", dec_["pred6"].sum() / dec_["real6"].sum())
# Model-free: realised Jan-Jun 25 GMV per Dec-24 active user, by Dec-24 band
real_t = dec_.groupby("band", observed=True).agg(users=("real6", "size"), realised_gmv_next6m=("real6", "mean"),
                                                 total=("real6", "sum"))
real_t["share_of_users"] = real_t["users"] / real_t["users"].sum()
real_t["share_of_next6m_gmv"] = real_t["total"] / real_t["total"].sum()
save(real_t.round(4), "n6_realised_next6m_gmv_by_dec24_band")
print(real_t)
for b_, nm in (("avg <=1.5", "light"), ("avg 1.5-3", "b15_3"), ("avg 3-5", "b3_5"), ("avg >5", "heavy")):
    key(f"n6c_realised6m_gmv_{nm}_m", real_t.loc[b_, "realised_gmv_next6m"] / 1e6)
    key(f"n6c_share_users_{nm}", real_t.loc[b_, "share_of_users"])
    key(f"n6c_share_next6m_gmv_{nm}", real_t.loc[b_, "share_of_next6m_gmv"])
key("n6c_ratio_heavy_light", real_t.loc["avg >5", "realised_gmv_next6m"] / real_t.loc["avg <=1.5", "realised_gmv_next6m"])

section("N7. Credit field: repayment is a user-independent coin flip; limits not enforced")
s = d[d["prev_out"].notna()].copy()
s["rep"] = s["repay"] > 0
s["cap_touch"] = (s["total_outstanding"] >= s["total_limit"]) | (s["pre"] >= s["total_limit"])
key("n7_rows_touching_cap", int(s["cap_touch"].sum()))
cr = s[~s["cap_touch"]].copy()
key("n7_repay_rate_excl_cap", cr["rep"].mean())
grp = {
    "gap_days": cr["gap"].clip(upper=30),
    "day_of_month": pd.cut(cr["dom"], [0, 5, 10, 15, 20, 25, 31]),
    "weekday": cr["trxn_date"].dt.dayofweek,
    "tenure_month": cr["age"].clip(upper=12),
    "limit_band": pd.cut(cr["total_limit"], [0, 1e6, 2e6, 4e6, 6e6, 8e6, 1e7]),
    "util_before_decile": pd.qcut(cr["prev_out"] / cr["total_limit"], 10, duplicates="drop"),
    "amount_decile": pd.qcut(cr["trxn_amount"], 10, duplicates="drop"),
    "calendar_month": cr["mi"],
}
rr = []
for nm, gg in grp.items():
    t_ = cr.groupby(gg, observed=True)["rep"].agg(["sum", "size"])
    chi = stats.chi2_contingency(np.c_[t_["sum"], t_["size"] - t_["sum"]])
    rr.append(dict(variable=nm, min_rate=(t_["sum"] / t_["size"]).min(), max_rate=(t_["sum"] / t_["size"]).max(), chi2_p=chi[1], groups=len(t_)))
rr = pd.DataFrame(rr).set_index("variable")
save(rr.round(4), "n7_repay_rate_independence")
key("n7_repay_indep_min_p", rr["chi2_p"].min())
key("n7_repay_rate_range_lo", rr["min_rate"].min()); key("n7_repay_rate_range_hi", rr["max_rate"].max())
gu = cr.groupby("user_id")["rep"].agg(["sum", "size"])
gu = gu[gu["size"] >= 10]
pbar = gu["sum"].sum() / gu["size"].sum()
chi = ((gu["sum"] - gu["size"] * pbar) ** 2 / (gu["size"] * pbar * (1 - pbar))).sum()
key("n7_user_dispersion_ratio", chi / (len(gu) - 1)); key("n7_user_dispersion_p", stats.chi2.sf(chi, len(gu) - 1))
key("n7_user_dispersion_users", len(gu))
cr["rep_prev"] = cr.groupby("user_id")["rep"].shift()
x_ = cr.dropna(subset=["rep_prev"])
key("n7_p_repay_after_repay", x_[x_["rep_prev"] == True]["rep"].mean())
key("n7_p_repay_after_none", x_[x_["rep_prev"] == False]["rep"].mean())
rp = cr[cr["rep"]]
frac = rp["repay"] / rp["pre"]
key("n7_repaid_frac_min", frac.min()); key("n7_repaid_frac_max", frac.max())
key("n7_repaid_frac_ks_uniform_0p3_1_p", stats.kstest((frac - 0.3) / 0.7, "uniform").pvalue)
first = d[d["prev_out"].isna()]
key("n7_first_txn_out_below_amount", (first["total_outstanding"] < first["trxn_amount"]).mean())
key("n7_first_txn_out_ratio_max", (first["total_outstanding"] / first["trxn_amount"]).max())
key("n7_full_payoff_events", int((s["total_outstanding"] == 0).sum()))
# never-repayers vs chance
d["rep_any"] = np.where(d["prev_out"].isna(), d["total_outstanding"] < d["trxn_amount"], d["repay"] > 0)
p_any = d["rep_any"].mean()
nr = ~d.groupby("user_id")["rep_any"].any()
key("n7_never_repay_users_obs", int(nr.sum()))
key("n7_never_repay_users_exp", ((1 - p_any) ** users["n_txn"]).sum())
# limit enforcement
s["headroom"] = s["total_limit"] - s["prev_out"]
key("n7_purchases_over_headroom", int((s["trxn_amount"] > s["headroom"]).sum()))
key("n7_purchases_over_headroom_share", (s["trxn_amount"] > s["headroom"]).mean())
key("n7_purchases_at_zero_headroom", int((s["headroom"] <= 0).sum()))
key("n7_amount_at_zero_headroom_k", s[s["headroom"] <= 0]["trxn_amount"].mean() / 1e3)
key("n7_amount_headroom_gt1m_k", s[s["headroom"] > 1e6]["trxn_amount"].mean() / 1e3)
fm = um_full.groupby("user_id")["n"].mean()
key("n7_spearman_limit_vs_freq", stats.spearmanr(users["limit"], fm.reindex(users.index), nan_policy="omit")[0])
key("n7_spearman_limit_vs_freq_p", stats.spearmanr(users["limit"], fm.reindex(users.index), nan_policy="omit")[1])
# balance after the last purchase vs lifetime purchases (random-walk saturation)
lt = d.groupby("user_id").tail(1).set_index("user_id")
chm = users["last_mi"] < LAST
bal = lt[chm].groupby(pd.cut(users[chm]["n_txn"], [0, 1, 4, 9, 19, 1000]), observed=True)["total_outstanding"].mean()
save((bal / 1e3).round(0).to_frame("balance_after_last_purchase_k"), "n7_balance_at_exit_by_lifetime_txns")
key("n7_balance_exit_1txn_k", bal.iloc[0] / 1e3); key("n7_balance_exit_20plus_k", bal.iloc[-1] / 1e3)
key("n7_churner_total_balance_bn", lt[chm]["total_outstanding"].sum() / 1e9)
key("n7_churner_median_util_at_exit", (lt[chm]["total_outstanding"] / lt[chm]["total_limit"]).median())
key("n7_month_end_balance_positive_share", (um["out_end"] > 0).mean())

section("E1/E3/E4/E5 verification")
key("e1_avg_limit_m", users["limit"].mean() / 1e6)
key("e1_median_util_month_end", um["util_end"].median())
key("e1_share_um_util_gt80", (um["util_end"] > 0.8).mean())
key("e1_avg_monthly_gmv_k", um["gmv"].mean() / 1e3)
peak = d[d["mi"] == LAST].groupby("user_id")["util"].max()
cur = cur.set_index("user_id")
cur["peak"] = peak
hungry = cur[cur["peak"] >= 0.8]
key("e3_hungry_users", len(hungry)); key("e3_hungry_avg_limit_m", hungry["limit"].mean() / 1e6)
key("e3_hungry_avg_txn", hungry["n"].mean()); key("e3_all_avg_txn", cur["n"].mean())
# E3 counterfactual: same frequency, same limit, balances re-simulated under the coin-flip process ->
# how many would be 'hungry' by chance? Compare small-limit users' frequency to large-limit users'.
sm = cur[cur["limit"] <= 2e6]
key("e3_small_limit_users_jun25", len(sm))
key("e3_small_limit_avg_txn_jun25", sm["n"].mean())
key("e3_large_limit_avg_txn_jun25", cur[cur["limit"] > 2e6]["n"].mean())
# E4 replication
rpm = d[d["prev_out"].notna()].groupby(["user_id", "mi"])["repay"].apply(lambda x: (x > 0).any()).rename("any_repay").reset_index()
e4 = panel.merge(rpm, on=["user_id", "mi"])
e4 = e4.assign(any_repay=e4["any_repay"].astype(int), Nb=e4["n"].clip(upper=6).astype(str),
               Pb=e4["prev_n"].fillna(0).clip(upper=4).astype(int).astype(str), Ab=e4["age"].clip(lower=1, upper=6).astype(str))
m_e4 = logit_cl("churn ~ C(Nb) + C(Pb) + C(Ab) + any_repay", e4)
key("e4_raw_churn_no_repay", e4[e4["any_repay"] == 0]["churn"].mean())
key("e4_raw_churn_repay", e4[e4["any_repay"] == 1]["churn"].mean())
key("e4_coef", m_e4.params["any_repay"]); key("e4_p", m_e4.pvalues["any_repay"])
# E5 replication
mx = d.groupby(["user_id", "mi"])["trxn_amount"].max().rename("max_amt").reset_index()
e5 = panel.merge(mx, on=["user_id", "mi"])
e5 = e5.assign(Nb=e5["n"].clip(upper=6).astype(str), Pb=e5["prev_n"].fillna(0).clip(upper=4).astype(int).astype(str),
               Ab=e5["age"].clip(lower=1, upper=6).astype(str))
e5["big50"] = (e5["max_amt"] / e5["limit"] >= 0.5).astype(int)
m_e5 = logit_cl("churn ~ C(Nb) + C(Pb) + C(Ab) + big50", e5)
key("e5_big50_share_um", e5["big50"].mean())
key("e5_big50_coef", m_e5.params["big50"]); key("e5_big50_p", m_e5.pvalues["big50"])
key("e5_big50_share_limit_le1m", (e5[e5["big50"] == 1]["limit"] <= 1e6).mean())

section("D1/D2/N8. Categories: a fixed personal mix with no sequence and no churn link")
dom_ = d.groupby(["user_id", "package_code"]).size().groupby(level=0).max() / d.groupby("user_id").size()
key("d1_home_share_median_5plus", dom_[users["n_txn"] >= 5].median())
upk = d.groupby("user_id")["package_code"].nunique()
key("d1_distinct_pkg_n5", upk[users["n_txn"] == 5].mean()); key("d1_distinct_pkg_n10", upk[users["n_txn"] == 10].mean())
# Breadth in first 30 days within purchase-count band (D1)
mt = d[d["user_id"].isin(mat.index)]
a30 = mt[mt["dsf"] < 30].groupby("user_id").agg(n=("txn_seq", "size"), car=("carrier", "nunique"))
a30 = a30[a30["n"] >= 2].assign(active=lambda x: x.index.isin(act), multi=lambda x: (x["car"] >= 2).astype(int),
                                 band=lambda x: pd.cut(x["n"], [1, 2, 3, 5, 1000], labels=["2", "3", "4-5", "6+"]).astype(str),
                                 user_id=lambda x: x.index)
a30["active"] = a30["active"].astype(int)
key("d1_breadth_raw_gap_pp", (a30[a30["multi"] == 1]["active"].mean() - a30[a30["multi"] == 0]["active"].mean()) * 100)
br = smf.ols("active ~ multi + C(band)", data=a30).fit(cov_type="HC1")
key("d1_breadth_adj_gap_pp", br.params["multi"] * 100)
key("d1_breadth_adj_ci_lo_pp", br.conf_int().loc["multi", 0] * 100); key("d1_breadth_adj_ci_hi_pp", br.conf_int().loc["multi", 1] * 100)
key("d1_breadth_adj_p", br.pvalues["multi"])
br2 = smf.ols("active ~ multi + C(n.clip(upper=12))", data=a30).fit(cov_type="HC1")
key("d1_breadth_adj_exact_n_gap_pp", br2.params["multi"] * 100); key("d1_breadth_adj_exact_n_p", br2.pvalues["multi"])
# Sequence dependence: P(next category = previous) vs user's own mix
xs = d.copy()
xs["prev_pkg"] = xs.groupby("user_id")["package_code"].shift()
xs["prev_car"] = xs.groupby("user_id")["carrier"].shift()
xs = xs[xs["prev_pkg"].notna() & xs["user_id"].isin(users[users["n_txn"] >= 6].index)]
cpk = d.groupby(["user_id", "package_code"]).size()
ccr = d.groupby(["user_id", "carrier"]).size()
xs["N"] = users["n_txn"].reindex(xs["user_id"]).values
xs["e_pkg"] = (cpk.reindex(pd.MultiIndex.from_arrays([xs["user_id"], xs["prev_pkg"]])).values - 1) / (xs["N"] - 1)
xs["e_car"] = (ccr.reindex(pd.MultiIndex.from_arrays([xs["user_id"], xs["prev_car"]])).values - 1) / (xs["N"] - 1)
key("n8_same_pkg_as_prev_obs", (xs["package_code"] == xs["prev_pkg"]).mean())
key("n8_same_pkg_as_prev_exp", xs["e_pkg"].mean())
key("n8_same_car_as_prev_obs", (xs["carrier"] == xs["prev_car"]).mean())
key("n8_same_car_as_prev_exp", xs["e_car"].mean())
sd_ = xs[xs["gap"] == 0]
key("n8_same_day_pairs", len(sd_))
key("n8_same_day_same_car_obs", (sd_["carrier"] == sd_["prev_car"]).mean())
key("n8_same_day_same_car_exp", sd_["e_car"].mean())
# Home package / carrier as of month t vs churn, controlling for running frequency and tenure
cum = d.groupby(["user_id", "mi", "package_code"]).size().unstack(fill_value=0).groupby(level=0).cumsum()
hp = cum.idxmax(axis=1).rename("hp_t")
hs = (cum.max(axis=1) / cum.sum(axis=1)).rename("hs_t")
cumc = d.groupby(["user_id", "mi", "carrier"]).size().unstack(fill_value=0).groupby(level=0).cumsum()
hc = cumc.idxmax(axis=1).rename("hc_t")
fc = full.join(hp, on=["user_id", "mi"]).join(hs, on=["user_id", "mi"]).join(hc, on=["user_id", "mi"])
b0 = smf.logit("churn ~ np.log(cum_avg) + C(age_c)", data=fc).fit(disp=0)
b1 = smf.logit("churn ~ np.log(cum_avg) + C(age_c) + C(hp_t)", data=fc).fit(disp=0)
b2 = smf.logit("churn ~ np.log(cum_avg) + C(age_c) + C(hc_t)", data=fc).fit(disp=0)
b3 = logit_cl("churn ~ np.log(cum_avg) + C(age_c) + hs_t", fc)
key("n8_lr_p_home_pkg", stats.chi2.sf(2 * (b1.llf - b0.llf), b1.df_model - b0.df_model))
key("n8_lr_p_home_carrier", stats.chi2.sf(2 * (b2.llf - b0.llf), b2.df_model - b0.df_model))
key("n8_home_share_coef", b3.params["hs_t"]); key("n8_home_share_p", b3.pvalues["hs_t"])
hcar = fc.groupby("hc_t")["churn"].agg(["size", "mean"])
key("n8_home_carrier_churn_min", hcar["mean"].min()); key("n8_home_carrier_churn_max", hcar["mean"].max())
fm_u = um_full.groupby("user_id")["n"].agg(["mean", "size"])
uh = users.join(fm_u).assign(home_pkg=cum.groupby(level=0).last().idxmax(axis=1))
uh = uh[uh["size"] >= 3]
u10 = users[users["n_txn"] >= 10].index
pk10 = d[d["user_id"].isin(u10)].groupby(["user_id", "package_code"]).size().unstack(fill_value=0)
hs10 = (pk10.max(axis=1) / pk10.sum(axis=1)).groupby(pk10.idxmax(axis=1)).mean()
key("n8_home_share_by_home_pkg_min", hs10.min()); key("n8_home_share_by_home_pkg_max", hs10.max())
key("n8_freq_by_home_pkg_anova_p", stats.f_oneway(*[g_["mean"].values for _, g_ in uh.groupby("home_pkg")]).pvalue)
# D2 replications
fpk = d[d["pos"] == 0].set_index("user_id")["package_code"]
matu = users[users["cohort"] <= 2024 * 12 + 5].assign(first_pkg=fpk)
fp_ = matu.groupby("first_pkg")["n_months"].mean()
key("d2_first_pkg_months_min", fp_.min()); key("d2_first_pkg_months_max", fp_.max())
key("d2_first_pkg_months_kruskal_p", stats.kruskal(*[g_["n_months"].values for _, g_ in matu.groupby("first_pkg")]).pvalue)
lastrow = d.groupby("user_id").tail(1)
lastrow = lastrow[lastrow["mi"] < LAST]
key("d2_exit_category_max_dev_pp", (lastrow["package_code"].value_counts(normalize=True) - d["package_code"].value_counts(normalize=True)).abs().max() * 100)
fcar = d[d["pos"] == 0].set_index("user_id")["carrier"]
e1u = users[users["cohort"] < LAST].assign(first_car=fcar)
key("d2_first_carrier_m1_chi2_p", stats.chi2_contingency(pd.crosstab(e1u["first_car"], e1u["m1"]))[1])
# Category in the month before an upgrade (light -> heavy) vs light months that do not upgrade
lm_ = tr[tr["seg"] == "Light (1)"].copy()
lm_["upgrade"] = (lm_["next_state"] == "Heavy (4+)").astype(int)
lm_ = lm_.merge(d.groupby(["user_id", "mi"])["package_code"].first().rename("pkg").reset_index(), on=["user_id", "mi"])
key("n8_light_month_pkg_vs_upgrade_chi2_p", stats.chi2_contingency(pd.crosstab(lm_["pkg"], lm_["upgrade"]))[1])
key("n8_light_month_pkg_vs_churn_chi2_p", stats.chi2_contingency(pd.crosstab(lm_["pkg"], lm_["next_state"] == "Churned"))[1])

section("N9. Cohort x behaviour: early vs late cohorts")
def coh_group(c_):
    return np.where(c_ <= 2024 * 12 + 5, "2024H1", np.where(c_ <= 2024 * 12 + 11, "2024H2", "2025H1"))


ug_ = users[users["cohort"] < LAST].copy()
ug_["cg"] = coh_group(ug_["cohort"])
cb = ug_.groupby("cg").agg(users=("n0", "size"), mean_n0=("n0", "mean"), share_n0_1=("n0", lambda x: (x == 1).mean()),
                           m1=("m1", "mean"), limit_m=("limit", lambda x: x.mean() / 1e6))
fq = full.assign(cg=coh_group(full["cohort"]))
fq = fq[fq["age"] <= 3]
cb = cb.join(fq.groupby("cg")["n"].mean().rename("mean_n_full_months_M1_M3"))
cb = cb.join(fq.groupby("cg")["churn"].mean().rename("churn_M1_M3"))
save(cb.round(4), "n9_cohort_group_behaviour")
# Does the frequency -> churn gradient differ by cohort group? interaction test (M1-M3)
fq["lc"] = np.log(fq["cum_avg"])
i0 = smf.logit("churn ~ lc + C(cg) + C(age_c)", data=fq).fit(disp=0)
i1 = smf.logit("churn ~ lc * C(cg) + C(age_c)", data=fq).fit(disp=0)
key("n9_freq_x_cohort_interaction_lr_p", stats.chi2.sf(2 * (i1.llf - i0.llf), i1.df_model - i0.df_model))
key("n9_mean_n0_2024H1", cb.loc["2024H1", "mean_n0"]); key("n9_mean_n0_2025H1", cb.loc["2025H1", "mean_n0"])
key("n9_churn_M1_M3_2024H1", cb.loc["2024H1", "churn_M1_M3"]); key("n9_churn_M1_M3_2025H1", cb.loc["2025H1", "churn_M1_M3"])
key("n9_n0_dist_chi2_p", stats.chi2_contingency(pd.crosstab(ug_["cg"], ug_["n0"].clip(upper=8)))[1])
rpc = cr.assign(cg=coh_group(cr["cohort"])).groupby("cg")["rep"].mean()
key("n9_repay_rate_2024H1", rpc.loc["2024H1"]); key("n9_repay_rate_2025H1", rpc.loc["2025H1"])

section("Multiple-testing summary (Holm) for the new-finding headline tests")
tests = {
    "N1 this-month deviation | 3m avg (expect null)": K["n1_p_dev"],
    "N1 log 3m avg": K["n1_p_log_avg3"],
    "N1 churners last month vs own avg (expect null)": K["n1_churners_paired_p"],
    "N2 tenure | running freq (expect null)": K["n2_age_p_ctrl"],
    "N2 tenure raw": K["n2_age_p_raw"],
    "N3 ticket ANOVA (expect null)": K["n3_ticket_anova_p"],
    "N5 join day | n0 + freq (expect null)": K["n5_join_joint_p_ctrl"],
    "N5 join day raw": K["n5_join_late_p_raw"],
    "N5 n0 vs n1 paired (expect null)": K["n5_paired_p_n0_vs_n1"],
    "N7 repay dispersion (expect null)": K["n7_user_dispersion_p"],
    "N8 home pkg (expect null)": K["n8_lr_p_home_pkg"],
    "N8 home carrier (expect null)": K["n8_lr_p_home_carrier"],
    "N9 freq x cohort (expect null)": K["n9_freq_x_cohort_interaction_lr_p"],
}
tt = pd.DataFrame({"p": tests}).sort_values("p")
m_ = len(tt)
tt["holm_adj"] = np.minimum(1, np.maximum.accumulate((m_ - np.arange(m_)) * tt["p"].values))
save(tt, "multiple_testing_holm")
print(tt)

with open(os.path.join(OUT, "eda_numbers.json"), "w") as fh:
    json.dump(K, fh, indent=1, default=str)
print(f"\nWrote {len(K)} numbers to outputs/eda_numbers.json")
