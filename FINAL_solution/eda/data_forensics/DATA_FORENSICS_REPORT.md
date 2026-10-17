> **Review report written by an independent review agent (Oct 2026) against the earlier version of `REPORT.md`.** Its corrections have since been applied to the report; section references (A1–F3, 2.x) point to that earlier version.

# Feature-level EDA and data forensics: BNPL extract (CE BI test 2026)

Scope: the 8 columns, how they relate, whether they hold together, and what they show about how the file was generated and loaded. User behaviour and business segments are covered elsewhere.
Data: clean file (204,590 rows, the 104 out-of-sequence rows removed) unless marked *raw*. Every number comes from `data_forensics.py` (written to `eda_numbers.json` and `tables/`).

**In one paragraph.** Every column follows a simple, recoverable rule.
- `total_outstanding` follows three mechanical rules that explain 100% of clean rows. Its "repayments" are a 35% coin flip that ignores time, so the field carries no repayment information.
- `trxn_amount` is one i.i.d. lognormal draw. It is floored at 20K and capped at exactly 60% of the limit, but never checked against available credit.
- `total_limit` is a flat random draw over a 100K grid.
- Merchant volume is split almost equally across 34 package×carrier cells.
- Purchase days are uniform within each calendar month, including the first month. The "onboarding waves" are therefore an order-statistic by-product.
- The 104 suspect rows are not just out of sequence. They were built by resampling each user's own earlier rows.

---

## Part 1. Verification of existing findings (REPORT.md data notes, Bonus A–F, Appendix A/C/E)

