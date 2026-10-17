"""
Extra charts for the chart-led story (report_visual.html). They replace tables and paragraphs of the full
story with one picture each. Reads the tables written by analysis.py; build_html.py calls main().
Same palette and mark style as analysis.py.
"""

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm

HERE = Path(__file__).resolve().parent
TBL = HERE / "outputs" / "tables"
FIG = HERE / "outputs" / "charts"
K = json.loads((HERE / "outputs" / "key_numbers.json").read_text())

SURFACE, INK, INK2, MUTED = "#fcfcfb", "#0b0b0b", "#52514e", "#898781"
GRID, BASE = "#e1e0d9", "#c3c2b7"
BLUE, ORANGE, AQUA, YELLOW = "#2a78d6", "#eb6834", "#1baf7a", "#eda100"
GRAY = "#c3c2b7"

STYLE = {
    "font.family": ["Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"],
    "font.size": 10, "axes.facecolor": SURFACE, "figure.facecolor": SURFACE,
    "axes.edgecolor": BASE, "axes.labelcolor": INK2, "axes.titlecolor": INK,
    "axes.titlesize": 12, "axes.titleweight": "semibold", "axes.titlelocation": "left", "axes.titlepad": 12,
    "xtick.color": MUTED, "ytick.color": MUTED, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8,
    "axes.axisbelow": True, "legend.frameon": False, "lines.linewidth": 2, "lines.solid_capstyle": "round",
    "savefig.dpi": 170, "savefig.bbox": "tight",
}
plt.rcParams.update(STYLE)


def tidy(ax, ygrid=True, xgrid=False):
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(BASE)
    ax.grid(axis="x", visible=xgrid)
    ax.grid(axis="y", visible=ygrid)
    ax.tick_params(length=0)


def pct_axis(ax, lo, hi, axis="y"):
    fmt = matplotlib.ticker.PercentFormatter(1.0, decimals=0)
    if axis == "y":
        ax.set_ylim(lo, hi)
        ax.yaxis.set_major_formatter(fmt)
    else:
        ax.set_xlim(lo, hi)
        ax.xaxis.set_major_formatter(fmt)


def caption(fig, text):
    fig.text(0.0, -0.02, text, ha="left", va="top", fontsize=8.5, color=MUTED, wrap=True)


def bump_text(fig):
    """Wide charts are shown ~7in wide on an A4 page or in the report column: scale their text up so it stays readable."""
    f = min(1.35, max(1.0, fig.get_figwidth() / 9))
    if f == 1.0:
        return
    tick_labels = set()
    for ax in fig.axes:
        for axis, name in ((ax.xaxis, "x"), (ax.yaxis, "y")):
            ticks = axis.get_major_ticks() + axis.get_minor_ticks()
            tick_labels.update(t for tk in ticks for t in (tk.label1, tk.label2))
            if ticks:
                ax.tick_params(axis=name, which="both", labelsize=ticks[0].label1.get_fontsize() * f)
    for t in fig.findobj(matplotlib.text.Text):
        if t not in tick_labels:
            t.set_fontsize(t.get_fontsize() * f)


def save(fig, name):
    bump_text(fig)
    fig.tight_layout()
    fig.savefig(FIG / name)
    plt.close(fig)


MONTHS = pd.read_csv(TBL / "q1b_monthly_dynamics.csv", index_col=0)
TICKS = {0: "Jan 24", 6: "Jul 24", 12: "Jan 25", 17: "Jun 25"}


