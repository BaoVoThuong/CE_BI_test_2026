# BNPL active users are falling: recover inflow, then test repeat-use nudges

**Decision for the Business Lead | 18,000-user extract, Jan 2024–Jun 2025**

## What is happening

Monthly active users fell from **4,162 in Oct 2024 to 3,022 in Jun 2025 (−27%)**. First-time purchasers fell from **about 1,367/month in Q1 2024 to 596 in Jun 2025 (−56%)**. About **one in four** active users does not buy the next month. In the latest transition, **752** users exited and only **596** first-time users arrived.

## Why we think it is happening

The count of first-time buyers has shrunk while cohort retention is broadly similar. Users who buy just once in a month are more likely to stop (30%) than those who buy four or more times (21%). It is not one merchant category: new and active users fell by about the same amount in all 7 packages and 33 merchant groups, and churners buy the same things as stayers. The data cannot tell whether this is caused by marketing, approvals, repayment experience or a product restriction. No user returns after an inactive month in this extract, so check how the extract was built.

## What to do in the next two weeks

| Priority | Owner | Deliverable / success check |
|---|---|---|
| 1. Find the acquisition drop | Growth + Risk | Monthly eligible → invited → approved → first purchase funnel, reconciled to official MAU. At current churn, roughly **733** arrivals/month would hold a base of 3,022. |
| 2. Test repeat-use contact | Product + CRM | Randomised second-purchase prompt and mid-month reminder with holdouts. Judge **incremental M1 retention and net value**, including incentive and credit cost. |
| 3. Resolve data questions | Data Engineering + Risk | Verify 104 appended purchases and why lapsed users never return before setting transaction-count targets or launching win-back. |

**Target caution:** four first-month purchases look special only if 104 appended records are kept; their provenance is unconfirmed. A second purchase within 30 days is a simpler milestone to *test*. The observed 17-point retention gap between one and two early purchases is an association, not a promised campaign lift.
