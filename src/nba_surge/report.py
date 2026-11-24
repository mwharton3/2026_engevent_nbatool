"""Render risers to the terminal and to a self-contained HTML page."""

from __future__ import annotations

import html
import json
from datetime import date

from .analysis import Riser

VERDICT_GLYPH = {"Likely sustained": "▲ SUSTAIN", "Toss-up": "◆ TOSS-UP", "Likely to fade": "▼ FADE"}


def _ts(x):
    return f"{x:.0%}" if x is not None else "  - "


def render_text(risers: list[Riser], window_start: date, end: date, verbose: bool = False) -> str:
    lines = [
        f"NBA risers: {window_start:%a %b %d} → {end:%a %b %d, %Y}  (Game Score, last 7 days vs season-to-date)",
        "",
        f"{'#':>2}  {'Player':<24}{'Tm':<4}{'GmSc':>12}{'Δ':>6}{'MPG':>12}{'PTS/REB/AST (wk)':>19}{'TS%':>11}"
        f"  {'Outlook':<11}{'conf':<6}",
        "-" * 112,
    ]
    for i, r in enumerate(risers, 1):
        b, w = r.base, r.recent
        lines.append(
            f"{i:>2}  {r.name[:23]:<24}{r.team:<4}{b.gmsc:5.1f}→{w.gmsc:5.1f}{r.delta:+6.1f}"
            f"{b.mpg:5.1f}→{w.mpg:5.1f}{w.pts:8.1f}/{w.reb:4.1f}/{w.ast:4.1f}"
            f"{_ts(b.ts):>5}→{_ts(w.ts):>4}  {VERDICT_GLYPH[r.verdict]:<11}{r.confidence:<6}"
        )
        reasons = sorted(r.signals, key=lambda s: -abs(s.weight))
        for s in reasons if verbose else reasons[:2]:
            mark = "+" if s.weight > 0 else "-"
            lines.append(f"{'':>6}{mark} {s.text}")
    lines += [
        "",
        "Δ = change in avg Game Score. Outlook weighs why minutes rose (injuries/returns/trades via ESPN",
        "injury report + rosters), shooting-luck regression, usage, own health, and sample size.",
    ]
    return "\n".join(lines)


def _riser_payload(r: Riser, season_games: list[dict]) -> dict:
    return {
        "name": r.name, "team": r.team, "pos": r.position, "id": r.player_id,
        "verdict": r.verdict, "confidence": r.confidence, "score": round(r.score, 2),
        "delta": round(r.delta, 1), "minutesEffect": round(r.minutes_effect, 1),
        "rateEffect": round(r.rate_effect, 1),
        "base": _split(r.base), "recent": _split(r.recent),
        "signals": [{"w": round(s.weight, 2), "t": s.text} for s in sorted(r.signals, key=lambda s: -abs(s.weight))],
        "absences": [{"name": a.name, "baseMpg": round(a.base_mpg, 1), "missed": a.missed, "of": a.of_games,
                      "status": a.status, "detail": a.detail} for a in r.absences[:5]],
        "injury": ({"status": r.own_injury.status, "note": r.own_injury.note} if r.own_injury else None),
        "games": season_games,
    }


def _split(s) -> dict:
    return {"g": s.games, "mpg": round(s.mpg, 1), "gmsc": round(s.gmsc, 1), "pts": round(s.pts, 1),
            "reb": round(s.reb, 1), "ast": round(s.ast, 1), "ts": round(s.ts, 3) if s.ts is not None else None,
            "usg": round(s.usage36, 1), "start": round(s.start_rate, 2)}


def render_html(risers: list[Riser], all_games: dict[str, list], window_start: date, end: date,
                generated: str) -> str:
    data = []
    for r in risers:
        games = [
            {"d": g.game_date.isoformat(), "gs": round(g.game_score, 1), "min": round(g.minutes, 1),
             "w": g.game_date >= window_start, "line": f"{g.pts}p {g.reb}r {g.ast}a, {g.minutes:.0f}m"}
            for g in all_games.get(r.player_id, []) if g.played
        ]
        data.append(_riser_payload(r, games))
    payload = json.dumps({"start": window_start.isoformat(), "end": end.isoformat(),
                          "generated": generated, "risers": data})
    return HTML_TEMPLATE.replace("/*__DATA__*/null", payload.replace("</", "<\\/")).replace(
        "__TITLE__", html.escape(f"NBA Weekly Risers · {end:%b %d, %Y}"))


