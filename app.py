"""
File Server — a simple web-based file manager
- Browse filesystem (default root: ./data)
- Upload files / entire folders (with drag-and-drop)
- Copy absolute path of any file with one click
- Download files
"""

import os
import shutil
from pathlib import Path
from flask import (
    Flask, request, send_file, jsonify, render_template_string,
    abort, redirect, url_for
)
from werkzeug.utils import secure_filename

app = Flask(__name__)
# Allow single request up to 200MB (chunk size is 50MB on client; header overhead safe margin)
app.config['MAX_CONTENT_LENGTH'] = 200 * 1024 * 1024

# Storage root — everything lives under here
BASE_DIR = Path(__file__).parent / "data"
BASE_DIR.mkdir(exist_ok=True)

# Temp dir for chunked uploads
CHUNK_DIR = Path(__file__).parent / ".upload_chunks"
CHUNK_DIR.mkdir(exist_ok=True)


def safe_path(rel: str) -> Path:
    """Resolve a relative path under BASE_DIR; raise 403 if escape attempt."""
    target = (BASE_DIR / rel.lstrip("/")).resolve()
    if not str(target).startswith(str(BASE_DIR.resolve())):
        abort(403)
    return target


# ─── HTML Template ────────────────────────────────────────────────────────────

HTML = r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>File Server — {{ rel_path or '/' }}</title>
<style>
  :root {
    --bg: #0f1117; --panel: #1a1d27; --border: #2a2d3a;
    --accent: #4f8ef7; --accent2: #7c6af7;
    --text: #e0e0e8; --sub: #8888a8; --danger: #f74f4f; --ok: #4fc88e;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: var(--bg); color: var(--text); font-family: 'Segoe UI', system-ui, sans-serif; min-height: 100vh; }

  header { background: var(--panel); border-bottom: 1px solid var(--border); padding: 14px 24px; display: flex; align-items: center; gap: 16px; }
  header h1 { font-size: 1.1rem; font-weight: 600; background: linear-gradient(90deg, var(--accent), var(--accent2)); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }

  .breadcrumb { font-size: 0.85rem; color: var(--sub); display: flex; align-items: center; flex-wrap: wrap; gap: 4px; }
  .breadcrumb a { color: var(--accent); text-decoration: none; } .breadcrumb a:hover { text-decoration: underline; }
  .breadcrumb span { color: var(--sub); }

  .container { max-width: 1200px; margin: 0 auto; padding: 24px; }

  /* Upload zone */
  .upload-zone {
    border: 2px dashed var(--border); border-radius: 12px; padding: 24px;
    text-align: center; cursor: pointer; transition: border-color 0.2s, background 0.2s;
    margin-bottom: 24px; background: var(--panel);
  }
  .upload-zone.drag-over { border-color: var(--accent); background: rgba(79,142,247,0.08); }
  .upload-zone p { color: var(--sub); font-size: 0.9rem; margin-top: 6px; }
  .upload-zone .icon { font-size: 2rem; }
  #fileInput, #folderInput { display: none; }
  .btn { display: inline-flex; align-items: center; gap: 6px; padding: 7px 16px; border-radius: 8px; font-size: 0.85rem; font-weight: 500; cursor: pointer; border: none; transition: opacity 0.15s; }
  .btn:hover { opacity: 0.85; }
  .btn-primary { background: var(--accent); color: #fff; }
  .btn-secondary { background: var(--panel); color: var(--text); border: 1px solid var(--border); }
  .btn-danger { background: var(--danger); color: #fff; }
  .btn-row { display: flex; gap: 10px; justify-content: center; flex-wrap: wrap; margin-top: 12px; }

  /* Progress */
  #progressArea { display: none; margin-bottom: 16px; }
  .progress-bar-wrap { background: var(--border); border-radius: 4px; height: 6px; overflow: hidden; margin-top: 8px; }
  .progress-bar { height: 100%; background: linear-gradient(90deg, var(--accent), var(--accent2)); width: 0; transition: width 0.2s; }
  #progressLabel { font-size: 0.82rem; color: var(--sub); }

  /* File table */
  .file-table { background: var(--panel); border-radius: 12px; overflow: hidden; border: 1px solid var(--border); }
  .file-table table { width: 100%; border-collapse: collapse; }
  .file-table th { padding: 12px 16px; text-align: left; font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.05em; color: var(--sub); border-bottom: 1px solid var(--border); }
  .file-table td { padding: 10px 16px; font-size: 0.88rem; border-bottom: 1px solid var(--border); vertical-align: middle; }
  .file-table tr:last-child td { border-bottom: none; }
  .file-table tr:hover td { background: rgba(255,255,255,0.02); }

  .file-name a { color: var(--text); text-decoration: none; display: flex; align-items: center; gap: 8px; }
  .file-name a:hover { color: var(--accent); }
  .file-icon { font-size: 1.1rem; width: 22px; text-align: center; flex-shrink: 0; }
  .file-size { color: var(--sub); white-space: nowrap; }
  .file-date { color: var(--sub); font-size: 0.82rem; white-space: nowrap; }

  .copy-path-btn {
    background: none; border: 1px solid var(--border); color: var(--sub);
    border-radius: 6px; padding: 3px 10px; font-size: 0.78rem; cursor: pointer;
    transition: all 0.15s; white-space: nowrap;
  }
  .copy-path-btn:hover { border-color: var(--accent); color: var(--accent); }
  .copy-path-btn.copied { border-color: var(--ok); color: var(--ok); }

  .delete-btn { background: none; border: none; color: var(--sub); cursor: pointer; font-size: 1rem; padding: 2px 6px; border-radius: 4px; }
  .delete-btn:hover { color: var(--danger); background: rgba(247,79,79,0.1); }

  /* Drag & drop for moving files */
  .file-table tr[draggable="true"] { cursor: grab; }
  .file-table tr[draggable="true"]:active { cursor: grabbing; }
  .file-table tr.dragging { opacity: 0.4; }
  .file-table tr.drop-target td { background: rgba(79,142,247,0.18) !important; box-shadow: inset 0 0 0 2px var(--accent); }
  .breadcrumb a.drop-target { background: rgba(79,142,247,0.2); padding: 2px 6px; border-radius: 4px; box-shadow: inset 0 0 0 2px var(--accent); }

  /* Drag-and-drop UPLOAD highlight (external files being dragged in) */
  .file-table tr.upload-drop-target td { background: rgba(124,106,247,0.22) !important; box-shadow: inset 0 0 0 2px var(--accent2); }
  .breadcrumb a.upload-drop-target { background: rgba(124,106,247,0.22); padding: 2px 6px; border-radius: 4px; box-shadow: inset 0 0 0 2px var(--accent2); }

  /* Multi-select state */
  .file-table tr.selected td { background: rgba(79,142,247,0.15) !important; }
  .file-table tr.selected td:first-child { box-shadow: inset 3px 0 0 var(--accent); }
  /* Disable native text selection while we're rubber-band selecting */
  body.rubberbanding, body.rubberbanding * { user-select: none !important; }

  /* Rubber-band selection rectangle */
  #rubberBand {
    position: absolute;
    border: 1px solid var(--accent);
    background: rgba(79,142,247,0.12);
    pointer-events: none;
    z-index: 500;
    display: none;
    border-radius: 2px;
  }

  /* Context menu */
  #contextMenu {
    position: absolute;
    background: var(--panel); border: 1px solid var(--border);
    border-radius: 8px; box-shadow: 0 6px 30px rgba(0,0,0,0.5);
    padding: 4px 0; min-width: 180px;
    display: none; z-index: 900;
    font-size: 0.88rem;
  }
  #contextMenu.visible { display: block; }
  #contextMenu .item {
    padding: 7px 14px; cursor: pointer; color: var(--text);
    display: flex; align-items: center; gap: 10px; user-select: none;
  }
  #contextMenu .item:hover { background: rgba(79,142,247,0.15); color: var(--accent); }
  #contextMenu .item.danger:hover { background: rgba(247,79,79,0.15); color: var(--danger); }
  #contextMenu .sep { height: 1px; background: var(--border); margin: 4px 0; }
  #contextMenu .item .kbd {
    margin-left: auto; font-size: 0.72rem; color: var(--sub);
    border: 1px solid var(--border); padding: 1px 5px; border-radius: 3px;
  }

  /* Floating selection toolbar */
  #selectionBar {
    position: fixed;
    bottom: 24px; left: 50%;
    transform: translateX(-50%) translateY(20px);
    background: var(--panel); border: 1px solid var(--border);
    border-radius: 12px; box-shadow: 0 6px 30px rgba(0,0,0,0.5);
    padding: 10px 16px;
    display: none;
    align-items: center; gap: 14px;
    font-size: 0.88rem; z-index: 800;
    transition: transform 0.18s ease, opacity 0.18s ease;
    opacity: 0;
  }
  #selectionBar.visible { display: flex; transform: translateX(-50%) translateY(0); opacity: 1; }
  #selectionBar .count { color: var(--accent); font-weight: 600; }
  #selectionBar .hint  { color: var(--sub); font-size: 0.78rem; }
  #selectionBar button {
    background: var(--panel); border: 1px solid var(--border); color: var(--text);
    border-radius: 6px; padding: 5px 12px; font-size: 0.82rem; cursor: pointer;
  }
  #selectionBar button:hover { border-color: var(--accent); color: var(--accent); }
  #selectionBar button.danger:hover { border-color: var(--danger); color: var(--danger); }

  /* Full-page drop overlay */
  #dragOverlay {
    position: fixed; inset: 0; z-index: 1000;
    background: rgba(15,17,23,0.75);
    backdrop-filter: blur(4px);
    border: 4px dashed var(--accent);
    display: none;
    pointer-events: none;
    align-items: center; justify-content: center;
  }
  #dragOverlay.active { display: flex; }
  #dragOverlayLabel {
    font-size: 1.4rem; font-weight: 600; color: var(--text);
    background: var(--panel); padding: 18px 28px; border-radius: 12px;
    box-shadow: 0 8px 40px rgba(0,0,0,0.5);
    max-width: 90%; text-align: center; word-break: break-all;
  }

  .actions-cell { display: flex; align-items: center; gap: 8px; }

  /* toast */
  #toast { position: fixed; bottom: 24px; right: 24px; background: var(--panel); border: 1px solid var(--border); color: var(--text); padding: 10px 18px; border-radius: 10px; font-size: 0.88rem; display: none; z-index: 999; box-shadow: 0 4px 20px rgba(0,0,0,0.4); }

  /* New folder */
  .new-folder-row { display: flex; gap: 8px; margin-bottom: 24px; }
  .new-folder-row input { flex: 1; background: var(--panel); border: 1px solid var(--border); color: var(--text); border-radius: 8px; padding: 8px 12px; font-size: 0.88rem; outline: none; min-width: 0; }
  .new-folder-row input:focus { border-color: var(--accent); }

  /* ── Mobile ─────────────────────────────────────────────── */
  @media (max-width: 640px) {
    header { padding: 10px 14px; gap: 8px; flex-wrap: wrap; }
    header h1 { font-size: 1rem; }
    .breadcrumb { font-size: 0.8rem; width: 100%; }

    .container { padding: 12px; }

    .upload-zone { padding: 16px 12px; margin-bottom: 16px; }
    .upload-zone .icon { font-size: 1.6rem; }
    .upload-zone strong { font-size: 0.9rem; }
    .upload-zone p { font-size: 0.8rem; }
    .btn-row { gap: 6px; }
    .btn { padding: 10px 14px; font-size: 0.85rem; }

    .new-folder-row { margin-bottom: 16px; }

    /* Convert table rows to cards — use flex wrap so children sit on one line when they fit */
    .file-table { border-radius: 10px; }
    .file-table table,
    .file-table thead,
    .file-table tbody { display: block; width: 100%; }
    .file-table thead { display: none; }

    .file-table tr {
      display: flex;
      flex-wrap: wrap;
      align-items: baseline;
      border-bottom: 1px solid var(--border);
      padding: 10px 12px;
      position: relative;
      column-gap: 10px;
    }
    .file-table tr:hover td { background: transparent; }
    .file-table td {
      padding: 0; border: none; font-size: 0.88rem;
      background: transparent;
    }

    /* Row 1 (full width): name; reserves space for absolute actions */
    .file-table td.file-name {
      flex: 1 1 100%;
      padding-right: 100px;
      min-width: 0;
    }
    .file-name a {
      overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
      display: block;
    }

    /* Row 2: size + date inline (flex children, auto-width) */
    .file-table td.file-size,
    .file-table td.file-date {
      flex: 0 0 auto;
      font-size: 0.75rem;
      color: var(--sub);
      line-height: 1.3;
      margin-top: 2px;
    }
    .file-table td.file-size:not(:empty)::after {
      content: "\00a0·";
      color: var(--sub);
      margin-left: 4px;
    }

    /* Row 3 (full width): copy-path */
    .file-table td:nth-of-type(4) {
      flex: 1 1 100%;
      margin-top: 8px;
    }
    .copy-path-btn { width: 100%; padding: 8px; font-size: 0.8rem; text-align: center; }

    /* Actions pinned absolutely to top-right */
    .file-table td:nth-of-type(5) {
      position: absolute;
      top: 10px; right: 12px;
      flex: 0 0 auto;
    }
    .actions-cell { justify-content: flex-end; gap: 4px; }
    .delete-btn { font-size: 1.1rem; padding: 4px 8px; }
    .actions-cell a.btn { padding: 4px 10px !important; font-size: 0.85rem !important; }

    /* Parent ".. (up)" row — name takes full width, no action slot */
    .file-table tr:first-child td.file-name { padding-right: 0; }

    #toast { left: 12px; right: 12px; bottom: 12px; text-align: center; }
  }