| # | Existing finding | Verdict | Evidence (this script) |
|---|---|---|---|
| 1 | 18 months, 204,694 rows, 18,000 users, no nulls | **Confirmed** | 547 of 547 calendar days have transactions; user_ids are exactly 100000–117999 |
| 2 | 104 out-of-sequence rows TXN00204591–694 are "very unlikely to be organic"; quarantine "provisional" | **Confirmed and strengthened** | They were built from the user's own rows, not just mis-ordered (Part 2, finding 4). Chance probability is about 0.0078^104. Quarantine should be permanent. |
| 3 | 5 package→carrier violations, all in the 104 | **Confirmed; mechanism found** | Package and carrier were each drawn independently from the user's own 4 earlier rows. All 5 violations combine a package from one source row with a carrier from another. |
| 4 | "Balance rises by more than the purchase": 5 rows, all in the 104 | **Confirmed but understated** | **0 of 104** rows follow "balance = previous + amount" (organic: 63.7%). **19 of 104** break the balance rule outright (organic: 0 of 204,590). |
| 5 | The 104 balances fall vs previous 57% of the time, vs 29% organic | Confirmed, superseded | The balance is copied from one of the user's 4 earlier balances: 104/104 (k = 0/1/2/3: 27/29/23/25). The chance baseline is 0.78%. |
| 6 | Balance capped at the limit: 2,645 rows, 671 users, 1,589 purchases at an already-full limit | **Numbers confirmed; interpretation corrected** | The cap is mechanical: balance = min(prev + amount, limit) unless the 35% pay-down fires. 4,032 purchases exceeded the remaining headroom, 2,394 of them at zero headroom. Their amounts are the same as everyone else's. 65.4% were capped and 34.6% randomly paid down (Part 2, findings 1–2). |
| 7 | 1 exact duplicate pair (TXN00016242/43), kept | **Challenged (probably not a duplicate)** | Both rows are 300K = exactly 60% of a 500K limit (amount cap), and the balance is pinned at 500K (balance cap). Two caps plus 40% carrier stickiness make identical rows likely by chance. Same-day, same-amount, same-carrier pairs: 19 observed vs ~18 expected. |
| 8 | Same user + day + amount: 61 pairs vs ~45 expected | **Corrected: no excess** | The expected count must use each limit's own amount distribution, because the 60% cap creates an atom of mass. That gives **54.2 expected, p = 0.19**. |
| 9 | `Other services` vs `Other Services` (5,727 rows, Channel Partner) merged as a spelling variant | **Challenged** | The lower-case label behaves exactly like a separate carrier. Users who use both labels: 253 vs 1,231 if labels were random (ratio 0.21). Pairs of clearly distinct carriers give 0.20–0.23. It is present in all 18 months, and its ~1/34 volume share matches every other cell. Keep it separate and ask the data owner. |
| 10 | F2: first-transaction balance < amount for 35% of users | **Confirmed and generalised** | 35.1% at the first transaction and 35.0% at later ones: the same random pay-down. Across all rows, **18.7% (38,228) show a balance below the purchase just made**, and 146 rows show a balance of 0 right after a purchase. |
| 11 | `total_limit` never changes | **Confirmed** | 18,000 of 18,000 users have one value |
| 12 | F1: no seasonality or weekly rhythm | **Confirmed and strengthened** | Existing users' purchase days are exactly uniform across the calendar month (χ² p = 0.19; every day between 0.97× and 1.04×). Daily counts are Poisson around the monthly mean (dispersion 1.04, p = 0.25). No holiday reaches significance: max \|z\| = 2.44 (Tết 2024, −9%) across 14 windows, below the Bonferroni threshold of ~2.9. 11/11, 12/12 and Black Friday sit within ±3%. |
| 13 | F3: the extract looks simulated (equal tickets, contiguous IDs, 95 limit levels, exponential inflow) | **Confirmed and strengthened** | Part 2 recovers the generating rules. Minor fixes: there are 22 carrier labels (34 pair cells), not "21 merchant groups". The 95 levels are the complete 100K grid from 0.5M to 9.9M with ~equal users per level. Inflow is −4.7%/month plus pure Poisson noise (dispersion 1.01, p = 0.44), except Oct-24 (z = +3.8). |
| 14 | E1: limits ≈10× usage; median utilisation 6.8% | **Number confirmed; meaning corrected** | Median balance is ~304–334K in every limit band. Utilisation is therefore just a synthetic balance divided by the limit: 41% at ≤1M and 3.8% at >7.5M. "Users use ~7% of their line" describes the generator, not demand for credit. |
| 15 | E1: lowest and highest limits behave the same | **Confirmed** | Limit is independent of everything: \|ρ\| ≤ 0.015 with cohort, user_id, count, GMV, first amount and first day. Cohort Kruskal–Wallis p = 0.68. |
| 16 | E2: "either approved over limit or balance capped; ask the data owner" | **Corrected/answered** | Both happen. Amounts ignore the available credit, the balance is truncated at the limit, and a separate per-purchase cap at 60% of the limit is never breached (0 rows above it, 698 exactly at it). |
| 17 | E3: 128 "credit-hungry" users (≥80% of limit in Jun-25) | **Challenged** | Count confirmed (128, average limit 1.01M). But limit and June transaction count alone predict the flag with **AUC 0.97**. It is a small-limit artefact of the synthetic balance, not a sign of credit appetite. |
| 18 | E4: inferred repayment does not predict churn | **Confirmed, but uninformative** | The pay-down is an i.i.d. 35% coin. It is independent of gap, day of month, month boundary, user (dispersion 0.998, p = 0.54) and previous event (34.9% vs 35.0%). A null result was guaranteed. |
| 19 | E5: no "buy big and leave" | **Confirmed (mechanical)** | Amounts are independent of limit (ρ = 0.002) and capped at 0.6× the limit. "≥50% of limit" just means a small limit, and the "50–100%" band can only hold 50–60%. |
| 20 | D1: home package 67%; 2.1 packages at n = 5 (3.3 random); CP+DS = 61% of GMV | **Numbers confirmed; 61% is an artefact** | Package share = (number of carriers under it)/34, within 0.42pp (r = 0.9998). CP has 12 carriers and DS has 9. Stickiness is real in the data: 40.1% repeat the previous pair vs 2.9% by chance. It is flat across gaps of 0 to 90 days (39.9–40.4%). |
| 21 | D2 / exec. summary: ticket size and category have no effect | **Confirmed (by construction)** | Amount has zero user effect (ICC −0.0007, p = 0.78; lag-1 r = −0.001). η² < 0.00013 against every feature (Part 3). |
| 22 | A1/A2/A4 GMV segments and value | **Nuance** | User GMV is count × i.i.d. ticket (R² = 0.96). Every "value" finding is a frequency finding restated in VND. |
| 23 | Q1b anomaly 6, 2.7–2.8, 2.10: "new users arrive in monthly onboarding waves (25% in days 1–3)" | **Challenged** | The first-transaction day is exactly the minimum of the user's uniformly placed first-month days (KS p = 0.12–0.80 for every N0 = 1…8). Same users: N0 = 3.232, N1 = 3.224, N2 = 3.230 (Wilcoxon p = 0.89). The day-1–3 share is the same in all 18 cohorts (23.6–26.9%, χ² p = 0.87). The inflow decline is real in-data; the "waves" are not. |
| 24 | Q1a #5 / Q1c #5: "M0 is a partial month for late joiners"; the day-1–3 subgroup "gives everyone a full first month" | **Challenged** | M0 is already a full month for everyone (N0 = N1). The day-1–3 subgroup is selected on N0 (mean 4.29 vs 3.02; only 12.6% have N0 = 1). Given N0, first-day band adds nothing to M1 (LR p = 0.11). |
| 25 | B3: day-1–3 joiners 76% active in days 30–59 vs 53% for >day-20 | **Nuance** | Mostly N0 composition: first-day band is not significant once N0 is controlled (raw calendar M1 75.8% vs 67.5%). Statement or due-date drivers: no trace anywhere (finding 8). |
| 26 | Appendix C: at-limit flag +0.24 log-odds (p = 0.02) | **Confirmed but fragile** | Re-estimated at +0.21 (p = 0.02) with limit bands. 2024: +0.26 (p = 0.02). 2025: +0.08 (p = 0.61). ≥80% utilisation (p = 0.36) and continuous utilisation (p = 0.32) show nothing, so there is no dose-response. Treat as unconfirmed. |
| 27 | 2.4 credit lens (churners leave 6.1B VND; balances look normal), 2.5 "don't raise limits, users use 7%" | **Uninformative** | Both rest on the synthetic balance (finding 1). The data cannot inform limit or collections decisions; the report's own "only a randomised limit test can tell" is the right conclusion. |
| 28 | Appendix E: Jan-24 users are genuinely new; IDs unrelated to join date | **Confirmed** | No user's first balance exceeds the first purchase (0 rows), so nobody carries a prior balance into the extract. Spearman(user_id, first date) = 0.012, p = 0.12. |