HTML_TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<style>
:root{--bg:#f7f7f5;--card:#fff;--ink:#1b1d21;--mut:#6b7079;--line:#e3e4e8;--up:#13795b;--up-bg:#e3f4ec;
--down:#b4372f;--down-bg:#fbe6e4;--mid:#8a6a00;--mid-bg:#fbf1d3;--base:#b9bcc4;--acc:#2a5bd7}
@media (prefers-color-scheme:dark){:root{--bg:#111316;--card:#1a1d21;--ink:#e8e9ec;--mut:#9399a3;--line:#2b2f35;
--up:#4ccb98;--up-bg:#123227;--down:#f08a82;--down-bg:#3a1a18;--mid:#e5c15a;--mid-bg:#342a0c;--base:#4a4f58;--acc:#7aa2ff}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 system-ui,-apple-system,Segoe UI,sans-serif}
header{max-width:1100px;margin:0 auto;padding:28px 16px 8px}h1{font-size:24px;margin:0 0 4px}
.sub{color:var(--mut)}main{max-width:1100px;margin:0 auto;padding:8px 16px 48px}
.controls{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0 16px}
.controls button{border:1px solid var(--line);background:var(--card);color:var(--ink);border-radius:999px;padding:5px 12px;cursor:pointer;font:inherit}
.controls button.on{border-color:var(--acc);color:var(--acc)}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px;margin-bottom:12px;display:grid;
grid-template-columns:28px minmax(0,1fr) 260px;gap:4px 16px;align-items:start}
.rank{font-weight:700;color:var(--mut);font-size:18px}.name{font-weight:650;font-size:16px}.meta{color:var(--mut);font-size:12px}
.badge{display:inline-block;font-size:12px;font-weight:600;padding:2px 8px;border-radius:999px;margin-left:8px;vertical-align:2px}
.b-up{background:var(--up-bg);color:var(--up)}.b-down{background:var(--down-bg);color:var(--down)}.b-mid{background:var(--mid-bg);color:var(--mid)}
.stats{display:flex;flex-wrap:wrap;gap:6px 18px;margin:8px 0}.stat .k{color:var(--mut);font-size:11px;text-transform:uppercase;letter-spacing:.04em}
.stat .v{font-variant-numeric:tabular-nums}.arrow{color:var(--mut)}.delta{font-weight:700;color:var(--up)}
ul.sig{list-style:none;padding:0;margin:6px 0 0}ul.sig li{padding-left:18px;position:relative;margin:2px 0}
ul.sig li:before{position:absolute;left:0;font-weight:700}ul.sig li.p:before{content:"+";color:var(--up)}ul.sig li.n:before{content:"−";color:var(--down)}
.spark{grid-column:3;grid-row:1/span 3}.spark svg{width:100%;height:90px;display:block}.spark .cap{color:var(--mut);font-size:11px;display:flex;justify-content:space-between}
.decomp{height:6px;border-radius:3px;background:var(--line);display:flex;overflow:hidden;margin-top:4px;max-width:260px}
.decomp span:first-child{background:var(--acc)}.decomp span:last-child{background:var(--up)}
details{margin-top:6px;color:var(--mut)}summary{cursor:pointer}table{border-collapse:collapse;font-size:12px;margin-top:4px}
td,th{padding:2px 10px 2px 0;text-align:left}
footer{color:var(--mut);font-size:12px;max-width:1100px;margin:0 auto;padding:0 16px 32px}
@media (max-width:720px){.card{grid-template-columns:24px minmax(0,1fr)}.spark{grid-column:1/-1;grid-row:auto}}
</style></head><body>
<header><h1>NBA Weekly Risers</h1><div class="sub" id="sub"></div></header>
<main><div class="controls" id="controls"></div><div id="list"></div></main>
<footer>Performance = Hollinger Game Score. Δ is last-7-day average minus season-to-date (pre-window) average.
Bar shows how much of the gain came from <b style="color:var(--acc)">more minutes</b> vs <b style="color:var(--up)">more per minute</b>.
Outlook weighs why minutes rose (teammate injuries, expected return dates, trades, returns already made), shooting-luck regression,
usage change, the player's own injury status and sample size. Data: ESPN public API.</footer>
<script>
const D=/*__DATA__*/null;
const fmt=d=>new Date(d+"T12:00").toLocaleDateString(undefined,{month:"short",day:"numeric"});
document.getElementById("sub").textContent=`Week of ${fmt(D.start)} – ${fmt(D.end)} · generated ${D.generated}`;
const cls={"Likely sustained":"b-up","Likely to fade":"b-down","Toss-up":"b-mid"};
let filter="All";
const ctl=document.getElementById("controls");
["All","Likely sustained","Toss-up","Likely to fade"].forEach(f=>{const b=document.createElement("button");b.textContent=f;
b.onclick=()=>{filter=f;draw()};ctl.appendChild(b)});
const esc=s=>String(s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const pct=x=>x==null?"–":(x*100).toFixed(0)+"%";
function spark(g,base){const W=260,H=90,P=4;if(!g.length)return"";
 const ys=g.map(x=>x.gs),lo=Math.min(0,...ys),hi=Math.max(...ys,1);const sx=i=>P+i*(W-2*P)/Math.max(1,g.length-1),sy=v=>H-P-(v-lo)*(H-2*P)/(hi-lo);
 let s=`<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="Game Score by game">`;
 s+=`<line x1="0" x2="${W}" y1="${sy(base)}" y2="${sy(base)}" stroke="var(--mut)" stroke-dasharray="3 3" stroke-width="1"/>`;
 const bw=Math.max(2,(W-2*P)/g.length-2);
 g.forEach((x,i)=>{const y=sy(Math.max(x.gs,0)),y0=sy(Math.min(x.gs,0));s+=`<rect x="${sx(i)-bw/2}" y="${Math.min(y,sy(0))}" width="${bw}" height="${Math.max(1,Math.abs(sy(x.gs)-sy(0)))}" rx="1" fill="${x.w?"var(--up)":"var(--base)"}"><title>${fmt(x.d)}: GmSc ${x.gs} (${x.line})</title></rect>`});
 return s+"</svg>"}
function draw(){[...ctl.children].forEach(b=>b.classList.toggle("on",b.textContent===filter));
 const L=document.getElementById("list");L.innerHTML="";
 D.risers.forEach((r,i)=>{if(filter!=="All"&&r.verdict!==filter)return;
  const b=r.base,w=r.recent,me=Math.max(0,r.minutesEffect),re=Math.max(0,r.rateEffect),tot=me+re||1;
  const ab=r.absences.length?`<details><summary>Teammate absences this week (${r.absences.length})</summary><table><tr><th>Player</th><th>Base MPG</th><th>Missed</th><th>Status</th></tr>${r.absences.map(a=>`<tr><td>${esc(a.name)}</td><td>${a.baseMpg}</td><td>${a.missed}/${a.of}</td><td>${esc(a.detail)}</td></tr>`).join("")}</table></details>`:"";
  const el=document.createElement("div");el.className="card";
  el.innerHTML=`<div class="rank">${i+1}</div>
  <div><div class="name">${esc(r.name)}<span class="badge ${cls[r.verdict]}">${r.verdict}</span></div>
   <div class="meta">${esc(r.team)} · ${esc(r.pos)} · ${w.g} games this week vs ${b.g} before · confidence ${r.confidence}</div>
   <div class="stats">
    <div class="stat"><div class="k">Game Score</div><div class="v">${b.gmsc} <span class="arrow">→</span> ${w.gmsc} <span class="delta">+${r.delta}</span></div></div>
    <div class="stat"><div class="k">Minutes</div><div class="v">${b.mpg} <span class="arrow">→</span> ${w.mpg}</div></div>
    <div class="stat"><div class="k">Pts / Reb / Ast</div><div class="v">${b.pts}/${b.reb}/${b.ast} <span class="arrow">→</span> ${w.pts}/${w.reb}/${w.ast}</div></div>
    <div class="stat"><div class="k">TS%</div><div class="v">${pct(b.ts)} <span class="arrow">→</span> ${pct(w.ts)}</div></div>
    <div class="stat"><div class="k">Started</div><div class="v">${pct(b.start)} <span class="arrow">→</span> ${pct(w.start)}</div></div>
   </div>
   <div class="meta">Gain from minutes ${r.minutesEffect>0?"+":""}${r.minutesEffect} · per-minute ${r.rateEffect>0?"+":""}${r.rateEffect}</div>
   <div class="decomp"><span style="width:${100*me/tot}%"></span><span style="width:${100*re/tot}%"></span></div>
   <ul class="sig">${r.signals.map(s=>`<li class="${s.w>0?"p":"n"}">${esc(s.t)}</li>`).join("")}</ul>${ab}</div>
  <div class="spark">${spark(r.games,b.gmsc)}<div class="cap"><span>season, by game</span><span>▮ this week</span></div></div>`;
  L.appendChild(el)})}
draw();
</script></body></html>"""
