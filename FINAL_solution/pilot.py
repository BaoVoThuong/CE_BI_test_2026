"""
Offline tooling for the two proposed retention pilots. Nothing here contacts a user.

  Test A - second-purchase nudge: new users with exactly one purchase in days 0-13 after their
           first purchase. Outcome: any purchase in days 30-59 after the first purchase.
  Test B - mid-month reminder: users active in month m with no purchase by day 15 of month m+1.
           Outcome: any purchase in days 16-end of month m+1.

Usage
  python3 FINAL_solution/pilot.py dry-run --test A --month 2025-05   # historical assignment example
  python3 FINAL_solution/pilot.py dry-run --test B --month 2025-05   # users active in May, silent by 15 June
  python3 FINAL_solution/pilot.py evaluate --test A --assignment real_assignment.csv --transactions tx.csv

Design choices
- The arm is a stable property of the user: the parity of a salted hash of user_id. A user who is eligible
  in several months (Test B runs for 1-3 months) therefore always lands in the same arm, and each user
  enters a test once - the first month they are eligible (pass earlier assignment files via --registry).
- The baseline differs a lot between strata (Test A: 69% for day 1-3 joiners vs 42% for day 21-31), so the
  analysis is post-stratified: the pooled lift is the stratum-size-weighted mean of within-stratum lifts,
  with a normal-approximation p-value from that stratified estimate.
- Evaluation is intention-to-treat: every assigned user counts, whether or not the message was delivered.
- A dry-run file carries simulation_only=True and the evaluator refuses it.
- Eligibility checks that this CSV cannot support (account status, DPD, consent, offer rules) must be joined
  before a real send. The evaluation logic follows the independent solution's evaluate_pilot.py, extended
  with stratification and Test B.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import fisher_exact, norm

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "data.csv"
OUT = HERE / "outputs" / "pilot"
QUARANTINE_FROM = 204591          # suspect out-of-sequence rows (see REPORT.md, data notes)


def load(path: Path, quarantine: bool = True) -> pd.DataFrame:
    tx = pd.read_csv(path, parse_dates=["trxn_date"])
    assert tx["transaction_id"].is_unique and not tx.isna().any().any()
    if quarantine:
        tx = tx[tx["transaction_id"].str[3:].astype(int) < QUARANTINE_FROM]
    tx["first_date"] = tx["user_id"].map(tx.groupby("user_id")["trxn_date"].min())
    tx["day"] = (tx["trxn_date"] - tx["first_date"]).dt.days
    tx["month"] = tx["trxn_date"].dt.to_period("M")
    return tx


def stable_hash(user_id: int, salt: str) -> int:
    return int.from_bytes(hashlib.blake2b(f"{salt}|{user_id}".encode(), digest_size=8).digest(), "big")


def assign(frame: pd.DataFrame, salt: str, registry: list[str] | None = None) -> pd.DataFrame:
    """Stable user-level arm (hash parity); users already in an earlier wave are excluded."""
    if registry:
        seen = pd.concat([pd.read_csv(r, usecols=["user_id"]) for r in registry])["user_id"]
        frame = frame[~frame["user_id"].isin(seen)]
    frame = frame.assign(arm=["treatment" if stable_hash(int(u), salt) % 2 else "holdout" for u in frame["user_id"]])
    return frame.sort_values(["stratum", "user_id"])


def join_band(day: pd.Series) -> pd.Series:
    return pd.cut(day, [0, 3, 10, 20, 31], labels=["day 1-3", "day 4-10", "day 11-20", "day 21-31"]).astype(str)


def eligible_a(tx: pd.DataFrame, cohort: pd.Period) -> pd.DataFrame:
    first = tx.groupby("user_id")["first_date"].first()
    ids = first[first.dt.to_period("M") == cohort].index
    assert first.loc[ids].max() + pd.Timedelta(days=14) <= tx["trxn_date"].max(), "day-14 trigger not observable"
    cnt = tx[tx["user_id"].isin(ids) & (tx["day"] < 14)].groupby("user_id").size()
    one = cnt[cnt == 1].index
    return pd.DataFrame({"user_id": one, "first_purchase_date": first.loc[one].values,
                         "trigger_date": (first.loc[one] + pd.Timedelta(days=14)).values,
                         "stratum": join_band(first.loc[one].dt.day).values})


def eligible_b(tx: pd.DataFrame, month: pd.Period) -> pd.DataFrame:
    nxt = month + 1
    assert nxt <= tx["month"].max(), "the following month is not in the file"
    active = tx[tx["month"] == month].groupby("user_id").size()
    early = set(tx[(tx["month"] == nxt) & (tx["trxn_date"].dt.day <= 15)]["user_id"])
    silent = active[~active.index.isin(early)]
    band = pd.cut(silent, [0, 1, 3, 1000], labels=["1 txn", "2-3 txns", "4+ txns"]).astype(str)
    return pd.DataFrame({"user_id": silent.index, "trigger_date": nxt.start_time + pd.Timedelta(days=15),
                         "stratum": band.values})


def dry_run(test: str, month: str, registry: list[str] | None = None) -> Path:
    tx = load(DATA)
    m = pd.Period(month, freq="M")
    frame = eligible_a(tx, m) if test == "A" else eligible_b(tx, m)
    out = assign(frame, f"bnpl_test{test}_v1", registry).assign(test=test, simulation_only=True)
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"dry_run_test{test}_{month}.csv"
    out.to_csv(path, index=False)
    print(out.groupby(["stratum", "arm"]).size().unstack().to_string())
    print(f"{len(out)} users written to {path} (simulation only - do not send)")
    return path


def outcome(tx: pd.DataFrame, a: pd.DataFrame, test: str) -> pd.Series:
    if test == "A":
        first = tx.groupby("user_id")["first_date"].first()
        if not (a["first_purchase_date"] + pd.Timedelta(days=59) <= tx["trxn_date"].max()).all():
            raise SystemExit("every assigned user needs 60 days of follow-up")
        if not (a["first_purchase_date"].values == first.reindex(a["user_id"]).values).all():
            raise SystemExit("first_purchase_date does not match the transaction history")
        hit = set(tx[tx["day"].between(30, 59)]["user_id"])
    else:
        end = a["trigger_date"].dt.to_period("M").max().end_time
        if end > tx["trxn_date"].max() + pd.Timedelta(days=1):
            raise SystemExit("the trigger month is not complete yet")
        t = tx.merge(a[["user_id", "trigger_date"]], on="user_id")
        hit = set(t[(t["trxn_date"] >= t["trigger_date"]) & (t["month"] == t["trigger_date"].dt.to_period("M"))]["user_id"])
    return a["user_id"].isin(hit)


def evaluate(test: str, assignment: str, transactions: str, quarantine: bool = False) -> dict:
    a = pd.read_csv(assignment, parse_dates=[c for c in ("first_purchase_date", "trigger_date")
                                              if c in pd.read_csv(assignment, nrows=0).columns])
    if not ({"user_id", "arm", "stratum", "simulation_only"} <= set(a.columns)) or not a["user_id"].is_unique:
        raise SystemExit("assignment file needs unique user_id plus arm, stratum and simulation_only columns")
    if a["simulation_only"].astype(str).str.lower().isin(["true", "1"]).any():
        raise SystemExit("dry-run assignments cannot be evaluated as a treatment effect")
    tx = load(Path(transactions), quarantine=quarantine)
    a["y"] = outcome(tx, a, test)
    rows, lifts, weights = [], [], []
    for st, g in a.groupby("stratum"):
        t, c = g[g["arm"] == "treatment"]["y"], g[g["arm"] == "holdout"]["y"]
        if len(t) == 0 or len(c) == 0:
            continue
        lift = t.mean() - c.mean()
        var = t.mean() * (1 - t.mean()) / len(t) + c.mean() * (1 - c.mean()) / len(c)
        rows.append(dict(stratum=st, n_treatment=len(t), n_holdout=len(c), rate_treatment=t.mean(), rate_holdout=c.mean(), lift_pp=lift * 100))
        lifts.append((lift, var)); weights.append(len(g))
    w = np.array(weights) / sum(weights)
    pooled = float(sum(wi * l for wi, (l, _) in zip(w, lifts)))
    se = float(np.sqrt(sum(wi ** 2 * v for wi, (_, v) in zip(w, lifts))))
    t_all, c_all = a[a["arm"] == "treatment"]["y"], a[a["arm"] == "holdout"]["y"]
    _, p = fisher_exact([[int(t_all.sum()), int(len(t_all) - t_all.sum())], [int(c_all.sum()), int(len(c_all) - c_all.sum())]])
    res = {"test": test, "analysis": "intention_to_treat, post-stratified", "strata": rows,
           "pooled_lift_pp": pooled * 100, "ci95_pp": [100 * (pooled - 1.96 * se), 100 * (pooled + 1.96 * se)],
           "p_value_stratified": float(2 * norm.sf(abs(pooled / se))) if se > 0 else None,
           "fisher_p_unstratified_secondary": float(p),
           "note": "Behavioural lift only. Net value needs incentive cost, repayment and credit-loss data."}
    print(json.dumps(res, indent=2, default=float))
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("dry-run"); d.add_argument("--test", choices=["A", "B"], required=True); d.add_argument("--month", required=True)
    d.add_argument("--registry", nargs="*", help="earlier assignment files; their users are not re-enrolled")
    e = sub.add_parser("evaluate"); e.add_argument("--test", choices=["A", "B"], required=True)
    e.add_argument("--assignment", required=True); e.add_argument("--transactions", required=True)
    e.add_argument("--quarantine-suspect-rows", action="store_true", help="drop TXN IDs >= 204591 (only relevant for this extract)")
    args = ap.parse_args()
    if args.cmd == "dry-run":
        dry_run(args.test, args.month, args.registry)
    else:
        evaluate(args.test, args.assignment, args.transactions, args.quarantine_suspect_rows)
