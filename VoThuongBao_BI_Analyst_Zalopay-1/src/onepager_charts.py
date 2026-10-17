"""
Six small charts for the one-page summary (1_One_Page_Summary), drawn at print size (one A4 column each).
Reads the tables written by analysis.py; build_html.py calls main() before building the page.
Chart titles live in the HTML, so each image carries only axes and direct labels.
"""

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

HERE = Path(__file__).resolve().parent
TBL = HERE / "outputs" / "tables"
FIG = HERE / "outputs" / "charts"
K = json.loads((HERE / "outputs" / "key_numbers.json").read_text())

SURFACE, INK, INK2, MUTED = "#fcfcfb", "#0b0b0b", "#52514e", "#898781"
GRID, BASE = "#e1e0d9", "#c3c2b7"
BLUE, ORANGE, AQUA, YELLOW = "#2a78d6", "#eb6834", "#1baf7a", "#eda100"
W, H = 2.47, 1.5            # inches = one column of the A4 page

plt.rcParams.update({
    "font.family": ["Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"],
    "font.size": 6.5,
    "axes.facecolor": SURFACE, "figure.facecolor": SURFACE,
    "axes.edgecolor": BASE, "axes.labelcolor": INK2,
    "xtick.color": MUTED, "ytick.color": MUTED,
    "xtick.labelsize": 6, "ytick.labelsize": 6,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.5,
    "axes.axisbelow": True, "legend.frameon": False,
    "lines.linewidth": 1.4, "lines.solid_capstyle": "round",
    "savefig.dpi": 300,
})


def tidy(ax, ygrid=True):
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(BASE)
    ax.spines["bottom"].set_linewidth(0.6)
    ax.grid(axis="x", visible=False)
    ax.grid(axis="y", visible=ygrid)
    ax.tick_params(length=0, pad=2)


def pct(ax, lo, hi, step):
    ax.set_ylim(lo, hi)
    ax.set_yticks([x / 100 for x in range(int(lo * 100), int(hi * 100) + 1, step)])
    ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0, decimals=0))


def save(fig, name, left=0.14, bottom=0.17):
    """Fixed canvas (no tight bbox) so every image prints at the same scale."""
    fig.subplots_adjust(left=left, right=0.98, top=0.95, bottom=bottom)
    fig.savefig(FIG / name)
    plt.close(fig)


def chart_mau():
    m = pd.read_csv(TBL / "q1b_monthly_dynamics.csv", index_col=0)
    x = range(len(m))
    fig, ax = plt.subplots(figsize=(W, H))
    ax.bar(x, m["returning"], width=0.72, color=BLUE, linewidth=0)
    ax.bar(x, m["new"], bottom=m["returning"], width=0.72, color=ORANGE, linewidth=0)
    ax.set_xticks([0, 6, 12, 17], ["Jan 24", "Jul 24", "Jan 25", "Jun 25"])
    ax.set_ylim(0, 5000)
    ax.set_yticks([0, 2000, 4000], ["0", "2,000", "4,000"])
    ip = int(m["mau"].values.argmax())
    ax.text(ip, m["mau"].iloc[ip] + 120, f"{m['mau'].iloc[ip]:,}", ha="center", fontsize=6, color=INK)
    ax.text(17, m["mau"].iloc[-1] + 120, f"{m['mau'].iloc[-1]:,}", ha="center", fontsize=6, color=INK, weight="bold")
    ax.text(0.3, 4650, "New users", color=ORANGE, fontsize=6.3, weight="bold")
    ax.text(5.2, 4650, "Returning users", color=BLUE, fontsize=6.3, weight="bold")
    tidy(ax)
    save(fig, "op1_mau_new_returning.png", bottom=0.12)