</style>
</head>
<body>

<header>
  <h1>📁 File Server</h1>
  <nav class="breadcrumb">
    <a href="/?path=" data-drop-rel="">root</a>
    {% for crumb in breadcrumbs %}
      <span>/</span>
      <a href="/?path={{ crumb.path }}" data-drop-rel="{{ crumb.path }}">{{ crumb.name }}</a>
    {% endfor %}
  </nav>
</header>

<div class="container">

  <!-- New folder -->
  <div class="new-folder-row">
    <input type="text" id="newFolderName" placeholder="New folder name…" />
    <button class="btn btn-secondary" onclick="createFolder()">＋ Folder</button>
  </div>

  <!-- Upload zone -->
  <div class="upload-zone" id="dropZone">
    <div class="icon">☁️</div>
    <strong>Drop files or folders here</strong>
    <p>or click a button below to browse</p>
    <div class="btn-row">
      <button class="btn btn-primary" onclick="document.getElementById('fileInput').click()">Upload Files</button>
      <button class="btn btn-secondary" onclick="document.getElementById('folderInput').click()">Upload Folder</button>
    </div>
    <input type="file" id="fileInput" multiple />
    <input type="file" id="folderInput" multiple webkitdirectory />
  </div>

  <!-- Progress -->
  <div id="progressArea">
    <div id="progressLabel">Uploading…</div>
    <div class="progress-bar-wrap"><div class="progress-bar" id="progressBar"></div></div>
  </div>

  <!-- File listing -->
  <div class="file-table">
    <table>
      <thead>
        <tr>
          <th>Name</th>
          <th>Size</th>
          <th>Modified</th>
          <th>Path</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        {% if rel_path %}
        <tr data-drop-rel="{{ parent_path }}" class="parent-row">
          <td class="file-name"><a href="/?path={{ parent_path }}"><span class="file-icon">⬆️</span>.. (up)</a></td>
          <td></td><td></td><td></td><td></td>
        </tr>
        {% endif %}
        {% for item in items %}
        <tr draggable="true" data-src-rel="{{ item.rel }}" {% if item.is_dir %}data-drop-rel="{{ item.rel }}"{% endif %}>
          <td class="file-name">
            {% if item.is_dir %}
            <a href="/?path={{ item.rel }}"><span class="file-icon">📂</span>{{ item.name }}</a>
            {% else %}
            <a href="/download?path={{ item.rel }}" target="_blank"><span class="file-icon">{{ item.icon }}</span>{{ item.name }}</a>
            {% endif %}
          </td>
          <td class="file-size">{{ item.size_str }}</td>
          <td class="file-date">{{ item.mtime }}</td>
          <td>
            <button class="copy-path-btn" onclick="copyPath(this, '{{ item.abs_path }}')" title="{{ item.abs_path }}">
              Copy path
            </button>
          </td>
          <td>
            <div class="actions-cell">
              {% if not item.is_dir %}
              <a href="/download?path={{ item.rel }}" class="btn btn-secondary" style="padding:3px 10px;font-size:0.78rem;" download>↓</a>
              {% endif %}
              <button class="delete-btn" onclick="deleteItem('{{ item.rel }}', {{ 'true' if item.is_dir else 'false' }})" title="Delete">🗑</button>
            </div>
          </td>
        </tr>
        {% endfor %}
        {% if not items %}
        <tr><td colspan="5" style="text-align:center;color:var(--sub);padding:32px;">Empty folder</td></tr>
        {% endif %}
      </tbody>
    </table>
  </div>
