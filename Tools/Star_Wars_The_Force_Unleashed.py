#!/usr/bin/env python3
"""
Star Wars: The Force Unleashed (THQ) — String Editor
Web interface via Flask - Versão Mobile First
"""

import copy
import io
from flask import Flask, render_template_string, request, jsonify, send_file

app = Flask(__name__)

# ── Parser / Rebuilder ─────────────────────────────────────────────────────────

def _decode_string(raw_bytes: bytes):
    """
    Detecta e decodifica os bytes da string.
    Retorna (texto, encoding_detectado).
    Prioridade: UTF-8 → Latin-1.
    """
    try:
        return raw_bytes.decode('utf-8'), 'utf-8'
    except UnicodeDecodeError:
        return raw_bytes.decode('latin-1', errors='replace'), 'latin-1'


def _encode_string(text: str, encoding: str) -> bytes:
    """
    Codifica o texto respeitando o encoding original da entrada.
    """
    enc = encoding if encoding in ('utf-8', 'latin-1') else 'utf-8'
    try:
        return text.encode(enc, errors='replace')
    except Exception:
        return text.encode('utf-8', errors='replace')


def _try_entry_3b(raw: bytes, offset: int):
    """
    Tenta ler entrada com header de 3 bytes:
      [outer:1][0x00:1][inner:1][string:inner][flag:1][lo:1][hi:1]
      Regra: outer == inner + 2, unk == 0x00
    """
    if offset + 5 >= len(raw):
        return None
    outer = raw[offset]
    unk   = raw[offset + 1]
    inner = raw[offset + 2]
    if unk != 0x00 or inner == 0 or outer != inner + 2:
        return None
    str_end = offset + 3 + inner
    if str_end + 2 >= len(raw):
        return None
    flag = raw[str_end]
    if flag not in (0x00, 0x01):
        return None
    lo = raw[str_end + 1]
    hi = raw[str_end + 2]
    s, enc = _decode_string(raw[offset + 3:str_end])
    return {
        'offset':   offset,
        'hdr_size': 3,
        'inner':    inner,
        'string':   s,
        'encoding': enc,
        'flag':     flag,
        'lo':       lo,
        'hi':       hi,
        'value':    lo | (hi << 8),
        'next_off': str_end + 3,
    }


def _try_entry_4b(raw: bytes, offset: int):
    """
    Tenta ler entrada com header de 4 bytes (uint16 big-endian):
      [outer_hi:1][outer_lo:1][inner_hi:1][inner_lo:1][string:inner][flag:1][lo:1][hi:1]
      Regra: outer == inner + 2
    """
    if offset + 6 >= len(raw):
        return None
    outer = (raw[offset] << 8) | raw[offset + 1]
    inner = (raw[offset + 2] << 8) | raw[offset + 3]
    if inner == 0 or outer != inner + 2:
        return None
    str_end = offset + 4 + inner
    if str_end + 2 >= len(raw):
        return None
    flag = raw[str_end]
    if flag not in (0x00, 0x01):
        return None
    lo = raw[str_end + 1]
    hi = raw[str_end + 2]
    s, enc = _decode_string(raw[offset + 4:str_end])
    return {
        'offset':   offset,
        'hdr_size': 4,
        'inner':    inner,
        'string':   s,
        'encoding': enc,
        'flag':     flag,
        'lo':       lo,
        'hi':       hi,
        'value':    lo | (hi << 8),
        'next_off': str_end + 3,
    }


def parse_en_file(raw: bytes) -> dict:
    """
    Parse the .en binary e retorna representação estruturada completa.
    Suporta:
      - Header de 3 bytes (formato original Latin-1)
      - Header de 4 bytes uint16 BE (formato UTF-8 / strings longas)
      - Detecção automática de codificação (UTF-8 vs Latin-1) por entrada
    """
    if raw[:4] != b'ST0\x01':
        raise ValueError("Magic inválido – esperado 'ST0\\x01'")

    entries = []
    offset  = 8   # pula os 8 bytes de header global

    while offset < len(raw) - 5:
        # Tenta header 3 bytes primeiro (mais comum)
        e = _try_entry_3b(raw, offset)
        if e is None:
            # Tenta header 4 bytes (UTF-8 / strings longas)
            e = _try_entry_4b(raw, offset)
        if e:
            entries.append(e)
            offset = e['next_off']
        else:
            offset += 1

    section1 = [e for e in entries if e['flag'] == 0]
    section2 = [e for e in entries if e['flag'] == 1]

    for i, e in enumerate(section1):
        e['game_id'] = section1[i - 1]['value'] if i > 0 else 0

    for e in section2:
        e['seq'] = e['value']

    all_sorted = sorted(entries, key=lambda e: e['offset'])
    gaps = {}
    for i in range(len(all_sorted) - 1):
        curr     = all_sorted[i]
        nxt      = all_sorted[i + 1]
        curr_end = curr['next_off']
        gap      = raw[curr_end:nxt['offset']]
        if gap:
            gaps[i] = gap

    last     = all_sorted[-1]
    trailing = raw[last['next_off']:]

    # Detectar encoding global (majoritário)
    enc_counts = {'utf-8': 0, 'latin-1': 0}
    for e in entries:
        enc_counts[e.get('encoding', 'utf-8')] += 1
    global_encoding = 'utf-8' if enc_counts['utf-8'] >= enc_counts['latin-1'] else 'latin-1'

    return {
        'header':          raw[:8],
        'section1':        section1,
        'section2':        section2,
        '_sorted':         all_sorted,
        '_gaps':           gaps,
        '_trailing':       trailing,
        'global_encoding': global_encoding,
    }


