"""
Builds the shareable, self-contained HTML deliverables (charts embedded as base64):
  - report.html     <- REPORT.md
  - one_pager.html  <- Part 3 one-pager for the Business Lead (A4, print-ready)

Run after analysis.py:  python3 AI_solution/build_html.py
"""

import base64
import json
import re
from pathlib import Path

import markdown

HERE = Path(__file__).resolve().parent
K = json.loads((HERE / "outputs" / "key_numbers.json").read_text())


def data_uri(rel_path: str) -> str:
    b64 = base64.b64encode((HERE / rel_path).read_bytes()).decode()
    return f"data:image/png;base64,{b64}"


BASE_CSS = """
:root{
  --bg:#f9f9f7; --surface:#fcfcfb; --ink:#0b0b0b; --ink-2:#52514e; --muted:#898781;
  --rule:#e1e0d9; --accent:#2a78d6; --accent-soft:#e8f1fc; --warn:#b4541f;
  color-scheme: light;
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --bg:#0d0d0d; --surface:#1a1a19; --ink:#ffffff; --ink-2:#c3c2b7; --muted:#898781;
    --rule:#2c2c2a; --accent:#3987e5; --accent-soft:#16263a; --warn:#ec835a; color-scheme: dark;
  }
}
:root[data-theme="dark"]{
  --bg:#0d0d0d; --surface:#1a1a19; --ink:#ffffff; --ink-2:#c3c2b7; --muted:#898781;
  --rule:#2c2c2a; --accent:#3987e5; --accent-soft:#16263a; --warn:#ec835a; color-scheme: dark;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
  font:16px/1.6 system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;}
img{max-width:100%;height:auto;border-radius:8px;background:#fcfcfb}
a{color:var(--accent)}
"""

REPORT_CSS = BASE_CSS + """
main{max-width:920px;margin:0 auto;padding:40px 16px 80px}
h1{font-size:1.9rem;line-height:1.2;margin:0 0 8px}
h2{font-size:1.4rem;margin:48px 0 12px;padding-top:16px;border-top:1px solid var(--rule)}
h3{font-size:1.12rem;margin:32px 0 8px}
p,li{color:var(--ink)}
hr{border:0;border-top:1px solid var(--rule);margin:32px 0}
blockquote{margin:16px 0;padding:12px 16px;background:var(--accent-soft);border-left:3px solid var(--accent);border-radius:6px}
blockquote p{margin:4px 0}
code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.88em;background:var(--accent-soft);padding:1px 5px;border-radius:4px}
.table-wrap{overflow-x:auto;margin:12px 0 20px}
table{border-collapse:collapse;width:100%;font-size:.9rem;font-variant-numeric:tabular-nums}
th,td{padding:7px 10px;border-bottom:1px solid var(--rule);text-align:left;vertical-align:top}
th{color:var(--ink-2);font-weight:600;background:var(--surface)}
em{color:var(--ink-2)}
@media print{ main{max-width:none;padding:0} h2{break-before:auto} img{break-inside:avoid} }
"""