</div>

<div id="toast"></div>
<div id="dragOverlay"><div id="dragOverlayLabel">Drop to upload</div></div>
<div id="rubberBand"></div>
<div id="contextMenu"></div>
<div id="selectionBar">
  <span><span class="count" id="selCount">0</span> selected</span>
  <span class="hint">Drag any selected row to a folder · Esc to clear</span>
  <button id="selClear">Clear</button>
  <button id="selDelete" class="danger">Delete</button>
</div>

<script>
const currentPath = {{ rel_path | tojson }};

// ── Copy path ──────────────────────────────────────────────────────────────
function copyPath(btn, path) {
  navigator.clipboard.writeText(path).then(() => {
    btn.textContent = 'Copied!';
    btn.classList.add('copied');
    setTimeout(() => { btn.textContent = 'Copy path'; btn.classList.remove('copied'); }, 1500);
  });
}

// ── Toast ──────────────────────────────────────────────────────────────────
function toast(msg, duration=2500) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.style.display = 'block';
  setTimeout(() => { t.style.display = 'none'; }, duration);
}

// ── New folder ─────────────────────────────────────────────────────────────
function createFolder() {
  const name = document.getElementById('newFolderName').value.trim();
  if (!name) return;
  fetch('/mkdir', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({path: currentPath, name})
  }).then(r => r.json()).then(d => {
    if (d.ok) { toast('Folder created'); location.reload(); }
    else toast('Error: ' + d.error);
  });
}