def v1_inflow():
    """New users: smooth exponential decline (one outlier); replaying history with more inflow removes the MAU decline."""
    new = MONTHS["new"].values
    x = np.arange(len(new), dtype=float)
    glm = sm.GLM(new, sm.add_constant(x), family=sm.families.Poisson()).fit()
    fit = glm.predict(sm.add_constant(x))
    oct_i = list(MONTHS.index).index("2024-10")

    coh = pd.read_csv(TBL / "q1b_cohort_retention_users.csv", index_col=0)
    target_oct = coh.loc["2024-10", "cohort_size"]
    target_24 = coh.loc[[c for c in coh.index if c.startswith("2024")], "cohort_size"].mean()
    months = list(MONTHS.index)
    start = months.index("2024-11")

    def replay(target):
        out = MONTHS["mau"].astype(float).copy()
        for c in months[start:]:
            extra = target - coh.loc[c, "cohort_size"]
            for t in range(months.index(c), len(months)):
                out.iloc[t] += extra * coh.loc[c, str(t - months.index(c))]
        return out

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.1))
    ax = axes[0]
    colors = [ORANGE if i == oct_i else BLUE for i in range(len(new))]
    ax.bar(x, new, width=0.7, color=colors)
    ax.plot(x, fit, color=INK2, linewidth=1.5, linestyle=(0, (4, 3)))
    ax.text(14.5, 1010, f"trend: −{abs(K['f_inflow_monthly_change']) * 100:.1f}% a month", ha="center", fontsize=9, color=INK2)
    ax.annotate(f"Oct 2024: {new[oct_i]:,} vs ~{round(fit[oct_i] / 10) * 10:,.0f} expected\nthe only month above trend (z = +{K['f_oct24_z']:.1f})",
                (oct_i, new[oct_i]), xytext=(oct_i - 0.2, 1330), fontsize=8.5, color=INK, ha="center",
                arrowprops=dict(arrowstyle="-", color=MUTED, lw=0.8))
    ax.set_xticks(list(TICKS), list(TICKS.values()))
    ax.set_ylim(0, 1550)
    ax.set_title("New users fall a steady 4.7% a month")
    tidy(ax)

    ax = axes[1]
    a_oct, a_24 = replay(target_oct), replay(target_24)
    ax.plot(x, MONTHS["mau"].values, color=INK2, linewidth=2.2)
    ax.plot(x[start - 1:], a_24.values[start - 1:], color=AQUA, linewidth=2)
    ax.plot(x[start - 1:], a_oct.values[start - 1:], color=BLUE, linewidth=2)
    ax.text(17.3, a_24.iloc[-1], f"2024-average inflow: ~{round(a_24.iloc[-1] / 10) * 10:,.0f}", va="center", fontsize=9, color=INK)
    ax.text(17.3, a_oct.iloc[-1] - 60, f"Oct 2024 inflow: ~{round(a_oct.iloc[-1] / 10) * 10:,.0f}", va="center", fontsize=9, color=INK)
    ax.text(17.3, MONTHS["mau"].iloc[-1], f"actual: {MONTHS['mau'].iloc[-1]:,}", va="center", fontsize=9, color=INK)
    ax.set_xlim(-0.5, 23.5)
    ax.set_xticks(list(TICKS), list(TICKS.values()))
    ax.set_ylim(0, 5200)
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax.set_title("Same retention, more new users: no decline")
    tidy(ax)
    ax.spines["bottom"].set_bounds(-0.5, 17.5)
    caption(fig, "Right: each cohort keeps its own observed retention; only the size of the Nov-24 to Jun-25 cohorts is changed. "
                 "An in-sample accounting check, not a forecast.")
    save(fig, "fig_v1_inflow_trend_and_replay.png")


def v2_q1c():
    q = pd.read_csv(TBL / "q1c_m1_by_first_month_txns.csv").iloc[:8]
    scan = pd.read_csv(TBL / "q1c_threshold_scan.csv")
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.2))
    ax = axes[0]
    ax.fill_between(q["N"], q["ci_low"], q["ci_high"], color=BLUE, alpha=0.10, linewidth=0)
    ax.plot(q["N"], q["m1_raw"], color=ORANGE, marker="o", markersize=6, markeredgecolor=SURFACE, markeredgewidth=1.5, label="As delivered")
    ax.plot(q["N"], q["m1_clean"], color=BLUE, marker="o", markersize=6, markeredgecolor=SURFACE, markeredgewidth=1.5, label="Clean (104 suspect rows removed)")
    ax.annotate("82.1%: created by\nthe 104 suspect rows", (4, q.loc[3, "m1_raw"]), xytext=(4.6, 0.835), fontsize=8.5, color=INK,
                arrowprops=dict(arrowstyle="-", color=MUTED, lw=0.8))
    pct_axis(ax, 0.6, 0.9)
    ax.set_xticks(range(1, 9))
    ax.set_xlabel("Purchases in the first calendar month (N)")
    ax.set_title("Active in M1, by first-month purchases")
    ax.legend(loc="lower right", fontsize=8.5)
    tidy(ax)
    ax = axes[1]
    for data, col, lab in (("raw", ORANGE, "As delivered"), ("clean", BLUE, "Clean")):
        s = scan[(scan["data"] == data) & scan["N"].between(2, 8)]
        ax.plot(s["N"], s["lift_pp"], color=col, marker="o", markersize=6, markeredgecolor=SURFACE, markeredgewidth=1.5, label=lab)
    c = scan[(scan["data"] == "clean") & scan["N"].between(2, 8)]
    ax.axhspan(c["lift_pp"].min(), c["lift_pp"].max(), color=BLUE, alpha=0.08, linewidth=0)
    ax.text(8.3, c["lift_pp"].mean(), f"any N from 2 to 8:\n+{c['lift_pp'].min():.1f} to +{c['lift_pp'].max():.1f}pp", va="center", fontsize=8.5, color=INK)
    ax.set_xlim(1.6, 9.8)
    ax.set_ylim(0, 10)
    ax.set_xticks(range(2, 9))
    ax.set_xlabel("Cut-off N (users with ≥ N vs < N)")
    ax.set_ylabel("Gap in M1 (pp)")
    ax.set_title("No cut-off is special once the suspect rows go")
    ax.legend(loc="lower left", fontsize=8.5)
    tidy(ax)
    caption(fig, "Users from the Jan-24 to May-25 cohorts; shaded band left = 95% Wilson CI. "
                 "In this file the first calendar month behaves like a full month (Chapter 8).")
    save(fig, "fig_v2_q1c_threshold.png")