def rebuild_en_file(parsed: dict) -> bytes:
    """
    Reconstrói o arquivo binário preservando:
      - header global (8 bytes)
      - hdr_size original de cada entrada (3 ou 4 bytes)
      - encoding original de cada entrada (utf-8 ou latin-1)
      - gaps entre entradas (bytes brutos)
      - trailing bytes
    """
    out = bytearray(parsed['header'])

    all_sorted      = sorted(parsed['section1'] + parsed['section2'],
                             key=lambda e: e['offset'])
    entry_by_offset = {e['offset']: e for e in all_sorted}
    orig_sorted     = parsed['_sorted']
    gaps            = parsed['_gaps']
    global_enc      = parsed.get('global_encoding', 'utf-8')

    for i, orig_e in enumerate(orig_sorted):
        e        = entry_by_offset.get(orig_e['offset'], orig_e)
        hdr_size = orig_e.get('hdr_size', 3)
        enc      = orig_e.get('encoding', global_enc)

        s_enc = _encode_string(e['string'], enc)
        inner = len(s_enc)
        outer = inner + 2

        if hdr_size == 4:
            # Header uint16 big-endian (2B outer + 2B inner)
            out += bytes([(outer >> 8) & 0xFF, outer & 0xFF,
                          (inner >> 8) & 0xFF, inner & 0xFF])
        else:
            # Header padrão 3 bytes
            out += bytes([outer & 0xFF, 0x00, inner & 0xFF])

        out += s_enc
        out += bytes([e['flag'], e['lo'], e['hi']])
        if i in gaps:
            out += gaps[i]

    out += parsed['_trailing']
    return bytes(out)


import uuid
state = {
    'parsed':     None,
    'filename':   'en',
    'session_id': str(uuid.uuid4()),  # novo ID a cada execução do servidor
}


# ── HTML Mobile First ──────────────────────────────────────────────────────────

HTML = r"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=yes, viewport-fit=cover"/>
<title>TFU String Editor</title>
<style>
* {
    margin: 0;
    padding: 0;
    box-sizing: border-box;
    -webkit-tap-highlight-color: transparent;
}

:root {
    --bg: #0a0a12;
    --panel: #12121c;
    --panel2: #18182a;
    --border: #2a2a3a;
    --border2: #353548;
    --accent: #ffe81f;
    --accent2: #d4b800;
    --red: #d04040;
    --green: #3ab060;
    --text: #e0e4f0;
    --muted: #6a6a8a;
    --input: #0e0e18;
    --hover: #202038;
}

body {
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
    min-height: 100vh;
    padding: 12px;
}

/* Upload Container - Tela inicial */
.upload-container {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    min-height: 85vh;
    gap: 20px;
}

.dropzone {
    border: 2px dashed var(--border2);
    border-radius: 20px;
    padding: 40px 24px;
    text-align: center;
    cursor: pointer;
    transition: all 0.2s;
    background: var(--panel);
    width: 100%;
    max-width: 400px;
}

.dropzone:active {
    transform: scale(0.98);
}

.dropzone b {
    color: var(--accent);
    font-size: 1.2rem;
}

.dropzone p {
    font-size: 0.85rem;
    color: var(--muted);
    margin-top: 12px;
    line-height: 1.5;
}

.info-text {
    font-size: 0.8rem;
    color: var(--muted);
    text-align: center;
    max-width: 300px;
    line-height: 1.5;
}

#fileInput {
    display: none;
}

/* Main App - Só aparece após upload */
.app-container {
    display: none;
    flex-direction: column;
    gap: 10px;
}