ONEPAGER_CSS = BASE_CSS + """
.page{max-width:820px;margin:24px auto;padding:28px 32px;background:var(--surface);
  border:1px solid var(--rule);border-radius:12px}
.eyebrow{font-size:.78rem;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);margin:0 0 6px}
h1{font-size:1.55rem;line-height:1.25;margin:0 0 18px}
.kpis{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:16px}
.kpi{border:1px solid var(--rule);border-radius:10px;padding:12px 14px}
.kpi .label{font-size:.8rem;color:var(--ink-2)}
.kpi .value{font-size:1.9rem;font-weight:600;line-height:1.2;margin:2px 0}
.kpi .delta{font-size:.8rem;color:var(--warn)}
figure{margin:4px 0 14px}
figcaption{font-size:.8rem;color:var(--ink-2);margin-top:4px}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:18px}
h2{font-size:.95rem;margin:4px 0 6px;color:var(--accent)}
ul,ol{margin:0;padding-left:18px}
li{font-size:.9rem;line-height:1.45;margin-bottom:5px}
.actions{margin-top:14px}
.actions table{width:100%;border-collapse:collapse;font-size:.84rem}
.actions th,.actions td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--rule);vertical-align:top}
.actions th{color:var(--ink-2);font-weight:600}
.ask{margin-top:12px;padding:10px 14px;border-radius:8px;background:var(--accent-soft);font-size:.9rem}
.foot{margin-top:10px;font-size:.72rem;color:var(--muted)}
@media (max-width:640px){ .page{margin:0;border:0;border-radius:0;padding:20px 16px} .kpis,.cols{grid-template-columns:1fr} }
@media print{
  @page{size:A4;margin:9mm}
  body{background:#fff;font-size:13px}
  .page{max-width:none;margin:0;padding:0;border:0}
  .eyebrow{font-size:.68rem;margin-bottom:2px}
  h1{font-size:1.2rem;margin-bottom:8px}
  .kpis{gap:8px;margin-bottom:8px} .kpi{padding:6px 10px} .kpi .value{font-size:1.3rem} .kpi .label,.kpi .delta{font-size:.7rem}
  figure{margin:0 0 6px} figure img{max-height:60mm;width:auto} figcaption{font-size:.7rem}
  .cols{gap:12px} h2{font-size:.85rem;margin:2px 0 4px}
  li{font-size:.76rem;line-height:1.35;margin-bottom:3px}
  .actions{margin-top:8px} .actions table{font-size:.72rem} .actions th,.actions td{padding:4px 6px}
  .ask{margin-top:8px;padding:6px 10px;font-size:.78rem} .foot{font-size:.64rem;margin-top:6px}
}
"""


