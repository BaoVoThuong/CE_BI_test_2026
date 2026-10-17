"""
Builds the two deliverables from the outputs of analysis.py:
  - 1_One_Page_Summary  Part 3, one page for the Business Lead (A4)
  - 2_Full_Report       the full analysis (Part 1, Part 2, Bonus), source report_src.html
Each is written as a self-contained HTML file (charts embedded) and printed to PDF with headless Chrome.
Every number quoted in the text is checked against outputs/key_numbers.json; the build stops on any mismatch.

Run after analysis.py:  python3 src/build_report.py
"""

import base64
import json
import re
import shutil
import subprocess
from pathlib import Path

import pandas as pd

import onepager_charts
import visual_charts

HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs"
K = json.loads((OUT / "key_numbers.json").read_text())
ONE, REP = "1_One_Page_Summary", "2_Full_Report"


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


ONEPAGER_CSS = BASE_CSS + """
:root{--warn-soft:#fbeee6}
@media (prefers-color-scheme: dark){ :root:not([data-theme="light"]){--warn-soft:#2b1c13} }
:root[data-theme="dark"]{--warn-soft:#2b1c13}
.page{max-width:920px;margin:24px auto;padding:26px 30px;background:var(--surface);border:1px solid var(--rule);border-radius:12px}
.eyebrow{font-size:.74rem;letter-spacing:.07em;text-transform:uppercase;color:var(--muted);margin:0 0 6px;font-weight:600}
h1{font-size:1.5rem;line-height:1.22;margin:0 0 6px;letter-spacing:-.01em}
.sub{margin:0 0 14px;color:var(--ink-2);font-size:.95rem;line-height:1.45}
.kpis{display:grid;grid-template-columns:repeat(5,1fr);gap:8px;margin-bottom:6px}
.kpi{border:1px solid var(--rule);border-radius:9px;padding:8px 10px}
.kpi .label{font-size:.72rem;color:var(--ink-2);line-height:1.25}
.kpi .value{font-size:1.4rem;font-weight:700;line-height:1.15;margin:3px 0 2px;font-variant-numeric:tabular-nums}
.kpi .delta{font-size:.7rem;color:var(--ink-2);line-height:1.3}
.kpi .delta.bad{color:var(--warn)}
h2.band{font-size:.74rem;letter-spacing:.07em;text-transform:uppercase;color:var(--accent);margin:14px 0 8px;padding-bottom:4px;border-bottom:1px solid var(--rule)}
.grid3{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}
.mini{margin:0}
.mini h3{font-size:.86rem;line-height:1.3;margin:0 0 5px}
.side-h{font-size:.74rem;font-weight:700;color:var(--ink-2);margin:0 0 5px}
.mini img{display:block;width:100%;border-radius:6px}
.mini p{font-size:.78rem;line-height:1.42;color:var(--ink-2);margin:5px 0 0}
.bottom{display:grid;grid-template-columns:1.7fr 1fr;gap:18px}
table.act{width:100%;border-collapse:collapse;font-size:.78rem}
table.act th,table.act td{text-align:left;padding:5px 6px;border-bottom:1px solid var(--rule);vertical-align:top;line-height:1.38}
table.act th{color:var(--ink-2);font-weight:600}
table.act td:first-child{color:var(--muted);font-weight:700}
.side ul{margin:0;padding-left:16px}
.side li{font-size:.78rem;line-height:1.42;margin-bottom:5px}
.dont{margin-top:8px;padding:7px 10px;border-radius:8px;background:var(--warn-soft);font-size:.76rem;line-height:1.4}
.ask{margin-top:12px;padding:9px 12px;border-radius:8px;background:var(--accent-soft);font-size:.86rem;line-height:1.45}
.foot{margin-top:8px;font-size:.68rem;color:var(--muted);line-height:1.45}
@media screen and (max-width:760px){
  .page{margin:0;border:0;border-radius:0;padding:20px 16px}
  .kpis{grid-template-columns:repeat(2,1fr)} .grid3,.bottom{grid-template-columns:1fr}
}
@media print{
  @page{size:A4;margin:8mm}
  html,body{background:#fff}
  .page{max-width:none;margin:0;padding:0;border:0;border-radius:0;background:#fff}
  .eyebrow{font-size:6.3pt;margin-bottom:2pt}
  h1{font-size:14pt;margin-bottom:3pt}
  .sub{font-size:8.2pt;margin-bottom:6pt}
  .kpis{gap:5pt;margin-bottom:2pt} .kpi{padding:3.5pt 6pt;border-radius:6pt}
  .kpi .label{font-size:6.3pt} .kpi .value{font-size:12.5pt;margin:1pt 0} .kpi .delta{font-size:6.1pt}
  h2.band{font-size:6.8pt;margin:7pt 0 4pt;padding-bottom:2pt}
  .grid3{gap:9pt}
  .mini h3{font-size:7.8pt;margin-bottom:2pt}
  .mini p{font-size:6.8pt;line-height:1.32;margin-top:2pt}
  .bottom{gap:10pt}
  table.act{font-size:6.8pt} table.act th,table.act td{padding:2.4pt 4pt;line-height:1.3}
  .side li{font-size:6.8pt;line-height:1.32;margin-bottom:2pt} .side-h{font-size:6.8pt;margin-bottom:2pt}
  .dont{font-size:6.7pt;padding:3.5pt 6pt;margin-top:5pt}
  .ask{font-size:7.4pt;padding:4pt 8pt;margin-top:6pt}
  .foot{font-size:6pt;margin-top:4pt}
  .mini,tr,.kpi{break-inside:avoid}
}
"""


