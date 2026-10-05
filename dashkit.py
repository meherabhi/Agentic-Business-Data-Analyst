"""dashkit — a single-file, dependency-free dashboard renderer.

Emits one self-contained HTML page (inline CSS + SVG + vanilla JS, no network
calls) from a small spec. Every project in the portfolio renders its live demo
through this so the whole set shares one premium, dark, animated visual language.

Public API:
    render(out_path, *, title, subtitle, accent="#7c9cff",
           kpis=[...], sections=[...], footer="...", meta="...")

A KPI is: {label, value, sub?, trend?}   (trend is a signed number; arrow + color)
A section is: {title?, note?, cols?(1-3), panels:[panel]}
A panel is: {title?, help?, span?(1-3), chart:{type, ...}}

Chart types (all animate on load, all have hover tooltips where meaningful):
  line     {x:[labels], series:[{name,color?,values:[],dashed?}], area?, band?:{lo:[],hi:[]}, yfmt?}
  bars     {x:[labels], series:[{name,color?,values:[]}], stacked?, yfmt?}
  hbars    {items:[{label,value,color?}], vfmt?}
  donut    {items:[{label,value,color?}], center?}
  gauge    {value, min, max, label, color?, zones?:[{to,color}]}
  heatmap  {xLabels, yLabels, matrix:[[..]], lo?, hi?, fmt?, colorHi?}
  scatter  {points:[{x,y,g?}], groups?:{name:color}, xLabel?, yLabel?}
  roc      {points:[{x,y}], auc}
  table    {columns:[...], rows:[[...]], accentCol?}
"""
from __future__ import annotations

import html
import json
import os
from datetime import datetime, timezone

# --- shared palette (kept in sync with the JS below) ------------------------
SERIES = ["#7c9cff", "#5eead4", "#fca5a5", "#fcd34d", "#c4b5fd", "#f9a8d4", "#93c5fd", "#86efac"]