// ── Delete ─────────────────────────────────────────────────────────────────
function deleteItem(path, isDir) {
  const what = isDir ? 'folder and all its contents' : 'file';
  if (!confirm(`Delete this ${what}?`)) return;
  fetch('/delete', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({path})
  }).then(r => r.json()).then(d => {
    if (d.ok) { toast('Deleted'); location.reload(); }
    else toast('Error: ' + d.error);
  });
}

// ── Upload ─────────────────────────────────────────────────────────────────
function showProgress(label) {
  document.getElementById('progressArea').style.display = 'block';
  document.getElementById('progressLabel').textContent = label;
  document.getElementById('progressBar').style.width = '0%';
}
function setProgress(pct) {
  document.getElementById('progressBar').style.width = pct + '%';
}
function hideProgress() {
  setTimeout(() => { document.getElementById('progressArea').style.display = 'none'; }, 800);
}

// 50 MB chunk size — safely under Cloudflare's 100 MB per-request limit
const CHUNK_SIZE = 50 * 1024 * 1024;
const LARGE_FILE_THRESHOLD = 80 * 1024 * 1024;  // switch to chunked mode above this

function genUploadId() {
  return 'u' + Date.now().toString(36) + Math.random().toString(36).slice(2, 10);
}

async function uploadSingle(file, rel, dest) {
  const fd = new FormData();
  fd.append('file', file, rel);
  fd.append('dest', dest);
  fd.append('rel', rel);
  const r = await fetch('/upload', { method: 'POST', body: fd });
  if (!r.ok) throw new Error(`upload failed: ${r.status}`);
}

async function uploadChunked(file, rel, dest, onChunkProgress) {
  const uploadId = genUploadId();
  const total = Math.ceil(file.size / CHUNK_SIZE);
  for (let i = 0; i < total; i++) {
    const start = i * CHUNK_SIZE;
    const blob = file.slice(start, Math.min(start + CHUNK_SIZE, file.size));
    const fd = new FormData();
    fd.append('upload_id', uploadId);
    fd.append('index', String(i));
    fd.append('chunk', blob);
    const r = await fetch('/upload-chunk', { method: 'POST', body: fd });
    if (!r.ok) throw new Error(`chunk ${i} failed: ${r.status}`);
    if (onChunkProgress) onChunkProgress(i + 1, total);
  }
  const r = await fetch('/upload-finalize', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ upload_id: uploadId, total, dest, rel })
  });
  const d = await r.json();
  if (!d.ok) throw new Error(d.error || 'finalize failed');
}

function humanSize(n) {
  const units = ['B','KB','MB','GB'];
  let i = 0;
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
  return n.toFixed(1) + ' ' + units[i];
}

async function uploadFiles(files, dest) {
  if (!files.length) return;
  if (dest === undefined) dest = currentPath;
  const where = dest === '' ? '/' : '/' + dest;
  showProgress(`Uploading ${files.length} file(s) → ${where}`);
  const label = document.getElementById('progressLabel');
  let done = 0;
  const total = files.length;

  for (const file of files) {
    const rel = file.webkitRelativePath || file.name;
    try {
      if (file.size > LARGE_FILE_THRESHOLD) {
        await uploadChunked(file, rel, dest, (i, n) => {
          const fileFrac = i / n;
          const overall = ((done + fileFrac) / total) * 100;
          setProgress(overall);
          label.textContent = `${done+1}/${total} — ${rel} (chunk ${i}/${n}, ${humanSize(file.size)})`;
        });
      } else {
        label.textContent = `${done+1}/${total} — ${rel} (${humanSize(file.size)})`;
        await uploadSingle(file, rel, dest);
      }
    } catch (e) {
      hideProgress();
      toast(`Error uploading ${rel}: ${e.message}`, 5000);
      return;
    }
    done++;
    setProgress(Math.round(done / total * 100));
  }
  label.textContent = `${done}/${total} uploaded`;
  hideProgress();
  toast(`Uploaded ${done} file(s) → ${where}`);
  location.reload();
}

// ── Extract files from a DataTransfer (handles folders) ────────────────────
async function extractFilesFromDrop(dataTransfer) {
  const files = [];
  async function traverseEntry(entry, prefix='') {
    if (entry.isFile) {
      await new Promise(res => entry.file(f => {
        Object.defineProperty(f, 'webkitRelativePath', { value: prefix + f.name });
        files.push(f); res();
      }));
    } else if (entry.isDirectory) {
      const reader = entry.createReader();
      // readEntries only returns up to 100 entries per call — loop until empty
      let batch;
      do {
        batch = await new Promise(res => reader.readEntries(res));
        for (const child of batch) await traverseEntry(child, prefix + entry.name + '/');
      } while (batch.length > 0);
    }
  }
  const items = [...(dataTransfer.items || [])];
  if (items.length) {
    for (const item of items) {
      const entry = item.webkitGetAsEntry?.();
      if (entry) await traverseEntry(entry);
    }
  } else {
    // Fallback: files only (no folder structure)
    for (const f of dataTransfer.files) files.push(f);
  }
  return files;
}

