"""Evaluate an executed day-14 pilot using intention-to-treat assignment.

Example after a real pilot has run and at least 60 days have elapsed:
python My_solution/evaluate_pilot.py --assignment actual_assignments.csv \
    --transactions updated_transactions.csv --out pilot_result.json

Assignments must have user_id, first_purchase_date, trigger_date, arm, and
simulation_only=False. This deliberately rejects the historical dry-run file.
It reports behavioural outcomes only; net contribution requires incentive,
repayment, fee and credit-loss data that are absent from the supplied CSV.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import fisher_exact


parser = argparse.ArgumentParser()
parser.add_argument("--assignment", required=True)
parser.add_argument("--transactions", required=True)
parser.add_argument("--out", required=True)
args = parser.parse_args()

assignment = pd.read_csv(args.assignment, parse_dates=["first_purchase_date", "trigger_date"])
required = {"user_id", "first_purchase_date", "trigger_date", "arm", "simulation_only"}
assert required <= set(assignment.columns), f"Missing columns: {required - set(assignment.columns)}"
assert not assignment.empty and assignment.user_id.is_unique
assert set(assignment.arm) == {"prompt", "holdout"}
assert not assignment.simulation_only.astype(str).str.lower().isin(["true", "1"]).any(), (
    "Historical dry-run assignments cannot be evaluated as a treatment effect"
)
assert (assignment.trigger_date == assignment.first_purchase_date + pd.Timedelta(days=14)).all()

tx = pd.read_csv(args.transactions, parse_dates=["trxn_date"])
assert tx.transaction_id.is_unique and not tx.isna().any().any()
end = tx.trxn_date.max()
assert (assignment.first_purchase_date + pd.Timedelta(days=59) <= end).all(), (
    "Some assigned users do not yet have 60 days of observable follow-up"
)
first = tx.groupby("user_id").trxn_date.min()
assert assignment.user_id.isin(first.index).all()
assert (assignment.first_purchase_date.values == first.loc[assignment.user_id].values).all()

records = tx[tx.user_id.isin(assignment.user_id)].copy()
records["first_purchase_date"] = records.user_id.map(first)
records["day"] = (records.trxn_date - records.first_purchase_date).dt.days
n_before_trigger = records[records.day < 14].groupby("user_id").size()
assert (n_before_trigger.reindex(assignment.user_id).values == 1).all(), (
    "Assignment contains users who did not meet the one-purchase day-14 rule"
)

future = records[records.day.between(30, 59)].groupby("user_id").agg(
    txns=("transaction_id", "size"), gmv_vnd=("trxn_amount", "sum")
)
assignment["active_days_30_59"] = assignment.user_id.isin(future.index)
assignment["txns_days_30_59"] = assignment.user_id.map(future.txns).fillna(0).astype(int)
assignment["gmv_days_30_59_vnd"] = assignment.user_id.map(future.gmv_vnd).fillna(0)

arms = assignment.groupby("arm").agg(
    users=("user_id", "size"),
    retained=("active_days_30_59", "sum"),
    retention=("active_days_30_59", "mean"),
    txns_per_assigned=("txns_days_30_59", "mean"),
    gmv_per_assigned_vnd=("gmv_days_30_59_vnd", "mean"),
)
t, c = arms.loc["prompt"], arms.loc["holdout"]
lift = float(t.retention - c.retention)
se = float(np.sqrt(t.retention * (1 - t.retention) / t.users
                   + c.retention * (1 - c.retention) / c.users))
_, pvalue = fisher_exact([
    [int(t.retained), int(t.users - t.retained)],
    [int(c.retained), int(c.users - c.retained)],
])

result = {
    "analysis": "intention_to_treat",
    "outcome": "at_least_one_purchase_in_days_30_59_after_first_purchase",
    "as_of_date": str(end.date()),
    "arms": arms.reset_index().to_dict(orient="records"),
    "absolute_retention_lift_pp": lift * 100,
    "normal_approx_95pct_ci_lift_pp": [100 * (lift - 1.96 * se), 100 * (lift + 1.96 * se)],
    "fisher_exact_two_sided_p": float(pvalue),
    "incremental_gmv_per_assigned_vnd": float(t.gmv_per_assigned_vnd - c.gmv_per_assigned_vnd),
    "net_profit_estimable_from_input": False,
}
Path(args.out).write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result, indent=2))
