"""Out-of-time XGBoost for next-calendar-month BNPL inactivity.

Run: python My_solution/churn_xgboost.py
Prediction cutoff: end of active month t. Label: no purchase in t+1.
Train: Jan–Oct 2024. Tune: Nov–Dec 2024. Final refit: Jan–Dec 2024.
Untouched test: Jan–May 2025, predicting Feb–Jun 2025.

No user_id, transaction_id, future-month event, future balance or future
account status is used as a feature. Repeated user-months across splits are
appropriate for scoring existing users in future months; results should not
be read as generalisation to entirely new customer populations.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score


ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "My_solution" / "outputs" / "churn_xgboost"
OUT.mkdir(parents=True, exist_ok=True)
tx = pd.read_csv(ROOT / "data.csv", parse_dates=["trxn_date"])
assert tx.transaction_id.is_unique and not tx.isna().any().any()
tx["month"] = tx.trxn_date.dt.to_period("M")
last_month = tx.month.max()
tx = tx.sort_values(["user_id", "trxn_date", "transaction_id"]).copy()
tx["carrier_norm"] = tx.carrier.replace({"Other services": "Other Services"})
tx["util"] = tx.total_outstanding / tx.total_limit
tx["gap_days"] = tx.groupby("user_id").trxn_date.diff().dt.days
tx["weekend"] = tx.trxn_date.dt.dayofweek >= 5
tx["second_half"] = tx.trxn_date.dt.day >= 16

first_txn = tx.groupby("user_id").first()
first_dates = first_txn.trxn_date
cohort = first_dates.dt.to_period("M")

um = tx.groupby(["user_id", "month"]).agg(
    n_txn=("transaction_id", "size"),
    gmv=("trxn_amount", "sum"),
    avg_ticket=("trxn_amount", "mean"),
    std_ticket=("trxn_amount", "std"),
    max_ticket=("trxn_amount", "max"),
    min_ticket=("trxn_amount", "min"),
    n_days=("trxn_date", "nunique"),
    first_txn_date=("trxn_date", "min"),
    last_txn_date=("trxn_date", "max"),
    n_carriers=("carrier_norm", "nunique"),
    n_packages=("package_code", "nunique"),
    balance_last=("total_outstanding", "last"),
    util_last=("util", "last"),
    util_max=("util", "max"),
    credit_limit=("total_limit", "last"),
    gap_mean=("gap_days", "mean"),
    gap_last=("gap_days", "last"),
    gap_max=("gap_days", "max"),
    n_weekend=("weekend", "sum"),
    n_second_half=("second_half", "sum"),
).reset_index().sort_values(["user_id", "month"])

# Current-month package mix. Categories are known from rows at the cutoff.
pkg = pd.get_dummies(tx.package_code, dtype=np.int16)
pkg.columns = ["pkg_" + re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_") for s in pkg.columns]
pkg_month = pkg.groupby([tx.user_id, tx.month]).sum().reset_index()
um = um.merge(pkg_month, on=["user_id", "month"], how="left", validate="one_to_one")

um["cohort"] = um.user_id.map(cohort)
um["first_date"] = um.user_id.map(first_dates)
um["first_ticket"] = um.user_id.map(first_txn.trxn_amount)
um["age_months"] = (
    (um.month.dt.year - um.cohort.dt.year) * 12
    + um.month.dt.month - um.cohort.dt.month
)
um["month_number"] = um.month.dt.month
um["month_end"] = um.month.dt.to_timestamp(how="end").dt.normalize()
um["days_in_month"] = um.month.dt.days_in_month
um["days_since_first"] = (um.month_end - um.first_date).dt.days
um["days_since_last_txn"] = (um.month_end - um.last_txn_date).dt.days
um["first_txn_day"] = um.first_txn_date.dt.day
um["last_txn_day"] = um.last_txn_date.dt.day
um["active_span_days"] = (um.last_txn_date - um.first_txn_date).dt.days
um["weekend_share"] = um.n_weekend / um.n_txn
um["second_half_share"] = um.n_second_half / um.n_txn
um["at_limit"] = (um.util_last >= 1).astype(int)

group = um.groupby("user_id", sort=False)
um["active_months_to_date"] = group.cumcount() + 1
um["first_month_n"] = group.n_txn.transform("first")
um["cum_n_txn"] = group.n_txn.cumsum()
um["cum_gmv"] = group.gmv.cumsum()
um["mean_n_to_date"] = um.cum_n_txn / um.active_months_to_date
um["mean_gmv_to_date"] = um.cum_gmv / um.active_months_to_date
um["max_n_to_date"] = group.n_txn.cummax()

for lag in (1, 2, 3):
    um[f"n_lag{lag}"] = group.n_txn.shift(lag).fillna(0)
    um[f"gmv_lag{lag}"] = group.gmv.shift(lag).fillna(0)
um["util_lag1"] = group.util_last.shift(1)
um["n_change_1m"] = um.n_txn - um.n_lag1
um["n_recent_3m"] = um.n_txn + um.n_lag1 + um.n_lag2
um["gmv_recent_3m"] = um.gmv + um.gmv_lag1 + um.gmv_lag2
um["n_vs_prior_mean"] = um.n_txn - (
    (um.cum_n_txn - um.n_txn) / (um.active_months_to_date - 1).replace(0, np.nan)
)
um["util_change_1m"] = um.util_last - um.util_lag1

# Static first-merchant signal (known at activation). No target encoding.
first_carrier = first_txn.carrier_norm.rename("first_carrier")
um["first_carrier"] = um.user_id.map(first_carrier)
first_carrier_dummy = pd.get_dummies(um.first_carrier, prefix="first_carrier", dtype=np.int8)
um = pd.concat([um, first_carrier_dummy], axis=1)

# The only use of t+1 is the target label. June 2025 is right-censored.
observed = pd.MultiIndex.from_frame(um[["user_id", "month"]])
next_month = pd.MultiIndex.from_frame(um.assign(month=um.month + 1)[["user_id", "month"]])
um["churn_next_month"] = (~next_month.isin(observed)).astype(int)
panel = um[um.month < last_month].copy()
assert len(panel) > 0 and panel.churn_next_month.between(0, 1).all()

non_features = {
    "user_id", "month", "cohort", "first_date", "first_txn_date", "last_txn_date",
    "month_end", "first_carrier", "churn_next_month",
}
rich_features = [c for c in panel if c not in non_features]
assert all(pd.api.types.is_numeric_dtype(panel[c]) for c in rich_features)
simple_features = [
    "n_txn", "n_lag1", "n_lag2", "age_months", "credit_limit", "avg_ticket",
    "gmv", "n_carriers", "util_last", "days_since_last_txn", "first_month_n",
]
assert set(simple_features) <= set(rich_features)

train = panel.month <= pd.Period("2024-10", freq="M")
valid = panel.month.isin([pd.Period("2024-11", freq="M"), pd.Period("2024-12", freq="M")])
test = panel.month.between(pd.Period("2025-01", freq="M"), pd.Period("2025-05", freq="M"))
assert train.sum() and valid.sum() and test.sum()
y = panel.churn_next_month

# Predeclared small search. The test period is not touched until a candidate is
# selected on Nov–Dec 2024. Early stopping uses validation AUC only.
grid = [
    {"max_depth": 2, "min_child_weight": 20, "reg_lambda": 10, "subsample": 1.0, "colsample_bytree": 1.0},
    {"max_depth": 3, "min_child_weight": 20, "reg_lambda": 10, "subsample": .9, "colsample_bytree": .9},
    {"max_depth": 4, "min_child_weight": 20, "reg_lambda": 10, "subsample": .9, "colsample_bytree": .9},
    {"max_depth": 3, "min_child_weight": 5, "reg_lambda": 5, "subsample": .8, "colsample_bytree": .8},
]
attempts = []
for feature_set, features in (("simple", simple_features), ("rich", rich_features)):
    for i, params in enumerate(grid):
        model = xgb.XGBClassifier(
            objective="binary:logistic", tree_method="hist", eval_metric="auc",
            n_estimators=650, learning_rate=.04, early_stopping_rounds=45,
            random_state=42, n_jobs=4, **params,
        )
        model.fit(panel.loc[train, features], y.loc[train],
                  eval_set=[(panel.loc[valid, features], y.loc[valid])], verbose=False)
        prob = model.predict_proba(panel.loc[valid, features])[:, 1]
        attempts.append({"feature_set": feature_set, "grid_index": i,
                         "validation_auc": float(roc_auc_score(y.loc[valid], prob)),
                         "best_iteration": int(model.best_iteration), **params})

search = pd.DataFrame(attempts).sort_values("validation_auc", ascending=False)
search.to_csv(OUT / "validation_search.csv", index=False, float_format="%.6f")
winner = search.iloc[0]
chosen_features = simple_features if winner.feature_set == "simple" else rich_features
params = grid[int(winner.grid_index)]
final = xgb.XGBClassifier(
    objective="binary:logistic", tree_method="hist", eval_metric="auc",
    n_estimators=max(1, int(winner.best_iteration) + 1), learning_rate=.04,
    random_state=42, n_jobs=4, **params,
)
final.fit(panel.loc[train | valid, chosen_features], y.loc[train | valid], verbose=False)
score = final.predict_proba(panel.loc[test, chosen_features])[:, 1]
actual = y.loc[test].to_numpy()
test_frame = panel.loc[test, ["user_id", "month", "churn_next_month", "n_txn", "age_months"]].copy()
test_frame["score"] = score
test_frame.month = test_frame.month.astype(str)
test_frame.to_csv(OUT / "test_scores.csv", index=False, float_format="%.7f")

auc = float(roc_auc_score(actual, score))
ap = float(average_precision_score(actual, score))
brier = float(brier_score_loss(actual, score))
frequency_rule_auc = float(roc_auc_score(actual, -panel.loc[test, "n_txn"].to_numpy()))
test_frame["risk_decile"] = pd.qcut(
    test_frame.score.rank(method="first", ascending=False), 10,
    labels=list(range(1, 11)),
).astype(int)
deciles = test_frame.groupby("risk_decile").agg(
    user_months=("churn_next_month", "size"), churners=("churn_next_month", "sum"),
    observed_churn=("churn_next_month", "mean"), mean_score=("score", "mean"),
)
deciles["capture_cumulative"] = deciles.churners.cumsum() / deciles.churners.sum()
deciles.to_csv(OUT / "test_deciles.csv", float_format="%.6f")
by_month = test_frame.groupby("month").apply(
    lambda s: pd.Series({"user_months": len(s), "churn_rate": s.churn_next_month.mean(),
                         "auc": roc_auc_score(s.churn_next_month, s.score),
                         "average_precision": average_precision_score(s.churn_next_month, s.score)}),
)
by_month.to_csv(OUT / "test_by_month.csv", float_format="%.6f")

# Cluster bootstrap by user: repeated user-months must travel together.
rng = np.random.default_rng(42)
ids = test_frame.user_id.to_numpy()
unique_ids, inverse = np.unique(ids, return_inverse=True)
row_groups = [np.flatnonzero(inverse == i) for i in range(len(unique_ids))]
boot = []
for _ in range(200):
    sampled_users = rng.integers(0, len(unique_ids), len(unique_ids))
    rows = np.concatenate([row_groups[i] for i in sampled_users])
    if len(np.unique(actual[rows])) == 2:
        boot.append(roc_auc_score(actual[rows], score[rows]))
auc_ci = np.quantile(boot, [.025, .975]).tolist()

importance = final.get_booster().get_score(importance_type="gain")
importance_table = pd.DataFrame({"feature": chosen_features,
                                 "gain": [importance.get(c, 0.0) for c in chosen_features]})
importance_table.sort_values("gain", ascending=False).to_csv(
    OUT / "feature_importance_gain.csv", index=False, float_format="%.6f"
)
final.save_model(OUT / "model.json")
(OUT / "feature_columns.json").write_text(json.dumps(chosen_features, indent=2) + "\n")

metrics = {
    "task": "no transaction in the next calendar month among currently active users",
    "prediction_cutoff": "end of current active month",
    "train_months": ["2024-01", "2024-10"],
    "validation_months": ["2024-11", "2024-12"],
    "test_months": ["2025-01", "2025-05"],
    "train_rows": int(train.sum()), "validation_rows": int(valid.sum()), "test_rows": int(test.sum()),
    "chosen_feature_set": str(winner.feature_set), "chosen_features": len(chosen_features),
    "chosen_grid_index": int(winner.grid_index), "chosen_best_iteration": int(winner.best_iteration),
    "validation_auc": float(winner.validation_auc),
    "test_auc": auc, "test_auc_cluster_bootstrap_95pct_ci": auc_ci,
    "test_average_precision": ap, "test_base_churn_rate": float(actual.mean()),
    "test_brier": brier, "test_frequency_only_auc": frequency_rule_auc,
    "test_top_decile_churn": float(deciles.loc[1, "observed_churn"]),
    "test_bottom_decile_churn": float(deciles.loc[10, "observed_churn"]),
    "test_top_20pct_churn_capture": float(deciles.loc[1:2, "capture_cumulative"].iloc[-1]),
    "reached_auc_0_8": bool(auc >= .8),
    "xgboost_version": xgb.__version__,
}
(OUT / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")

fig, axes = plt.subplots(1, 2, figsize=(10, 4))
axes[0].bar(deciles.index, deciles.observed_churn, color="#315da7")
axes[0].axhline(actual.mean(), color="#d65f34", ls="--", label="test base rate")
axes[0].set_title("Observed next-month churn by predicted risk decile")
axes[0].set_xlabel("1 = highest score")
axes[0].set_ylabel("Churn rate")
axes[0].legend(frameon=False)
axes[1].plot(by_month.index, by_month.auc, "o-", color="#315da7")
axes[1].axhline(.8, color="#d65f34", ls="--", label="AUC target 0.80")
axes[1].set_ylim(.45, .85)
axes[1].set_title("Out-of-time AUC by scoring month")
axes[1].set_ylabel("AUC")
axes[1].tick_params(axis="x", rotation=35)
axes[1].legend(frameon=False)
fig.tight_layout()
fig.savefig(OUT / "evaluation.png", dpi=160)
plt.close(fig)

print(json.dumps(metrics, indent=2))