_CSS = """
:root{
  --bg:#0a0c12; --panel:#111520; --panel2:#0d111a; --line:#1e2534; --line2:#2a3346;
  --txt:#e8ecf4; --mut:#8b95ab; --dim:#5b6580; --accent:__ACCENT__;
  --grid:#171d2b; --ok:#34d399; --bad:#f87171;
  --shadow:0 1px 0 rgba(255,255,255,.03), 0 18px 40px -18px rgba(0,0,0,.7);
}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;background:
  radial-gradient(1100px 620px at 82% -8%, color-mix(in srgb, var(--accent) 16%, transparent), transparent 60%),
  radial-gradient(900px 520px at 8% 4%, rgba(94,234,212,.06), transparent 55%),
  var(--bg);
  color:var(--txt);
  font:14px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,sans-serif;
  -webkit-font-smoothing:antialiased;}
.wrap{max-width:1200px;margin:0 auto;padding:44px 26px 80px}
a{color:var(--accent);text-decoration:none}
.eyebrow{display:inline-flex;align-items:center;gap:8px;font-size:11px;letter-spacing:.16em;
  text-transform:uppercase;color:var(--mut);border:1px solid var(--line2);
  padding:5px 11px;border-radius:999px;background:rgba(255,255,255,.02)}
.eyebrow .live{width:7px;height:7px;border-radius:50%;background:var(--ok);box-shadow:0 0 0 0 rgba(52,211,153,.6);
  animation:pulse 2s infinite}
@keyframes pulse{0%{box-shadow:0 0 0 0 rgba(52,211,153,.5)}70%{box-shadow:0 0 0 7px rgba(52,211,153,0)}100%{box-shadow:0 0 0 0 rgba(52,211,153,0)}}
h1{font-size:clamp(24px,3.4vw,38px);line-height:1.08;margin:18px 0 8px;letter-spacing:-.02em;font-weight:750}
.sub{color:var(--mut);max-width:70ch;font-size:15px;margin:0}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(178px,1fr));gap:14px;margin:34px 0 8px}
.kpi{background:linear-gradient(180deg,var(--panel),var(--panel2));border:1px solid var(--line);
  border-radius:15px;padding:17px 18px;box-shadow:var(--shadow);position:relative;overflow:hidden}
.kpi::after{content:"";position:absolute;inset:0 0 auto 0;height:2px;
  background:linear-gradient(90deg,var(--accent),transparent 70%);opacity:.6}
.kpi .l{color:var(--dim);font-size:11px;letter-spacing:.05em;text-transform:uppercase}
.kpi .v{font-size:29px;font-weight:740;margin-top:7px;letter-spacing:-.02em;font-variant-numeric:tabular-nums}
.kpi .s{color:var(--mut);font-size:12px;margin-top:3px}
.kpi .t{font-size:12px;font-weight:650;margin-top:6px}
.kpi .t.up{color:var(--ok)} .kpi .t.down{color:var(--bad)}
section.blk{margin-top:34px}
.blk > .h{display:flex;align-items:baseline;gap:12px;margin:0 0 15px}
.blk > .h h2{font-size:15px;font-weight:680;margin:0;letter-spacing:.01em}
.blk > .h .note{color:var(--dim);font-size:12.5px}
.grid{display:grid;gap:16px}
.panel{background:linear-gradient(180deg,var(--panel),var(--panel2));border:1px solid var(--line);
  border-radius:16px;padding:18px 18px 14px;box-shadow:var(--shadow);min-width:0}
.panel .pt{display:flex;justify-content:space-between;align-items:center;gap:10px;margin-bottom:12px}
.panel .pt h3{font-size:13px;font-weight:640;margin:0;color:var(--txt)}
.panel .pt .help{color:var(--dim);font-size:11px;text-align:right;max-width:52%}
.chart{width:100%}
.legend{display:flex;flex-wrap:wrap;gap:12px;margin-top:10px;font-size:11.5px;color:var(--mut)}
.legend i{display:inline-block;width:9px;height:9px;border-radius:3px;margin-right:6px;vertical-align:middle}
svg{display:block;width:100%;height:auto;overflow:visible}
.ax{stroke:var(--line2)} .axg{stroke:var(--grid)} .axt{fill:var(--dim);font-size:10px}
.tt{position:fixed;pointer-events:none;background:#05070c;border:1px solid var(--line2);
  border-radius:9px;padding:8px 10px;font-size:12px;color:var(--txt);opacity:0;transform:translateY(4px);
  transition:opacity .12s, transform .12s;z-index:50;box-shadow:0 10px 30px -10px #000;max-width:240px}
.tt.on{opacity:1;transform:translateY(0)}
.tt b{color:var(--accent)}
table.dk{width:100%;border-collapse:collapse;font-size:12.5px}
table.dk th{color:var(--dim);text-transform:uppercase;font-size:10px;letter-spacing:.05em;text-align:left;
  padding:8px 10px;border-bottom:1px solid var(--line2)}
table.dk td{padding:8px 10px;border-bottom:1px solid var(--grid);font-variant-numeric:tabular-nums}
table.dk tr:hover td{background:rgba(255,255,255,.02)}
.badge{display:inline-block;padding:2px 8px;border-radius:999px;font-size:11px;font-weight:600}
.foot{margin-top:46px;padding-top:20px;border-top:1px solid var(--line);color:var(--dim);font-size:12.5px;
  display:flex;justify-content:space-between;flex-wrap:wrap;gap:12px}
.foot b{color:var(--mut);font-weight:600}
@media (max-width:820px){.grid{grid-template-columns:1fr!important}}
"""