---

## Part 2. New findings, ranked by importance to a BNPL business lead / data owner

### 1. `total_outstanding` is generated by three mechanical rules and carries no repayment information
- **Numbers.** Every clean row (204,590 of 204,590, within ±1,000 VND rounding) falls into one of three cases:
  - (a) balance = previous balance + amount (63.7%);
  - (b) balance = limit, when that sum exceeds the limit (1.3%);
  - (c) balance = round(U × (previous + amount)), with U ~ Uniform(0, 0.70) (35.0%, 95% CI 34.8–35.2%).
- **The pay-down event (c) depends on nothing:**
  - same-day purchase 34.9% vs ≥30 days since the last purchase 35.2% (χ² over gap bands p = 0.92);
  - same month vs crossing a month boundary: 34.9% vs 35.1%;
  - day of month p = 0.76; package, carrier, limit, tenure, transaction index, user decile all p > 0.04 (10 tests);
  - previous row paid down or not: 34.9% vs 35.0%;
  - per-user rates are exactly binomial (dispersion 0.998, p = 0.54, 6,864 users with ≥10 transactions).
- **The size looks nothing like a statement repayment.** U fits Uniform(0, 0.7) (KS p = 0.80; flat at ~5,100 per 0.05 bin). Only 0.28% of pay-downs clear the prior balance exactly. Pay-down amounts are no rounder than chance (10.2% multiples of 10K).
- **Method.** Implied repayment = prev + amount − balance, classified by rule; χ² and KS tests; per-user binomial dispersion test.
- **Robustness.** Same rate at the first transaction (35.1%) and later ones (35.0%). The 146 zero balances match round-to-1,000 (169 expected), not floor (337). The 2 rows that need more than ±500 VND tolerance exceed 70% by ~600 VND.
- **So what.**
  - Every balance-derived statement describes the generator, not customers: utilisation, "at the limit", "credit-hungry", inferred repayment, churners' outstanding, "users use 7% of their line".
  - Do not use this field for risk, collections or limit decisions.
  - Ask the data owner for the real ledger: statement date, due date, repayments, DPD.
  - Real repayment would cluster after statement and due dates and rise with time since purchase. Here it does neither.
