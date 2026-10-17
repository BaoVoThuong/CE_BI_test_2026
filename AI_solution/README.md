# AI reference solution: BI Analyst take-home (BNPL retention & churn)

| Open this | For |
|---|---|
| `report.html` | Full answer to every question (self-contained, with charts). `REPORT.md` is the same content as Markdown. |
| `one_pager.html` | Part 3: one page for the Business Lead (prints to one A4 page) |
| `outputs/key_numbers.json` | Every number quoted in the report |
| `outputs/tables/` | Cohort matrices, Q1c tables, churn tables, scenarios, data-quality log (`dq_*.csv`) |
| `outputs/charts/` | Figures 1–7 |

## Reproduce

```bash
pip install pandas numpy scipy statsmodels scikit-learn matplotlib markdown
python3 AI_solution/analysis.py     # reads ../data.csv, writes outputs/ (about 15 s)
python3 AI_solution/build_html.py   # builds report.html and one_pager.html
```

## Key decisions

- **Retention:** at least one transaction in calendar month cohort + k. Cohort = month of first transaction.
- **Data cleaning:** 104 out-of-sequence rows (TXN00204591–TXN00204694) are quarantined. Each belongs to a user with exactly 4 transactions in M0 and lands in M1, and together they contain every hierarchy and balance inconsistency in the file. Removing them changes cohort M1 by less than 1pp. It removes the apparent "N = 4" effect in Q1c.
- **Part 2:** Option A (churn). The growth screen found no segment that outgrows the others.
