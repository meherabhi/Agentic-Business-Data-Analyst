"""Interactive live demo: the real agent, replayed step by step in the browser.

Instead of a static dashboard, this ships the agent's actual runs as JSON inside
one self-contained HTML page. The engine — `warehouse.build()`, `planner.plan()`,
`sql_tool.build_sql()`, `guardrails.check()`, `sql_tool.run()`, all stitched by
`agent.run_question()` — executes here, in Python, exactly as it always does.
Every trace, every generated SQL string, every guardrail verdict, and every
result row is captured from that real run and embedded.

A visitor clicks a natural-language question (or types their own, which routes to
the nearest question by keyword overlap) and watches the agent's plan -> act ->
observe -> reflect -> answer loop animate one step at a time: the chosen intent
and confidence, the parameterized SQL, the guardrail pass/deny badge, and the
result table. An always-visible guardrail bench lets them fire adversarial probes
(stacked DROP, bare DELETE, sqlite_master, comment bypasses) and see them blocked.

No server, no library, no network. Just the agent, frozen and made playable.
"""
from __future__ import annotations

import json
import os

import agent
import guardrails
import planner
import warehouse

ACCENT = "#22d3ee"  # signature cyan — distinct from the other demos

# lightweight stopwords for the free-text keyword router (mirrored in JS only
# for tokenizing user input; the question keyword sets are computed here).
_STOP = {
    "the", "a", "an", "of", "by", "in", "for", "to", "and", "or", "is", "are",
    "me", "my", "show", "what", "whats", "how", "has", "have", "list", "give",
    "get", "with", "on", "over", "across", "that", "this", "s", "do", "i",
    "there", "was", "were", "be", "it", "all",
}


def _tokens(text: str) -> list[str]:
    out, cur = [], []
    for ch in text.lower():
        if ch.isalnum():
            cur.append(ch)
        else:
            if cur:
                out.append("".join(cur))
            cur = []
    if cur:
        out.append("".join(cur))
    seen, keep = set(), []
    for t in out:
        if t in _STOP or len(t) <= 1:
            continue
        if t not in seen:
            seen.add(t)
            keep.append(t)
    return keep


def _clean_rows(rows: list) -> list:
    out = []
    for r in rows:
        row = []
        for v in r:
            row.append(round(v, 2) if isinstance(v, float) else v)
        out.append(row)
    return out


def _schema(con) -> list[dict]:
    tables = []
    for t in ("regions", "customers", "products", "dim_dates", "orders"):
        cols = [r[1] for r in con.execute(f"PRAGMA table_info({t})").fetchall()]
        n = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        tables.append({"table": t, "columns": cols, "rows": n})
    return tables


def build_export() -> dict:
    warehouse.build()
    con = warehouse.connect_readonly()
    run = agent.run_suite(con)

    questions = []
    for o in run["outcomes"]:
        plan = planner.plan(o["question"])
        res = o["result"]
        sql = res["sql"] if (res and res.get("sql")) else None
        guard = None
        if sql is not None:
            ok, reason = guardrails.check(sql)
            guard = {"ok": ok, "reason": reason}
        questions.append({
            "q": o["question"],
            "intent": o["intent"],
            "confidence": round(o["confidence"], 2),
            "rationale": plan.get("rationale", ""),
            "keywords": _tokens(o["question"]),
            "sql": sql,
            "guard": guard,
            "columns": (res["columns"] if res else []),
            "rows": (_clean_rows(res["rows"]) if res else []),
            "trace": o["trace"],
            "answer": o["answer"],
            "success": o["success"],
            "retried": o["retried"],
            "total_latency_ms": o["total_latency_ms"],
        })

    schema = _schema(con)
    con.close()
    return {
        "questions": questions,
        "probes": run["probes"],
        "metrics": run["metrics"],
        "intents": run["intents"],
        "schema": schema,
    }