- **Confidence: high.**

### 2. No available-credit control: purchases go through at a full limit, but no single purchase can exceed 60% of the limit
- **Numbers.**
  - 4,032 purchases (2.0%) exceeded the remaining headroom, and 2,394 were made with zero headroom. Their amounts look like everyone else's: median 135K at zero headroom vs 133K with >1M headroom.
  - Yet no row exceeds 0.6 × limit, and **698 rows (460 users) sit exactly at 0.6 × limit**. The pile-up equals the lognormal tail above the cap: 500K limits 10.8% vs 12.4% expected; 600K 7.5% vs 7.8%; 700K 5.4% vs 5.1%; 1M 1.5% vs 1.6%.
  - Exact matches at other fractions are rare and look like coincidences: 0.5× = 9 rows, 0.4× = 16, 0.3× = 43.
- **Method.** Headroom = limit − previous balance; amount distribution by headroom band; comparison with a censored-lognormal fit.
- **So what.** Two possible readings, and the data owner must say which:
  - (a) Production has a single-purchase cap of 60% of the line but no available-credit check. That is a credit-control gap: 2,394 purchases approved on a fully used line.
  - (b) The extract was simulated with `amount = min(draw, 0.6 × limit)` and `balance = min(…, limit)`.

  Either way, "maxed-out" users are an artefact of the truncation.
- **Confidence: high** on the pattern; the interpretation is open.

### 3. "Onboarding waves" are a statistical by-product: the first calendar month behaves like a full month
- **Numbers.**
  - For users with N0 = n first-month transactions, the first-transaction day follows the minimum of n uniform days over the whole month, and the last day follows the maximum (see the table below). N0 = 1 users' first day is uniform (mean 15.8 vs 15.7).
  - The 9,103 users active in M0, M1 and M2 made **3.232 / 3.224 / 3.230** transactions (Wilcoxon M0 vs M1 p = 0.89). This holds in 2024H1, 2024H2 and 2025 cohorts.
  - In real onboarding (sign-up mid-month), M0 would be visibly lighter than M1.
  - The day-1–3 share of first transactions is the same in all 18 cohorts (23.6–26.9%, χ² p = 0.87).
  - The model also reproduces the halved same-day repeat after the first purchase: 819 observed vs 831 simulated.

| N0 | Mean first day: observed | Mean first day: model | Mean last day: observed | Mean last day: model | KS p (first day) |
|---|---|---|---|---|---|
| 1 | 15.8 | 15.7 | 15.8 | 15.7 | 0.17 |
| 4 | 6.4 | 6.6 | 24.8 | 24.8 | 0.27 |
| 8 | 4.0 | 3.9 | 27.4 | 27.5 | 0.28 |