def chart_retention():
    coh = pd.read_csv(TBL / "q1b_cohort_retention_users.csv", index_col=0)
    avg = pd.read_csv(TBL / "q1b_average_retention_curve.csv").set_index("age")["user_retention"].loc[0:12]
    fig, ax = plt.subplots(figsize=(W, H))
    for _, row in coh.iterrows():
        y = row[[str(i) for i in range(13)]].dropna()
        if len(y) > 2:
            ax.plot(range(len(y)), y.values, color=BASE, linewidth=0.6, zorder=1)
    ax.plot(avg.index, avg.values, color=BLUE, linewidth=1.8, zorder=3)
    for k, dx, dy in ((1, 0.35, 0.03), (3, 0.35, 0.03), (6, 0.3, 0.05), (12, -0.2, 0.07)):
        ax.plot(k, avg[k], "o", color=BLUE, markersize=2.6, zorder=4)
        ax.text(k + dx, avg[k] + dy, f"{avg[k] * 100:.0f}%", fontsize=6.3, color=INK, weight="bold")
    ax.text(4.6, 0.62, "each grey line = one\nmonthly intake of new users", fontsize=5.6, color=MUTED, linespacing=1.15)
    ax.set_xticks([0, 1, 3, 6, 9, 12], ["0", "1", "3", "6", "9", "12"])
    ax.set_xlabel("Months after first purchase", fontsize=6, labelpad=2)
    pct(ax, 0, 1, 25)
    ax.set_xlim(-0.3, 12.8)
    tidy(ax)
    save(fig, "op2_retention_curves.png")


def chart_churn():
    """Next-month churn by how often a user usually buys (3-month average), the strongest churn signal."""
    t = pd.read_csv(TBL / "b_churn_by_usual_vs_this_month.csv", header=[0, 1], index_col=0)["by_3_month_average"]
    top = t.iloc[3:]
    vals = list(t["mean"].iloc[:3]) + [float((top["mean"] * top["size"]).sum() / top["size"].sum())]
    fig, ax = plt.subplots(figsize=(W, H))
    cols = [ORANGE, BLUE, BLUE, BLUE]
    ax.bar(range(4), vals, width=0.62, color=cols, linewidth=0)
    for i, v in enumerate(vals):
        ax.text(i, v - 0.012, f"{v * 100:.1f}%", ha="center", va="top", fontsize=6.3, color="white", weight="bold")
    ax.axhline(K["overall_monthly_churn"], color=INK2, linewidth=0.7, linestyle=(0, (3, 2)))
    ax.text(3.4, K["overall_monthly_churn"] + 0.01, "average 25%", ha="right", fontsize=5.6, color=INK2)
    ax.set_xticks(range(4), ["1 or less", "1–2", "2–3", "more than 3"])
    ax.set_xlabel("Usual purchases a month (3-month average)", fontsize=6, labelpad=2)
    pct(ax, 0, 0.35, 10)
    tidy(ax)
    save(fig, "op3_churn_by_frequency.png")


def chart_q1c():
    q = pd.read_csv(TBL / "q1c_m1_by_first_month_txns.csv").iloc[:8]
    fig, ax = plt.subplots(figsize=(W, H))
    ax.fill_between(q["N"], q["ci_low"], q["ci_high"], color=BLUE, alpha=0.12, linewidth=0)
    ax.plot(q["N"], q["m1_raw"], color=ORANGE, linewidth=1.1, marker="o", markersize=2.4)
    ax.plot(q["N"], q["m1_clean"], color=BLUE, linewidth=1.6, marker="o", markersize=2.6)
    ax.annotate("82%: created by\n104 suspect rows", xy=(4, q["m1_raw"].iloc[3]), xytext=(4.9, 0.815),
                fontsize=5.8, color=ORANGE, arrowprops=dict(arrowstyle="-", color=ORANGE, lw=0.6), va="center")
    ax.text(5.0, 0.712, "clean data: gradual,\nno jump at 4", fontsize=5.8, color=BLUE, linespacing=1.15)
    ax.set_xticks(range(1, 9))
    ax.set_xlabel("Purchases in the first month", fontsize=6, labelpad=2)
    pct(ax, 0.65, 0.85, 5)
    tidy(ax)
    save(fig, "op4_first_month_purchases.png")


