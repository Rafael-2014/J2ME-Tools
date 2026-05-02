#!/usr/bin/env python3
"""Editor UTF-16 J2ME — Flask, mobile-first"""

from flask import Flask, request, jsonify, send_file
import io

app = Flask(__name__)
state = {"entries": [], "bom": b'\xff\xfe', "sep": "\r\n", "suffix": "\r\n", "filename": "output.txt"}

def parse_bytes(raw):
    bom = raw[:2] if raw[:2] in (b'\xff\xfe', b'\xfe\xff') else b'\xff\xfe'
    text = raw.decode("utf-16")
    # Detecta e preserva o separador exato do arquivo
    if "\r\n" in text:
        sep = "\r\n"
    elif "\r" in text:
        sep = "\r"
    else:
        sep = "\n"
    suffix = sep if text.endswith(sep) else ""
    parts = text.split(sep)
    if parts and parts[-1] == "":
        parts = parts[:-1]
    entries = []
    for i, line in enumerate(parts):
        s = line.strip()
        if s.startswith('"') and s.endswith('"') and len(s) >= 2:
            entries.append({"i": i, "c": s[1:-1], "o": s[1:-1], "e": True})
        else:
            entries.append({"i": i, "c": None, "o": line, "e": False})
    return entries, bom, sep, suffix

def serialize(entries, bom, sep="\r\n", suffix="\r\n"):
    lines = [f'"{e["c"]}"' if e["e"] else e["o"] for e in entries]
    enc = "utf-16-be" if bom == b'\xfe\xff' else "utf-16-le"
    return bom + (sep.join(lines) + suffix).encode(enc)

@app.route("/api/upload", methods=["POST"])
def api_upload():
    f = request.files.get("file")
    if not f: return jsonify({"error": "Sem arquivo"}), 400
    try:
        entries, bom, sep, suffix = parse_bytes(f.read())
        state.update(entries=entries, bom=bom, sep=sep, suffix=suffix, filename=f.filename or "output.txt")
        strings = [{"idx": i, "c": e["c"], "o": e["o"]}
                   for i, e in enumerate(entries) if e["e"]]
        return jsonify({"ok": True, "filename": state["filename"], "strings": strings})
    except Exception as ex:
        return jsonify({"error": str(ex)}), 500

@app.route("/api/save_string", methods=["POST"])
def api_save_string():
    data = request.json
    i, c = data.get("idx"), data.get("c", "")
    if i is None or i >= len(state["entries"]): return jsonify({"error": "índice inválido"}), 400
    state["entries"][i]["c"] = c
    return jsonify({"ok": True})

@app.route("/api/download")
def api_download():
    if not state["entries"]: return "vazio", 400
    return send_file(io.BytesIO(serialize(state["entries"], state["bom"], state["sep"], state["suffix"])),
                     as_attachment=True, download_name=state["filename"],
                     mimetype="application/octet-stream")

@app.route("/")
def index(): return HTML