- **Method.** Exact order-statistic model per N0 with month length; randomised-PIT KS test; paired Wilcoxon; 20-run simulation of within-M0 offsets.
- **Robustness.** Given N0, first-day band does not predict M1 (LR p = 0.11). Caveat: the full offset profile deviates mildly from the model (χ² p = 0.016), but every first-day KS passes. A real process could mimic this only if join timing decayed at exactly each user's own purchase rate.
- **So what.**
  - Drop "monthly onboarding waves / eligibility batches" from the growth story. The decline in new users is the in-data fact; the "waves" are not.
  - Drop "M0 is a partial month" as a reason for the day-1–3 subgroup in Q1c. That subgroup is selected on N0 (mean 4.29 vs 3.02).
  - Join-day bands in the test design (2.6) are harmless but unnecessary.
- **Confidence: high** for the statistical pattern; **medium** for the interpretation.

### 4. The 104 suspect rows were constructed from each user's own history
- **Numbers.** Each row was built field by field:
  - **balance** copied from one of the user's 4 earlier rows: 104/104 (chance baseline 0.78%);
  - **package** drawn from the user's own packages: 104/104 (baseline 83%);
  - **carrier** drawn from the user's own carriers: 104/104 (baseline 73%), independently of the package, which explains all 5 hierarchy breaks;
  - **limit** copied: 104/104;
  - **amount** newly drawn: 0/104 repeat an earlier amount, and the distribution matches organic rows (KS p = 0.99);
  - **date**: spread across days 1–29 of M1 (uniform, p = 0.32; mean day 16.8). Organic returns among users with N0 = 4 come early in M1 (mean day 9.0, gap 14.7 days vs 22.1; KS p ≈ 1e-12 and 1e-16).
- **Balance rule.** 0/104 follow the rule (organic 63.7%), and 19/104 violate it (organic 0).
- **Target group.** The users are a random 21.9% of the 475 users with exactly 4 first-month transactions and no M1. Limit, cohort and first day show no difference (KS p = 0.58 / 0.17 / 1.00).
- **Load order.** IDs were appended after ID assignment, with no order by user or date (ρ = 0.05, p = 0.62). The file was then re-sorted by date, so the rows look interleaved.
- **So what.**
  - This is a deliberate planted pattern aimed at the Q1c "N = 4" hypothesis, not a mis-load.
  - Make the quarantine permanent.
  - Add the rule checks above (balance identity; package/carrier pairing; ID contiguity) to any ingestion test.
- **Confidence: very high.**

### 5. `trxn_amount` is one i.i.d. draw: no user, merchant, time or price-point structure
- **Distribution.**
  - Censored-lognormal MLE: median 133.4K VND, σ = 0.70, rounded to 1,000.
  - Floored at 20K: 787 rows sit at exactly 20K vs 160 at 21K. 0.385% at the floor matches the lognormal mass below 20.5K (0.369%).
  - Capped at 0.6 × limit (finding 2).
  - Interior bins fit within 0.98–1.01 (limits ≥2M).
- **No structure anywhere.**
  - User effect ICC = −0.0007 (ANOVA p = 0.78).
  - Within-user lag-1 correlation −0.001.
  - η² of log-amount on package, carrier, limit decile, day of week, day of month, month, tenure, transaction index, user decile and monthly frequency is ≤ 0.00013 for all (min p = 0.08).
- **No price points.** Excluding the clipped rows, the last thousand digit is uniform (p = 0.11). Multiples of 10K / 50K / 100K are 9.96% / 2.05% / 0.96%, vs 10.0% / 2.0% / 0.95% for a smooth density. Telco and Voucher, which sell fixed denominations in real life, show 2.2% multiples of 50K. 100K appears 1,042 times vs 1,010 and 1,084 for its neighbours.
- **So what.**
  - GMV is count × ~170K (user-level R² = 0.96), so ticket-based targeting, category pricing and "big spender" segments cannot be studied with this file.
  - The apparent Spearman(mean ticket, count) = 0.14 is a small-sample skew artefact, not a real link; the ICC is the proper test.