/* HEADER FIXO - NÃO ROLA */
.app-header {
    position: sticky;
    top: 0;
    z-index: 100;
    background: var(--bg);
    padding-bottom: 8px;
}

/* Barra superior com ações - compacta */
.action-bar {
    display: flex;
    gap: 6px;
    background: var(--panel);
    padding: 8px 10px;
    border-radius: 12px;
}

.action-bar button {
    flex: 1;
    padding: 8px 0;
    border: none;
    border-radius: 10px;
    font-size: 0.75rem;
    font-weight: 600;
    background: var(--input);
    color: var(--text);
    cursor: pointer;
    transition: all 0.1s;
    white-space: nowrap;
}

.action-bar button:active {
    transform: scale(0.96);
}

.action-bar button.primary {
    background: var(--accent);
    color: #000;
}

.action-bar button.danger {
    background: #3a2020;
    color: var(--red);
}

/* Stats bar compacta */
.stats-bar {
    background: var(--panel);
    padding: 6px 10px;
    border-radius: 10px;
    font-size: 0.7rem;
    color: var(--muted);
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
    gap: 6px;
}

.stats-bar span:first-child {
    color: var(--accent);
    font-size: 0.7rem;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

/* CONTEÚDO ROLÁVEL */
.app-content {
    flex: 1;
    overflow-y: auto;
    max-height: calc(100vh - 100px);
}

/* Lista de strings */
.strings-list {
    background: var(--panel);
    border-radius: 12px;
    overflow: hidden;
    margin-bottom: 12px;
}

.list-header {
    display: flex;
    gap: 8px;
    padding: 8px 10px;
    background: var(--panel2);
    border-bottom: 1px solid var(--border);
}

.list-header button {
    flex: 1;
    padding: 8px;
    border: none;
    border-radius: 8px;
    font-size: 0.8rem;
    font-weight: 600;
    background: var(--input);
    color: var(--text);
    cursor: pointer;
}

.list-header button.active {
    background: var(--accent);
    color: #000;
}

.search-box {
    width: 100%;
    padding: 8px 10px;
    background: var(--input);
    border: none;
    border-radius: 0;
    color: var(--text);
    font-size: 0.85rem;
    border-bottom: 1px solid var(--border);
}

.items-container {
    max-height: 35vh;
    overflow-y: auto;
}

.string-item {
    padding: 10px;
    border-bottom: 1px solid var(--border);
    cursor: pointer;
    transition: background 0.1s;
}

.string-item:active {
    background: var(--hover);
}

.string-item.selected {
    background: rgba(255, 232, 31, 0.15);
    border-left: 3px solid var(--accent);
}

.string-item.modified {
    border-left: 3px solid var(--accent2);
}

.item-id {
    font-size: 0.6rem;
    color: var(--muted);
    font-family: monospace;
    margin-bottom: 4px;
}

.item-preview {
    font-size: 0.75rem;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

/* Editor */
.editor-card {
    background: var(--panel);
    border-radius: 12px;
    padding: 10px;
    margin-bottom: 12px;
}

.editor-header {
    display: flex;
    gap: 6px;
    margin-bottom: 10px;
    flex-wrap: wrap;
}

.editor-header button {
    padding: 8px 10px;
    border: none;
    border-radius: 8px;
    background: var(--input);
    color: var(--text);
    font-size: 0.7rem;
    cursor: pointer;
    flex: 1;
    min-width: 55px;
}

.editor-header button.primary {
    background: var(--accent);
    color: #000;
    font-weight: bold;
}

.editor-meta {
    font-size: 0.65rem;
    color: var(--muted);
    margin-bottom: 10px;
    padding: 4px 0;
    word-break: break-word;
}

.editor-meta b {
    color: var(--accent);
}

.label {
    font-size: 0.65rem;
    color: var(--muted);
    text-transform: uppercase;
    margin-bottom: 4px;
    display: block;
}

.original-box {
    background: var(--input);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 8px;
    font-size: 0.8rem;
    line-height: 1.45;
    white-space: pre-wrap;
    word-break: break-word;
    margin-bottom: 12px;
    max-height: 120px;
    overflow-y: auto;
}

.edit-textarea {
    width: 100%;
    background: var(--input);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 8px;
    color: var(--text);
    font-size: 0.85rem;
    font-family: inherit;
    line-height: 1.45;
    resize: vertical;
    margin-bottom: 10px;
}

.special-chars {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin-bottom: 10px;
}

.special-chars button {
    padding: 5px 10px;
    background: var(--input);
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--muted);
    font-size: 0.65rem;
    cursor: pointer;
}

.diff-box {
    background: var(--input);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 8px;
    font-size: 0.75rem;
    line-height: 1.45;
    max-height: 100px;
    overflow-y: auto;
}

.diff-del {
    color: var(--red);
}

.diff-add {
    color: var(--green);
}

/* Modal */
.modal {
    display: none;
    position: fixed;
    inset: 0;
    background: rgba(0,0,0,0.85);
    z-index: 1000;
    align-items: center;
    justify-content: center;
    padding: 20px;
}

.modal.show {
    display: flex;
}

.modal-content {
    background: var(--panel2);
    border-radius: 16px;
    padding: 20px;
    max-width: 90%;
    max-height: 80vh;
    overflow-y: auto;
}

.modal-content h3 {
    color: var(--accent);
    margin-bottom: 12px;
}

.modal-content table {
    width: 100%;
    font-size: 0.75rem;
    border-collapse: collapse;
}

.modal-content td {
    padding: 6px 2px;
}

/* ========== LANDSCAPE MODE - CORRIGIDO ========== */
@media (orientation: landscape) {
    body {
        padding: 8px;
        height: 100vh;
        overflow: hidden;
    }
    
    .app-container {
        height: 100vh;
        display: flex;
        flex-direction: column;
        gap: 8px;
        overflow: hidden;
    }
    
    .app-header {
        flex-shrink: 0;
        position: static;
        padding-bottom: 0;
    }
    
    .action-bar {
        padding: 6px 8px;
    }
    
    .action-bar button {
        font-size: 0.7rem;
        padding: 6px 0;
    }
    
    .stats-bar {
        padding: 5px 8px;
        font-size: 0.65rem;
    }
    
    .app-content {
        display: flex;
        flex-direction: row;
        gap: 10px;
        flex: 1;
        overflow: hidden;
        min-height: 0;
    }
    
    .strings-list {
        flex: 1.2;
        display: flex;
        flex-direction: column;
        margin-bottom: 0;
        overflow: hidden;
        min-width: 200px;
    }
    
    .items-container {
        flex: 1;
        max-height: none;
        overflow-y: auto;
    }
    
    .editor-card {
        flex: 2;
        display: flex;
        flex-direction: column;
        margin-bottom: 0;
        min-width: 250px;
        height: 100%;
        overflow-y: scroll;
        padding-right: 5px;
        padding-bottom: 20px;
    }
    
    .editor-header {
        flex-shrink: 0;
    }
    
    .editor-meta {
        flex-shrink: 0;
    }
    
    .original-box {
        flex-shrink: 0;
        min-height: 100px;
        max-height: 100px;
        overflow-y: auto;
        font-size: 0.85rem;
        padding: 10px;
        margin-bottom: 12px;
    }
    
    .edit-textarea {
        flex-shrink: 0;
        min-height: 100px;
        max-height: 100px;
        font-size: 0.85rem;
        padding: 10px;
        margin-bottom: 12px;
    }
    
    .special-chars {
        flex-shrink: 0;
        margin-bottom: 12px;
    }
    
    .diff-box {
        flex-shrink: 0;
        margin-bottom: 20px;
        min-height: 80px;
        max-height: 120px;
        overflow-y: auto;
        font-size: 0.75rem;
        padding: 10px;
    }
}

/* Portrait - normal */
@media (orientation: portrait) {
    .app-content {
        overflow-y: auto;
        max-height: calc(100vh - 100px);
    }
    
    .strings-list {
        margin-bottom: 12px;
    }
    
    .editor-card {
        margin-bottom: 12px;
    }
}

/* Touch optimizations */
button, .string-item, .dropzone {
    cursor: pointer;
    touch-action: manipulation;
}

button:disabled {
    opacity: 0.4;
    transform: none;
}
</style>
</head>
<body>

<!-- Upload inicial -->
<div id="uploadContainer" class="upload-container">
    <div class="dropzone" id="dropZone">
        <b>📁 Arraste o arquivo <code>en</code> aqui</b>
        <p>ou clique para selecionar<br>Arquivo de strings do SW:TFU (THQ)</p>
    </div>
    <div class="info-text">
        Seção 1: strings de UI/jogo (menu, HUD, mensagens)<br>
        Seção 2: strings de diálogos com sequência
    </div>
    <input type="file" id="fileInput" accept="*">
</div>

<!-- App principal (aparece após upload) -->
<div id="appContainer" class="app-container">
    <!-- HEADER FIXO (NÃO ROLA) -->
    <div class="app-header">
        <div class="action-bar">
            <button id="btnSave" class="primary">💾 Salvar</button>
            <button id="btnRevert">↩ Reverter</button>
            <button id="btnStats">📊 Info</button>
        </div>
        <div class="stats-bar">
            <span id="fileInfo">—</span>
            <span id="modCount"></span>
        </div>
    </div>
    
    <!-- CONTEÚDO ROLÁVEL (2 COLUNAS NO LANDSCAPE) -->
    <div class="app-content">
        <div class="strings-list">
            <div class="list-header">
                <button id="tab1" data-sec="1" class="active">UI</button>
                <button id="tab2" data-sec="2">Diálogos</button>
            </div>
            <input type="text" id="searchBox" class="search-box" placeholder="🔍 Buscar...">
            <div id="itemsContainer" class="items-container"></div>
        </div>
        
        <div class="editor-card">
            <div class="editor-header">
                <button id="btnPrev">◀ Anterior</button>
                <button id="btnNext">Próximo ▶</button>
                <button id="btnApply" class="primary">✔ Aplicar</button>
                <button id="btnDiscard">✖ Descartar</button>
            </div>
            <div id="editorMeta" class="editor-meta">Selecione uma string</div>
            
            <span class="label">Original</span>
            <div id="origBox" class="original-box">—</div>
            
            <span class="label">Edição</span>
            <textarea id="editBox" class="edit-textarea" rows="4" placeholder="Selecione uma string..."></textarea>
            
            <div class="special-chars">
                <button class="ins" data-ch="|">↵ newline</button>
                <button class="ins" data-ch="{0}">{0}</button>
                <button class="ins" data-ch="{1}">{1}</button>
                <button class="ins" data-ch="{2}">{2}</button>
                <button class="ins" data-ch="{3}">{3}</button>
                <button class="ins" data-ch="…">…</button>
            </div>
            
            <span class="label">Diferença</span>
            <div id="diffBox" class="diff-box"><span class="diff-same">—</span></div>
        </div>
    </div>
</div>

<div id="statsModal" class="modal">
    <div class="modal-content">
        <h3>📊 Informações</h3>
        <div id="statsContent"></div>
        <button onclick="closeModal()" style="margin-top:12px;padding:8px 16px;">Fechar</button>
    </div>
</div>

<script>
// ── Estado ────────────────────────────────────────────────────────────────────
let D = null, O = null;
let sec = 1, idx = null, q = '';
let mods = new Set();

const $ = id => document.getElementById(id);
const esc = s => s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
function entries()     { return D ? (sec===1 ? D.section1 : D.section2) : []; }
function origEntries() { return O ? (sec===1 ? O.section1 : O.section2) : []; }

// ── localStorage (apenas para sair/voltar com servidor ativo) ─────────────────
const LS_DATA = 'tfu_D';
const LS_ORIG = 'tfu_O';
const LS_MODS = 'tfu_mods';
const LS_FILE = 'tfu_filename';
const LS_SEC  = 'tfu_sec';
const LS_IDX  = 'tfu_idx';
const LS_SID  = 'tfu_sid';   // ID de sessão do servidor

function lsSave() {
    try {
        localStorage.setItem(LS_DATA, JSON.stringify(D));
        localStorage.setItem(LS_ORIG, JSON.stringify(O));
        localStorage.setItem(LS_MODS, JSON.stringify([...mods]));
        localStorage.setItem(LS_SEC,  String(sec));
        localStorage.setItem(LS_IDX,  idx !== null ? String(idx) : '');
    } catch(e) { console.warn('localStorage cheio:', e); }
}

function lsSaveFilename(name) {
    try { localStorage.setItem(LS_FILE, name); } catch(e) {}
}

function lsRestore() {
    try {
        const raw_d = localStorage.getItem(LS_DATA);
        const raw_o = localStorage.getItem(LS_ORIG);
        if (!raw_d || !raw_o) return false;
        D    = JSON.parse(raw_d);
        O    = JSON.parse(raw_o);
        mods = new Set(JSON.parse(localStorage.getItem(LS_MODS) || '[]'));
        sec  = parseInt(localStorage.getItem(LS_SEC) || '1') || 1;
        const si = localStorage.getItem(LS_IDX);
        idx  = (si !== null && si !== '') ? parseInt(si) : null;
        return true;
    } catch(e) { return false; }
}

function lsClearAll() {
    [LS_DATA, LS_ORIG, LS_MODS, LS_FILE, LS_SEC, LS_IDX, LS_SID]
        .forEach(k => localStorage.removeItem(k));
}

// ── UI helpers ────────────────────────────────────────────────────────────────
function showApp() {
    $('uploadContainer').style.display = 'none';
    $('appContainer').style.display = 'flex';
}
function hideApp() {
    $('uploadContainer').style.display = 'flex';
    $('appContainer').style.display = 'none';
}
function status(msg) { $('fileInfo').innerHTML = msg; }
function badgeMod()  { $('modCount').textContent = mods.size ? `✏ ${mods.size}` : ''; }

function syncTabs() {
    $('tab1').classList.toggle('active', sec===1);
    $('tab2').classList.toggle('active', sec===2);
}

function clearEditor() {
    $('editorMeta').textContent = 'Selecione uma string';
    $('origBox').textContent = '—';
    $('editBox').value = '';
    $('diffBox').innerHTML = '<span class="diff-same">—</span>';
    $('editBox').disabled = true;
    $('btnApply').disabled = true;
    $('btnDiscard').disabled = true;
    $('btnPrev').disabled = true;
    $('btnNext').disabled = true;
}

// ── Renderização ──────────────────────────────────────────────────────────────
function renderList() {
    const container = $('itemsContainer');
    container.innerHTML = '';
    const es = entries();
    
    es.forEach((e, i) => {
        const k = `${sec}_${i}`;
        const lbl = sec===1 ? `ID:${e.game_id??i}` : `SEQ:${e.seq??i}`;
        const prev = e.string.replace(/\|/g,'↵');
        if (q && !prev.toLowerCase().includes(q) && !String(e.game_id??e.seq??i).includes(q)) return;
        const div = document.createElement('div');
        div.className = `string-item ${idx===i?'selected':''} ${mods.has(k)?'modified':''}`;
        div.innerHTML = `<div class="item-id">${esc(lbl)}</div>
                         <div class="item-preview">${esc(prev)}</div>`;
        div.onclick = () => select(i);
        container.appendChild(div);
    });
}

function select(i) {
    idx = i;
    renderList();
    const e  = entries()[i];
    const oe = origEntries()[i];
    const encTag = `<span style="color:${e.encoding==='utf-8'?'var(--green)':'var(--accent2)'}">${e.encoding??'utf-8'}</span>`;
    $('editorMeta').innerHTML = sec===1
        ? `ID: <b>${e.game_id??i}</b> · idx_next: <b>${e.value}</b> · hdr:<b>${e.hdr_size??3}B</b> · ${encTag}`
        : `SEQ: <b>${e.seq??i}</b> · hdr:<b>${e.hdr_size??3}B</b> · ${encTag}`;
    $('origBox').textContent    = oe.string;
    $('editBox').value          = e.string;
    $('editBox').disabled       = false;
    $('btnApply').disabled      = false;
    $('btnDiscard').disabled    = false;
    $('btnPrev').disabled       = i === 0;
    $('btnNext').disabled       = i === entries().length - 1;
    updateDiff();
    lsSave();   // persiste posição selecionada
}

function updateDiff() {
    if (idx === null) return;
    const v = $('editBox').value;
    const orig = origEntries()[idx].string;
    if (v === orig) {
        $('diffBox').innerHTML = '<span class="diff-same">Sem alterações</span>';
    } else {
        $('diffBox').innerHTML =
            `<div class="diff-del">− ${esc(orig.replace(/\|/g,'↵'))}</div>
             <div class="diff-add">+ ${esc(v.replace(/\|/g,'↵'))}</div>`;
    }
}

// ── Edição ────────────────────────────────────────────────────────────────────
function applyEdit() {
    if (idx === null) return;
    const v  = $('editBox').value;
    const k  = `${sec}_${idx}`;
    entries()[idx].string = v;
    if (v !== origEntries()[idx].string) mods.add(k);
    else mods.delete(k);
    badgeMod();
    renderList();
    lsSave();   // ← persiste imediatamente
    status(`String ${idx} alterada · ${mods.size} modificação(ões)`);
}

function discardEdit() {
    if (idx === null) return;
    const k  = `${sec}_${idx}`;
    const oe = origEntries()[idx];
    entries()[idx].string = oe.string;
    mods.delete(k);
    $('editBox').value = oe.string;
    badgeMod();
    renderList();
    updateDiff();
    lsSave();
}

// ── Upload ────────────────────────────────────────────────────────────────────
function doUpload(file) {
    status('Carregando...');
    const fd = new FormData();
    fd.append('file', file);
    fetch('/upload', { method:'POST', body:fd })
        .then(r => r.json())
        .then(d => {
            if (d.error) { status('Erro: '+d.error); return; }
            D = d;
            O = JSON.parse(JSON.stringify(d));
            mods.clear();
            idx = null; sec = 1;
            // Salvar ID de sessão do servidor junto com os dados
            localStorage.setItem(LS_SID, d.session_id || '');
            lsSaveFilename(file.name);
            lsSave();
            syncTabs();
            const enc = (d.global_encoding??'utf-8').toUpperCase();
            status(`📄 ${file.name} · S1:${d.section1.length} S2:${d.section2.length} · ${enc}`);
            showApp();
            renderList();
        })
        .catch(e => status('Falha: '+e));
}

// ── Restaurar sessão ao carregar página ───────────────────────────────────────
window.addEventListener('DOMContentLoaded', () => {
    // Verificar se o servidor está ativo e tem a mesma sessão
    fetch('/session')
        .then(r => r.json())
        .then(srv => {
            const lsSid   = localStorage.getItem(LS_SID) || '';
            const hasData = !!localStorage.getItem(LS_DATA);

            if (srv.loaded && lsSid && srv.session_id === lsSid && hasData) {
                // Servidor ativo COM o mesmo arquivo → restaurar do localStorage
                if (lsRestore()) {
                    syncTabs();
                    const fname   = localStorage.getItem(LS_FILE) || 'arquivo';
                    const enc     = (D.global_encoding??'utf-8').toUpperCase();
                    const modInfo = mods.size ? ` · ✏ ${mods.size} mod(s)` : '';
                    status(`📄 ${fname} · S1:${(D.section1||[]).length} S2:${(D.section2||[]).length} · ${enc}${modInfo}`);
                    badgeMod();
                    showApp();
                    renderList();
                    if (idx !== null && idx < entries().length) {
                        select(idx);
                        setTimeout(() => {
                            $('itemsContainer').querySelectorAll('.string-item.selected')
                                .forEach(el => el.scrollIntoView({ block:'nearest' }));
                        }, 100);
                    }
                }
            } else {
                // Servidor reiniciou (session_id diferente) → pedir arquivo
                lsClearAll();
                // Fica na tela de upload — não faz nada
            }
        })
        .catch(() => {
            // Servidor offline → fica na tela de upload
            lsClearAll();
        });
});

// ── Eventos ───────────────────────────────────────────────────────────────────
$('fileInput').addEventListener('change', e => { if (e.target.files[0]) doUpload(e.target.files[0]); });
$('dropZone').addEventListener('click',   () => $('fileInput').click());
$('dropZone').addEventListener('dragover', e => e.preventDefault());
$('dropZone').addEventListener('drop', e => {
    e.preventDefault();
    if (e.dataTransfer.files[0]) doUpload(e.dataTransfer.files[0]);
});

$('tab1').addEventListener('click', () => {
    sec = 1; idx = null; syncTabs();
    renderList(); clearEditor(); lsSave();
});
$('tab2').addEventListener('click', () => {
    sec = 2; idx = null; syncTabs();
    renderList(); clearEditor(); lsSave();
});

$('searchBox').addEventListener('input', () => { q = $('searchBox').value.toLowerCase(); renderList(); });
$('editBox').addEventListener('input', updateDiff);
$('btnApply').addEventListener('click',   applyEdit);
$('btnDiscard').addEventListener('click', discardEdit);
$('btnPrev').addEventListener('click', () => { if (idx > 0) select(idx-1); });
$('btnNext').addEventListener('click', () => { if (idx < entries().length-1) select(idx+1); });

$('btnSave').addEventListener('click', () => {
    fetch('/save', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(D) })
        .then(r => { if (!r.ok) throw new Error('Erro'); return r.blob(); })
        .then(blob => {
            const a = document.createElement('a');
            a.href = URL.createObjectURL(blob);
            a.download = 'en';
            a.click();
            status(`✅ Salvo · ${mods.size} mods`);
        })
        .catch(() => status('Erro ao salvar'));
});