_JS = r"""
const PAL=["#7c9cff","#5eead4","#fca5a5","#fcd34d","#c4b5fd","#f9a8d4","#93c5fd","#86efac"];
const NS="http://www.w3.org/2000/svg";
const el=(t,a={})=>{const e=document.createElementNS(NS,t);for(const k in a)e.setAttribute(k,a[k]);return e;};
const $=s=>document.querySelector(s);
let TT;
function tip(){if(!TT){TT=document.createElement('div');TT.className='tt';document.body.appendChild(TT);}return TT;}
function showTip(html,x,y){const t=tip();t.innerHTML=html;t.classList.add('on');t.style.left=(x+14)+'px';t.style.top=(y+14)+'px';}
function hideTip(){if(TT)TT.classList.remove('on');}
const fmt=(v,f)=>{if(f==='pct')return (v*100).toFixed(1)+'%';if(f==='usd')return '$'+Math.round(v).toLocaleString();
  if(f==='usdk')return '$'+(v/1000).toFixed(1)+'k';if(f==='k')return (v/1000).toFixed(1)+'k';
  if(f==='int')return Math.round(v).toLocaleString();if(f==='2')return (+v).toFixed(2);return (typeof v==='number'?(Math.round(v*100)/100).toLocaleString():v);};
const lerp=(a,b,t)=>a+(b-a)*t;
function mixHex(c1,c2,t){const p=c=>[parseInt(c.slice(1,3),16),parseInt(c.slice(3,5),16),parseInt(c.slice(5,7),16)];
  const A=p(c1),B=p(c2);const r=A.map((v,i)=>Math.round(lerp(v,B[i],t)));return `rgb(${r[0]},${r[1]},${r[2]})`;}
function reveal(node){node.querySelectorAll('[data-draw]').forEach(p=>{
  const len=p.getTotalLength?p.getTotalLength():0;p.style.strokeDasharray=len;p.style.strokeDashoffset=len;
  requestAnimationFrame(()=>{p.style.transition='stroke-dashoffset 1.05s cubic-bezier(.22,.61,.36,1)';p.style.strokeDashoffset=0;});});
  node.querySelectorAll('[data-grow]').forEach((r,i)=>{const to=r.getAttribute('data-grow');const attr=r.getAttribute('data-growattr');
    const v0=r.getAttribute(attr);setTimeout(()=>{r.style.transition=`${attr} .8s cubic-bezier(.22,.61,.36,1), y .8s cubic-bezier(.22,.61,.36,1), opacity .5s`;r.setAttribute(attr,to);if(r.getAttribute('data-toY')!=null)r.setAttribute('y',r.getAttribute('data-toY'));r.style.opacity=1;},60+i*22);});
  node.querySelectorAll('[data-fade]').forEach((n,i)=>{n.style.opacity=0;setTimeout(()=>{n.style.transition='opacity .6s';n.style.opacity=1;},120+i*35);});
}

function axes(svg,W,H,P,xl,xt,yl,yt,opt={}){
  // grid + ticks; xt: array of {t,label}, yt: array of numbers, yfmt
  const x0=P.l,x1=W-P.r,y0=H-P.b,y1=P.t;
  (yt||[]).forEach(v=>{const y=lerp(y0,y1,(v-yl[0])/(yl[1]-yl[0]||1));
    svg.appendChild(el('line',{x1:x0,x2:x1,y1:y,y2:y,class:'axg','stroke-width':1}));
    const tx=el('text',{x:x0-8,y:y+3,class:'axt','text-anchor':'end'});tx.textContent=fmt(v,opt.yfmt);svg.appendChild(tx);});
  (xt||[]).forEach(o=>{const t=el('text',{x:o.x,y:y0+16,class:'axt','text-anchor':'middle'});t.textContent=o.label;svg.appendChild(t);});
  svg.appendChild(el('line',{x1:x0,x2:x1,y1:y0,y2:y0,class:'ax','stroke-width':1}));
}

const R={};
R.line=(host,c)=>{const W=680,H=300,P={l:46,r:18,t:16,b:28};const svg=el('svg',{viewBox:`0 0 ${W} ${H}`});
  const n=c.x.length;const all=[].concat(...c.series.map(s=>s.values),...(c.band?c.band.lo.concat(c.band.hi):[]));
  let lo=Math.min(...all),hi=Math.max(...all);if(lo>0)lo=Math.min(lo,0);const pad=(hi-lo)*.08||1;hi+=pad;lo-=(lo<0?pad:0);
  const X=i=>lerp(P.l,W-P.r,n<2?.5:i/(n-1)),Y=v=>lerp(H-P.b,P.t,(v-lo)/(hi-lo||1));
  const yt=[];for(let k=0;k<=4;k++)yt.push(lo+(hi-lo)*k/4);
  const xt=c.x.map((l,i)=>({x:X(i),label:l}));const step=Math.ceil(n/8);
  axes(svg,W,H,P,[lo,hi],[lo,hi],[lo,hi],yt,{yfmt:c.yfmt});
  xt.forEach((o,i)=>{if(i%step===0||i===n-1){const t=el('text',{x:o.x,y:H-P.b+16,class:'axt','text-anchor':'middle'});t.textContent=o.label;svg.appendChild(t);}});
  if(c.band){let d='M'+c.band.lo.map((v,i)=>`${X(i)},${Y(v)}`).join('L');for(let i=n-1;i>=0;i--)d+=`L${X(i)},${Y(c.band.hi[i])}`;d+='Z';
    svg.appendChild(el('path',{d,fill:c.series[0].color||PAL[0],'fill-opacity':.10,'data-fade':1}));}
  c.series.forEach((s,si)=>{const col=s.color||PAL[si%PAL.length];
    if(c.area){let d=`M${X(0)},${Y(s.values[0])}`;s.values.forEach((v,i)=>d+=`L${X(i)},${Y(v)}`);d+=`L${X(n-1)},${Y(lo)}L${X(0)},${Y(lo)}Z`;
      const g='g'+si+Math.random().toString(36).slice(2,6);const defs=el('defs');const lg=el('linearGradient',{id:g,x1:0,y1:0,x2:0,y2:1});
      lg.appendChild(el('stop',{offset:0,'stop-color':col,'stop-opacity':.35}));lg.appendChild(el('stop',{offset:1,'stop-color':col,'stop-opacity':0}));
      defs.appendChild(lg);svg.appendChild(defs);svg.appendChild(el('path',{d,fill:`url(#${g})`,'data-fade':1}));}
    let d='M'+s.values.map((v,i)=>`${X(i)},${Y(v)}`).join('L');
    svg.appendChild(el('path',{d,fill:'none',stroke:col,'stroke-width':2.4,'stroke-linejoin':'round','stroke-linecap':'round','data-draw':1,'stroke-dasharray':s.dashed?'6 5':''}));
    s.values.forEach((v,i)=>{const cx=X(i),cy=Y(v);const dot=el('circle',{cx,cy,r:3.2,fill:'var(--bg)',stroke:col,'stroke-width':2,'data-fade':1});
      dot.addEventListener('mousemove',e=>showTip(`<b>${s.name}</b><br>${c.x[i]}: ${fmt(v,c.yfmt)}`,e.clientX,e.clientY));dot.addEventListener('mouseleave',hideTip);svg.appendChild(dot);});});
  host.appendChild(svg);if(c.series.length>1||c.series[0].name)legend(host,c.series.map((s,i)=>({name:s.name,color:s.color||PAL[i%PAL.length]})));};

R.bars=(host,c)=>{const W=680,H=300,P={l:46,r:14,t:16,b:30};const svg=el('svg',{viewBox:`0 0 ${W} ${H}`});
  const n=c.x.length,m=c.series.length;const tot=c.stacked?c.x.map((_,i)=>c.series.reduce((a,s)=>a+s.values[i],0)):null;
  let hi=c.stacked?Math.max(...tot):Math.max(...[].concat(...c.series.map(s=>s.values)));hi*=1.12||1;const lo=0;
  const Y=v=>lerp(H-P.b,P.t,(v-lo)/(hi-lo||1));const bw=(W-P.l-P.r)/n;const yt=[];for(let k=0;k<=4;k++)yt.push(hi*k/4);
  axes(svg,W,H,P,[lo,hi],[lo,hi],[lo,hi],yt,{yfmt:c.yfmt});
  c.x.forEach((l,i)=>{const t=el('text',{x:P.l+bw*(i+.5),y:H-P.b+16,class:'axt','text-anchor':'middle'});t.textContent=l;svg.appendChild(t);});
  c.x.forEach((_,i)=>{let acc=0;const iw=c.stacked?bw*.5:(bw*.66)/m;
    c.series.forEach((s,si)=>{const col=s.color||PAL[si%PAL.length];const v=s.values[i];const h=(H-P.b)-Y(v);
      const x=c.stacked?P.l+bw*i+bw*.25:P.l+bw*i+bw*.17+si*iw;const y=c.stacked?Y(acc+v):Y(v);
      const r=el('rect',{x,y:H-P.b,width:iw,height:0,rx:3,fill:col,'data-grow':h,'data-growattr':'height','data-toY':y,opacity:.9});
      r.addEventListener('mousemove',e=>showTip(`<b>${s.name}</b><br>${c.x[i]}: ${fmt(v,c.yfmt)}`,e.clientX,e.clientY));r.addEventListener('mouseleave',hideTip);
      svg.appendChild(r);acc+=v;});});
  host.appendChild(svg);if(m>1)legend(host,c.series.map((s,i)=>({name:s.name,color:s.color||PAL[i%PAL.length]})));};

R.hbars=(host,c)=>{const items=c.items;const W=680,rh=30,P={l:150,r:58,t:8,b:8};const H=P.t+P.b+items.length*rh;
  const svg=el('svg',{viewBox:`0 0 ${W} ${H}`});const vals=items.map(i=>i.value);
  const mn=Math.min(0,...vals),mx=Math.max(0,...vals);const span=(mx-mn)||1;const x0=P.l,x1=W-P.r;
  const X=v=>x0+(x1-x0)*((v-mn)/span);const zx=X(0);const signed=mn<0;
  items.forEach((it,i)=>{const y=P.t+i*rh+rh/2;
    const col=it.color||(signed?(it.value<0?'#fca5a5':'#5eead4'):PAL[i%PAL.length]);
    const lb=el('text',{x:P.l-12,y:y+4,class:'axt','text-anchor':'end'});lb.textContent=it.label;lb.setAttribute('fill','var(--mut)');svg.appendChild(lb);
    svg.appendChild(el('rect',{x:x0,y:y-8,width:x1-x0,height:16,rx:5,fill:'var(--grid)'}));
    const xv=X(it.value);const bx=Math.min(zx,xv),bw=Math.abs(xv-zx);
    const r=el('rect',{x:bx,y:y-8,width:0,height:16,rx:5,fill:col,'data-grow':bw,'data-growattr':'width'});
    r.addEventListener('mousemove',e=>showTip(`<b>${it.label}</b><br>${fmt(it.value,c.vfmt)}`,e.clientX,e.clientY));r.addEventListener('mouseleave',hideTip);svg.appendChild(r);
    const vv=el('text',{x:x1+8,y:y+4,class:'axt','text-anchor':'start'});vv.textContent=fmt(it.value,c.vfmt);vv.setAttribute('fill','var(--txt)');svg.appendChild(vv);});
  if(signed)svg.appendChild(el('line',{x1:zx,y1:P.t,x2:zx,y2:H-P.b,stroke:'var(--line2)','stroke-width':1}));
  host.appendChild(svg);};

R.donut=(host,c)=>{const W=320,H=250,cx=W/2,cy=H/2,r=86,ir=56;const svg=el('svg',{viewBox:`0 0 ${W} ${H}`});
  const tot=c.items.reduce((a,i)=>a+i.value,0)||1;let a0=-Math.PI/2;
  c.items.forEach((it,i)=>{const frac=it.value/tot;const a1=a0+frac*2*Math.PI;const col=it.color||PAL[i%PAL.length];
    const p=(ang,rad)=>[cx+rad*Math.cos(ang),cy+rad*Math.sin(ang)];const large=frac>.5?1:0;
    const[x0,y0]=p(a0,r),[x1,y1]=p(a1,r),[x2,y2]=p(a1,ir),[x3,y3]=p(a0,ir);
    const d=`M${x0},${y0}A${r},${r} 0 ${large} 1 ${x1},${y1}L${x2},${y2}A${ir},${ir} 0 ${large} 0 ${x3},${y3}Z`;
    const path=el('path',{d,fill:col,opacity:.92,'data-fade':1});
    path.addEventListener('mousemove',e=>showTip(`<b>${it.label}</b><br>${fmt(it.value)} · ${(frac*100).toFixed(1)}%`,e.clientX,e.clientY));path.addEventListener('mouseleave',hideTip);
    svg.appendChild(path);a0=a1;});
  if(c.center){const t1=el('text',{x:cx,y:cy-2,'text-anchor':'middle',fill:'var(--txt)','font-size':22,'font-weight':720});t1.textContent=c.center.value;
    const t2=el('text',{x:cx,y:cy+16,'text-anchor':'middle',fill:'var(--dim)','font-size':11});t2.textContent=c.center.label;svg.appendChild(t1);svg.appendChild(t2);}
  host.appendChild(svg);legend(host,c.items.map((it,i)=>({name:`${it.label} · ${fmt(it.value)}`,color:it.color||PAL[i%PAL.length]})));};

R.gauge=(host,c)=>{const W=320,H=210,cx=W/2,cy=170,r=118;const svg=el('svg',{viewBox:`0 0 ${W} ${H}`});
  const a=v=>Math.PI*(1+(v-c.min)/(c.max-c.min||1));const arc=(a0,a1,col,w)=>{const p=ang=>[cx+r*Math.cos(ang),cy+r*Math.sin(ang)];
    const[x0,y0]=p(a0),[x1,y1]=p(a1);const large=(a1-a0)>Math.PI?1:0;return el('path',{d:`M${x0},${y0}A${r},${r} 0 ${large} 1 ${x1},${y1}`,fill:'none',stroke:col,'stroke-width':w,'stroke-linecap':'round'});};
  svg.appendChild(arc(Math.PI,2*Math.PI,'var(--grid)',16));
  const zones=c.zones||[{to:c.max,color:c.color||PAL[0]}];let from=c.min;
  zones.forEach(z=>{svg.appendChild(arc(a(from),a(z.to),z.color,16));from=z.to;});
  const av=a(Math.max(c.min,Math.min(c.max,c.value)));const nx=cx+(r-6)*Math.cos(av),ny=cy+(r-6)*Math.sin(av);
  const nd=el('line',{x1:cx,y1:cy,x2:cx,y2:cy,stroke:'var(--txt)','stroke-width':3,'stroke-linecap':'round'});svg.appendChild(nd);
  setTimeout(()=>{nd.style.transition='all .9s cubic-bezier(.22,.61,.36,1)';nd.setAttribute('x2',nx);nd.setAttribute('y2',ny);},80);
  svg.appendChild(el('circle',{cx,cy,r:5,fill:'var(--txt)'}));
  const t1=el('text',{x:cx,y:cy-24,'text-anchor':'middle',fill:'var(--txt)','font-size':30,'font-weight':740});t1.textContent=fmt(c.value,c.vfmt);
  const t2=el('text',{x:cx,y:cy-6,'text-anchor':'middle',fill:'var(--dim)','font-size':11});t2.textContent=c.label;svg.appendChild(t1);svg.appendChild(t2);
  host.appendChild(svg);};

R.heatmap=(host,c)=>{const cols=c.xLabels.length,rows=c.yLabels.length;const cell=Math.min(52,Math.max(26,520/cols));
  const P={l:96,t:26,r:14,b:10};const W=P.l+cols*cell+P.r,H=P.t+rows*cell+P.b;const svg=el('svg',{viewBox:`0 0 ${W} ${H}`});
  let lo=c.lo,hi=c.hi;if(lo==null||hi==null){const f=[].concat(...c.matrix);lo=Math.min(...f);hi=Math.max(...f);}
  const hiCol=c.colorHi||'#7c9cff';
  c.xLabels.forEach((l,i)=>{const t=el('text',{x:P.l+i*cell+cell/2,y:P.t-8,class:'axt','text-anchor':'middle'});t.textContent=l;svg.appendChild(t);});
  c.yLabels.forEach((l,j)=>{const t=el('text',{x:P.l-10,y:P.t+j*cell+cell/2+3,class:'axt','text-anchor':'end'});t.textContent=l;svg.appendChild(t);});
  c.matrix.forEach((row,j)=>row.forEach((v,i)=>{const t=(v-lo)/(hi-lo||1);const col=mixHex('#0e1523',hiCol,Math.max(.04,t));
    const rc=el('rect',{x:P.l+i*cell+2,y:P.t+j*cell+2,width:cell-4,height:cell-4,rx:5,fill:col,'data-fade':1,stroke:'rgba(255,255,255,.04)'});
    rc.addEventListener('mousemove',e=>showTip(`<b>${c.yLabels[j]} · ${c.xLabels[i]}</b><br>${fmt(v,c.fmt)}`,e.clientX,e.clientY));rc.addEventListener('mouseleave',hideTip);svg.appendChild(rc);
    if(cell>=34){const tv=el('text',{x:P.l+i*cell+cell/2,y:P.t+j*cell+cell/2+3,'text-anchor':'middle','font-size':9.5,fill:t>.5?'#08111f':'var(--mut)'});tv.textContent=fmt(v,c.fmt);svg.appendChild(tv);}}));
  host.appendChild(svg);};

R.scatter=(host,c)=>{const W=680,H=320,P={l:46,r:16,t:14,b:32};const svg=el('svg',{viewBox:`0 0 ${W} ${H}`});
  const xs=c.points.map(p=>p.x),ys=c.points.map(p=>p.y);let xl=[Math.min(...xs),Math.max(...xs)],yl=[Math.min(...ys),Math.max(...ys)];
  const px=(xl[1]-xl[0])*.06||1,py=(yl[1]-yl[0])*.08||1;xl=[xl[0]-px,xl[1]+px];yl=[yl[0]-py,yl[1]+py];
  const X=v=>lerp(P.l,W-P.r,(v-xl[0])/(xl[1]-xl[0])),Y=v=>lerp(H-P.b,P.t,(v-yl[0])/(yl[1]-yl[0]));
  const yt=[];for(let k=0;k<=4;k++)yt.push(yl[0]+(yl[1]-yl[0])*k/4);axes(svg,W,H,P,yl,yl,yl,yt,{yfmt:c.yfmt});
  c.points.forEach((p,i)=>{const col=(c.groups&&p.g&&c.groups[p.g])||PAL[0];const dot=el('circle',{cx:X(p.x),cy:Y(p.y),r:p.r||3.4,fill:col,'fill-opacity':.7,'data-fade':1});
    dot.addEventListener('mousemove',e=>showTip(`${p.g?('<b>'+p.g+'</b><br>'):''}${c.xLabel||'x'}: ${fmt(p.x,c.xfmt)}<br>${c.yLabel||'y'}: ${fmt(p.y,c.yfmt)}`,e.clientX,e.clientY));dot.addEventListener('mouseleave',hideTip);svg.appendChild(dot);});
  host.appendChild(svg);if(c.groups)legend(host,Object.entries(c.groups).map(([k,v])=>({name:k,color:v})));};

R.roc=(host,c)=>{const W=360,H=320,P={l:44,r:16,t:14,b:34};const svg=el('svg',{viewBox:`0 0 ${W} ${H}`});
  const X=v=>lerp(P.l,W-P.r,v),Y=v=>lerp(H-P.b,P.t,v);const yt=[0,.25,.5,.75,1];
  axes(svg,W,H,P,[0,1],[0,1],[0,1],yt,{yfmt:'2'});[.25,.5,.75,1].forEach(v=>{const t=el('text',{x:X(v),y:H-P.b+16,class:'axt','text-anchor':'middle'});t.textContent=v.toFixed(2);svg.appendChild(t);});
  svg.appendChild(el('line',{x1:X(0),y1:Y(0),x2:X(1),y2:Y(1),stroke:'var(--line2)','stroke-dasharray':'4 4','stroke-width':1}));
  let d='M'+c.points.map(p=>`${X(p.x)},${Y(p.y)}`).join('L');
  const g='roc'+Math.random().toString(36).slice(2,6);const defs=el('defs');const lg=el('linearGradient',{id:g,x1:0,y1:1,x2:0,y2:0});
  lg.appendChild(el('stop',{offset:0,'stop-color':'#7c9cff','stop-opacity':0}));lg.appendChild(el('stop',{offset:1,'stop-color':'#7c9cff','stop-opacity':.28}));defs.appendChild(lg);svg.appendChild(defs);
  svg.appendChild(el('path',{d:d+`L${X(1)},${Y(0)}L${X(0)},${Y(0)}Z`,fill:`url(#${g})`,'data-fade':1}));
  svg.appendChild(el('path',{d,fill:'none',stroke:'#7c9cff','stroke-width':2.6,'data-draw':1}));
  const t=el('text',{x:X(.62),y:Y(.28),fill:'var(--txt)','font-size':13,'font-weight':680});t.textContent='AUC '+c.auc.toFixed(3);svg.appendChild(t);
  const xl=el('text',{x:(P.l+W-P.r)/2,y:H-6,class:'axt','text-anchor':'middle'});xl.textContent='False positive rate';svg.appendChild(xl);
  host.appendChild(svg);};

R.table=(host,c)=>{const t=document.createElement('table');t.className='dk';const thead=document.createElement('thead');const tr=document.createElement('tr');
  c.columns.forEach(col=>{const th=document.createElement('th');th.textContent=col;tr.appendChild(th);});thead.appendChild(tr);t.appendChild(thead);
  const tb=document.createElement('tbody');c.rows.forEach(row=>{const r=document.createElement('tr');row.forEach((cell,ci)=>{const td=document.createElement('td');
    if(cell&&typeof cell==='object'){const b=document.createElement('span');b.className='badge';b.textContent=cell.t;b.style.background=(cell.c||'#7c9cff')+'22';b.style.color=cell.c||'#7c9cff';td.appendChild(b);}
    else{td.textContent=cell;if(ci===c.accentCol)td.style.color='var(--accent)';}r.appendChild(td);});tb.appendChild(r);});t.appendChild(tb);host.appendChild(t);};

function legend(host,items){const d=document.createElement('div');d.className='legend';
  items.forEach(it=>{const s=document.createElement('span');s.innerHTML=`<i style="background:${it.color}"></i>${it.name}`;d.appendChild(s);});host.appendChild(d);}

function boot(){const data=window.__DASH__;const io=new IntersectionObserver((es)=>{es.forEach(e=>{if(e.isIntersecting){reveal(e.target);io.unobserve(e.target);}});},{threshold:.15});
  Object.entries(data).forEach(([id,spec])=>{const host=document.getElementById(id);if(!host)return;(R[spec.type]||(()=>{}))(host,spec);io.observe(host);});
  // count-up KPIs
  document.querySelectorAll('[data-count]').forEach(n=>{const to=parseFloat(n.getAttribute('data-count'));const suf=n.getAttribute('data-suf')||'';const pre=n.getAttribute('data-pre')||'';const dec=+(n.getAttribute('data-dec')||0);
    let t0=null;const dur=1100;function step(ts){if(!t0)t0=ts;const p=Math.min(1,(ts-t0)/dur);const e=1-Math.pow(1-p,3);n.textContent=pre+(to*e).toLocaleString(undefined,{minimumFractionDigits:dec,maximumFractionDigits:dec})+suf;if(p<1)requestAnimationFrame(step);}requestAnimationFrame(step);});}
document.addEventListener('DOMContentLoaded',boot);
"""