- **Confidence: high.**

### 6. The merchant mix is fixed by construction
- **Numbers.**
  - The 34 package×carrier cells (33 merchant groups plus the lower-case variant) hold 5,411–6,495 rows each (CV 4.2%).
  - Package GMV share = carriers/34 within 0.42pp (r = 0.9998).
  - The mix is flat over time: max monthly range 1.2pp, Cramér's V 0.018.
  - Users repeat their previous cell 40.1% of the time, and this does not decay with time (39.9% same day, 40.1% after 30+ days).
- **So what.**
  - "Channel Partner + Digital Services = 61% of GMV" reflects how many carriers are listed under them, not demand.
  - No category ranking from this file should drive merchant strategy.
  - The data owner should confirm that `carrier` is a real merchant group and whether `Other services` is a separate one.
- **Confidence: high.**

### 7. `total_limit` is a flat random assignment over a 100K grid
- **Numbers.**
  - All 95 levels from 0.5M to 9.9M in 100K steps; 161–245 users per level (expected 189).
  - Mild extra spread vs uniform (χ² p = 0.013, variance/mean 1.35), so it is nearly but not perfectly flat.
  - Mean 5.23M vs 5.20M for a uniform grid; cohort means 5.05–5.39M (Kruskal–Wallis p = 0.68).
  - Unrelated to user_id, count, months, GMV, first amount and first day (all \|ρ\| ≤ 0.008, p ≥ 0.30).
  - The only link, ρ(limit, mean ticket) = 0.015 (p = 0.04), comes from the 60% cap on small limits.
- **So what.** No scoring or limit policy can be recovered. Real limits are skewed, cluster at policy tiers and rise with tenure; these do none of that. Any "limit effect" analysis on this file is a placebo test.
- **Confidence: high.**

### 8. Calendar: no rhythm of any kind (strengthens F1)
- **Numbers.**
  - Existing users (age ≥1) buy on every day of the month equally (χ² p = 0.19; range 0.97–1.04×). There is no payday, month-end or due-date effect.
  - Day of week: max deviation ±1.7% (p = 0.056).
  - Daily totals are Poisson (dispersion 1.04; the largest \|z\| over 516 days is 2.8, about what chance gives).
  - Holidays (table in `tables/holiday_effects_age1plus.csv`): Tết 2025 0.99×, 30/4 1.02× and 1.00×, 11/11 0.98×, 12/12 1.01×, Black Friday 1.03×. Tết 2024 0.91× (z = −2.4) is the only dip and is not significant across 14 windows.
- **So what.** CRM timing (mid-month reminders, pre-due-date nudges) cannot be calibrated on this file. Real VN e-wallet data would show Tết and double-day spikes, so this is also a quick realism check for any future extract.
- **Confidence: high.**

### 9. New-user inflow is an exact exponential plus noise, except for one shock in Oct-24
- **Numbers.**
  - Poisson GLM: −4.7% a month.
  - Pearson dispersion 1.89 overall (p = 0.017), but **1.01 without Oct-24 (p = 0.44)**.
  - Oct-24 has 1,063 new users vs 939 predicted (z = +3.8). It is the only month that is more than noise.
  - Every other month's residual is within ±2.0.
- **So what.**
  - The decline is a smooth programmed decay. Nothing in the extract (mix, limits, tickets, timing) explains it.
  - Oct-24 is the single real "event" in the inflow and is worth asking Growth about (campaign?).
  - This partly overlaps the existing Q1b note (+13%) but adds that the rest is pure noise.
- **Confidence: high** (statistics); possible overlap with the behaviour workstream.