// ── Multi-select + drag-and-drop move ─────────────────────────────────────
//   - Click empty area in the table and drag → rubber-band selection
//   - Click row: select single (resets others)
//   - Cmd/Ctrl+click row: toggle one
//   - Shift+click row: range select
//   - Esc: clear selection
//   - Drag any selected row → moves all selected to drop target
//   - Floating toolbar shows count + Delete button
(function setupSelectionAndMove() {
  const selected = new Set();          // set of srcRel
  let lastClickedRow = null;           // for shift-range selection
  const bar = document.getElementById('selectionBar');
  const countEl = document.getElementById('selCount');

  function rowFor(srcRel) {
    return document.querySelector(`tr[data-src-rel="${CSS.escape(srcRel)}"]`);
  }
  function allRows() {
    return [...document.querySelectorAll('tr[draggable="true"]')];
  }

  function refreshBar() {
    countEl.textContent = selected.size;
    if (selected.size > 0) bar.classList.add('visible');
    else bar.classList.remove('visible');
  }

  function setSelected(srcRel, on) {
    const tr = rowFor(srcRel);
    if (!tr) return;
    if (on) { selected.add(srcRel); tr.classList.add('selected'); }
    else { selected.delete(srcRel); tr.classList.remove('selected'); }
  }
  function clearSelection() {
    [...selected].forEach(s => setSelected(s, false));
    refreshBar();
  }
  function selectOnly(srcRel) {
    clearSelection();
    setSelected(srcRel, true);
    refreshBar();
  }
  function toggle(srcRel) {
    setSelected(srcRel, !selected.has(srcRel));
    refreshBar();
  }
  function selectRange(fromRel, toRel) {
    const rows = allRows();
    const a = rows.findIndex(r => r.dataset.srcRel === fromRel);
    const b = rows.findIndex(r => r.dataset.srcRel === toRel);
    if (a === -1 || b === -1) return;
    const [lo, hi] = a < b ? [a, b] : [b, a];
    for (let i = lo; i <= hi; i++) setSelected(rows[i].dataset.srcRel, true);
    refreshBar();
  }

  // ── Click to select ───────────────────────────────────────────────────
  allRows().forEach(row => {
    row.addEventListener('click', e => {
      // Don't hijack clicks on links / buttons (download, copy-path, etc.)
      if (e.target.closest('a, button')) return;
      const rel = row.dataset.srcRel;
      if (e.shiftKey && lastClickedRow) {
        selectRange(lastClickedRow, rel);
      } else if (e.metaKey || e.ctrlKey) {
        toggle(rel);
      } else {
        // Plain click on a row that's already the only selection → keep selection
        // (so we don't clobber a multi-select right before drag)
        if (!selected.has(rel) || selected.size > 1) {
          selectOnly(rel);
        }
      }
      lastClickedRow = rel;
      e.preventDefault();
    });
  });

  // ── Esc clears selection ──────────────────────────────────────────────
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') clearSelection();
  });

  // Toolbar buttons
  document.getElementById('selClear').addEventListener('click', clearSelection);
  document.getElementById('selDelete').addEventListener('click', async () => {
    const items = [...selected];
    if (!items.length) return;
    if (!confirm(`Delete ${items.length} item(s)?`)) return;
    let ok = 0;
    for (const rel of items) {
      try {
        const r = await fetch('/delete', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({path: rel})
        });
        const d = await r.json();
        if (d.ok) ok++;
      } catch {}
    }
    toast(`Deleted ${ok}/${items.length}`);
    location.reload();
  });

  // ── Rubber-band selection — drag in empty area of the page ─────────────
  // Initiate from anywhere outside interactive elements (rows, buttons, inputs,
  // breadcrumbs, upload zone). Works even when the table has no empty space:
  // user can start the drag in the page margin / below the table.
  const band = document.getElementById('rubberBand');
  let bandStart = null;

  document.addEventListener('mousedown', e => {
    if (e.button !== 0) return;
    // Skip when starting on something interactive
    if (e.target.closest(
      'tr[draggable="true"], a, button, input, label, ' +
      '.upload-zone, .breadcrumb, .new-folder-row, ' +
      '#selectionBar, header'
    )) return;
    bandStart = { x: e.pageX, y: e.pageY };
    Object.assign(band.style, { left: e.pageX + 'px', top: e.pageY + 'px', width: '0px', height: '0px', display: 'block' });
    document.body.classList.add('rubberbanding');
    if (!(e.metaKey || e.ctrlKey || e.shiftKey)) clearSelection();
    e.preventDefault();
  });

  document.addEventListener('mousemove', e => {
    if (!bandStart) return;
    const x = Math.min(e.pageX, bandStart.x);
    const y = Math.min(e.pageY, bandStart.y);
    const w = Math.abs(e.pageX - bandStart.x);
    const h = Math.abs(e.pageY - bandStart.y);
    Object.assign(band.style, { left: x+'px', top: y+'px', width: w+'px', height: h+'px' });

    // Live-highlight rows whose bounding box overlaps the band
    const bx1 = x, by1 = y, bx2 = x + w, by2 = y + h;
    allRows().forEach(row => {
      const r = row.getBoundingClientRect();
      // pageY = clientY + scrollY
      const rx1 = r.left + window.scrollX, ry1 = r.top + window.scrollY;
      const rx2 = rx1 + r.width, ry2 = ry1 + r.height;
      const intersects = !(rx2 < bx1 || rx1 > bx2 || ry2 < by1 || ry1 > by2);
      setSelected(row.dataset.srcRel, intersects);
    });
    refreshBar();
  });

  document.addEventListener('mouseup', () => {
    if (!bandStart) return;
    bandStart = null;
    band.style.display = 'none';
    document.body.classList.remove('rubberbanding');
  });

  // ── Drag selected rows to a folder/breadcrumb to move ─────────────────
  let draggingSrcs = [];

  allRows().forEach(row => {
    row.addEventListener('dragstart', e => {
      const rel = row.dataset.srcRel;
      // If user starts dragging an unselected row, treat it as a single-row drag
      if (!selected.has(rel)) {
        selectOnly(rel);
      }
      draggingSrcs = [...selected];
      row.classList.add('dragging');
      e.dataTransfer.effectAllowed = 'move';
      e.dataTransfer.setData('text/plain', JSON.stringify(draggingSrcs));
      // Custom drag image for multi-select
      if (draggingSrcs.length > 1) {
        const ghost = document.createElement('div');
        ghost.style.cssText = `
          position:absolute; top:-9999px; left:-9999px;
          padding:8px 14px; border-radius:8px;
          background:var(--accent); color:#fff; font-weight:600;
          font-size:0.85rem; box-shadow:0 4px 14px rgba(0,0,0,0.4);
        `;
        ghost.textContent = `${draggingSrcs.length} items`;
        document.body.appendChild(ghost);
        e.dataTransfer.setDragImage(ghost, 30, 18);
        setTimeout(() => ghost.remove(), 0);
      }
    });
    row.addEventListener('dragend', () => {
      row.classList.remove('dragging');
      draggingSrcs = [];
      document.querySelectorAll('.drop-target').forEach(el => el.classList.remove('drop-target'));
    });
  });

  function canDrop(target) {
    if (!draggingSrcs.length) return false;
    const destRel = target.dataset.dropRel;
    if (destRel === undefined) return false;
    // Reject if destination IS one of the dragged sources or a descendant of one
    for (const src of draggingSrcs) {
      if (destRel === src) return false;
      if (destRel.startsWith(src + '/')) return false;
    }
    return true;
  }

  function attachDropTarget(el) {
    el.addEventListener('dragover', e => {
      if (!canDrop(el)) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';
      el.classList.add('drop-target');
    });
    el.addEventListener('dragleave', () => el.classList.remove('drop-target'));
    el.addEventListener('drop', async e => {
      if (!canDrop(el)) return;
      e.preventDefault();
      el.classList.remove('drop-target');
      const srcs = [...draggingSrcs];
      const destDir = el.dataset.dropRel;
      try {
        const r = await fetch('/move-batch', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({srcs, dest_dir: destDir})
        });
        const d = await r.json();
        if (d.ok) {
          const fails = (d.results || []).filter(x => !x.ok);
          if (fails.length === 0) toast(`Moved ${d.moved} item(s)`);
          else toast(`Moved ${d.moved}/${d.total} — ${fails.length} failed: ${fails[0].error}`, 5000);
          location.reload();
        } else {
          toast('Error: ' + d.error, 4000);
        }
      } catch (err) {
        toast('Error: ' + err.message, 4000);
      }
    });
  }

  document.querySelectorAll('tr[data-drop-rel], .breadcrumb a[data-drop-rel]').forEach(attachDropTarget);
})();