$('btnRevert').addEventListener('click', () => {
    if (!confirm('Reverter TODAS as alterações para o original?')) return;
    D = JSON.parse(JSON.stringify(O));
    mods.clear();
    idx = null;
    lsSave();
    renderList();
    clearEditor();
    badgeMod();
    status('Revertido ao original');
});

$('btnStats').addEventListener('click', () => {
    if (!D) return;
    const all    = [...D.section1, ...D.section2];
    const encUtf = all.filter(e => e.encoding==='utf-8').length;
    const encLat = all.filter(e => e.encoding==='latin-1').length;
    const hdr3   = all.filter(e => e.hdr_size===3).length;
    const hdr4   = all.filter(e => e.hdr_size===4).length;
    const lsKB   = (() => {
        try {
            let b = 0;
            ['tfu_D','tfu_O','tfu_mods','tfu_filename','tfu_sec','tfu_idx']
                .forEach(k => { b += (localStorage.getItem(k)||'').length * 2; });
            return (b/1024).toFixed(1);
        } catch(e) { return '?'; }
    })();
    $('statsContent').innerHTML = `<table>
        <tr><th>Magic</th><td><code>ST0\\x01</code></td></tr>
        <tr><th>Seção 1</th><td><b>${D.section1.length}</b></td></tr>
        <tr><th>Seção 2</th><td><b>${D.section2.length}</b></td></tr>
        <tr><th>Total</th><td><b>${all.length}</b></td></tr>
        <tr><th>Alteradas</th><td><b>${mods.size}</b></td></tr>
        <tr><th>Encoding</th><td><b>${(D.global_encoding??'utf-8').toUpperCase()}</b></td></tr>
        <tr><th>UTF-8</th><td><b>${encUtf}</b> strings</td></tr>
        <tr><th>Latin-1</th><td><b>${encLat}</b> strings</td></tr>
        <tr><th>Header 3B</th><td><b>${hdr3}</b> entradas</td></tr>
        <tr><th>Header 4B</th><td><b>${hdr4}</b> entradas</td></tr>
        <tr><th>Sessão salva</th><td><b>${lsKB} KB</b> no localStorage</td></tr>
    </table>`;
    $('statsModal').classList.add('show');
});