### 10. `transaction_id` is a row number, not a system ID
- **Numbers.**
  - IDs run 1–204,590 in (user_id, date) order: TXN00000001 is user 100000's first purchase, whenever that happened.
  - Within a user, dates never decrease (0 cases).
  - The file is sorted by date with a random order inside each day (0 of 547 days follow ID order).
- **So what.** Never use transaction_id for time ordering, deduplication across users or incremental loads. The 104 rows prove that rows were appended after ID assignment.
- **Confidence: high.**

### 11. The "at-limit raises churn" signal is fragile
- **Numbers.** See Part 1, #26: +0.21 log-odds (p = 0.02) pooled, driven by 2024 (p = 0.02) and absent in 2025 (p = 0.61). No gradient (≥80% p = 0.36; continuous p = 0.32).
- **So what.** Because the balance is synthetic (finding 1), do not quote "maxing out adds churn" as a driver.
- **Confidence: low** that the effect is real.

---

## Part 3. Checked and found nothing
- Amount vs package, carrier, limit decile, day of week, day of month, month, tenure, transaction index, user_id decile, monthly frequency: η² ≤ 0.00013, all p ≥ 0.08.
- Pay-down event vs the same 10 features: all p ≥ 0.04 (one of ten at 0.043, as expected by chance).
- Pay-down autocorrelation within user: 34.9% vs 35.0%. Per-user heterogeneity: none (dispersion 0.998).
- Pay-down vs time since last purchase: χ² p = 0.92; vs month boundary: 34.9% vs 35.1%.
- Round-number or denomination heaping in amounts (Telco and Voucher included): none.
- Last digits of amounts once the two clipped values are excluded: uniform (p = 0.11).
- Missing calendar days: none (547/547).
- Holiday, e-commerce double-day and payday effects: none significant.
- Day-of-week effect: ±1.7%, p = 0.056.
- Same-day purchase pairs within a user-month: 13,231 observed vs 13,150 expected from uniform placement.
- user_id vs cohort, limit, activity: \|ρ\| ≤ 0.012, all p ≥ 0.12.
- Limit vs cohort: Kruskal–Wallis p = 0.68.
- Package/carrier mix drift over 18 months: max 1.2pp.
- Carrier habit decaying with time: none (39.9% → 40.4%).
- Balance above the limit: 0 rows. Pre-existing balances at entry: 0 users.
- Same user + day + amount excess (after the limit-specific correction): p = 0.19.
- The 104 injected users vs the 475 eligible: no difference in limit, cohort or first day.
- Near-limit (≥80%) or continuous utilisation as a churn signal: none.

---

## Part 4. Script

- **Script:** `FINAL_solution/eda/data_forensics/data_forensics.py`
- **Run:** `python3 -I data_forensics.py [path/to/data.csv]`. The default path is `data.csv` in the project root. It takes about 60 seconds and needs pandas, numpy, scipy, statsmodels and scikit-learn.
- **Outputs (next to the script):**
  - `eda_numbers.json`: 232 numbers, including every number quoted above;
  - `tables/*.csv`: 16 tables (pay-down by gap, headroom vs amount, balance/utilisation by limit band, 60% pile-up, dependence screen, user-level Spearman, users per limit level, day-of-month index, holiday effects, first-day vs order-statistic model, N0/N1 by first-day band, pair counts, package share vs carrier count, pair stickiness, Other-services co-usage);
  - `run_log.txt`: the full printed output.
- **Sections:**
  - 0 load and flags;
  - 1 balance rule;
  - 2 amount;
  - 3 dependence screen;
  - 4 limit;
  - 5 dates (calendar, order-statistic test, M0 = M1);
  - 6 IDs;
  - 7 package×carrier;
  - 8 the 104 rows;
  - 9 re-checks of existing claims (duplicate, same-day pairs, at-limit churn, hungry users, first-day vs M1, inflow fit).
- **Read-only:** nothing under `FINAL_solution/` or `My_solution/` was modified.