document.getElementById('fileInput').addEventListener('change', e => uploadFiles([...e.target.files]));
document.getElementById('folderInput').addEventListener('change', e => uploadFiles([...e.target.files]));

// ── Right-click context menu ───────────────────────────────────────────────
(function setupContextMenu() {
  const menu = document.getElementById('contextMenu');

  function close() { menu.classList.remove('visible'); menu.innerHTML = ''; }

  function item(label, kbd, fn, danger=false) {
    const el = document.createElement('div');
    el.className = 'item' + (danger ? ' danger' : '');
    el.innerHTML = `<span>${label}</span>` + (kbd ? `<span class="kbd">${kbd}</span>` : '');
    el.addEventListener('click', () => { close(); fn(); });
    return el;
  }
  function sep() {
    const el = document.createElement('div');
    el.className = 'sep';
    return el;
  }

  function showAt(x, y, items) {
    menu.innerHTML = '';
    items.forEach(i => menu.appendChild(i));
    menu.classList.add('visible');
    // Position, then nudge if it would overflow viewport
    menu.style.left = x + 'px';
    menu.style.top = y + 'px';
    const rect = menu.getBoundingClientRect();
    if (rect.right > window.innerWidth - 4) menu.style.left = (window.innerWidth - rect.width - 4) + 'px';
    if (rect.bottom > window.innerHeight - 4) menu.style.top = (y - rect.height) + 'px';
  }

  // Close on outside click / scroll / Esc
  document.addEventListener('click', e => { if (!e.target.closest('#contextMenu')) close(); });
  document.addEventListener('scroll', close, true);
  document.addEventListener('keydown', e => { if (e.key === 'Escape') close(); });

  // Right-click on a row
  document.addEventListener('contextmenu', e => {
    const row = e.target.closest('tr[draggable="true"]');
    if (!row) return;
    e.preventDefault();
    const rel = row.dataset.srcRel;
    const isDir = row.dataset.dropRel !== undefined;  // folders have data-drop-rel
    const absPath = row.querySelector('.copy-path-btn')?.getAttribute('onclick')
                       ?.match(/'([^']+)'/g)?.[1]?.replace(/'/g, '');

    // Build menu items
    const items = [];
    items.push(item('Rename…', 'F2', () => promptRename(rel)));
    items.push(item('Copy absolute path', '', () => {
      const t = row.querySelector('.copy-path-btn');
      if (t) t.click();
    }));
    if (!isDir) {
      items.push(item('Download', '', () => {
        window.open('/download?path=' + encodeURIComponent(rel), '_blank');
      }));
    } else {
      items.push(item('Open', '', () => { location.href = '/?path=' + encodeURIComponent(rel); }));
    }
    items.push(sep());
    items.push(item('Delete', 'Del', () => {
      if (!confirm(`Delete this ${isDir ? 'folder and all its contents' : 'file'}?`)) return;
      fetch('/delete', {
        method: 'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify({path: rel})
      }).then(r => r.json()).then(d => {
        if (d.ok) { toast('Deleted'); location.reload(); }
        else toast('Error: ' + d.error, 4000);
      });
    }, true));

    showAt(e.pageX, e.pageY, items);
  });

  // F2 keyboard shortcut renames the (single) selected row
  document.addEventListener('keydown', e => {
    if (e.key === 'F2') {
      const sel = document.querySelector('tr.selected');
      if (sel) {
        e.preventDefault();
        promptRename(sel.dataset.srcRel);
      }
    }
  });
})();

async function promptRename(rel) {
  const oldName = rel.split('/').pop();
  const newName = prompt('Rename to:', oldName);
  if (!newName || newName === oldName) return;
  try {
    const r = await fetch('/rename', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({path: rel, new_name: newName})
    });
    const d = await r.json();
    if (d.ok) { toast('Renamed'); location.reload(); }
    else toast('Error: ' + d.error, 4000);
  } catch (err) {
    toast('Error: ' + err.message, 4000);
  }
}