STORY_CSS = BASE_CSS + """
:root{--surface:#ffffff; --surface-2:#f2f1ec; --warn-soft:#fbeee6; --good:#13865a; --good-soft:#e6f4ed}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){--surface:#161615; --surface-2:#1f1f1d; --warn-soft:#2b1c13; --good:#3fbf8a; --good-soft:#11251b}
}
:root[data-theme="dark"]{--surface:#161615; --surface-2:#1f1f1d; --warn-soft:#2b1c13; --good:#3fbf8a; --good-soft:#11251b}
.layout{max-width:1200px;margin:0 auto;padding:0 16px;display:grid;grid-template-columns:minmax(0,1fr)}
main{max-width:820px;width:100%;padding:40px 0 96px;justify-self:center}
nav.toc{display:none}
@media (min-width:1120px){
  .layout{grid-template-columns:230px minmax(0,1fr);gap:56px}
  main{justify-self:start}
  nav.toc{display:block;position:sticky;top:0;align-self:start;max-height:100vh;overflow:auto;padding:44px 0 24px}
  .toc-mobile{display:none}
}
nav.toc p{font-size:.72rem;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);margin:0 0 10px;font-weight:600}
nav.toc ol{list-style:none;margin:0;padding:0;border-left:1px solid var(--rule)}
nav.toc a{display:block;padding:6px 0 6px 14px;margin-left:-1px;border-left:2px solid transparent;color:var(--ink-2);text-decoration:none;font-size:.88rem;line-height:1.35}
nav.toc a:hover{color:var(--ink)}
nav.toc a.active{color:var(--accent);border-left-color:var(--accent);font-weight:600}
.toc-tools{margin-top:18px;display:flex;flex-direction:column;gap:8px}
.btn{font:inherit;font-size:.8rem;padding:6px 10px;border:1px solid var(--rule);border-radius:8px;background:var(--surface);color:var(--ink-2);cursor:pointer;text-align:left;text-decoration:none}
.btn:hover{color:var(--ink);border-color:var(--muted)}
.toc-mobile{margin:0 0 24px}
h1,h2,h3,h4{letter-spacing:-.01em}
.hero{padding-bottom:8px}
.eyebrow{font-size:.75rem;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);margin:0 0 12px;font-weight:600}
.hero h1{font-size:clamp(1.9rem,4.4vw,2.8rem);line-height:1.12;margin:0 0 16px;font-weight:750}
.lede{font-size:1.15rem;line-height:1.55;color:var(--ink-2);margin:0 0 28px;max-width:44em}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin:0 0 8px}
.kpi{background:var(--surface);border:1px solid var(--rule);border-radius:12px;padding:14px 16px}
.kpi .label{font-size:.8rem;color:var(--ink-2)}
.kpi .value{font-size:2rem;font-weight:700;line-height:1.15;margin:4px 0 2px;font-variant-numeric:tabular-nums}
.kpi .delta{font-size:.8rem;color:var(--ink-2)}
.kpi .delta.bad{color:var(--warn)}
.two{display:grid;grid-template-columns:1fr;gap:14px;margin:8px 0 18px}
@media (min-width:760px){.two{grid-template-columns:1fr 1fr}}
.panel{background:var(--surface);border:1px solid var(--rule);border-radius:12px;padding:16px 18px}
.panel h3{margin:0 0 10px;font-size:1rem}
.panel.reco{border-color:var(--accent);box-shadow:inset 3px 0 0 var(--accent)}
.panel ol{margin:0;padding-left:20px} .panel li{font-size:.92rem;margin-bottom:8px;line-height:1.45}
.storyline{list-style:none;padding:0 !important;counter-reset:s}
.storyline li{counter-increment:s;position:relative;padding-left:34px}
.storyline li::before{content:counter(s);position:absolute;left:0;top:1px;width:22px;height:22px;border-radius:50%;
  background:var(--accent-soft);color:var(--accent);font-weight:700;font-size:.75rem;display:grid;place-items:center}
.storyline a{color:var(--ink);text-decoration:none} .storyline a:hover{color:var(--accent);text-decoration:underline}
.ask{margin:14px 0 0;padding:10px 14px;border-radius:8px;background:var(--accent-soft);font-size:.92rem}
section.chapter{padding-top:40px;margin-top:40px;border-top:1px solid var(--rule);scroll-margin-top:8px}
.chap-head{display:flex;flex-wrap:wrap;align-items:center;gap:10px;margin-bottom:6px}
.chap-num{font-size:.75rem;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--accent)}
.tag{font-size:.72rem;padding:2px 9px;border-radius:999px;border:1px solid var(--rule);color:var(--ink-2);background:var(--surface)}
section.chapter h2{font-size:clamp(1.4rem,2.6vw,1.75rem);line-height:1.22;margin:4px 0 16px;font-weight:700}
h3{font-size:1.12rem;margin:32px 0 10px}
h3.group{font-size:.8rem;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);margin:26px 0 10px}
p,li{line-height:1.62}
.takeaway{margin:0 0 22px;padding:14px 18px;background:var(--accent-soft);border-left:4px solid var(--accent);border-radius:0 10px 10px 0;font-size:1.04rem;line-height:1.55}
.takeaway::before{content:"Bottom line";display:block;font-size:.7rem;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--accent);margin-bottom:4px}
.sowhat{margin:24px 0 0;padding:12px 16px;border:1px dashed var(--accent);border-radius:10px}
.callout{padding:12px 16px;border-radius:10px;margin:18px 0}
.callout.caution{background:var(--warn-soft);border-left:4px solid var(--warn)}
.callout.note{background:var(--surface-2);border-left:4px solid var(--muted)}
.definition{background:var(--surface);border:1px solid var(--rule);border-radius:12px;padding:16px 18px;margin:0 0 24px}
.def-label{font-size:.72rem;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--accent);margin:0 0 6px}
.def-main{font-size:1.06rem;margin:0 0 8px}
.formula{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.86rem;background:var(--surface-2);padding:8px 12px;border-radius:8px;margin:0 0 10px;overflow-x:auto}
.why{margin:0 0 8px;padding-left:20px} .why li{font-size:.92rem;margin-bottom:4px}
.small{font-size:.85rem;color:var(--ink-2)}
.lead-small{color:var(--ink-2)}
.evidence-grid,.cards,.roadmap{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:12px;margin:18px 0}
.cards{grid-template-columns:repeat(auto-fit,minmax(280px,1fr))}
td.r{white-space:nowrap}
figure img{cursor:zoom-in}
.lightbox{position:fixed;inset:0;z-index:50;display:none;align-items:center;justify-content:center;padding:24px;background:rgba(0,0,0,.82);cursor:zoom-out}
.lightbox.open{display:flex}
.lightbox img{max-width:100%;max-height:100%;border-radius:8px;background:#fcfcfb}
.card{background:var(--surface);border:1px solid var(--rule);border-radius:12px;padding:14px 16px}
.card.warn{border-color:var(--warn);box-shadow:inset 3px 0 0 var(--warn)}
.card h4{margin:0 0 6px;font-size:.98rem;line-height:1.35}
.card p{margin:0 0 6px;font-size:.9rem;line-height:1.5}
.card ul{margin:0;padding-left:18px} .card li{font-size:.9rem;margin-bottom:6px;line-height:1.45}
.card .so{color:var(--accent);font-weight:600;margin:6px 0 0}
.when{font-size:.75rem;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--accent);margin:0 0 8px !important}
ol.findings,ol.steps{padding-left:0;list-style:none}
ol.findings{counter-reset:f} ol.findings[start="3"]{counter-reset:f 2}
ol.findings>li{counter-increment:f;position:relative;padding-left:34px;margin-bottom:12px}
ol.findings>li::before{content:counter(f);position:absolute;left:0;top:2px;width:22px;height:22px;border-radius:6px;background:var(--surface-2);
  color:var(--ink-2);font-weight:700;font-size:.75rem;display:grid;place-items:center}
ol.steps{counter-reset:st;border-left:2px solid var(--rule);margin-left:13px;padding-left:0}
ol.steps>li{counter-increment:st;position:relative;padding:0 0 14px 30px}
ol.steps>li::before{content:counter(st);position:absolute;left:-14px;top:0;width:26px;height:26px;border-radius:50%;background:var(--accent);
  color:#fff;font-weight:700;font-size:.8rem;display:grid;place-items:center}
figure{margin:26px 0}
figure img{display:block;width:100%;border:1px solid var(--rule);border-radius:10px;background:#fcfcfb}
figcaption{font-size:.88rem;color:var(--ink-2);margin-top:8px;line-height:1.5}
.table-wrap{overflow-x:auto;margin:14px 0 18px}
table{border-collapse:collapse;width:100%;font-size:.9rem;font-variant-numeric:tabular-nums}
th,td{padding:8px 10px;border-bottom:1px solid var(--rule);text-align:left;vertical-align:top}
th{color:var(--ink-2);font-weight:600;background:var(--surface-2)}
table.num td:not(:first-child),table.num th:not(:first-child),td.r,th.r{text-align:right}
tr.hl td{background:var(--accent-soft)}
tr.muted td{color:var(--muted)}
table.actions td:first-child{color:var(--muted);font-weight:700}
.donts{margin:18px 0;padding:12px 16px;border-radius:10px;background:var(--warn-soft);border-left:4px solid var(--warn)}
.donts .def-label{color:var(--warn)} .donts ul{margin:0;padding-left:18px} .donts li{font-size:.92rem}
.metrics li{margin-bottom:4px}
.answer{background:var(--surface);border:1px solid var(--rule);border-left:4px solid var(--good);border-radius:0 10px 10px 0;padding:14px 18px;margin:0 0 22px}
.answer .def-label{color:var(--good)}
.answer dl{display:grid;grid-template-columns:max-content 1fr;gap:8px 16px;margin:6px 0 0}
.answer dt{font-weight:700;color:var(--ink-2);font-size:.9rem;line-height:1.55}
.answer dd{margin:0;line-height:1.55}
@media (max-width:640px){.answer dl{grid-template-columns:1fr;gap:2px}.answer dd{margin-bottom:8px}}
.why-matters{margin:-8px 0 22px;padding-left:12px;border-left:2px solid var(--rule);color:var(--ink-2);font-size:.95rem}
table.brief td:first-child{white-space:nowrap;font-weight:600}
details.more{border:1px solid var(--rule);border-radius:10px;background:var(--surface);margin:16px 0}
details.more>summary{cursor:pointer;padding:11px 16px 11px 40px;font-weight:600;font-size:.93rem;color:var(--ink-2);list-style:none;position:relative}
details.more>summary::-webkit-details-marker{display:none}
details.more>summary::before{content:"+";position:absolute;left:14px;top:9px;width:18px;height:18px;border-radius:5px;border:1px solid var(--rule);
  display:grid;place-items:center;font-size:.85rem;color:var(--accent);line-height:1}
details.more[open]>summary::before{content:"−"}
details.more>summary:hover{color:var(--ink)}
details.more>*:not(summary){margin-left:16px;margin-right:16px}
details.more>*:last-child{margin-bottom:14px}
details.more figure{margin-top:6px}
.brief-map{margin-top:4px}
code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.85em;background:var(--surface-2);padding:1px 5px;border-radius:4px;word-break:break-word}
footer{margin-top:48px;padding-top:16px;border-top:1px solid var(--rule);font-size:.82rem;color:var(--muted)}
@media (max-width:640px){ main{padding-top:24px} .lede{font-size:1.05rem} th,td{padding:7px 8px} }
@media print{
  @page{size:A4;margin:14mm}
  body{background:#fff;font-size:12.5px}
  nav.toc,.toc-mobile,.toc-tools{display:none !important}
  .layout{display:block;max-width:none;padding:0} main{max-width:none;padding:0}
  section.chapter{break-before:page;border-top:0;margin-top:0;padding-top:0}
  figure,.card,.takeaway,table,.definition,.panel,.donts,.why-matters,.roadmap,tr,h2,h3,.answer dt,.answer dd{break-inside:avoid}
  .chap-head,h2,h3,h4,.def-label,summary,.answer dt{break-after:avoid}
  .roadmap{grid-template-columns:repeat(3,1fr)}
  .answer dl{display:block} .answer dt{margin-top:6pt} .answer dd{margin:1pt 0 0}
  figure img{max-height:80mm;width:auto;max-width:100%;margin:0 auto;display:block}
  .kpis{grid-template-columns:repeat(4,1fr)}
  details.more>summary::before{display:none} details.more>summary{padding-left:16px}
}
"""