def v3_churn_profile_and_silence():
    m = pd.read_csv(TBL / "p2_profile_month_level.csv", index_col=0)
    u = pd.read_csv(TBL / "p2_profile_user_level.csv", index_col=0)
    rows = [
        ("Share of 1-purchase months", m.loc["share_1_txn"].iloc[1] / m.loc["share_1_txn"].iloc[0] - 1, True),
        ("Purchases in the month", m.loc["avg_txns"].iloc[1] / m.loc["avg_txns"].iloc[0] - 1, True),
        ("Purchases in the first month", u.loc["first_month_txns"].iloc[1] / u.loc["first_month_txns"].iloc[0] - 1, True),
        ("2nd purchase within 30 days", u.loc["share_2plus_txn_first_30d"].iloc[1] / u.loc["share_2plus_txn_first_30d"].iloc[0] - 1, True),
        ("Merchant categories used", m.loc["merchant_categories"].iloc[1] / m.loc["merchant_categories"].iloc[0] - 1, False),
        ("Average ticket", m.loc["avg_ticket"].iloc[1] / m.loc["avg_ticket"].iloc[0] - 1, False),
        ("Credit limit", m.loc["credit_limit"].iloc[1] / m.loc["credit_limit"].iloc[0] - 1, False),
    ]
    sil = pd.read_csv(TBL / "p2_lapse_signal.csv")
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.2), gridspec_kw={"width_ratios": [1.15, 1]})
    ax = axes[0]
    y = np.arange(len(rows))[::-1]
    vals = [v for _, v, _ in rows]
    ax.barh(y, vals, height=0.6, color=[BLUE if f else GRAY for _, _, f in rows])
    for yi, v in zip(y, vals):
        ax.text(v + (0.008 if v >= 0 else -0.008), yi, f"{v * 100:+.0f}%", va="center", ha="left" if v >= 0 else "right", fontsize=9, color=INK)
    ax.axvline(0, color=INK2, linewidth=0.8)
    ax.set_yticks(y, [r for r, _, _ in rows])
    pct_axis(ax, -0.25, 0.35, axis="x")
    ax.set_title("Churners vs stayers: only frequency differs")
    tidy(ax, ygrid=False, xgrid=True)
    ax = axes[1]
    ax.plot(sil["day"], sil["share_silent"], color=GRAY, marker="o", markersize=6, markeredgecolor=SURFACE, markeredgewidth=1.5)
    ax.plot(sil["day"], sil["p_lost_for_good"], color=ORANGE, marker="o", markersize=6, markeredgecolor=SURFACE, markeredgewidth=1.5)
    d15 = sil[sil["day"] == 15].iloc[0]
    ax.axvline(15, color=BASE, linewidth=1)
    ax.text(15.4, d15["p_lost_for_good"] - 0.08, f"day 15: {d15['share_silent'] * 100:.0f}% still silent,\n"
            f"{d15['p_lost_for_good'] * 100:.0f}% of them lost", fontsize=8.5, color=INK)
    ax.text(25.4, sil["share_silent"].iloc[-1], "still silent", va="center", fontsize=9, color=INK2)
    ax.text(25.4, sil["p_lost_for_good"].iloc[-1], "of those, lost", va="center", fontsize=9, color=INK2)
    ax.axhline(K["overall_monthly_churn"], color=INK2, linewidth=0.8, linestyle=(0, (3, 2)))
    ax.text(5, K["overall_monthly_churn"] + 0.02, "average churn 25%", fontsize=8.5, color=INK2)
    ax.set_xlim(4, 30)
    ax.set_xticks([5, 10, 15, 20, 25])
    pct_axis(ax, 0, 1)
    ax.set_xlabel("Day of the following month")
    ax.set_title("Silence by mid-month is the trigger")
    tidy(ax)
    caption(fig, "Left: churned = the month before leaving; stayed = months followed by more activity (user-level rows for first month and 2nd purchase). "
                 "Blue = frequency measures. Right: last month's active users with no purchase yet by day d.")
    save(fig, "fig_v3_churner_profile_and_silence.png")