def build_report():
    md = (HERE / "REPORT.md").read_text()
    html = markdown.markdown(md, extensions=["tables", "sane_lists"])
    html = re.sub(r'src="(outputs/charts/[^"]+\.png)"', lambda m: f'src="{data_uri(m.group(1))}"', html)
    html = html.replace("<table>", '<div class="table-wrap"><table>').replace("</table>", "</table></div>")
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>BNPL Retention Analysis</title><style>{REPORT_CSS}</style></head>
<body><main>{html}</main></body></html>"""
    (HERE / "report.html").write_text(page)


def build_one_pager():
    k = K
    pct = lambda x: f"{abs(x) * 100:.0f}%"
    r50 = lambda v: f"{round(v / 50) * 50:,.0f}"
    r10 = lambda v: f"{round(v / 10) * 10:,.0f}"
    sz = {key_.split("_", 2)[2]: v for key_, v in k.items() if key_.startswith("sizing_")}
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>BNPL Business Update</title><style>{ONEPAGER_CSS}</style></head>
<body><div class="page">
<p class="eyebrow">BNPL credit line · Business update · Data Jan 2024 to Jun 2025</p>
<h1>BNPL is shrinking because fewer new users join, not because users leave faster</h1>

<div class="kpis">
  <div class="kpi"><div class="label">Active users, Jun 2025</div><div class="value">{k['mau_last']:,}</div>
    <div class="delta">down {pct(k['mau_change_from_peak'])} from Jul–Oct 2024 (~{r50(k['mau_peak'])})</div></div>
  <div class="kpi"><div class="label">New users per month</div><div class="value">{k['new_users_last']:,}</div>
    <div class="delta">down {pct(k['new_users_change_q1_2024_avg_to_jun25'])} from early 2024 (~{r10(k['new_users_q1_2024_avg'])})</div></div>
  <div class="kpi"><div class="label">Active users lost every month</div><div class="value">1 in 4</div>
    <div class="delta">unchanged for 18 months, and none came back</div></div>
</div>

<figure><img src="{data_uri('outputs/charts/fig7_onepager_mau_paths.png')}" alt="Monthly active users, actual Jan 2024 to Jun 2025 and three paths to Jun 2026: new users keep falling (about {r50(k['scenario_A_mau_jun26'])}), new users stop falling (about {r50(k['scenario_B_mau_jun26'])}), new users back to 2024 level (about {r50(k['scenario_D_mau_jun26'])}).">
<figcaption>If new users keep falling at today's pace, we end Jun 2026 with about {r50(k['scenario_A_mau_jun26'])} active users.
If they just stop falling, we end with about {r50(k['scenario_B_mau_jun26'])}. Back at 2024 levels, we end with about {r50(k['scenario_D_mau_jun26'])}.</figcaption></figure>

<div class="cols">
  <div>
    <h2>What is happening</h2>
    <ul>
      <li>Active users are down {pct(k['mau_change_from_peak'])} since autumn 2024. Payment volume is down {pct(k['gmv_last_vs_peak'])} from its Nov 2024 peak.</li>
      <li>New users per month have more than halved and are still falling about 5% a month.</li>
      <li>We lose about {r50(k['users_lost_may_to_jun25'])} active users a month and gain about {r50(k['new_users_last'])}, so the base shrinks every month.</li>
      <li>Only {k['avg_user_retention_M12'] * 100:.0f}% of new users are still using BNPL a year later. None of the people who stopped came back.</li>
    </ul>
  </div>
  <div>
    <h2>Why</h2>
    <ul>
      <li><b>Fewer people are joining.</b> New users look the same as before (same credit limits, same spending); there are just fewer of them. This still needs to be confirmed against the official acquisition numbers.</li>
      <li><b>Light users leave first.</b> People who use BNPL once in a month are more likely to stop ({pct(k['churn_n1'])}) than people who use it four or more times ({pct(k['churn_n4plus'])}), and people don't use it more over time.</li>
      <li><b>Credit limits are not what holds users back.</b> Users use only about {k['median_util_end_month'] * 100:.0f}% of their limit, and limit size, purchase size and shopping category show no link to leaving. Repayment behaviour isn't in this data and still needs checking.</li>
    </ul>
  </div>
</div>

<div class="actions">
<h2>What we should do next</h2>
<table>
<tr><th>#</th><th>Action</th><th>Proposed owner</th><th>Why it matters</th></tr>
<tr><td>1</td><td><b>Find where new-user numbers fell</b> (approvals, marketing, partner traffic) and fix it</td><td>Growth + Risk</td><td>The biggest lever: about {r50(sz['recover'])} more active users by Jun 2026 than if new users just stop falling</td></tr>
<tr><td>2</td><td><b>Remind users who haven't used BNPL by mid-month</b> (test on a sample first)</td><td>CRM</td><td>6 in 10 of them would otherwise be gone for good. Saving 1 in 10 of those adds about {r10(sz['mid-month'])} active users in a year.</td></tr>
<tr><td>3</td><td><b>Reward people who use BNPL only a few times a month</b> for using it more often (test first)</td><td>Product + CRM</td><td>Occasional users leave the most. Worth up to about {r10(sz['frequency'])} active users in a year.</td></tr>
<tr><td>4</td><td><b>Ask Risk why people who stop never come back</b> (account lock?) before testing any win-back offer</td><td>Risk + CRM</td><td>About 15,000 former users; the response is unknown.</td></tr>
</table>
</div>

<div class="ask"><b>Decision needed:</b> approve the review of where new users dropped (two weeks) and the two tests (actions 2 and 3).</div>
<p class="foot">Active user = made at least one BNPL purchase that month. A data error made "4 purchases in the first month" look like a magic number.
It isn't, and the data team should fix the source. The lines above are scenarios, not forecasts. Full analysis in report.html.</p>
</div></body></html>"""
    (HERE / "one_pager.html").write_text(page)


if __name__ == "__main__":
    build_report()
    build_one_pager()
    print("Built report.html and one_pager.html")