def render(out_path: str) -> str:
    data = build_export()
    m = data["metrics"]
    doc = (_TEMPLATE
           .replace("__ACCENT__", ACCENT)
           .replace("__DATA__", json.dumps(data))
           .replace("__SUCCESS__", f"{m['success_rate']*100:.0f}")
           .replace("__NQ__", str(m["questions"]))
           .replace("__BLOCKS__", str(m["guardrail_blocks"]))
           .replace("__PROBES__", str(m["guardrail_probes"]))
           .replace("__AVGLAT__", f"{m['avg_latency_ms']:.0f}"))
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w") as fh:
        fh.write(doc)
    return out_path


_TEMPLATE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Ask the Warehouse — live agent</title>
<style>
 :root{--accent:__ACCENT__;--bg:#080b11;--panel:#0f141d;--panel2:#0b1017;--line:#1e2836;
   --txt:#e8eef6;--mut:#93a2b6;--dim:#5c6b80;--ok:#34d399;--bad:#fb7185;--warn:#fbbf24;
   --mono:ui-monospace,"SF Mono",Menlo,Consolas,monospace;
   --shadow:0 24px 60px -26px rgba(0,0,0,.85)}
 *{box-sizing:border-box}
 body{margin:0;background:
   radial-gradient(1200px 720px at 82% -12%,rgba(34,211,238,.16),transparent 55%),
   radial-gradient(760px 520px at -5% 108%,rgba(34,211,238,.06),transparent 52%),var(--bg);
   color:var(--txt);font:14px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,sans-serif;
   -webkit-font-smoothing:antialiased}
 .wrap{max-width:1220px;margin:0 auto;padding:40px 22px 72px}
 .eyebrow{display:inline-flex;gap:8px;align-items:center;font-size:11px;letter-spacing:.16em;
   text-transform:uppercase;color:var(--mut);border:1px solid var(--line);border-radius:999px;padding:5px 13px}
 .eyebrow .d{width:7px;height:7px;border-radius:50%;background:var(--accent);
   box-shadow:0 0 12px var(--accent);animation:pulse 2.2s infinite}
 @keyframes pulse{0%,100%{opacity:1}50%{opacity:.35}}
 h1{font-size:clamp(28px,4.6vw,50px);margin:16px 0 8px;letter-spacing:-.025em;font-weight:780;line-height:1.02}
 h1 span{background:linear-gradient(90deg,var(--accent),#a5f3fc);-webkit-background-clip:text;
   background-clip:text;-webkit-text-fill-color:transparent}
 .lede{color:var(--mut);max-width:70ch;font-size:15px;margin:0 0 22px}
 .hero-metrics{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:8px}
 .hm{background:linear-gradient(180deg,var(--panel),var(--panel2));border:1px solid var(--line);
   border-radius:13px;padding:11px 16px;min-width:120px}
 .hm .k{font-size:10px;text-transform:uppercase;letter-spacing:.08em;color:var(--dim)}
 .hm .v{font-size:23px;font-weight:760;margin-top:3px;font-variant-numeric:tabular-nums}
 .hm .v small{font-size:12px;color:var(--dim);font-weight:600}

 .studio{display:grid;grid-template-columns:360px 1fr;gap:20px;margin-top:26px}
 @media(max-width:940px){.studio{grid-template-columns:1fr}}
 .card{background:linear-gradient(180deg,var(--panel),var(--panel2));border:1px solid var(--line);
   border-radius:18px;box-shadow:var(--shadow)}
 .pad{padding:20px 22px}
 h2.sec{font-size:12px;text-transform:uppercase;letter-spacing:.09em;color:var(--dim);margin:0 0 14px;font-weight:700}

 .asks{display:flex;flex-direction:column;gap:8px}
 .ask{text-align:left;border:1px solid var(--line);background:#0c121b;color:var(--txt);
   font:inherit;font-size:13px;padding:11px 13px;border-radius:11px;cursor:pointer;
   transition:all .16s;display:flex;justify-content:space-between;align-items:center;gap:10px}
 .ask:hover{border-color:var(--accent);background:#0e1621;transform:translateX(2px)}
 .ask.on{border-color:var(--accent);background:rgba(34,211,238,.09);box-shadow:0 0 0 1px var(--accent) inset}
 .ask .tag{font-family:var(--mono);font-size:10px;color:var(--dim);white-space:nowrap;text-transform:uppercase;letter-spacing:.04em}
 .ask.on .tag{color:var(--accent)}
 .askbox{margin-top:14px}
 .askbox .row{display:flex;gap:8px}
 .askbox input{flex:1;background:#0a0f16;border:1px solid var(--line);border-radius:11px;
   color:var(--txt);font:inherit;font-size:13px;padding:11px 13px;outline:none;transition:border-color .15s}
 .askbox input:focus{border-color:var(--accent)}
 .askbox button{background:var(--accent);border:0;color:#04141a;font:inherit;font-weight:720;
   font-size:13px;padding:0 16px;border-radius:11px;cursor:pointer;transition:filter .15s}
 .askbox button:hover{filter:brightness(1.08)}
 .routed{font-size:11.5px;color:var(--dim);margin-top:9px;min-height:16px}
 .routed b{color:var(--accent)}
 .schema{margin-top:20px;border-top:1px solid var(--line);padding-top:16px}
 .schema .st{font-size:11px;color:var(--dim);text-transform:uppercase;letter-spacing:.07em;margin-bottom:9px}
 .tchip{display:inline-flex;align-items:baseline;gap:6px;background:#0b1017;border:1px solid var(--line);
   border-radius:8px;padding:5px 9px;margin:0 6px 6px 0;font-family:var(--mono);font-size:11px}
 .tchip b{color:var(--accent);font-weight:600} .tchip s{color:var(--dim);text-decoration:none;font-size:10px}

 /* theater */
 .theater{min-height:520px;display:flex;flex-direction:column}
 .intentbar{display:flex;align-items:center;gap:14px;flex-wrap:wrap;padding:16px 22px;border-bottom:1px solid var(--line)}
 .intentbar .lbl{font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:var(--dim)}
 .ipill{font-family:var(--mono);font-size:13px;font-weight:600;color:var(--accent);
   background:rgba(34,211,238,.1);border:1px solid rgba(34,211,238,.3);border-radius:999px;padding:4px 12px}
 .confwrap{display:flex;align-items:center;gap:9px;margin-left:auto}
 .conftrack{width:120px;height:6px;border-radius:6px;background:#182230;overflow:hidden}
 .conffill{height:100%;width:0;background:linear-gradient(90deg,var(--accent),#a5f3fc);
   border-radius:6px;transition:width .6s cubic-bezier(.22,.61,.36,1)}
 .confval{font-family:var(--mono);font-size:12px;color:var(--mut);min-width:38px;text-align:right}

 /* pipeline chips */
 .pipeline{display:flex;gap:6px;padding:15px 22px 4px;flex-wrap:wrap}
 .pchip{flex:1;min-width:78px;text-align:center;font-size:10.5px;text-transform:uppercase;
   letter-spacing:.06em;color:var(--dim);border:1px solid var(--line);border-radius:9px;
   padding:8px 4px;background:#0a0f16;transition:all .3s;position:relative}
 .pchip.on{color:#04141a;background:var(--accent);border-color:var(--accent);
   box-shadow:0 0 18px -4px var(--accent);font-weight:700}
 .pchip.done{color:var(--accent);border-color:rgba(34,211,238,.4)}

 .steps{padding:14px 22px 4px;flex:1}
 .stephint{color:var(--dim);font-size:13px;padding:60px 10px;text-align:center}
 .stephint b{color:var(--mut)}
 .step{display:grid;grid-template-columns:74px 1fr auto;gap:12px;align-items:start;padding:11px 0;
   border-bottom:1px dashed #17202c;opacity:0;transform:translateY(8px);animation:rise .34s forwards}
 @keyframes rise{to{opacity:1;transform:none}}
 .step .ph{font-family:var(--mono);font-size:10.5px;text-transform:uppercase;letter-spacing:.05em;
   color:var(--accent);padding-top:2px}
 .step .body .tool{font-size:12px;color:var(--mut);font-weight:600}
 .step .body .io{font-size:12.5px;color:var(--txt);margin-top:3px;word-break:break-word}
 .step .body .io .arr{color:var(--dim);margin:0 6px}
 .badge{font-family:var(--mono);font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.04em;
   padding:3px 8px;border-radius:999px;white-space:nowrap}
 .b-ok{background:rgba(52,211,153,.14);color:var(--ok)}
 .b-warn{background:rgba(251,191,36,.14);color:var(--warn)}
 .b-retry{background:rgba(34,211,238,.14);color:var(--accent)}
 .b-blocked,.b-fail{background:rgba(251,113,133,.14);color:var(--bad)}
 .lat{font-family:var(--mono);font-size:10px;color:var(--dim);margin-top:5px;text-align:right}

 .reveal{margin:14px 22px;opacity:0;max-height:0;overflow:hidden;transition:opacity .4s,max-height .5s}
 .reveal.show{opacity:1;max-height:900px}
 .sqlpanel{border:1px solid var(--line);border-radius:12px;overflow:hidden;background:#070b11}
 .sqlhead{display:flex;justify-content:space-between;align-items:center;padding:9px 14px;
   background:#0a1019;border-bottom:1px solid var(--line)}
 .sqlhead .t{font-size:11px;text-transform:uppercase;letter-spacing:.07em;color:var(--dim)}
 .sqlcode{font-family:var(--mono);font-size:12.5px;line-height:1.7;padding:13px 15px;color:#cfe6ee;
   white-space:pre-wrap;word-break:break-word}
 .sqlcode .kw{color:var(--accent);font-weight:600}
 .sqlcode .fn{color:#a5f3fc}
 .gbadge{font-family:var(--mono);font-size:10.5px;font-weight:700;text-transform:uppercase;letter-spacing:.05em;
   padding:4px 10px;border-radius:999px;display:inline-flex;gap:6px;align-items:center}
 .g-pass{background:rgba(52,211,153,.15);color:var(--ok);border:1px solid rgba(52,211,153,.35)}
 .g-deny{background:rgba(251,113,133,.15);color:var(--bad);border:1px solid rgba(251,113,133,.35)}

 .resulttbl{width:100%;border-collapse:collapse;font-size:12.5px}
 .resulttbl th{text-align:left;font-size:10px;text-transform:uppercase;letter-spacing:.06em;
   color:var(--dim);padding:8px 12px;border-bottom:1px solid var(--line)}
 .resulttbl td{padding:8px 12px;border-bottom:1px solid #141c27;font-variant-numeric:tabular-nums}
 .resulttbl td.num{font-family:var(--mono);color:var(--accent);text-align:right}
 .resulttbl tr{opacity:0;animation:rise .3s forwards}
 .rescap{font-size:11px;color:var(--dim);padding:8px 12px}
 .answer{margin:6px 22px 22px;padding:15px 18px;border-radius:12px;border:1px solid rgba(34,211,238,.25);
   background:rgba(34,211,238,.06);font-size:14.5px;line-height:1.5;opacity:0;transition:opacity .5s}
 .answer.show{opacity:1}
 .answer .k{font-size:10px;text-transform:uppercase;letter-spacing:.08em;color:var(--accent);
   display:block;margin-bottom:6px}
 .answer.declined{border-color:rgba(251,191,36,.3);background:rgba(251,191,36,.06)}
 .answer.declined .k{color:var(--warn)}

 /* guardrail bench */
 .bench{margin-top:22px}
 .benchgrid{display:grid;grid-template-columns:300px 1fr;gap:22px}
 @media(max-width:760px){.benchgrid{grid-template-columns:1fr}}
 .probes{display:flex;flex-direction:column;gap:7px}
 .probe{text-align:left;border:1px solid var(--line);background:#0c121b;color:var(--txt);font:inherit;
   font-size:12.5px;padding:10px 12px;border-radius:10px;cursor:pointer;transition:all .15s;
   display:flex;align-items:center;gap:9px}
 .probe:hover{border-color:var(--accent);background:#0e1621}
 .probe.on{border-color:var(--accent);background:rgba(34,211,238,.08)}
 .probe .dot{width:8px;height:8px;border-radius:2px;flex:none}
 .probe.blk .dot{background:var(--bad)} .probe.alw .dot{background:var(--ok)}
 .probe .pl{flex:1}
 .probe .pv{font-family:var(--mono);font-size:9.5px;text-transform:uppercase;letter-spacing:.04em;color:var(--dim)}
 .benchview{border:1px solid var(--line);border-radius:12px;background:#070b11;overflow:hidden;align-self:start}
 .bvhead{display:flex;justify-content:space-between;align-items:center;padding:11px 15px;
   background:#0a1019;border-bottom:1px solid var(--line)}
 .bvhead .t{font-size:11px;text-transform:uppercase;letter-spacing:.07em;color:var(--dim)}
 .bvsql{font-family:var(--mono);font-size:12.5px;line-height:1.65;padding:15px;color:#cfe6ee;
   white-space:pre-wrap;word-break:break-word}
 .bvreason{padding:0 15px 15px;font-size:12.5px;color:var(--mut)}
 .bvreason b{color:var(--txt)}
 .shield{display:inline-block;transition:transform .3s}
 .foot{margin-top:34px;color:var(--dim);font-size:12.5px;border-top:1px solid var(--line);padding-top:18px}
 .foot b{color:var(--mut)}
</style></head><body><div class="wrap">
 <span class="eyebrow"><span class="d"></span>Live agent · replayed in your browser</span>
 <h1>Ask the <span>Warehouse</span></h1>
 <p class="lede">Click a question and watch my from-scratch data agent think: it plans an intent, writes
   parameterized SQL, clears it through a read-only guardrail, runs it against a seeded SQLite warehouse, and
   reflects on the rows. Every step, every SQL string, and every verdict below is captured from the real
   <b>agent.run_suite()</b> — not mocked.</p>
 <div class="hero-metrics">
   <div class="hm"><div class="k">Questions</div><div class="v">__NQ__</div></div>
   <div class="hm"><div class="k">Success rate</div><div class="v">__SUCCESS__<small>%</small></div></div>
   <div class="hm"><div class="k">Guardrail blocks</div><div class="v">__BLOCKS__<small>/__PROBES__</small></div></div>
   <div class="hm"><div class="k">Avg latency</div><div class="v">__AVGLAT__<small>ms</small></div></div>
 </div>

 <div class="studio">
   <div class="card pad">
     <h2 class="sec">Ask a question</h2>
     <div class="asks" id="asks"></div>
     <div class="askbox">
       <div class="row">
         <input id="freetext" placeholder="Type your own question…" autocomplete="off">
         <button id="asktext">Ask</button>
       </div>
       <div class="routed" id="routed"></div>
     </div>
     <div class="schema">
       <div class="st">Warehouse · star schema</div>
       <div id="schema"></div>
     </div>
   </div>

   <div class="card theater">
     <div class="intentbar">
       <span class="lbl">Intent</span>
       <span class="ipill" id="ipill">—</span>
       <span class="lbl" id="rationale" style="color:var(--dim);text-transform:none;letter-spacing:0;font-size:12px"></span>
       <div class="confwrap"><span class="lbl">conf</span>
         <div class="conftrack"><div class="conffill" id="conffill"></div></div>
         <span class="confval" id="confval">—</span></div>
     </div>
     <div class="pipeline" id="pipeline"></div>
     <div class="steps" id="steps">
       <div class="stephint">Pick a question on the left to watch the agent's
         <b>plan → act → observe → reflect → answer</b> loop run step by step.</div>
     </div>
     <div class="reveal" id="sqlReveal">
       <div class="sqlpanel">
         <div class="sqlhead"><span class="t">Generated SQL · parameterized</span><span id="gbadge"></span></div>
         <div class="sqlcode" id="sqlcode"></div>
       </div>
     </div>
     <div class="reveal" id="resReveal">
       <div class="sqlpanel">
         <div class="sqlhead"><span class="t">Result — real rows from the warehouse</span><span class="t" id="rescount"></span></div>
         <div style="overflow-x:auto"><table class="resulttbl" id="restbl"></table></div>
       </div>
     </div>
     <div class="answer" id="answer"><span class="k">Answer</span><span id="answertext"></span></div>
   </div>
 </div>

 <div class="card pad bench">
   <h2 class="sec"><span class="shield" id="shield">🛡️</span> Guardrail bench — fire an adversarial probe at the SQL boundary</h2>
   <div class="benchgrid">
     <div class="probes" id="probes"></div>
     <div class="benchview">
       <div class="bvhead"><span class="t">Probe → guardrails.check()</span><span id="bvverdict"></span></div>
       <div class="bvsql" id="bvsql">Click a probe to send it through the guardrail.</div>
       <div class="bvreason" id="bvreason"></div>
     </div>
   </div>
 </div>

 <div class="foot">Everything here runs from the deterministic engine — a seeded <b>sqlite3</b> warehouse, a
   rule-based planner, and an allowlist guardrail — captured from <b>agent.run_suite()</b> and replayed client-side.
   Step latencies are the engine's own deterministic simulation, not wall-clock model timing. No server, no library.</div>
</div>
<script>
const DATA=__DATA__;
const Q=DATA.questions, PROBES=DATA.probes, SCHEMA=DATA.schema;
const PHASES=["plan","act","observe","reflect","answer"];
const PHLABEL={plan:"Plan",act:"Act",observe:"Observe",reflect:"Reflect",answer:"Answer"};
const $=id=>document.getElementById(id);

// ---- SQL prettifier (display only) ----
const KW=["select","from","join","on","group by","order by","where","and","limit","desc","asc","as","with","coalesce"];
const FN=["sum","count","avg"];
function fmtSQL(sql){
  let s=sql.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
  // line breaks before major clauses
  s=s.replace(/\s+(FROM|JOIN|GROUP BY|ORDER BY|WHERE|LIMIT)\b/g,"\n$1");
  s=s.replace(/\b(SELECT|FROM|JOIN|ON|GROUP BY|ORDER BY|WHERE|AND|LIMIT|DESC|ASC|AS|WITH|COALESCE)\b/gi,
    m=>`<span class="kw">${m}</span>`);
  s=s.replace(/\b(SUM|COUNT|AVG)\s*\(/gi,m=>`<span class="fn">${m.slice(0,-1)}</span>(`);
  return s;
}
function isNum(v){return typeof v==="number";}
function fmtCell(v,col){
  if(v===null||v===undefined)return "—";
  if(isNum(v)){
    const cur=/reven|value/i.test(col);
    if(cur)return "$"+Math.round(v).toLocaleString();
    return v.toLocaleString();
  }
  return String(v);
}

// ---- build question list ----
const asksEl=$("asks");
Q.forEach((q,i)=>{
  const b=document.createElement("button");
  b.className="ask"; b.dataset.i=i;
  b.innerHTML=`<span>${q.q}</span><span class="tag">${q.intent}</span>`;
  b.addEventListener("click",()=>selectQuestion(i,b));
  asksEl.appendChild(b);
});

// ---- schema chips ----
$("schema").innerHTML=SCHEMA.map(t=>
  `<span class="tchip"><b>${t.table}</b><s>${t.rows} rows</s></span>`).join("");

// ---- pipeline chips ----
const pipeEl=$("pipeline");
pipeEl.innerHTML=PHASES.map(p=>`<div class="pchip" data-ph="${p}">${PHLABEL[p]}</div>`).join("");
function setPipe(ph,state){
  const el=pipeEl.querySelector(`[data-ph="${ph}"]`);
  if(!el)return;
  if(state==="on"){el.classList.add("on");}
  else if(state==="done"){el.classList.remove("on");el.classList.add("done");}
}
function resetPipe(){pipeEl.querySelectorAll(".pchip").forEach(e=>e.className="pchip");}

const badgeClass={ok:"b-ok",warn:"b-warn",retry:"b-retry",blocked:"b-blocked",fail:"b-fail"};

let gen=0;
function selectQuestion(i,btn){
  document.querySelectorAll(".ask").forEach(a=>a.classList.remove("on"));
  if(btn)btn.classList.add("on");
  runQuestion(Q[i]);
}

function runQuestion(q){
  gen++; const my=gen;
  // reset
  resetPipe();
  $("steps").innerHTML="";
  $("sqlReveal").classList.remove("show");
  $("resReveal").classList.remove("show");
  $("answer").classList.remove("show","declined");
  // intent bar
  $("ipill").textContent=q.intent;
  $("rationale").textContent=q.rationale?("· "+q.rationale):"";
  $("confval").textContent=q.confidence.toFixed(2);
  $("conffill").style.width="0%";
  requestAnimationFrame(()=>{ if(my===gen) $("conffill").style.width=(q.confidence*100)+"%"; });

  let delay=120;
  const at=(fn,gap)=>{ delay+=gap; setTimeout(()=>{ if(my===gen) fn(); },delay); };

  q.trace.forEach((s,idx)=>{
    at(()=>{
      // mark previous phase done, this phase on
      if(idx>0) setPipe(q.trace[idx-1].phase,"done");
      setPipe(s.phase,"on");
      appendStep(s);
      if(s.tool==="sql_tool" && q.sql){ showSQL(q); }
      if(s.tool==="observe"){ showResult(q); }
      if(s.tool==="answer"){ setPipe(s.phase,"done"); showAnswer(q,s); }
    }, idx===0?0:430);
  });
}

function appendStep(s){
  const stepsEl=$("steps");
  const d=document.createElement("div");
  d.className="step";
  const bc=badgeClass[s.status]||"b-ok";
  d.innerHTML=`
    <div class="ph">${PHLABEL[s.phase]||s.phase}</div>
    <div class="body">
      <div class="tool">${s.tool}</div>
      <div class="io">${esc(s.input)}<span class="arr">→</span>${esc(s.output)}</div>
    </div>
    <div>
      <span class="badge ${bc}">${s.status}</span>
      <div class="lat">${s.latency_ms}ms</div>
    </div>`;
  stepsEl.appendChild(d);
  stepsEl.parentElement.scrollTop=stepsEl.parentElement.scrollHeight;
}
function esc(t){return String(t).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");}

function showSQL(q){
  $("sqlcode").innerHTML=fmtSQL(q.sql);
  const g=q.guard;
  const gb=$("gbadge");
  if(g&&g.ok){ gb.className="gbadge g-pass"; gb.innerHTML="✓ guardrail "+g.reason; }
  else { gb.className="gbadge g-deny"; gb.innerHTML="✕ "+(g?g.reason:"blocked"); }
  $("sqlReveal").classList.add("show");
}

function showResult(q){
  const cols=q.columns, rows=q.rows;
  const t=$("restbl");
  let html="<thead><tr>"+cols.map(c=>`<th>${esc(c)}</th>`).join("")+"</tr></thead><tbody>";
  const shown=rows.slice(0,12);
  shown.forEach((r,ri)=>{
    html+=`<tr style="animation-delay:${ri*45}ms">`+
      r.map((v,ci)=>`<td class="${isNum(v)?'num':''}">${esc(fmtCell(v,cols[ci]))}</td>`).join("")+
      "</tr>";
  });
  html+="</tbody>";
  t.innerHTML=html;
  $("rescount").textContent=rows.length+(rows.length===1?" row":" rows");
  $("resReveal").classList.add("show");
}

function showAnswer(q,step){
  $("answertext").textContent=q.answer;
  const a=$("answer");
  a.classList.add("show");
  if(!q.success||q.intent==="unsupported"){ a.classList.add("declined"); }
  else { a.classList.remove("declined"); }
}

// ---- free text routing ----
const STOP=new Set(["the","a","an","of","by","in","for","to","and","or","is","are","me","my",
  "show","what","whats","how","has","have","list","give","get","with","on","over","across",
  "that","this","s","do","i","there","was","were","be","it","all"]);
function toks(text){
  const raw=text.toLowerCase().match(/[a-z0-9]+/g)||[];
  const out=[],seen=new Set();
  raw.forEach(t=>{ if(t.length>1&&!STOP.has(t)&&!seen.has(t)){seen.add(t);out.push(t);} });
  return out;
}
function route(text){
  const ts=toks(text);
  let best=-1,score=-1;
  Q.forEach((q,i)=>{
    let s=0; ts.forEach(t=>{ if(q.keywords.includes(t)) s++; });
    if(s>score){score=s;best=i;}
  });
  return {i:best,score:score,matched:ts};
}
function askFree(){
  const v=$("freetext").value.trim();
  if(!v){ $("routed").textContent=""; return; }
  const r=route(v);
  const q=Q[r.i];
  if(r.score<=0){
    $("routed").innerHTML=`No keyword overlap — routing to closest: <b>${esc(q.q)}</b>`;
  } else {
    $("routed").innerHTML=`Routed by keyword overlap (${r.score} match${r.score===1?"":"es"}) → <b>${esc(q.q)}</b>`;
  }
  document.querySelectorAll(".ask").forEach(a=>a.classList.remove("on"));
  const btn=asksEl.querySelector(`[data-i="${r.i}"]`);
  if(btn)btn.classList.add("on");
  runQuestion(q);
}
$("asktext").addEventListener("click",askFree);
$("freetext").addEventListener("keydown",e=>{ if(e.key==="Enter")askFree(); });

// ---- guardrail bench ----
const probesEl=$("probes");
PROBES.forEach((p,i)=>{
  const b=document.createElement("button");
  const blk=p.verdict==="blocked";
  b.className="probe "+(blk?"blk":"alw"); b.dataset.i=i;
  b.innerHTML=`<span class="dot"></span><span class="pl">${esc(p.label)}</span><span class="pv">${p.verdict}</span>`;
  b.addEventListener("click",()=>showProbe(i,b));
  probesEl.appendChild(b);
});
function showProbe(i,btn){
  document.querySelectorAll(".probe").forEach(p=>p.classList.remove("on"));
  if(btn)btn.classList.add("on");
  const p=PROBES[i];
  const blk=p.verdict==="blocked";
  $("bvsql").innerHTML=fmtSQL(p.sql);
  const v=$("bvverdict");
  v.className="gbadge "+(blk?"g-deny":"g-pass");
  v.innerHTML=blk?("✕ blocked"):("✓ allowed");
  $("bvreason").innerHTML=blk
    ? `Rejected before touching the warehouse — reason: <b>${esc(p.reason)}</b>. The agent never sees a connection for this string.`
    : `Cleared the read-only allowlist — reason: <b>${esc(p.reason)}</b>. A legitimate single-table SELECT is allowed through.`;
  const sh=$("shield");
  sh.style.transform=blk?"scale(1.25) rotate(-8deg)":"scale(1.1)";
  setTimeout(()=>{ sh.style.transform="none"; },320);
}

// ---- boot: run first question + first blocked probe ----
window.addEventListener("load",()=>{
  const firstBtn=asksEl.querySelector('[data-i="0"]');
  selectQuestion(0,firstBtn);
  const blkIdx=PROBES.findIndex(p=>p.verdict==="blocked");
  showProbe(blkIdx>=0?blkIdx:0, probesEl.querySelector(`[data-i="${blkIdx>=0?blkIdx:0}"]`));
});
</script>
</body></html>"""


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    p = render(os.path.join(here, "reports", "index.html"))
    print(f"wrote interactive demo -> {p} ({os.path.getsize(p)} bytes)")