def _kpi_html(k: dict) -> str:
    v = str(k["value"])
    num = k.get("count")
    if num is not None:
        val = (f'<div class="v" data-count="{num}" data-pre="{html.escape(k.get("pre",""))}" '
               f'data-suf="{html.escape(k.get("suf",""))}" data-dec="{k.get("dec",0)}">{html.escape(v)}</div>')
    else:
        val = f'<div class="v">{html.escape(v)}</div>'
    sub = f'<div class="s">{html.escape(k["sub"])}</div>' if k.get("sub") else ""
    trend = ""
    if k.get("trend") is not None:
        t = k["trend"]
        cls = "up" if t >= 0 else "down"
        arr = "▲" if t >= 0 else "▼"
        trend = f'<div class="t {cls}">{arr} {abs(t)}</div>'
    return f'<div class="kpi"><div class="l">{html.escape(k["label"])}</div>{val}{sub}{trend}</div>'


def render(out_path: str, *, title: str, subtitle: str = "", accent: str = "#7c9cff",
           eyebrow: str = "Live demo", kpis: list | None = None,
           sections: list | None = None, footer: str = "", meta: str = "") -> str:
    charts: dict[str, dict] = {}
    cid = [0]

    def panel_html(p: dict) -> str:
        cid[0] += 1
        hid = f"c{cid[0]}"
        charts[hid] = p["chart"]
        pt = ""
        if p.get("title") or p.get("help"):
            help_ = f'<span class="help">{html.escape(p["help"])}</span>' if p.get("help") else ""
            pt = f'<div class="pt"><h3>{html.escape(p.get("title",""))}</h3>{help_}</div>'
        span = p.get("span", 1)
        return f'<div class="panel" style="grid-column:span {span}">{pt}<div class="chart" id="{hid}"></div></div>'

    secs = []
    for s in (sections or []):
        cols = s.get("cols", 2)
        head = ""
        if s.get("title"):
            note = f'<span class="note">{html.escape(s["note"])}</span>' if s.get("note") else ""
            head = f'<div class="h"><h2>{html.escape(s["title"])}</h2>{note}</div>'
        panels = "".join(panel_html(p) for p in s["panels"])
        secs.append(f'<section class="blk">{head}<div class="grid" '
                    f'style="grid-template-columns:repeat({cols},1fr)">{panels}</div></section>')

    kpi_html = ""
    if kpis:
        kpi_html = '<div class="kpis">' + "".join(_kpi_html(k) for k in kpis) + "</div>"

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    foot = footer or "Self-contained demo · generated from a deterministic run · no external calls."
    css = _CSS.replace("__ACCENT__", accent)

    doc = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>{css}</style></head><body><div class="wrap">
<span class="eyebrow"><span class="live"></span>{html.escape(eyebrow)}</span>
<h1>{html.escape(title)}</h1>
<p class="sub">{html.escape(subtitle)}</p>
{kpi_html}
{''.join(secs)}
<div class="foot"><span>{html.escape(foot)}</span><span><b>{html.escape(meta)}</b> · built {now}</span></div>
</div>
<script>window.__DASH__={json.dumps(charts)};</script>
<script>{_JS}</script>
</body></html>"""
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w") as fh:
        fh.write(doc)
    return out_path
