# BNPL take-home: complete reference solution (final version)

This version merges two independent AI solutions: `../AI_solution` (Claude) and `../My_solution` (Codex). It takes the stronger analysis from each and fixes the points each review raised. `../REVIEW_CODEX_vs_CLAUDE.md` explains what came from where.

| Open this | For |
|---|---|
| `report.html` | **Main deliverable.** The analysis told as one story: answer first, 8 chapters with a "bottom line" each, evidence in expandable boxes. Tags show which brief question each chapter answers. Source: `report_src.html` |
| `report_concise.html` / `REPORT_CONCISE.md` | **Short version.** Answers every required question, chooses Part 2 Option A, and keeps the key evidence and caveats. Built by `build_concise.py`; the original report is untouched. |
| `report_visual.html` | **Chart-led story (~3,100 words, 15 charts; prints on ~19 A4 pages).** Same 8 chapters as `report.html`, told through charts with one-line takeaways; source `report_visual_src.html`, extra charts from `visual_charts.py` |
| `report_concise.html` | **Short version (~1,800 words, 7 charts).** Every brief question answered in a few bullets; source `report_concise_src.html` |
| `report_by_question.html` / `REPORT.md` | The same analysis organised question by question (Q1a, Q1b, Q1c, Part 2, Part 3, Bonus), handy for grading against the brief |
| `one_pager.html` | Part 3 one-pager for the Business Lead (prints on one A4 page) |
| `outputs/key_numbers.json` | Every number quoted in the report |
| `outputs/tables/` | All tables: `q1*` retention, `p2*` churn, `x*` extended findings, `m*` merged angles, `dq*` data quality |
| `outputs/charts/` | All charts (fig1–fig13, plus the six one-pager charts `op1`–`op6` from `onepager_charts.py`) |
| `eda/data_forensics/`, `eda/behaviour/` | Two independent deep-EDA reviews (column-level forensics; behaviour and segments): report, script and outputs each. Their headline numbers are recomputed in `analysis.py` section 7e |
| `outputs/pilot/` | Dry-run assignments for the two pilots (simulation only) |

```bash
pip install pandas numpy scipy statsmodels scikit-learn matplotlib markdown beautifulsoup4
python3 FINAL_solution/analysis.py                          # about 20 s
python3 FINAL_solution/build_html.py
python3 FINAL_solution/build_concise.py
python3 FINAL_solution/pilot.py dry-run --test B --month 2025-05
```

## Key decisions

- **Retention:** at least one purchase in calendar month cohort + k.
- **Data cleaning:** the 104 suspect rows (TXN00204591–TXN00204694) were built from each user's own rows and are excluded permanently; every headline is also shown on the delivered file (Appendix A2). Only Q1c's exact-N = 4 cell depends on that choice.
- **Simulated extract:** balances, amounts, limits, merchant mix and timing follow simple generating rules (Bonus part G / Chapter 8), so no credit, ticket, category or timing conclusion is drawn from them.
- **Recommendations:** each one comes with a randomised test design (2.6). Sizes in 2.5 are illustrations, not forecasts.
- **Story checks:** `build_html.py` refuses to build `report.html` if a headline number in `report_src.html` no longer matches `key_numbers.json`.