def v5_levers_users():
    sz = pd.read_csv(TBL / "p2_action_sizing.csv")
    lab = {
        "Recover new users to the 2024 average": ("New users back to 2024 level", BLUE),
        "Frequency rewards for light users": ("Frequency rewards (if light users churn like heavy)", AQUA),
        "Mid-month reminder to silent users": ("Mid-month reminder (saves 1 in 10 would-be churners)", AQUA),
        "Second-purchase offer for new users": ("Second-purchase nudge (if every 1-purchase user buys again)", AQUA),
        "Win-back of dormant users (illustration)": ("Win-back 1% a month (response unknown)", GRAY),
    }
    s = sz[sz["action"].isin(lab)].copy()
    s["label"] = s["action"].map(lambda a: lab[a][0])
    s["color"] = s["action"].map(lambda a: lab[a][1])
    s = s.sort_values("extra_active_users_jun26")
    fig, ax = plt.subplots(figsize=(12, 3.4))
    ax.barh(range(len(s)), s["extra_active_users_jun26"], height=0.6, color=s["color"])
    for i, v in enumerate(s["extra_active_users_jun26"]):
        ax.text(v + 25, i, f"+{round(v / 10) * 10:,.0f}", va="center", fontsize=9.5, color=INK)
    ax.set_yticks(range(len(s)), s["label"])
    ax.set_xlim(0, 2500)
    ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax.set_xlabel("Extra active users by Jun 2026, vs new users holding flat (~2,450)")
    ax.set_title("Inflow is the biggest lever; each retention lever, as assumed here, is far smaller")
    tidy(ax, ygrid=False, xgrid=True)
    caption(fig, "Illustrative assumptions (in brackets), not estimated effects or upper bounds; before incentive cost and credit losses. Blue = acquisition, aqua = retention, grey = untested.")
    save(fig, "fig_v5_levers_in_users.png")


def v6_segments():
    g = pd.read_csv(TBL / "g1_segment_growth.csv")
    v = pd.read_csv(TBL / "x2_segment_value_last6m.csv")
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.0))
    ax = axes[0]
    x = np.arange(len(g))
    ax.bar(x - 0.19, g["users_jun24"], width=0.36, color=GRAY, label="Jun 2024")
    ax.bar(x + 0.19, g["users_jun25"], width=0.36, color=BLUE, label="Jun 2025")
    for xi, (a, b, ch) in enumerate(zip(g["users_jun24"], g["users_jun25"], g["users_change"])):
        ax.text(xi + 0.19, b + 25, f"{ch * 100:.0f}%", ha="center", fontsize=9.5, color=INK)
    ax.set_xticks(x, g["segment"])
    ax.set_ylim(0, 1700)
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax.set_title("Active users by segment: every one is shrinking")
    ax.legend(loc="upper left", fontsize=8.5)
    tidy(ax)
    ax = axes[1]
    ax.bar(x - 0.19, v["share_user_months"], width=0.36, color=GRAY, label="Share of active users")
    ax.bar(x + 0.19, v["share_gmv"], width=0.36, color=BLUE, label="Share of GMV")
    for xi, (a, b) in enumerate(zip(v["share_user_months"], v["share_gmv"])):
        ax.text(xi - 0.19, a + 0.015, f"{a * 100:.0f}%", ha="center", fontsize=9, color=INK2)
        ax.text(xi + 0.19, b + 0.015, f"{b * 100:.0f}%", ha="center", fontsize=9, color=INK)
    ax.set_xticks(x, v["seg"])
    pct_axis(ax, 0, 0.75)
    ax.set_title("Heavy users carry two thirds of GMV")
    ax.legend(loc="upper left", fontsize=8.5)
    tidy(ax)
    caption(fig, "Segments by purchases in the month: light 1, medium 2–3, heavy 4+. Right: last 6 months (Jan–Jun 2025).")
    save(fig, "fig_v6_segments.png")


def main():
    # build_html imports onepager_charts too, whose print-size rcParams (6pt ticks) would leak into these charts
    matplotlib.rcdefaults()
    plt.rcParams.update(STYLE)
    v1_inflow()
    v2_q1c()
    v3_churn_profile_and_silence()
    v5_levers_users()
    v6_segments()


if __name__ == "__main__":
    main()
