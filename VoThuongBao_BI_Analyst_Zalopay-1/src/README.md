# Source code

Rebuilds both deliverables from the raw data (`../Input/data.csv`).

```bash
pip install -r src/requirements.txt
python3 src/analysis.py        # all numbers, tables and charts -> src/outputs/
python3 src/build_report.py    # 1_One_Page_Summary and 2_Full_Report -> src/outputs/ (.html and .pdf)
```

| File | What it does |
|---|---|
| `analysis.py` | End-to-end analysis: data checks, cohort retention (Q1a, Q1b), the first-month threshold test (Q1c), churn and growth deep-dives (Part 2), scenarios, data forensics (Bonus). Writes every quoted number to `outputs/key_numbers.json`, plus tables and charts. |
| `visual_charts.py` | Extra charts for the full report |
| `onepager_charts.py` | The six small charts of the one-page summary, drawn at print size |
| `report_src.html` | Text of the full report; charts are referenced by file name and embedded at build time |
| `build_report.py` | Builds both deliverables as self-contained HTML, checks every quoted number against `key_numbers.json` (stops on any mismatch), and prints them to A4 PDF with headless Chrome |

Python 3.11; PDF printing needs Google Chrome (or Chromium) installed.