STORY_JS = """
(function(){
  var links=[].slice.call(document.querySelectorAll('nav.toc a[href^="#"]'));
  var byId={}; links.forEach(function(a){byId[a.getAttribute('href').slice(1)]=a;});
  if('IntersectionObserver' in window){
    var io=new IntersectionObserver(function(es){es.forEach(function(e){
      if(e.isIntersecting&&byId[e.target.id]){links.forEach(function(a){a.classList.remove('active')});byId[e.target.id].classList.add('active');}
    });},{rootMargin:'-15% 0px -75% 0px'});
    document.querySelectorAll('section.chapter, header.hero').forEach(function(s){io.observe(s)});
  }
  var all=[].slice.call(document.querySelectorAll('main details'));
  var btn=document.getElementById('toggle-details');
  if(btn){btn.addEventListener('click',function(){var open=!all.every(function(d){return d.open});
    all.forEach(function(d){d.open=open});btn.textContent=open?'Collapse all details':'Expand all details';});}
  document.querySelectorAll('a[href^="#app-"]').forEach(function(a){a.addEventListener('click',function(){
    var d=document.getElementById(a.getAttribute('href').slice(1)); if(d&&d.tagName==='DETAILS'){d.open=true;}});});
  window.addEventListener('beforeprint',function(){all.forEach(function(d){d.open=true})});
  var lb=document.createElement('div'); lb.className='lightbox'; lb.innerHTML='<img alt="">'; document.body.appendChild(lb);
  document.querySelectorAll('figure img').forEach(function(img){img.title='Click to enlarge';
    img.addEventListener('click',function(){lb.firstChild.src=img.src; lb.firstChild.alt=img.alt; lb.classList.add('open');});});
  lb.addEventListener('click',function(){lb.classList.remove('open')});
  document.addEventListener('keydown',function(e){if(e.key==='Escape'){lb.classList.remove('open')}});
})();
"""



