"""Build the short, standalone report without changing the original report."""

from __future__ import annotations

import base64
import json
import re
from pathlib import Path

import markdown
from bs4 import BeautifulSoup

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "REPORT_CONCISE.md"
TARGET = HERE / "report_concise.html"
K = json.loads((HERE / "outputs" / "key_numbers.json").read_text())


def check_source(md: str) -> None:
    expected = {
        f"**{K['mau_last']:,}**": "Jun 2025 MAU",
        f"**{K['new_users_last']:,}**": "Jun 2025 first-time users",
        f"**{K['avg_user_retention_M1']:.1%}**": "M1 retention",
        f"**{K['avg_user_retention_M12']:.1%}**": "M12 retention",
        f"**{K['q1c_m1_clean_N4']:.1%}**": "clean N=4 retention",
        f"**{K['q1c_m1_raw_N4']:.1%}**": "raw N=4 retention",
        f"**{K['lapsed_users_with_a_chance_to_return']:,}**": "observable lapsed users",
    }
    missing = [name for token, name in expected.items() if token not in md]
    if missing:
        raise SystemExit("Concise report headline mismatch: " + ", ".join(missing))
    image_paths = re.findall(r"!\[[^]]*\]\(([^)]+)\)", md)
    missing_images = [p for p in image_paths if not (HERE / p).exists()]
    if missing_images:
        raise SystemExit("Missing chart(s): " + ", ".join(missing_images))


def inline_image(match: re.Match[str]) -> str:
    path = HERE / match.group(1)
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f'src="data:image/png;base64,{data}"'


CSS = r"""
:root{--ink:#172323;--muted:#5d6a68;--accent:#08745f;--paper:#fff;--soft:#eaf5f0;--line:#dce5e1}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;background:#f3f5f3;color:var(--ink);font:16px/1.5 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
main{max-width:860px;margin:28px auto 64px;padding:42px 58px;background:var(--paper);box-shadow:0 2px 20px #18312b12}
h1,h2,h3{line-height:1.22;letter-spacing:-.025em}
h1{font-size:2.25rem;margin:0 0 8px} h2{font-size:1.44rem;border-top:1px solid var(--line);padding-top:24px;margin:34px 0 14px}
h3{font-size:1.08rem;margin:25px 0 8px}
p{margin:9px 0 12px} p:first-of-type{color:var(--muted)}
strong{font-weight:700} a{color:var(--accent);text-underline-offset:2px}
blockquote{margin:22px 0;padding:12px 18px;border-left:4px solid var(--accent);background:var(--soft);font-size:1.04rem}
blockquote p{margin:0;color:var(--ink)!important}
table{width:100%;border-collapse:collapse;font-size:.91rem;margin:14px 0 18px;font-variant-numeric:tabular-nums}
th,td{text-align:left;vertical-align:top;border-bottom:1px solid var(--line);padding:9px 11px}
th{background:#f2f6f3;color:#365047;font-weight:650}
tr:nth-child(even) td{background:#fafcfa}
th:not(:first-child),td:not(:first-child){text-align:right}
main>table:first-of-type th,main>table:first-of-type td{text-align:center}
.part2-table th:last-child,.part2-table td:last-child{text-align:left}
.part3-table th,.part3-table td{text-align:left}
ol,ul{padding-left:24px;margin:10px 0 16px}li{margin:6px 0}
img{display:block;max-width:100%;height:auto;margin:20px auto 24px;border:1px solid var(--line);border-radius:8px}
code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;background:#f1f5f2;padding:1px 4px;border-radius:3px}
nav{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 28px;font-size:.83rem}
nav a{padding:5px 9px;border:1px solid var(--line);border-radius:5px;text-decoration:none;background:white}
nav a:hover{background:var(--soft)}
hr{border:0;border-top:1px solid var(--line)}
@media(max-width:680px){body{background:#fff}main{margin:0;padding:24px 18px;box-shadow:none}h1{font-size:1.85rem}table{font-size:.8rem}th,td{padding:7px 5px}nav{gap:5px}}
@media print{body{background:white;font-size:10.5pt}main{max-width:none;margin:0;padding:0;box-shadow:none}nav{display:none}h2{break-after:avoid}table,img,blockquote{break-inside:avoid}a{color:inherit;text-decoration:none}img{max-height:330px;object-fit:contain}#part3{break-before:page}}
"""


def main() -> None:
    source = SOURCE.read_text()
    check_source(source)
    content = markdown.markdown(source, extensions=["tables", "sane_lists"])
    soup = BeautifulSoup(content, "html.parser")
    for anchor in soup.select("p > a[id]"):
        heading = anchor.parent.find_next_sibling("h2")
        if heading is not None:
            heading["id"] = anchor["id"]
            anchor.parent.decompose()
    for table in soup.find_all("table"):
        heading = table.find_previous("h2")
        if heading and heading.get("id") == "part2":
            table["class"] = "part2-table"
        elif heading and heading.get("id") == "part3":
            table["class"] = "part3-table"
    content = str(soup)
    content = re.sub(r'src="(outputs/charts/[^"]+\.png)"', inline_image, content)
    nav = '<nav aria-label="Report sections">' + "".join(
        f'<a href="#{anchor}">{label}</a>' for anchor, label in [
            ("data", "Data"), ("q1a", "Q1a"), ("q1b", "Q1b"),
            ("q1c", "Q1c"), ("part2", "Part 2"), ("part3", "Part 3"),
            ("bonus", "Bonus")]) + '</nav>'
    page = ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            "<title>BNPL Retention — Concise Report</title><style>" + CSS +
            "</style></head><body><main>" + nav + content + "</main></body></html>")
    TARGET.write_text(page)
    word_count = len(re.findall(r"\b\w+\b", re.sub(r"<[^>]+>", " ", content)))
    print(f"Built {TARGET.name}: {word_count} words, {len(page):,} HTML characters")


if __name__ == "__main__":
    main()