document.querySelectorAll('.ins').forEach(b => b.addEventListener('click', () => {
    const ch = b.dataset.ch, ta = $('editBox');
    const s = ta.selectionStart, e = ta.selectionEnd;
    ta.value = ta.value.slice(0,s) + ch + ta.value.slice(e);
    ta.selectionStart = ta.selectionEnd = s + ch.length;
    ta.focus();
    ta.dispatchEvent(new Event('input'));
}));

function closeModal() { $('statsModal').classList.remove('show'); }
$('statsModal').addEventListener('click', e => { if (e.target===$('statsModal')) closeModal(); });
</script>
</body>
</html>"""


@app.route('/')
def index():
    return render_template_string(HTML)


@app.route('/session')
def session_info():
    """Retorna o ID de sessão atual e se há arquivo carregado."""
    return jsonify({
        'session_id': state['session_id'],
        'loaded':     state.get('parsed') is not None,
    })


@app.route('/upload', methods=['POST'])
def upload():
    if 'file' not in request.files:
        return jsonify({'error': 'Nenhum arquivo enviado'}), 400
    f = request.files['file']
    raw = f.read()
    try:
        parsed = parse_en_file(raw)
    except Exception as ex:
        return jsonify({'error': str(ex)}), 400

    state['parsed'] = parsed
    state['filename'] = f.filename or 'en'

    def fmt_entry(e, extra: dict):
        d = {
            'offset':   e['offset'],
            'hdr_size': e.get('hdr_size', 3),
            'inner':    e['inner'],
            'string':   e['string'],
            'encoding': e.get('encoding', 'utf-8'),
            'flag':     e['flag'],
            'lo':       e['lo'],
            'hi':       e['hi'],
            'value':    e['value'],
        }
        d.update(extra)
        return d

    s1 = [fmt_entry(e, {'game_id': e.get('game_id', 0)}) for e in parsed['section1']]
    s2 = [fmt_entry(e, {'seq': e.get('seq', e['value'])}) for e in parsed['section2']]

    return jsonify({
        'section1':        s1,
        'section2':        s2,
        'global_encoding': parsed.get('global_encoding', 'utf-8'),
        'session_id':      state['session_id'],
    })


@app.route('/save', methods=['POST'])
def save():
    body = request.get_json(force=True)
    if not body:
        return jsonify({'error': 'Payload vazio'}), 400
    if state.get('parsed') is None:
        return jsonify({'error': 'Nenhum arquivo carregado'}), 400

    parsed = copy.deepcopy(state['parsed'])

    for i, e in enumerate(body.get('section1', [])):
        if i < len(parsed['section1']):
            parsed['section1'][i]['string'] = e['string']

    for i, e in enumerate(body.get('section2', [])):
        if i < len(parsed['section2']):
            parsed['section2'][i]['string'] = e['string']

    try:
        out_bytes = rebuild_en_file(parsed)
    except Exception as ex:
        return jsonify({'error': str(ex)}), 500

    return send_file(
        io.BytesIO(out_bytes),
        as_attachment=True,
        download_name='en',
        mimetype='application/octet-stream',
    )


if __name__ == '__main__':
    print("=" * 58)
    print("  SW:TFU String Editor - Mobile First")
    print("  Acesse: http://localhost:5000")
    print("=" * 58)
    app.run(debug=False, host='0.0.0.0', port=5000)