def render_story_page(src_file: str, title: str, footer: str, checks) -> str:
    """Shared builder for the story-style pages: inline charts, number figures, contents list, number checks."""
    src = (HERE / src_file).read_text()
    src = re.sub(r"<!--.*?-->", "", src, count=1, flags=re.S)
    src = re.sub(r'data-fig="([^"]+)"', lambda m: f'src="{data_uri("outputs/charts/" + m.group(1))}"', src)
    n = iter(range(1, 100))      # figures inside collapsed details (class="nonum") stay unnumbered
    src = re.sub(r"(<figure[^>]*>)(.*?)<figcaption>",
                 lambda m: m.group(0) if "nonum" in m.group(1) else f"{m.group(1)}{m.group(2)}<figcaption><b>Figure {next(n)}.</b> ",
                 src, flags=re.S)
    chapters = re.findall(r'<section class="chapter[^"]*" id="([^"]+)" data-toc="([^"]+)"', src)
    items = "".join(f'<li><a href="#{i}">{t}</a></li>' for i, t in chapters)
    toggle = '<button class="btn" id="toggle-details" type="button">Expand all details</button>' if "<details" in src else ""
    toc = f"""<nav class="toc" aria-label="Contents"><p>Contents</p><ol><li><a href="#top">Summary</a></li>{items}</ol>
<div class="toc-tools">{toggle}
<p class="small" style="text-transform:none;letter-spacing:0;font-weight:400">Click any chart to enlarge it.</p></div></nav>"""
    mobile = f"""<details class="more toc-mobile"><summary>Contents</summary><ol>{items}</ol></details>"""
    missing = checks(src)
    if missing:
        raise SystemExit(f"{src_file} is out of line with key_numbers.json:\n  " + "\n  ".join(missing))
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title><style>{STORY_CSS}</style></head>
<body><div class="layout">{toc}<main>{mobile}{src}
<footer>{footer}</footer>
</main></div><script>{STORY_JS}</script></body></html>"""



def visual_checks(html: str) -> list[str]:
    """Numbers quoted in the full report that must match key_numbers.json."""
    k = K
    r = lambda v, step: f"{round(v / step) * step:,.0f}"
    pct0 = lambda v: f"{abs(v) * 100:.0f}%"
    pct1 = lambda v: f"{v * 100:.1f}%"
    share = pd.read_csv(HERE / "outputs" / "tables" / "g3_growth_levers_gmv.csv")["share_of_monthly_gmv"]
    expected = [
        f"{k['mau_last']:,}", f"−{pct0(k['mau_change_from_peak'])} vs Jul–Oct 2024", f"−{pct0(k['new_users_change_q1_2024_avg_to_jun25'])} vs Q1 2024",
        pct1(k["overall_monthly_churn"]), f"of {k['lapsed_users_with_a_chance_to_return']:,} lapsed", f"GMV −{pct0(k['gmv_last_vs_peak'])}",
        f"~+{r(k['sizing_0_recover'], 50)}", f"{k['m_quality_q1_24_n30']:.2f} vs {k['m_quality_q1_25_n30']:.2f} purchases",
        f"{k['f_same_users_txn_m0']:.2f} purchases in M0 vs {k['f_same_users_txn_m1']:.2f} in M1",
        f"only {k['x_sbg_share_churn_below_10pct'] * 100:.1f}% below 10% a month", f"{pct0(k['avg_user_retention_M1'])} → {pct0(k['avg_user_retention_M3'])} → {pct0(k['avg_user_retention_M6'])} → {pct0(k['avg_user_retention_M12'])}",
        f"{pct0(k['one_txn_first_month_share'])} of new users stop at one", f"{pct0(k['m_second_purchase_by_day14_all_users'])} of new users make a second purchase",
        f"{k['m_fixed12_gmv_n5plus_m']:.2f}M vs {k['m_fixed12_gmv_n1_m']:.2f}M VND",
        f"AUC {k['oot_auc']:.2f}", f"churn at {k['b_churn_avg3_low'] * 100:.1f}% a month, against {k['b_churn_avg3_high'] * 100:.1f}%", f"{pct0(k['b_heavy_lost_if_silent_day10'])} are lost",
        f"{pct0(k['b_heavy_share_of_churned_gmv'])} of churners' last-month GMV", f"{pct0(k['lapse_share_silent_day15'])} are silent and {pct0(k['lapse_p_lost_day15'])}",
        f"+{share[1] * 100:.1f}% vs +{share[2] * 100:.1f}%", f"+{share[0] * 100:.0f}%", f"+{share[3] * 100:.1f}% GMV",
        f"~{k['m_fixed_M0_M6_gmv_m']:.2f}M VND",
        f"−{abs(k['g_m1_change_at_2024_volume_pp']):.1f}pp of M1 (95% CI −{abs(k['g_m1_change_ci_low_pp']):.1f} to +{k['g_m1_change_ci_high_pp']:.1f})",
        f"r = −{abs(k['g_size_vs_m1_r']):.2f}, p = {k['g_size_vs_m1_p']:.2f}",
        f"{k['m_pilot_A_10pp_n']:,} / {k['m_pilot_A_5pp_n']:,}", f"{k['m_pilot_B_10pp_n']:,} / {k['m_pilot_B_5pp_n']:,}",
        f"+purchase ({k['f_balance_rule_add_share'] * 100:.1f}%)", f"random pay-down ({k['f_balance_paydown_share'] * 100:.1f}%)",
        f"{k['f_first_day_1_3_observed'] * 100:.1f}% of first purchases on days 1–3 vs {k['f_first_day_1_3_expected'] * 100:.1f}%",
        f"(p = {k['b_tenure_p_given_usual_frequency']:.2f})", f"(p = {k['f_ticket_icc_p']:.2f})",
        f"{k['b_same_package_as_previous_observed'] * 100:.1f}% same package vs {k['b_same_package_as_previous_expected'] * 100:.1f}%",
        f"yet {k['f_purchases_above_headroom']:,} went through", f"({k['f_oos_balance_copied_from_own_rows']} of 104)",
    ]
    return [e for e in expected if e not in html]



def build_full_report():
    footer = "All figures are computed from the provided data.csv (204,694 transactions, Jan 2024 – Jun 2025)."
    (OUT / f"{REP}.html").write_text(render_story_page("report_src.html", "BNPL Retention &amp; Growth Review", footer, visual_checks))


def onepager_content() -> dict:
    """Content of the one-pager (Part 3)."""
    k = K
    pct = lambda x: f"{abs(x) * 100:.0f}%"
    r50 = lambda v: f"{round(v / 50) * 50:,.0f}"
    r10 = lambda v: f"{round(v / 10) * 10:,.0f}"
    sz = {key_.split("_", 2)[2]: v for key_, v in k.items() if key_.startswith("sizing_")}
    share = pd.read_csv(HERE / "outputs" / "tables" / "g3_growth_levers_gmv.csv")["share_of_monthly_gmv"]
    gmv = pd.read_csv(HERE / "outputs" / "tables" / "q1b_monthly_dynamics.csv")["gmv"]
    new_drop = pct(k["new_users_change_q1_2024_avg_to_jun25"])
    usual = pd.read_csv(HERE / "outputs" / "tables" / "b_churn_by_usual_vs_this_month.csv", header=[0, 1], index_col=0)["by_3_month_average"].iloc[3:]
    usual_top = float((usual["mean"] * usual["size"]).sum() / usual["size"].sum())
    churn_lo, churn_hi = (f"{k[f'churn_rate_range_{x}_from_feb24'] * 100:.1f}" for x in ("min", "max"))
    return dict(
        eyebrow="BNPL credit line · One-page summary for the Business Lead · Data Jan 2024 to Jun 2025 · Figures as of Jun 2025",
        title="BNPL is shrinking because fewer new users arrive, not because users leave faster",
        sub=(f"Users leave at about the same pace as before, 1 in 4 a month; new users fell {new_drop} since early 2024. "
             f"Retention alone would need churn below {k['churn_needed_to_hold_mau'] * 100:.0f}% for everyone, the level of our most frequent buyers, "
             "so bringing new users back is the bigger lever."),
        kpis=[
            ("Active users, Jun 2025", f"{k['mau_last']:,}", f"−{pct(k['mau_change_from_peak'])} from Jul–Oct 2024 (~{r50(k['mau_peak'])})", True),
            ("New users, Jun 2025", f"{k['new_users_last']:,}", f"−{new_drop} from early 2024 (~{r10(k['new_users_q1_2024_avg'])} a month)", True),
            ("Active users lost each month", "1 in 4", f"{churn_lo}–{churn_hi}% every month since Feb 2024", False),
            ("Still active after 12 months", f"{k['avg_user_retention_M12'] * 100:.0f}%", "none who stopped came back in this data", False),
            ("Payment volume, Jun 2025", f"{gmv.iloc[-1] / 1e9:.2f}B VND", f"−{pct(k['gmv_last_vs_peak'])} from the Nov 2024 peak", True),
        ],
        sections=[
            ("1 · What is happening", [
                ("op1_mau_new_returning.png", "Active users fell because new users fell",
                 f"New users a month went from ~{r10(k['new_users_q1_2024_avg'])} in early 2024 to {k['new_users_last']:,} in Jun 2025, about 5% fewer every month. "
                 f"From May to Jun 2025 we lost ~{r50(k['users_lost_may_to_jun25'])} active users and gained ~{r50(k['new_users_last'])}, so the base shrinks."),
                ("op2_retention_curves.png", "Every intake of new users loses about 1 in 4 a month",
                 f"{k['avg_user_retention_M1'] * 100:.0f}% are still active after 1 month, {k['avg_user_retention_M12'] * 100:.0f}% after 12. "
                 "Every monthly intake since Jan 2024 follows a very similar curve, and nobody who stopped came back."),
                ("op3_churn_by_frequency.png", "Users who rarely buy leave most",
                 f"Share who stop the next month, by usual purchases a month: {k['b_churn_avg3_low'] * 100:.1f}% for one or less, "
                 f"about {usual_top * 100:.0f}% above three. Limit, purchase size and category add nothing once frequency is known. "
                 f"{round(k['lapse_p_lost_day15'] * 10)} in 10 of last month's users still silent on the 15th buy nothing more that month."),
            ]),
            ("2 · What it means", [
                ("op4_first_month_purchases.png", "There is no magic “4 purchases in the first month”",
                 "Share active in month 2, by purchases in month 1. It rises gradually; the jump at 4 came from 104 suspect rows. "
                 f"A practical goal is a second purchase: {pct(k['one_txn_first_month_share'])} of new users stop at one."),
                ("op5_scenarios.png", "New users are the biggest lever",
                 "Active users to Jun 2026 under four assumptions. If light users churned like heavy users, "
                 "the line only flattens; 2024-level inflow turns it up."),
                ("op6_gmv_levers.png", "In payment volume, new users matter most",
                 f"100 extra new users a month add as much as light users churning like heavy users (+{share[1] * 100:.0f}% each). "
                 f"Moving 10% of medium users to 4 purchases adds {share[3] * 100:.1f}%."),
            ]),
        ],
        actions=[
            ("<b>Find where new users dropped and fix it</b>: reach, approval or first use? ~730 a month holds the Jun 2025 base.",
             "Growth + Risk", f"Biggest lever: ~{r50(sz['recover'])} more active users in a year at the 2024 level vs flat inflow."),
            ("<b>Remind users who haven't used BNPL by mid-month</b>, by day 10 for frequent users (test on eligible users first).", "CRM",
             f"If it saves 1 in 10 would-be leavers: ~{r10(sz['mid-month'])} more active users in a year. Answer in 1–3 months."),
            ("<b>Help new users make a second purchase, then reward occasional users for using BNPL more often</b> (test first; slower to read).",
             "Product + CRM", f"Occasional users leave most. ~{r10(sz['frequency'])} active users in a year if they churned like heavy users."),
            (f"<b>Give Finance what a new user brings</b>: ~{k['m_fixed_M0_M6_gmv_m']:.2f}M VND of payments in their first 7 months.",
             "Finance + Growth", "Finance sets a cost-per-user limit after revenue share, funding and credit losses."),
            ("<b>Ask Risk why people who stop never come back</b> (account lock?) before any win-back offer.", "Risk + CRM",
             "About 15,000 former users; the response is unknown."),
        ],
        also=[
            f"<b>Heavy users carry the business:</b> {pct(k['x_heavy_share_user_months'])} of active users, {pct(k['x_heavy_share_gmv'])} of payment volume.",
            f"<b>Frequent users can be reached earlier:</b> those who usually buy 5+ times a month and are silent on day 10 are already {k['b_heavy_lost_if_silent_day10'] * 100:.0f}% lost; they made {k['b_heavy_share_of_churned_gmv'] * 100:.0f}% of the last-month payments of users who leave.",
            "<b>The credit fields can't guide credit decisions:</b> limits look randomly assigned and balances follow a mechanical rule. Get the real repayment data first.",
            "<b>The data needs checking:</b> it covers 18 months, not 6; 104 suspect rows created the “4 purchases” myth; several fields look simulated. Confirm the new-user drop against official numbers.",
        ],
        dont="<b>Don't</b> set limits or risk rules from this file, and don't set a “4 purchases in the first month” target.",
        ask=("<b>Decision needed:</b> approve a two-week review of where new users dropped, and the mid-month reminder test (answer in 1–3 months) "
             "once eligibility and consent are confirmed."),
        foot=("Active user = at least one BNPL purchase that month; new user = first purchase seen in the data. Occasional / medium / heavy = 1 / 2–3 / 4+ purchases a month. "
              "Lines to Jun 2026 are scenarios from Jun 2025, not forecasts; sizes are assumptions to test, before incentive cost and credit losses. GMV is not revenue. "
              "104 suspect rows excluded. Full analysis: 2_Full_Report.pdf."),
    )



def build_one_pager():
    c = onepager_content()
    kpis = "".join(f'<div class="kpi"><div class="label">{l}</div><div class="value">{v}</div>'
                   f'<div class="delta{" bad" if bad else ""}">{d}</div></div>' for l, v, d, bad in c["kpis"])
    secs = ""
    for head, panels in c["sections"]:
        figs = "".join(f'<figure class="mini"><h3>{t}</h3><img src="{data_uri("outputs/charts/" + img)}" alt="{t}. {txt}"><p>{txt}</p></figure>'
                       for img, t, txt in panels)
        secs += f'<h2 class="band">{head}</h2><div class="grid3">{figs}</div>'
    rows = "".join(f"<tr><td>{i}</td><td>{a}</td><td>{o}</td><td>{w}</td></tr>" for i, (a, o, w) in enumerate(c["actions"], 1))
    also = "".join(f"<li>{x}</li>" for x in c["also"])
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>BNPL One-Page Summary</title><style>{ONEPAGER_CSS}</style></head>
<body><div class="page">
<p class="eyebrow">{c['eyebrow']}</p>
<h1>{c['title']}</h1>
<p class="sub">{c['sub']}</p>
<div class="kpis">{kpis}</div>
{secs}
<h2 class="band">3 · What we should do next</h2>
<div class="bottom">
  <table class="act"><tr><th>#</th><th>Action</th><th>Owner</th><th>Why it matters</th></tr>{rows}</table>
  <div class="side"><p class="side-h">Also worth knowing</p><ul>{also}</ul><div class="dont">{c['dont']}</div></div>
</div>
<div class="ask">{c['ask']}</div>
<p class="foot">{c['foot']}</p>
</div></body></html>"""
    (OUT / f"{ONE}.html").write_text(page)



def find_chrome():
    for c in ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "google-chrome", "chromium", "chromium-browser", "chrome"):
        if Path(c).exists() or shutil.which(c):
            return c
    return None


def print_pdf(chrome, name, open_details=False):
    """Print outputs/<name>.html to outputs/<name>.pdf (A4, as set by the page's print CSS)."""
    html = OUT / f"{name}.html"
    if open_details:   # collapsible notes are printed open
        tmp = OUT / f"_{name}_print.html"
        tmp.write_text(html.read_text().replace('<details class="more">', '<details class="more" open>'))
        html = tmp
    subprocess.run([chrome, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                    f"--print-to-pdf={OUT / (name + '.pdf')}", html.as_uri()], check=True, capture_output=True)
    if open_details:
        html.unlink()


if __name__ == "__main__":
    onepager_charts.main()
    visual_charts.main()
    build_one_pager()
    build_full_report()
    chrome = find_chrome()
    if chrome:
        print_pdf(chrome, ONE)
        print_pdf(chrome, REP, open_details=True)
        print(f"Built outputs/{ONE}.pdf and outputs/{REP}.pdf (and their HTML)")
    else:
        print(f"Built outputs/{ONE}.html and outputs/{REP}.html; install Google Chrome to print them to PDF")