// ── Drag & drop file upload ────────────────────────────────────────────────
// Features:
//   1. Drop anywhere on the page — uploads to current folder
//   2. Drop onto a folder row — uploads INTO that folder
//   3. Drop onto a breadcrumb — uploads into that ancestor
//   4. Full-screen overlay highlights the drop target live
//   5. Folder uploads preserve tree structure
(function setupDragDropUpload() {
  const zone = document.getElementById('dropZone');
  const overlay = document.getElementById('dragOverlay');

  // `dragDepth` guards against flicker from child-element dragenter/leave
  let dragDepth = 0;
  // True when the current drag contains external files (not an internal row move)
  function hasExternalFiles(e) {
    const types = e.dataTransfer?.types || [];
    return [...types].includes('Files');
  }

  function currentDropTarget(e) {
    // Target priority: folder row > breadcrumb > upload zone > whole page
    const el = e.target.closest?.('tr[data-drop-rel], .breadcrumb a[data-drop-rel]');
    if (el) return { rel: el.dataset.dropRel, node: el };
    if (e.target.closest?.('#dropZone')) return { rel: currentPath, node: zone };
    return { rel: currentPath, node: null };
  }

  function clearHighlights() {
    document.querySelectorAll('.upload-drop-target').forEach(el => el.classList.remove('upload-drop-target'));
    zone.classList.remove('drag-over');
  }

  document.addEventListener('dragenter', e => {
    if (!hasExternalFiles(e)) return;
    e.preventDefault();
    dragDepth++;
    overlay.classList.add('active');
  });

  document.addEventListener('dragover', e => {
    if (!hasExternalFiles(e)) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = 'copy';
    clearHighlights();
    const t = currentDropTarget(e);
    if (t.node) t.node.classList.add('upload-drop-target');
    else zone.classList.add('drag-over');
    // Update overlay label with target path
    const label = document.getElementById('dragOverlayLabel');
    const path = t.rel === '' ? '/ (root)' : '/ ' + t.rel;
    label.textContent = 'Drop to upload → ' + path;
  });

  document.addEventListener('dragleave', e => {
    if (!hasExternalFiles(e)) return;
    dragDepth--;
    if (dragDepth <= 0) {
      dragDepth = 0;
      overlay.classList.remove('active');
      clearHighlights();
    }
  });

  document.addEventListener('drop', async e => {
    if (!hasExternalFiles(e)) return;
    e.preventDefault();
    dragDepth = 0;
    overlay.classList.remove('active');
    const target = currentDropTarget(e);
    clearHighlights();
    const files = await extractFilesFromDrop(e.dataTransfer);
    if (files.length === 0) { toast('No files detected'); return; }
    uploadFiles(files, target.rel);
  });
})();
</script>
</body>
</html>
"""

# ─── Helpers ──────────────────────────────────────────────────────────────────

def file_icon(name: str) -> str:
    ext = Path(name).suffix.lower()
    icons = {
        '.png': '🖼', '.jpg': '🖼', '.jpeg': '🖼', '.gif': '🖼', '.webp': '🖼', '.svg': '🖼',
        '.mp4': '🎬', '.mov': '🎬', '.avi': '🎬', '.mkv': '🎬', '.webm': '🎬',
        '.mp3': '🎵', '.wav': '🎵', '.flac': '🎵',
        '.pdf': '📄', '.txt': '📝', '.md': '📝', '.rst': '📝',
        '.py': '🐍', '.js': '📜', '.ts': '📜', '.jsx': '📜', '.tsx': '📜',
        '.json': '🗒', '.yaml': '🗒', '.yml': '🗒', '.toml': '🗒',
        '.zip': '📦', '.tar': '📦', '.gz': '📦', '.bz2': '📦', '.7z': '📦',
        '.csv': '📊', '.parquet': '📊', '.xlsx': '📊',
        '.sh': '⚙️', '.bash': '⚙️',
        '.html': '🌐', '.htm': '🌐', '.css': '🎨',
    }
    return icons.get(ext, '📄')


def human_size(n: int) -> str:
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if n < 1024:
            return f"{n:.1f} {unit}" if unit != 'B' else f"{n} B"
        n /= 1024
    return f"{n:.1f} PB"


def list_dir(path: Path, rel: str):
    items = []
    try:
        entries = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except PermissionError:
        return []
    for entry in entries:
        entry_rel = (rel.rstrip('/') + '/' + entry.name).lstrip('/')
        stat = entry.stat()
        import datetime
        mtime = datetime.datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M')
        items.append({
            'name': entry.name,
            'rel': entry_rel,
            'abs_path': str(entry.resolve()),
            'is_dir': entry.is_dir(),
            'size_str': human_size(stat.st_size) if entry.is_file() else '—',
            'mtime': mtime,
            'icon': file_icon(entry.name),
        })
    return items


def make_breadcrumbs(rel: str):
    if not rel:
        return []
    parts = rel.strip('/').split('/')
    crumbs = []
    for i, part in enumerate(parts):
        crumbs.append({'name': part, 'path': '/'.join(parts[:i+1])})
    return crumbs


def parent_rel(rel: str) -> str:
    parts = rel.strip('/').split('/')
    return '/'.join(parts[:-1])


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    rel = request.args.get('path', '').strip('/')
    path = safe_path(rel)
    if not path.exists():
        abort(404)
    if path.is_file():
        return send_file(path)

    items = list_dir(path, rel)
    breadcrumbs = make_breadcrumbs(rel)
    return render_template_string(HTML,
        rel_path=rel,
        parent_path=parent_rel(rel),
        items=items,
        breadcrumbs=breadcrumbs,
    )


@app.route('/download')
def download():
    rel = request.args.get('path', '').strip('/')
    path = safe_path(rel)
    if not path.is_file():
        abort(404)
    return send_file(path, as_attachment=True)


@app.route('/upload', methods=['POST'])
def upload():
    """Single-shot upload — for files smaller than ~90MB.
    For larger files the client should use /upload-chunk + /upload-finalize."""
    dest_rel = request.form.get('dest', '').strip('/')
    file_rel = request.form.get('rel', '').lstrip('/')
    f = request.files.get('file')
    if not f:
        return jsonify(ok=False, error='no file')

    # Build target path preserving folder structure
    target = safe_path(dest_rel) / file_rel
    target.parent.mkdir(parents=True, exist_ok=True)
    f.save(str(target))
    return jsonify(ok=True, path=str(target))


@app.route('/upload-chunk', methods=['POST'])
def upload_chunk():
    """Receive a single chunk of a large file. Stored under CHUNK_DIR/<upload_id>/<index>."""
    upload_id = request.form.get('upload_id', '').strip()
    index = request.form.get('index', '').strip()
    if not upload_id or not index.isdigit():
        return jsonify(ok=False, error='bad params')
    # Sanitize upload_id (only hex-ish chars)
    safe_id = ''.join(c for c in upload_id if c.isalnum() or c in '-_')
    if not safe_id:
        return jsonify(ok=False, error='bad upload_id')

    chunk_file = request.files.get('chunk')
    if not chunk_file:
        return jsonify(ok=False, error='no chunk')

    chunk_folder = CHUNK_DIR / safe_id
    chunk_folder.mkdir(parents=True, exist_ok=True)
    chunk_file.save(str(chunk_folder / f"{int(index):08d}"))
    return jsonify(ok=True)


@app.route('/upload-finalize', methods=['POST'])
def upload_finalize():
    """Assemble all chunks into the final file and clean up."""
    data = request.json or {}
    upload_id = data.get('upload_id', '').strip()
    total = int(data.get('total', 0))
    dest_rel = data.get('dest', '').strip('/')
    file_rel = data.get('rel', '').lstrip('/')

    safe_id = ''.join(c for c in upload_id if c.isalnum() or c in '-_')
    chunk_folder = CHUNK_DIR / safe_id
    if not chunk_folder.exists():
        return jsonify(ok=False, error='upload not found')

    chunks = sorted(chunk_folder.iterdir())
    if len(chunks) != total:
        return jsonify(ok=False, error=f'missing chunks: got {len(chunks)}/{total}')

    target = safe_path(dest_rel) / file_rel
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, 'wb') as out:
        for c in chunks:
            with open(c, 'rb') as inp:
                shutil.copyfileobj(inp, out, length=8 * 1024 * 1024)

    # Cleanup
    shutil.rmtree(chunk_folder, ignore_errors=True)
    return jsonify(ok=True, path=str(target))


@app.route('/mkdir', methods=['POST'])
def mkdir():
    data = request.json
    path = safe_path(data.get('path', '')) / secure_filename(data.get('name', ''))
    try:
        path.mkdir(parents=True, exist_ok=True)
        return jsonify(ok=True)
    except Exception as e:
        return jsonify(ok=False, error=str(e))


@app.route('/rename', methods=['POST'])
def rename():
    """Rename a file or folder in place. Body: {path: rel, new_name: 'foo.txt'}.
    new_name must not contain path separators."""
    data = request.json or {}
    rel = (data.get('path') or '').strip('/')
    new_name = (data.get('new_name') or '').strip()
    if not rel or not new_name:
        return jsonify(ok=False, error='missing path or new_name')
    if '/' in new_name or '\\' in new_name or new_name in ('.', '..'):
        return jsonify(ok=False, error='invalid name')
    try:
        src = safe_path(rel)
        if not src.exists():
            return jsonify(ok=False, error='not found')
        target = src.parent / new_name
        # Resolve to make sure new path stays under BASE_DIR
        target_resolved = target.resolve()
        if not str(target_resolved).startswith(str(BASE_DIR.resolve())):
            return jsonify(ok=False, error='invalid target')
        if target.exists():
            return jsonify(ok=False, error='a file with that name already exists')
        src.rename(target)
        return jsonify(ok=True, path=str(target))
    except Exception as e:
        return jsonify(ok=False, error=str(e))


@app.route('/move', methods=['POST'])
def move():
    """Move a file or folder to a new parent directory (both paths relative to BASE_DIR)."""
    data = request.json or {}
    src_rel = (data.get('src') or '').strip('/')
    dest_dir_rel = (data.get('dest_dir') or '').strip('/')
    if not src_rel:
        return jsonify(ok=False, error='no src')
    try:
        src = safe_path(src_rel)
        dest_dir = safe_path(dest_dir_rel)
        if not src.exists():
            return jsonify(ok=False, error='src not found')
        if not dest_dir.exists() or not dest_dir.is_dir():
            return jsonify(ok=False, error='dest not a directory')
        # Prevent moving a folder into itself or its descendant
        try:
            dest_dir.resolve().relative_to(src.resolve())
            return jsonify(ok=False, error="can't move a folder into itself")
        except ValueError:
            pass
        target = dest_dir / src.name
        if target.resolve() == src.resolve():
            return jsonify(ok=True, path=str(target), note='same location')
        if target.exists():
            return jsonify(ok=False, error=f'"{src.name}" already exists in destination')
        shutil.move(str(src), str(target))
        return jsonify(ok=True, path=str(target))
    except Exception as e:
        return jsonify(ok=False, error=str(e))


@app.route('/move-batch', methods=['POST'])
def move_batch():
    """Move many items at once. Body: {srcs: [...], dest_dir: '...'}.
    Returns per-item ok/error so partial success is reported."""
    data = request.json or {}
    srcs = data.get('srcs') or []
    dest_dir_rel = (data.get('dest_dir') or '').strip('/')
    if not isinstance(srcs, list) or not srcs:
        return jsonify(ok=False, error='no srcs')
    try:
        dest_dir = safe_path(dest_dir_rel)
        if not dest_dir.exists() or not dest_dir.is_dir():
            return jsonify(ok=False, error='dest not a directory')
    except Exception as e:
        return jsonify(ok=False, error=f'bad dest: {e}')

    results = []
    moved = 0
    for src_rel in srcs:
        rel = (src_rel or '').strip('/')
        item = {'src': rel}
        try:
            if not rel:
                raise ValueError('empty src')
            src = safe_path(rel)
            if not src.exists():
                raise FileNotFoundError('src not found')
            # Prevent moving a folder into itself or its descendant
            try:
                dest_dir.resolve().relative_to(src.resolve())
                raise ValueError("can't move a folder into itself")
            except ValueError as ve:
                if "into itself" in str(ve):
                    raise
                # else: not a parent — fall through, this is the normal case
            target = dest_dir / src.name
            if target.resolve() == src.resolve():
                item.update(ok=True, note='same location')
            elif target.exists():
                raise FileExistsError(f'"{src.name}" already exists at destination')
            else:
                shutil.move(str(src), str(target))
                item.update(ok=True, path=str(target))
                moved += 1
        except Exception as e:
            item.update(ok=False, error=str(e))
        results.append(item)

    return jsonify(ok=True, moved=moved, total=len(srcs), results=results)


@app.route('/delete', methods=['POST'])
def delete():
    data = request.json
    path = safe_path(data.get('path', ''))
    try:
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        return jsonify(ok=True)
    except Exception as e:
        return jsonify(ok=False, error=str(e))


if __name__ == '__main__':
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 41011
    print(f"File server running on http://0.0.0.0:{port}")
    print(f"Storage root: {BASE_DIR.resolve()}")
    app.run(host='0.0.0.0', port=port, debug=False)