def chart_scenarios():
    m = pd.read_csv(TBL / "q1b_monthly_dynamics.csv", index_col=0)["mau"]
    s = pd.read_csv(TBL / "p2_mau_scenarios.csv", index_col=0).iloc[:, :4]
    n0 = len(m)
    fig, ax = plt.subplots(figsize=(W, H))
    ax.plot(range(n0), m.values, color=INK2, linewidth=1.5)
    labels = ["New users keep falling", "New users stop falling", "Stop falling + light users\nchurn like heavy users", "New users back to 2024 level"]
    cols = [ORANGE, MUTED, AQUA, BLUE]
    ends = [K["scenario_A_mau_jun26"], K["scenario_B_mau_jun26"], K["scenario_C_mau_jun26"], K["scenario_D_mau_jun26"]]
    for (name, col), lab, c, end, dy in zip(s.items(), labels, cols, ends, (0, -160, 160, 0)):
        ax.plot(range(n0 - 1, n0 + len(col)), [m.iloc[-1]] + list(col.values), color=c, linewidth=1.4, label=lab)
        ax.text(n0 + len(s) + 0.6, end + dy, f"~{round(end / 50) * 50:,.0f}", fontsize=5.8, va="center", weight="bold",
                color=c if c != MUTED else INK2)
    h, l = ax.get_legend_handles_labels()
    ax.legend(h[::-1], l[::-1], loc="lower left", bbox_to_anchor=(0.13, 0.0), fontsize=5.2, handlelength=1.1,
              handletextpad=0.4, labelspacing=0.25, borderaxespad=0.2)
    ax.axvline(n0 - 1, color=BASE, linewidth=0.6)
    ax.text(n0 - 0.5, 5150, "Jun 25", fontsize=5.4, color=MUTED, va="top")
    ax.set_xticks([0, 12, 29], ["Jan 24", "Jan 25", "Jun 26"])
    ax.set_ylim(0, 5200)
    ax.set_yticks([0, 2000, 4000], ["0", "2,000", "4,000"])
    ax.set_xlim(-0.5, n0 + len(s) + 5)
    tidy(ax)
    ax.spines["bottom"].set_bounds(-0.5, n0 + len(s))
    save(fig, "op5_scenarios.png", bottom=0.12)


def chart_levers():
    g = pd.read_csv(TBL / "g3_growth_levers_gmv.csv")
    labels = ["Back to 2024 inflow", "+100 new users a month", "Light users churn\nlike heavy users", "10% of medium users\nto 4 purchases", "10% of light users\nto 2 purchases"]
    vals = g["share_of_monthly_gmv"].values
    cols = [BLUE, BLUE, AQUA, AQUA, AQUA]
    fig, ax = plt.subplots(figsize=(W, H))
    y = list(range(len(vals)))[::-1]
    ax.barh(y, vals, height=0.62, color=cols, linewidth=0)
    for yi, v in zip(y, vals):
        ax.text(v + 0.012, yi, f"+{v * 100:.0f}%" if v >= 0.1 else f"+{v * 100:.1f}%", va="center", fontsize=6.3, color=INK, weight="bold")
    ax.set_yticks(y, labels, fontsize=5.8, color=INK2)
    ax.set_xlim(0, 0.78)
    ax.set_xticks([0, 0.25, 0.5])
    ax.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0, decimals=0))
    ax.set_xlabel("Extra monthly GMV by Jun 2026", fontsize=6, labelpad=2)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(BASE)
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", visible=True)
    ax.tick_params(length=0, pad=2)
    save(fig, "op6_gmv_levers.png", left=0.41)


def main():
    chart_mau()
    chart_retention()
    chart_churn()
    chart_q1c()
    chart_scenarios()
    chart_levers()


if __name__ == "__main__":
    main()
