"""Leakage-audited XGBoost with calendar, cadence and business interactions.

Run: python My_solution/churn_xgboost_v2.py [--exclude-tail]
Prediction at the end of active calendar month t: no purchase in t+1.
Candidates are selected using Nov-Dec 2024 only; Jan-May 2025 is touched once.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

ROOT = Path(__file__).resolve().parent.parent
BASE_OUT = ROOT / "My_solution" / "outputs" / "churn_xgboost_v2"


def div(a, b):
    return a / b.replace(0, np.nan)


def build_panel(tx: pd.DataFrame):
    tx = tx.sort_values(["user_id", "trxn_date", "transaction_id"]).copy()
    tx["month"] = tx.trxn_date.dt.to_period("M")
    tx["day"] = tx.trxn_date.dt.day
    tx["days_in_month"] = tx.trxn_date.dt.days_in_month
    tx["days_left"] = tx.days_in_month - tx.day
    tx["early7"] = tx.day <= 7
    tx["late7"] = tx.days_left <= 6
    tx["late14"] = tx.days_left <= 13
    tx["weekend"] = tx.trxn_date.dt.weekday >= 5
    tx["payday"] = tx.day.between(25, 31) | tx.day.between(1, 5)
    tx["util"] = div(tx.total_outstanding, tx.total_limit)
    tx["carrier"] = tx.carrier.replace({"Other services": "Other Services"})
    tx["gap"] = tx.groupby("user_id").trxn_date.diff().dt.days
    tx["prior_carrier"] = tx.groupby("user_id").carrier.shift()
    tx["carrier_switch"] = (tx.carrier != tx.prior_carrier) & tx.prior_carrier.notna()
    tx["prior_package"] = tx.groupby("user_id").package_code.shift()
    tx["package_switch"] = (tx.package_code != tx.prior_package) & tx.prior_package.notna()
    tx["amt_sq"] = tx.trxn_amount ** 2
    tx["gap_sq"] = tx.gap ** 2
    tx["early_gmv"] = tx.trxn_amount.where(tx.early7, 0)
    tx["late_gmv"] = tx.trxn_amount.where(tx.late7, 0)
    tx["late14_gmv"] = tx.trxn_amount.where(tx.late14, 0)
    top_train_carriers = tx.loc[tx.month <= pd.Period("2024-10"), "carrier"].value_counts().head(10).index

    keys = ["user_id", "month"]
    um = tx.groupby(keys, sort=True).agg(
        n_txn=("transaction_id", "size"), gmv=("trxn_amount", "sum"),
        amount_sq=("amt_sq", "sum"), ticket_mean=("trxn_amount", "mean"),
        ticket_std=("trxn_amount", "std"), ticket_max=("trxn_amount", "max"),
        ticket_min=("trxn_amount", "min"), ticket_first=("trxn_amount", "first"),
        ticket_last=("trxn_amount", "last"),
        active_days=("trxn_date", "nunique"), first_date=("trxn_date", "first"),
        last_date=("trxn_date", "last"), n_carriers=("carrier", "nunique"),
        n_packages=("package_code", "nunique"),
        carrier_switches=("carrier_switch", "sum"),
        package_switches=("package_switch", "sum"),
        n_early7=("early7", "sum"), n_late7=("late7", "sum"),
        n_late14=("late14", "sum"), n_weekend=("weekend", "sum"),
        n_payday=("payday", "sum"), early_gmv=("early_gmv", "sum"),
        late_gmv=("late_gmv", "sum"), late14_gmv=("late14_gmv", "sum"),
        gap_mean=("gap", "mean"), gap_std=("gap", "std"),
        gap_min=("gap", "min"), gap_max=("gap", "max"),
        gap_last=("gap", "last"), gap_sq=("gap_sq", "sum"),
        balance_first=("total_outstanding", "first"),
        balance_last=("total_outstanding", "last"),
        balance_min=("total_outstanding", "min"),
        balance_max=("total_outstanding", "max"),
        util_first=("util", "first"), util_last=("util", "last"),
        util_max=("util", "max"), limit_first=("total_limit", "first"),
        limit_last=("total_limit", "last"),
        first_carrier=("carrier", "first"), last_carrier=("carrier", "last"),
        first_package=("package_code", "first"),
    ).reset_index()

    # Concentration/mix computed only from transactions available by cutoff.
    for col, prefix in [("package_code", "pkg"), ("carrier", "carrier")]:
        count = tx.groupby(keys + [col]).size().unstack(fill_value=0)
        prop = count.div(count.sum(axis=1), axis=0)
        mix = pd.DataFrame(index=count.index)
        mix[f"{prefix}_hhi"] = (prop ** 2).sum(axis=1)
        mix[f"{prefix}_entropy"] = -(prop.where(prop > 0, 1) * np.log(prop.where(prop > 0, 1))).sum(axis=1)
        mix[f"{prefix}_top_share"] = prop.max(axis=1)
        if col == "package_code":
            for category in prop.columns:
                name = "pkg_share_" + str(category).lower().replace(" ", "_").replace("-", "_")
                mix[name] = prop[category]
        else:
            # Every first/last carrier is observed at scoring; no target encoding.
            for category in top_train_carriers:
                name = "carrier_share_" + str(category).lower().replace(" ", "_").replace("-", "_")
                mix[name] = prop[category]
        um = um.merge(mix.reset_index(), on=keys, how="left", validate="one_to_one")

    first_tx = tx.groupby("user_id", sort=False).first()
    first_month = first_tx.month
    um["cohort"] = um.user_id.map(first_month)
    um["age_months"] = (um.month.dt.year - um.cohort.dt.year) * 12 + um.month.dt.month - um.cohort.dt.month
    um["month_number"] = um.month.dt.month
    um["month_end"] = um.month.dt.to_timestamp(how="end").dt.normalize()
    um["days_in_month"] = um.month.dt.days_in_month
    um["days_since_last"] = (um.month_end - um.last_date).dt.days
    um["days_since_first_ever"] = (um.month_end - um.user_id.map(first_tx.trxn_date)).dt.days
    um["first_day"] = um.first_date.dt.day
    um["last_day"] = um.last_date.dt.day
    um["span_days"] = (um.last_date - um.first_date).dt.days
    um["first_purchase_ticket"] = um.user_id.map(first_tx.trxn_amount)
    um["first_purchase_util"] = um.user_id.map(first_tx.util)

    base = ["n_txn", "gmv", "ticket_mean", "ticket_std", "ticket_max", "ticket_min",
            "active_days", "n_carriers", "n_packages", "balance_last", "util_last",
            "limit_last", "gap_mean", "gap_last", "gap_max", "age_months",
            "month_number", "days_since_last", "first_purchase_ticket", "first_purchase_util"]

    within = ["amount_sq", "ticket_first", "ticket_last", "n_early7", "n_late7",
              "n_late14", "n_weekend", "n_payday", "early_gmv", "late_gmv",
              "late14_gmv", "gap_std", "gap_min", "gap_sq", "first_day", "last_day",
              "span_days", "days_in_month", "days_since_first_ever"]
    um["txn_per_active_day"] = div(um.n_txn, um.active_days)
    um["txn_per_span_day"] = div(um.n_txn, um.span_days + 1)
    um["within_month_gap"] = div(um.span_days, um.active_days - 1)
    um["late7_share"] = div(um.n_late7, um.n_txn)
    um["late14_share"] = div(um.n_late14, um.n_txn)
    um["early7_share"] = div(um.n_early7, um.n_txn)
    um["late_gmv_share"] = div(um.late_gmv, um.gmv)
    um["payday_share"] = div(um.n_payday, um.n_txn)
    um["weekend_share"] = div(um.n_weekend, um.n_txn)
    um["ticket_cv"] = div(um.ticket_std, um.ticket_mean)
    um["ticket_hhi"] = div(um.amount_sq, um.gmv ** 2)
    um["max_ticket_share"] = div(um.ticket_max, um.gmv)
    um["last_vs_mean_ticket"] = div(um.ticket_last, um.ticket_mean)
    um["last_vs_first_ticket"] = div(um.ticket_last, um.ticket_first)
    um["gap_cv"] = div(um.gap_std, um.gap_mean)
    um["gap_last_vs_mean"] = div(um.gap_last, um.gap_mean)
    um["time_since_last_vs_cadence"] = div(um.days_since_last, um.gap_mean)
    within += ["txn_per_active_day", "txn_per_span_day", "within_month_gap",
               "late7_share", "late14_share", "early7_share", "late_gmv_share",
               "payday_share", "weekend_share", "ticket_cv", "ticket_hhi",
               "max_ticket_share", "last_vs_mean_ticket", "last_vs_first_ticket",
               "gap_cv", "gap_last_vs_mean", "time_since_last_vs_cadence"]

    mix = [c for c in um if c.startswith(("pkg_", "carrier_")) and c not in
           {"carrier_switches", "package_switches"}]
    mix += ["carrier_switches", "package_switches"]
    um["carrier_switch_rate"] = div(um.carrier_switches, um.n_txn)
    um["package_switch_rate"] = div(um.package_switches, um.n_txn)
    um["same_carrier_first_last"] = (um.first_carrier == um.last_carrier).astype(int)
    mix += ["carrier_switch_rate", "package_switch_rate", "same_carrier_first_last"]

    credit = ["balance_first", "balance_min", "balance_max", "util_first",
              "util_max", "limit_first"]
    um["balance_range"] = um.balance_max - um.balance_min
    um["balance_delta"] = um.balance_last - um.balance_first
    um["balance_delta_vs_gmv"] = div(um.balance_delta, um.gmv)
    um["balance_vs_gmv"] = div(um.balance_last, um.gmv)
    um["limit_room"] = um.limit_last - um.balance_last
    um["limit_room_vs_ticket"] = div(um.limit_room, um.ticket_mean)
    um["at_limit"] = (um.util_last >= 1).astype(int)
    credit += ["balance_range", "balance_delta", "balance_delta_vs_gmv",
               "balance_vs_gmv", "limit_room", "limit_room_vs_ticket", "at_limit"]

    # Full monthly grid fixes the prior model's active-month lag ambiguity.
    months = pd.period_range(tx.month.min(), tx.month.max(), freq="M")
    all_index = pd.MultiIndex.from_product([um.user_id.unique(), months], names=keys)
    full = um.set_index(keys).reindex(all_index).reset_index()
    full = full[full.month >= full.user_id.map(first_month)].reset_index(drop=True)
    full["was_active"] = full.n_txn.notna().astype(int)
    for c in ["n_txn", "gmv", "active_days", "n_carriers", "n_packages"]:
        full[c] = full[c].fillna(0)
    g = full.groupby("user_id", sort=False)
    history = []
    for lag in (1, 2, 3, 6):
        for c in ("n_txn", "gmv", "was_active"):
            name = f"{c}_lag{lag}"
            full[name] = g[c].shift(lag).fillna(0)
            history.append(name)
    for width in (2, 3, 6):
        for c in ("n_txn", "gmv", "was_active"):
            name = f"{c}_roll{width}"
            full[name] = g[c].rolling(width, min_periods=1).sum().reset_index(level=0, drop=True)
            history.append(name)
    full["cum_n"] = g.n_txn.cumsum()
    full["cum_gmv"] = g.gmv.cumsum()
    full["active_months_to_date"] = g.was_active.cumsum()
    full["months_observed"] = full.age_months + 1
    full["active_fraction"] = div(full.active_months_to_date, full.months_observed)
    full["lifetime_txn_per_active"] = div(full.cum_n, full.active_months_to_date)
    full["lifetime_txn_per_calendar"] = div(full.cum_n, full.months_observed)
    full["lifetime_gmv_per_calendar"] = div(full.cum_gmv, full.months_observed)
    full["first_month_n"] = g.n_txn.transform("first")
    full["max_month_n"] = g.n_txn.cummax()
    full["prior_n_mean"] = div(full.cum_n - full.n_txn, full.active_months_to_date - 1)
    full["prior_gmv_mean"] = div(full.cum_gmv - full.gmv, full.active_months_to_date - 1)
    full["n_vs_prior_mean"] = full.n_txn - full.prior_n_mean
    full["n_ratio_prior_mean"] = div(full.n_txn, full.prior_n_mean)
    full["gmv_ratio_prior_mean"] = div(full.gmv, full.prior_gmv_mean)
    full["n_change_1m"] = full.n_txn - full.n_txn_lag1
    full["n_change_2m"] = full.n_txn - full.n_txn_lag2
    full["n_acceleration"] = full.n_txn - 2 * full.n_txn_lag1 + full.n_txn_lag2
    full["n_recent_vs_long"] = div(full.n_txn_roll3 / 3, full.lifetime_txn_per_calendar)
    full["n_3m_slope"] = full.n_txn - full.n_txn_lag2
    full["gmv_3m_slope"] = full.gmv - full.gmv_lag2
    full["current_n_share_3m"] = div(full.n_txn, full.n_txn_roll3)
    full["current_gmv_share_3m"] = div(full.gmv, full.gmv_roll3)
    history += ["cum_n", "cum_gmv", "active_months_to_date", "months_observed",
                "active_fraction", "lifetime_txn_per_active", "lifetime_txn_per_calendar",
                "lifetime_gmv_per_calendar", "first_month_n", "max_month_n",
                "prior_n_mean", "prior_gmv_mean", "n_vs_prior_mean",
                "n_ratio_prior_mean", "gmv_ratio_prior_mean", "n_change_1m",
                "n_change_2m", "n_acceleration", "n_recent_vs_long", "n_3m_slope",
                "gmv_3m_slope", "current_n_share_3m", "current_gmv_share_3m"]

    # Previous active month and run length are state variables known at cutoff.
    full["inactive_before"] = 0
    full["active_streak"] = 0
    for _, idx in full.groupby("user_id", sort=False).indices.items():
        a = full.loc[idx, "was_active"].to_numpy()
        streak = np.zeros(len(a), dtype=np.int16)
        before = np.zeros(len(a), dtype=np.int16)
        last_active = -1
        for j, active in enumerate(a):
            before[j] = 0 if last_active < 0 else j - last_active - 1
            if active:
                streak[j] = streak[j - 1] + 1 if j and a[j - 1] else 1
                last_active = j
        full.loc[idx, "inactive_before"] = before
        full.loc[idx, "active_streak"] = streak
    full["recovered_this_month"] = (full.inactive_before > 0).astype(int)
    full["long_streak"] = (full.active_streak >= 3).astype(int)
    full["prior_active_rate"] = div(full.active_months_to_date - 1, full.age_months)
    history += ["inactive_before", "active_streak", "recovered_this_month",
                "long_streak", "prior_active_rate"]

    # Transition history is fully observed at t: previous-month lapse is
    # resolved by whether the customer returned in this (known) month.
    full["prior_month_active"] = g.was_active.shift(1).fillna(0)
    full["completed_lapse"] = full.prior_month_active * (1 - full.was_active)
    full["completed_reactivation"] = (1 - full.prior_month_active) * full.was_active
    full["prior_lapses"] = full.groupby("user_id", sort=False).completed_lapse.cumsum()
    full["prior_reactivations"] = full.groupby("user_id", sort=False).completed_reactivation.cumsum() - 1
    full["prior_lapse_rate"] = div(full.prior_lapses, full.active_months_to_date - 1)
    full["ever_lapsed"] = (full.prior_lapses > 0).astype(int)
    full["month_seq"] = full.groupby("user_id", sort=False).cumcount()
    last_lapse_seq = full.month_seq.where(full.completed_lapse.eq(1))
    last_lapse_seq = last_lapse_seq.groupby(full.user_id).ffill()
    full["months_since_lapse"] = full.month_seq - last_lapse_seq
    full["lapse_x_low_frequency"] = full.prior_lapse_rate * (full.n_txn <= 2)
    transitions = ["prior_lapses", "prior_reactivations", "prior_lapse_rate",
                   "ever_lapsed", "months_since_lapse", "lapse_x_low_frequency"]

    # Last observed account state, compared to the previous calendar month.
    for c in ("ticket_mean", "util_last", "balance_last", "limit_last",
              "pkg_hhi", "carrier_hhi"):
        full[f"{c}_prev_active"] = g[c].ffill().groupby(full.user_id).shift(1)
    full["util_change"] = full.util_last - full.util_last_prev_active
    full["limit_change"] = full.limit_last - full.limit_last_prev_active
    full["ticket_change_ratio"] = div(full.ticket_mean, full.ticket_mean_prev_active)
    full["balance_change"] = full.balance_last - full.balance_last_prev_active
    full["pkg_hhi_change"] = full.pkg_hhi - full.pkg_hhi_prev_active
    full["carrier_hhi_change"] = full.carrier_hhi - full.carrier_hhi_prev_active
    credit += ["util_last_prev_active", "balance_last_prev_active",
               "limit_last_prev_active", "util_change", "limit_change", "balance_change"]
    history += ["ticket_mean_prev_active", "ticket_change_ratio"]
    mix += ["pkg_hhi_prev_active", "carrier_hhi_prev_active",
            "pkg_hhi_change", "carrier_hhi_change"]

    # Crosses chosen from behavior hypotheses, without labels or target encoding.
    full["frequency_x_recency"] = full.n_txn * full.days_since_last
    full["single_x_last_week"] = (full.n_txn == 1).astype(int) * (full.days_since_last <= 7)
    full["declining_x_sparse"] = (full.n_change_1m < 0).astype(int) * (full.n_txn <= 2)
    full["recovered_x_single"] = full.recovered_this_month * (full.n_txn == 1)
    full["tenure_x_active_fraction"] = full.age_months * full.active_fraction
    full["util_x_frequency"] = full.util_last * full.n_txn
    full["util_x_recent_drop"] = full.util_last * (-full.n_change_1m).clip(lower=0)
    full["credit_room_x_ticket"] = div(full.limit_room, full.ticket_mean)
    full["late_share_x_frequency"] = full.late7_share * full.n_txn
    full["cadence_x_recency"] = div(full.days_since_last, full.gap_last)
    full["growing_x_breadth"] = (full.n_change_1m > 0).astype(int) * full.n_carriers
    full["category_concentration_x_low_freq"] = full.pkg_hhi * (full.n_txn <= 2)
    full["ticket_drop_x_low_limit"] = (full.ticket_change_ratio < .8).astype(int) * (full.util_last >= .8)
    crosses = ["frequency_x_recency", "single_x_last_week", "declining_x_sparse",
               "recovered_x_single", "tenure_x_active_fraction", "util_x_frequency",
               "util_x_recent_drop", "credit_room_x_ticket", "late_share_x_frequency",
               "cadence_x_recency", "growing_x_breadth",
               "category_concentration_x_low_freq", "ticket_drop_x_low_limit"]

    full = full[full.was_active.eq(1)].copy()
    last_month = tx.month.max()
    observed = pd.MultiIndex.from_frame(full[keys])
    next_key = pd.MultiIndex.from_frame(full.assign(month=full.month + 1)[keys])
    full["churn_next_month"] = (~next_key.isin(observed)).astype(int)
    panel = full[full.month < last_month].copy()
    score_month = full[full.month == last_month].copy()
    families = {"base": base, "within_month": within, "calendar_history": history,
                "transition_history": transitions,
                "merchant_mix": mix, "credit_dynamics": credit, "interactions": crosses}
    all_features = list(dict.fromkeys(c for cols in families.values() for c in cols))
    for family, cols in families.items():
        assert all(c in panel and pd.api.types.is_numeric_dtype(panel[c]) for c in cols), family
    for c in all_features:
        panel[c] = panel[c].replace([np.inf, -np.inf], np.nan)
        score_month[c] = score_month[c].replace([np.inf, -np.inf], np.nan)
    assert panel.groupby("month").churn_next_month.nunique().eq(2).all()
    return panel, score_month, families, all_features


def fit_candidate(panel, train, valid, features, params):
    model = xgb.XGBClassifier(
        objective="binary:logistic", tree_method="hist", eval_metric="auc",
        n_estimators=550, learning_rate=.04, early_stopping_rounds=35,
        random_state=42, n_jobs=4, **params,
    )
    model.fit(panel.loc[train, features], panel.loc[train, "churn_next_month"],
              eval_set=[(panel.loc[valid, features], panel.loc[valid, "churn_next_month"])],
              verbose=False)
    prob = model.predict_proba(panel.loc[valid, features])[:, 1]
    return float(roc_auc_score(panel.loc[valid, "churn_next_month"], prob)), int(model.best_iteration)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--exclude-tail", action="store_true",
                        help="Sensitivity: omit TXN00204591-TXN00204694")
    args = parser.parse_args()
    out = BASE_OUT / "without_tail" if args.exclude_tail else BASE_OUT
    out.mkdir(parents=True, exist_ok=True)
    tx = pd.read_csv(ROOT / "data.csv", parse_dates=["trxn_date"])
    assert tx.transaction_id.is_unique and not tx.isna().any().any()
    if args.exclude_tail:
        tx = tx[tx.transaction_id.str[3:].astype(int) <= 204590].copy()
    panel, score_month, families, all_features = build_panel(tx)
    train = panel.month <= pd.Period("2024-10")
    valid = panel.month.isin([pd.Period("2024-11"), pd.Period("2024-12")])
    test = panel.month.between(pd.Period("2025-01"), pd.Period("2025-05"))
    assert train.sum() and valid.sum() and test.sum()
    assert not (train & valid).any() and not (test & (train | valid)).any()

    # Family search is selected entirely on the 2024 validation months.
    sets = {
        "base": families["base"],
        "base_calendar": families["base"] + families["calendar_history"],
        "base_calendar_transitions": families["base"] + families["calendar_history"] + families["transition_history"],
        "base_cadence_calendar": families["base"] + families["calendar_history"] + families["within_month"],
        "base_calendar_credit": families["base"] + families["calendar_history"] + families["credit_dynamics"],
        "base_calendar_credit_transitions": families["base"] + families["calendar_history"] + families["credit_dynamics"] + families["transition_history"],
        "all_no_cross": [c for fam, cols in families.items() if fam != "interactions" for c in cols],
        "all": all_features,
    }
    grid = [
        {"max_depth": 2, "min_child_weight": 20, "reg_lambda": 10, "subsample": .9, "colsample_bytree": .9},
        {"max_depth": 3, "min_child_weight": 20, "reg_lambda": 10, "subsample": .9, "colsample_bytree": .9},
        {"max_depth": 4, "min_child_weight": 20, "reg_lambda": 10, "subsample": .9, "colsample_bytree": .9},
    ]
    attempts = []
    for set_name, features in sets.items():
        features = list(dict.fromkeys(features))
        for i, params in enumerate(grid):
            auc, iteration = fit_candidate(panel, train, valid, features, params)
            attempts.append({"feature_set": set_name, "n_features": len(features),
                             "grid_index": i, "validation_auc": auc,
                             "best_iteration": iteration, **params})
    search = pd.DataFrame(attempts).sort_values("validation_auc", ascending=False)
    search.to_csv(out / "validation_search.csv", index=False, float_format="%.7f")
    winner = search.iloc[0]
    features = list(dict.fromkeys(sets[str(winner.feature_set)]))
    params = grid[int(winner.grid_index)]
    model_args = dict(objective="binary:logistic", tree_method="hist", eval_metric="auc",
                      n_estimators=max(1, int(winner.best_iteration) + 1),
                      learning_rate=.04, random_state=42, n_jobs=4, **params)
    model = xgb.XGBClassifier(**model_args)
    model.fit(panel.loc[train | valid, features], panel.loc[train | valid, "churn_next_month"])
    test_frame = panel.loc[test, ["user_id", "month", "churn_next_month", "n_txn", "age_months"]].copy()
    actual = test_frame.churn_next_month.to_numpy()
    prob = model.predict_proba(panel.loc[test, features])[:, 1]
    test_frame["score"] = prob
    test_frame["month"] = test_frame.month.astype(str)
    test_frame.to_csv(out / "test_scores.csv", index=False, float_format="%.7f")
    test_frame["risk_decile"] = pd.qcut(test_frame.score.rank(method="first", ascending=False),
                                         10, labels=list(range(1, 11))).astype(int)
    decile = test_frame.groupby("risk_decile").agg(
        user_months=("churn_next_month", "size"), churners=("churn_next_month", "sum"),
        observed_churn=("churn_next_month", "mean"), mean_score=("score", "mean"),
    )
    decile["capture_cumulative"] = decile.churners.cumsum() / decile.churners.sum()
    decile.to_csv(out / "test_deciles.csv", float_format="%.6f")
    by_month = test_frame.groupby("month").apply(lambda s: pd.Series({
        "user_months": len(s), "churn_rate": s.churn_next_month.mean(),
        "auc": roc_auc_score(s.churn_next_month, s.score),
        "average_precision": average_precision_score(s.churn_next_month, s.score),
    }))
    by_month.to_csv(out / "test_by_month.csv", float_format="%.6f")

    # Cluster bootstrap keeps a user's repeated monthly observations together.
    rng = np.random.default_rng(42)
    ids = test_frame.user_id.to_numpy()
    _, inverse = np.unique(ids, return_inverse=True)
    rows_by_user = [np.flatnonzero(inverse == i) for i in range(inverse.max() + 1)]
    boot = []
    for _ in range(200):
        sampled = rng.integers(0, len(rows_by_user), len(rows_by_user))
        rows = np.concatenate([rows_by_user[i] for i in sampled])
        if len(np.unique(actual[rows])) == 2:
            boot.append(roc_auc_score(actual[rows], prob[rows]))
    ci = np.quantile(boot, [.025, .975]).tolist()

    importance = model.get_booster().get_score(importance_type="gain")
    pd.DataFrame({"feature": features,
                  "gain": [importance.get(c, 0) for c in features]}) \
        .sort_values("gain", ascending=False).to_csv(out / "feature_importance_gain.csv", index=False)
    model.save_model(out / "model_evaluated.json")
    (out / "feature_columns.json").write_text(json.dumps(features, indent=2) + "\n")
    (out / "feature_families.json").write_text(json.dumps(families, indent=2) + "\n")

    # Demonstration score for the final observed month. No July 2025 label exists.
    deploy = xgb.XGBClassifier(**model_args)
    deploy.fit(panel.loc[train | valid | test, features],
               panel.loc[train | valid | test, "churn_next_month"])
    june = score_month[["user_id", "month", "n_txn", "age_months"]].copy()
    june["score"] = deploy.predict_proba(score_month[features])[:, 1]
    june["risk_decile"] = pd.qcut(june.score.rank(method="first", ascending=False),
                                  10, labels=list(range(1, 11))).astype(int)
    june.month = june.month.astype(str)
    june.to_csv(out / "june_2025_scores.csv", index=False, float_format="%.7f")
    deploy.save_model(out / "model_all_labeled.json")

    fixed_raw_spec_auc = None
    if args.exclude_tail:
        # Separate preprocessing sensitivity from a new validation winner.
        fixed_features = list(dict.fromkeys(sets["base_calendar_credit"]))
        fixed_args = dict(objective="binary:logistic", tree_method="hist", eval_metric="auc",
                          n_estimators=26, learning_rate=.04, random_state=42, n_jobs=4,
                          **grid[2])
        fixed_model = xgb.XGBClassifier(**fixed_args)
        fixed_model.fit(panel.loc[train | valid, fixed_features],
                        panel.loc[train | valid, "churn_next_month"])
        fixed_raw_spec_auc = float(roc_auc_score(
            actual, fixed_model.predict_proba(panel.loc[test, fixed_features])[:, 1]))

    metrics = {
        "task": "no transaction in next calendar month among current-month active users",
        "cutoff": "end of current calendar month", "excluded_tail": args.exclude_tail,
        "train_months": ["2024-01", "2024-10"],
        "validation_months": ["2024-11", "2024-12"],
        "test_months": ["2025-01", "2025-05"],
        "train_rows": int(train.sum()), "validation_rows": int(valid.sum()),
        "test_rows": int(test.sum()), "scored_june_users": int(len(june)),
        "selected_feature_set": str(winner.feature_set), "selected_features": len(features),
        "selected_grid_index": int(winner.grid_index),
        "selected_best_iteration": int(winner.best_iteration),
        "validation_auc": float(winner.validation_auc),
        "test_auc": float(roc_auc_score(actual, prob)),
        "test_auc_cluster_bootstrap_95pct_ci": ci,
        "test_average_precision": float(average_precision_score(actual, prob)),
        "test_base_churn_rate": float(actual.mean()),
        "test_brier": float(brier_score_loss(actual, prob)),
        "test_top_decile_churn": float(decile.loc[1, "observed_churn"]),
        "test_bottom_decile_churn": float(decile.loc[10, "observed_churn"]),
        "test_top20_churn_capture": float(decile.loc[1:2, "capture_cumulative"].iloc[-1]),
        "raw_selected_spec_on_clean_test_auc": fixed_raw_spec_auc,
        "xgboost_version": xgb.__version__,
    }
    (out / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")
    if not args.exclude_tail:
        prior_file = ROOT / "My_solution" / "outputs" / "churn_xgboost" / "test_scores.csv"
        if prior_file.exists():
            prior = pd.read_csv(prior_file, usecols=["user_id", "month", "churn_next_month", "score"])
            paired = prior.merge(test_frame[["user_id", "month", "churn_next_month", "score"]],
                                 on=["user_id", "month", "churn_next_month"],
                                 suffixes=("_v1", "_v2"), validate="one_to_one")
            if len(paired) == len(test_frame) == len(prior):
                labels = paired.churn_next_month.to_numpy()
                s1, s2 = paired.score_v1.to_numpy(), paired.score_v2.to_numpy()
                _, inv = np.unique(paired.user_id.to_numpy(), return_inverse=True)
                groups = [np.flatnonzero(inv == i) for i in range(inv.max() + 1)]
                rng = np.random.default_rng(77)
                differences = []
                for _ in range(300):
                    rows = np.concatenate([groups[i] for i in rng.integers(0, len(groups), len(groups))])
                    differences.append(roc_auc_score(labels[rows], s2[rows]) -
                                       roc_auc_score(labels[rows], s1[rows]))
                comparison = {
                    "paired_rows": len(paired), "auc_v1": float(roc_auc_score(labels, s1)),
                    "auc_v2": float(roc_auc_score(labels, s2)),
                    "delta_auc_v2_minus_v1": float(roc_auc_score(labels, s2) - roc_auc_score(labels, s1)),
                    "delta_auc_cluster_bootstrap_95pct_ci": np.quantile(differences, [.025, .975]).tolist(),
                    "score_correlation": float(np.corrcoef(s1, s2)[0, 1]),
                }
                (out / "comparison_v1.json").write_text(json.dumps(comparison, indent=2) + "\n")
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