HTML = r"""<!DOCTYPE html>
<html lang="pt">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>J2ME Editor</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700&display=swap');

*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

:root {
  --bg:    #0d0d16;
  --surf:  #12121e;
  --card:  #1a1a2e;
  --brd:   #2a2a45;
  --acc:   #7c6af7;
  --grn:   #3de8b0;
  --txt:   #dddaf8;
  --mut:   #55547a;
  --red:   #f56565;
  --org:   #f5a623;
  --mono:  'JetBrains Mono', monospace;
  --bar:   52px;
  --bot:   60px;
}

html { height: 100%; }
body {
  font-family: var(--mono);
  background: var(--bg);
  color: var(--txt);
  height: 100dvh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* ── TOPBAR ─────────────────────────────────────── */
#topbar {
  height: var(--bar);
  min-height: var(--bar);
  background: var(--surf);
  border-bottom: 1px solid var(--brd);
  display: flex;
  align-items: center;
  justify-content: flex-end;
  padding: 0 15px;
  gap: 8px;
  flex-shrink: 0;
}
#logo { 
  font-size: 0.85rem; 
  font-weight: 700; 
  color: var(--acc); 
  white-space: nowrap; 
  flex-shrink: 0;
  margin-right: auto;
}
#logo b { color: var(--grn); }

/* Botão salvar na topbar */
.hbtn {
  flex-shrink: 0;
  background: var(--card); border: 1px solid var(--brd); color: var(--txt);
  font-family: var(--mono); font-size: 0.7rem;
  padding: 7px 12px; border-radius: 8px; cursor: pointer;
  white-space: nowrap; transition: all .15s;
}
.hbtn:hover { border-color: var(--acc); color: var(--acc); }
.hbtn.g { background: var(--grn); color: #0d0d16; border-color: var(--grn); font-weight: 700; }

/* ── TELA INICIAL (welcome) ─────────────────────── */
#welcome {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 20px;
  padding: 32px 24px;
}
.w-icon { font-size: 3rem; opacity: .3; }
.w-title { font-size: 1.1rem; font-weight: 700; color: var(--acc); }
.w-title b { color: var(--grn); }
.w-sub { font-size: 0.72rem; color: var(--mut); text-align: center; line-height: 1.9; }

/* BOTÃO CENTRALIZADO DE ABRIR ARQUIVO */
#open-btn {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  width: 100%;
  max-width: 300px;
  padding: 30px 20px;
  background: var(--card);
  border: 2px dashed var(--brd);
  border-radius: 18px;
  cursor: pointer;
  transition: border-color .2s, background .2s;
  overflow: hidden;
}
#open-btn:hover, #open-btn.drag {
  border-color: var(--acc);
  background: rgba(124,106,247,.08);
}
#open-btn input { position: absolute; inset: 0; opacity: 0; cursor: pointer; width: 100%; height: 100%; }
.ob-icon { font-size: 2.8rem; pointer-events: none; }
.ob-label { font-size: 0.82rem; font-weight: 700; color: var(--txt); pointer-events: none; }
.ob-hint  { font-size: 0.64rem; color: var(--mut); pointer-events: none; }

/* ── CORPO (app carregado) ──────────────────────── */
#app {
  flex: 1;
  min-height: 0;
  display: none;
  flex-direction: column;
  overflow: hidden;
}
#app.loaded { display: flex; }

#body {
  flex: 1;
  min-height: 0;
  display: flex;
  overflow: hidden;
}

/* ── PAINEL LISTA ───────────────────────────────── */
#pane-list {
  display: flex; flex-direction: column;
  background: var(--surf);
  border-right: 1px solid var(--brd);
  overflow: hidden;
  width: 270px; flex-shrink: 0;
}

/* barra de busca */
.search-wrap {
  display: flex; align-items: center; gap: 6px;
  padding: 8px; border-bottom: 1px solid var(--brd); flex-shrink: 0;
}
.search-wrap input {
  flex: 1; background: var(--card); border: 1px solid var(--brd);
  color: var(--txt); font-family: var(--mono);
  font-size: 0.75rem; padding: 7px 9px; border-radius: 7px;
  outline: none; min-width: 0;
}
.search-wrap input:focus { border-color: var(--acc); }
.xbtn { background: none; border: none; color: var(--mut); font-size: 1rem; cursor: pointer; padding: 2px 4px; flex-shrink: 0; }
.xbtn:hover { color: var(--red); }
#str-count { font-size: 0.63rem; color: var(--mut); padding: 4px 10px 2px; flex-shrink: 0; }

#list { flex: 1; overflow-y: auto; overscroll-behavior: contain; scrollbar-width: thin; scrollbar-color: var(--brd) transparent; }

.row {
  display: flex; align-items: center;
  padding: 11px 12px;
  border-bottom: 1px solid rgba(255,255,255,.03);
  cursor: pointer; transition: background .1s;
  gap: 5px; min-height: 44px;
}
.row:hover { background: var(--card); }
.row.sel   { background: rgba(124,106,247,.15); border-left: 3px solid var(--acc); padding-left: 9px; }
.row-num   { font-size: 0.6rem; color: var(--mut); flex-shrink: 0; }
.row.sel .row-num { color: var(--acc); opacity: .5; }
.row-text  { font-size: 0.73rem; color: var(--mut); flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.row.sel .row-text { color: var(--acc); }
.row.mod .row-text { color: var(--org); }
.row-nl    { font-size: 0.55rem; color: var(--grn); border: 1px solid rgba(61,232,176,.3); border-radius: 3px; padding: 0 3px; flex-shrink: 0; }

/* ── PAINEL EDITOR ──────────────────────────────── */
#pane-edit {
  flex: 1; display: flex; flex-direction: column;
  overflow: hidden; padding: 10px; gap: 8px; min-width: 0;
}
#ph { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 10px; color: var(--mut); font-size: 0.78rem; text-align: center; }
#ph .e { font-size: 2.8rem; opacity: .18; }
#ec { flex: 1; display: none; flex-direction: column; gap: 7px; overflow: hidden; min-height: 0; }

.ibar { display: flex; align-items: center; gap: 8px; flex-shrink: 0; flex-wrap: wrap; }
.badge { background: var(--acc); color: #fff; font-size: 0.68rem; font-weight: 700; padding: 2px 9px; border-radius: 5px; }
.cc    { font-size: 0.68rem; color: var(--mut); }
.dot   { width: 7px; height: 7px; border-radius: 50%; background: var(--org); opacity: 0; transition: opacity .2s; }
.dot.on { opacity: 1; }
.nl-pill { font-size: 0.6rem; color: var(--grn); border: 1px solid rgba(61,232,176,.3); border-radius: 4px; padding: 1px 6px; display: none; }
.nl-pill.on { display: inline; }

.sec-lbl { font-size: 0.58rem; font-weight: 700; letter-spacing: 1.5px; text-transform: uppercase; margin-bottom: 3px; flex-shrink: 0; }
.sec-lbl.o { color: var(--mut); }
.sec-lbl.t { color: var(--grn); }

.orig {
  flex-shrink: 0; background: rgba(255,255,255,.02);
  border: 1px solid var(--brd); border-radius: 8px;
  padding: 8px 11px; font-size: 0.8rem; color: var(--mut);
  white-space: pre-wrap; word-break: break-word;
  max-height: 80px; overflow-y: auto; line-height: 1.6;
}
.tarea-wrap { flex: 1; display: flex; flex-direction: column; min-height: 0; }
#ta {
  flex: 1; background: var(--card);
  border: 1.5px solid var(--brd); border-radius: 8px;
  padding: 10px 12px; font-family: var(--mono);
  font-size: 0.88rem; color: var(--txt);
  resize: none; outline: none; line-height: 1.7; width: 100%;
  transition: border-color .15s;
}
#ta:focus { border-color: var(--acc); }

.abar { display: flex; align-items: center; gap: 6px; flex-shrink: 0; }
.nbtn {
  background: var(--card); border: 1px solid var(--brd); color: var(--mut);
  font-family: var(--mono); font-size: 0.73rem;
  padding: 9px 13px; border-radius: 7px; cursor: pointer;
  transition: all .15s; min-height: 40px;
}
.nbtn:hover:not(:disabled) { border-color: var(--acc); color: var(--acc); }
.nbtn:disabled { opacity: .28; cursor: default; }
.nbtn.wide { flex: 1; text-align: center; }
#st { font-size: 0.67rem; color: var(--mut); white-space: nowrap; }
#st.ok { color: var(--grn); }
.savebtn {
  background: var(--acc); color: #fff; border: none;
  font-family: var(--mono); font-size: 0.78rem; font-weight: 700;
  padding: 9px 16px; border-radius: 7px; cursor: pointer;
  min-height: 40px; transition: opacity .15s;
}
.savebtn:hover { opacity: .85; }

/* ── TABBAR (mobile) ────────────────────────────── */
#tabbar { display: none; height: var(--bot); min-height: var(--bot); background: var(--surf); border-top: 1px solid var(--brd); flex-shrink: 0; }
.tabs { display: flex; height: 100%; }
.tab {
  flex: 1; display: flex; flex-direction: column;
  align-items: center; justify-content: center; gap: 2px;
  background: none; border: none; color: var(--mut);
  font-family: var(--mono); font-size: 0.58rem;
  cursor: pointer; transition: color .15s; padding: 6px 4px; min-height: 44px;
}
.tab .ic { font-size: 1.25rem; line-height: 1; }
.tab.on  { color: var(--acc); }

/* ── TOAST ──────────────────────────────────────── */
#toast {
  position: fixed; bottom: calc(var(--bot) + 10px);
  left: 50%; transform: translateX(-50%) translateY(10px);
  background: var(--card); border: 1px solid var(--brd); color: var(--txt);
  font-size: 0.75rem; padding: 8px 18px; border-radius: 20px;
  opacity: 0; transition: all .22s; pointer-events: none;
  z-index: 998; white-space: nowrap; max-width: calc(100vw - 32px); text-align: center;
}
#toast.on { opacity: 1; transform: translateX(-50%) translateY(0); }
#toast.ok { border-color: var(--grn); color: var(--grn); }
#toast.er { border-color: var(--red); color: var(--red); }

/* ── MOBILE ≤ 680px ─────────────────────────────── */
@media (max-width: 680px) {
  #tabbar { display: block; }
  .hbtn   { display: none; }
  #logo   { font-size: 0.75rem; }

  #body { position: relative; }
  #pane-list, #pane-edit {
    position: absolute; inset: 0;
    width: 100%; border-right: none;
    display: none;
  }
  #pane-list.visible, #pane-edit.visible { display: flex; }

  .row { min-height: 50px; padding: 12px 14px; }
  .row-text { font-size: 0.78rem; }

  .abar { flex-wrap: wrap; }
  .nbtn.wide { flex-basis: calc(50% - 3px); }
  #st { order: 3; width: 100%; text-align: center; }
  .savebtn { order: 4; width: 100%; padding: 12px; font-size: 0.82rem; }
  .orig { max-height: 65px; font-size: 0.77rem; }
  #ta { font-size: 0.88rem; }
  #toast { bottom: calc(var(--bot) + 12px); }
}
</style>
</head>
<body>

<!-- TOPBAR -->
<div id="topbar">
  <div id="logo">UTF-16 <b>J2ME</b></div>
  <button class="hbtn g" onclick="doSave()">💾 Salvar</button>
</div>

<!-- TELA INICIAL -->
<div id="welcome">
  <div class="w-icon">🎮</div>
  <div class="w-title">UTF-16 <b>J2ME</b> Editor</div>
  <div class="w-sub">Tradutor de strings para jogos Java J2ME.<br>Suporta arquivos UTF-16 LE/BE.</div>

  <div id="open-btn">
    <input type="file" accept="*" onchange="openFile(this.files[0])">
    <div class="ob-icon">📂</div>
    <div class="ob-label">Escolher arquivo</div>
    <div class="ob-hint">Toque aqui ou arraste o arquivo</div>
  </div>
</div>

<!-- APP (aparece após carregar arquivo) -->
<div id="app">
  <div id="body">

    <!-- PAINEL LISTA -->
    <div id="pane-list">
      <div class="search-wrap">
        <input id="search" type="search" placeholder="🔍 Buscar string…" oninput="doFilter()">
        <button class="xbtn" onclick="clearSearch()">✕</button>
      </div>
      <div id="str-count">0 strings</div>
      <div id="list"></div>
    </div>

    <!-- PAINEL EDITOR -->
    <div id="pane-edit">
      <div id="ph">
        <div class="e">✏️</div>
        Selecione uma string na lista
      </div>
      <div id="ec">
        <div class="ibar">
          <span class="badge" id="bdg">#1</span>
          <span class="cc" id="cc">0 ch</span>
          <div class="dot" id="dot"></div>
          <span class="nl-pill" id="nlp">↵ \n</span>
        </div>
        <div>
          <div class="sec-lbl o">Original</div>
          <div class="orig" id="orig"></div>
        </div>
        <div class="tarea-wrap">
          <div class="sec-lbl t">Tradução</div>
          <textarea id="ta" spellcheck="false" oninput="onEdit()"
            placeholder="Digite a tradução…&#10;Enter = \n no jogo"></textarea>
        </div>
        <div class="abar">
          <button class="nbtn wide" id="bp" onclick="nav(-1)" disabled>◀ Ant.</button>
          <button class="nbtn wide" id="bn" onclick="nav(1)"  disabled>Próx. ▶</button>
          <span id="st">pronto</span>
          <button class="savebtn" onclick="saveStr()">✓ Salvar string</button>
        </div>
      </div>
    </div>
  </div>

  <!-- TABBAR mobile -->
  <div id="tabbar">
    <div class="tabs">
      <button class="tab on" id="t-list" onclick="goTab('list')">
        <span class="ic">☰</span><span>Lista</span>
      </button>
      <button class="tab" id="t-edit" onclick="goTab('edit')">
        <span class="ic">✏️</span><span>Editor</span>
      </button>
      <button class="tab" onclick="doSave()">
        <span class="ic">💾</span><span>Salvar</span>
      </button>
    </div>
  </div>
</div>

<div id="toast"></div>

<script>
'use strict';

let S = [], F = [], cur = -1, dirty = false, mobile = false;

/* ── mobile ──────────────────────────────────────── */
function checkMobile() {
  mobile = window.innerWidth <= 680;
  document.getElementById('tabbar').style.display = mobile ? 'block' : 'none';
  if (!mobile) {
    ['list','edit'].forEach(n => {
      const el = document.getElementById('pane-' + n);
      el.classList.remove('visible');
      el.style.display = 'flex';
    });
  } else {
    ['list','edit'].forEach(n => {
      document.getElementById('pane-' + n).style.display = '';
    });
    if (!document.getElementById('pane-list').classList.contains('visible') &&
        !document.getElementById('pane-edit').classList.contains('visible')) {
      showPane('list');
    }
  }
}
function showPane(n) {
  ['list','edit'].forEach(p => document.getElementById('pane-'+p).classList.toggle('visible', p===n));
  document.getElementById('t-list').classList.toggle('on', n==='list');
  document.getElementById('t-edit').classList.toggle('on', n==='edit');
}
function goTab(n) {
  if (n==='edit' && dirty) saveStr(true);
  showPane(n);
  if (n==='edit') setTimeout(() => document.getElementById('ta').focus(), 80);
}
window.addEventListener('resize', checkMobile);
checkMobile();

/* ── abrir arquivo ───────────────────────────────── */
async function openFile(file) {
  if (!file) return;
  const fd = new FormData();
  fd.append('file', file);
  try {
    const r = await fetch('/api/upload', {method:'POST', body:fd});
    const d = await r.json();
    if (d.error) { toast(d.error,'er'); return; }
    S = d.strings.map(s => ({...s, mod:false}));
    F = S.map((_,i) => i);

    document.title = d.filename;

    document.getElementById('welcome').style.display = 'none';
    document.getElementById('app').classList.add('loaded');

    drawList();
    if (mobile) showPane('list');
    toast(`${S.length} strings carregadas ✓`, 'ok');
  } catch(e) { toast('Erro: '+e,'er'); }
}

// drag & drop no open-btn
const openBtn = document.getElementById('open-btn');
openBtn.addEventListener('dragover',  e => { e.preventDefault(); openBtn.classList.add('drag'); });
openBtn.addEventListener('dragleave', () => openBtn.classList.remove('drag'));
openBtn.addEventListener('drop', e => {
  e.preventDefault(); openBtn.classList.remove('drag');
  if (e.dataTransfer.files[0]) openFile(e.dataTransfer.files[0]);
});

/* ── lista ───────────────────────────────────────── */
function doFilter() {
  const q = document.getElementById('search').value.toLowerCase();
  F = S.reduce((a,s,i) => {
    if (!q || s.c.toLowerCase().includes(q) || s.o.toLowerCase().includes(q)) a.push(i);
    return a;
  },[]);
  drawList();
}
function clearSearch() { document.getElementById('search').value=''; doFilter(); }

function drawList() {
  const el = document.getElementById('list');
  el.innerHTML = '';
  F.forEach((si, pos) => {
    const s = S[si];
    const hasNL = s.c.includes('\\n');
    const prev  = s.c.replace(/\\n/g,' ↵ ').slice(0,60) || '(vazio)';
    const div = document.createElement('div');
    div.className = 'row'+(pos===cur?' sel':'')+(s.mod?' mod':'');
    div.innerHTML =
      `<span class="row-num">${si+1}</span>`+
      `<span class="row-text">${esc(prev)}</span>`+
      (hasNL?`<span class="row-nl">↵</span>`:'');
    div.addEventListener('click', () => {
      saveStr(true); pick(pos);
      if (mobile) goTab('edit');
    });
    el.appendChild(div);
  });
  document.getElementById('str-count').textContent = `${F.length} / ${S.length}`;
}
function esc(s){ return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

/* ── selecionar ──────────────────────────────────── */
function g2e(s){ return s.replace(/\\n/g,'\n'); }
function e2g(s){ return s.replace(/\n/g,'\\n'); }

function pick(pos) {
  if (pos<0||pos>=F.length) return;
  cur = pos;
  const s = S[F[pos]];
  document.getElementById('ph').style.display = 'none';
  document.getElementById('ec').style.display = 'flex';
  document.getElementById('bdg').textContent  = '#'+(F[pos]+1);
  document.getElementById('orig').textContent = g2e(s.o);
  document.getElementById('ta').value         = g2e(s.c);
  updCC();
  const hasNL = s.c.includes('\\n');
  document.getElementById('nlp').className = 'nl-pill'+(hasNL?' on':'');
  document.getElementById('bp').disabled = pos===0;
  document.getElementById('bn').disabled = pos===F.length-1;
  dirty = false;
  document.getElementById('dot').className = 'dot';
  setSt('pronto');
  drawList();
  const rows = document.querySelectorAll('.row');
  if (rows[pos]) rows[pos].scrollIntoView({block:'nearest'});
}
function updCC(){ document.getElementById('cc').textContent = document.getElementById('ta').value.length+' ch'; }
function onEdit(){
  dirty=true;
  document.getElementById('dot').className='dot on';
  updCC();
  const hasNL = document.getElementById('ta').value.includes('\n');
  document.getElementById('nlp').className='nl-pill'+(hasNL?' on':'');
  setSt('editando…');
}

/* ── salvar string ───────────────────────────────── */
async function saveStr(silent=false){
  if(cur<0) return;
  const si=F[cur], c=e2g(document.getElementById('ta').value);
  const r=await fetch('/api/save_string',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({idx:S[si].idx,c})});
  const d=await r.json();
  if(d.error){toast(d.error,'er');return;}
  S[si].mod=c!==S[si].o; S[si].c=c;
  dirty=false;
  document.getElementById('dot').className='dot';
  if(!silent){setSt('salvo ✓');toast('String salva ✓','ok');}
  drawList();
}
async function nav(dir){ if(dirty) await saveStr(true); pick(cur+dir); }

/* ── salvar arquivo ──────────────────────────────── */
async function doSave(){
  if(!S.length){ toast('Nenhum arquivo carregado','er'); return; }
  if(dirty) await saveStr(true);
  window.location.href='/api/download';
  toast('Baixando arquivo…','ok');
}

/* ── helpers ─────────────────────────────────────── */
function setSt(m){ const el=document.getElementById('st'); el.textContent=m; el.className=m.includes('✓')?'ok':''; }
let toastT;
function toast(msg,type=''){
  const el=document.getElementById('toast');
  el.textContent=msg; el.className='on '+type;
  clearTimeout(toastT); toastT=setTimeout(()=>el.className='',2500);
}
document.addEventListener('keydown',e=>{
  const m=e.ctrlKey||e.metaKey;
  if(m&&e.key==='Enter'){e.preventDefault();saveStr();}
  if(m&&e.key==='s'){e.preventDefault();doSave();}
  if(m&&e.key==='ArrowDown'){e.preventDefault();nav(1);}
  if(m&&e.key==='ArrowUp'){e.preventDefault();nav(-1);}
});
</script>
</body>
</html>
"""

if __name__ == '__main__':
    print('\n╔══════════════════════════════╗')
    print('║  J2ME Editor — localhost:5000 ║')
    print('╚══════════════════════════════╝\n')
    app.run(host='0.0.0.0', port=5000, debug=False)