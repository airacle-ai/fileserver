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

# Storage root — everything lives under here
BASE_DIR = Path(__file__).parent / "data"
BASE_DIR.mkdir(exist_ok=True)


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

  .actions-cell { display: flex; align-items: center; gap: 8px; }

  /* toast */
  #toast { position: fixed; bottom: 24px; right: 24px; background: var(--panel); border: 1px solid var(--border); color: var(--text); padding: 10px 18px; border-radius: 10px; font-size: 0.88rem; display: none; z-index: 999; box-shadow: 0 4px 20px rgba(0,0,0,0.4); }

  /* New folder */
  .new-folder-row { display: flex; gap: 8px; margin-bottom: 24px; }
  .new-folder-row input { flex: 1; background: var(--panel); border: 1px solid var(--border); color: var(--text); border-radius: 8px; padding: 8px 12px; font-size: 0.88rem; outline: none; }
  .new-folder-row input:focus { border-color: var(--accent); }
</style>
</head>
<body>

<header>
  <h1>📁 File Server</h1>
  <nav class="breadcrumb">
    <a href="/?path=">root</a>
    {% for crumb in breadcrumbs %}
      <span>/</span>
      <a href="/?path={{ crumb.path }}">{{ crumb.name }}</a>
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
        <tr>
          <td class="file-name"><a href="/?path={{ parent_path }}"><span class="file-icon">⬆️</span>.. (up)</a></td>
          <td></td><td></td><td></td><td></td>
        </tr>
        {% endif %}
        {% for item in items %}
        <tr>
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

async function uploadFiles(files) {
  if (!files.length) return;
  showProgress(`Uploading ${files.length} file(s)…`);
  let done = 0;
  for (const file of files) {
    const fd = new FormData();
    // preserve relative path for folder uploads
    const rel = file.webkitRelativePath || file.name;
    fd.append('file', file, rel);
    fd.append('dest', currentPath);
    fd.append('rel', rel);
    await fetch('/upload', { method: 'POST', body: fd });
    done++;
    setProgress(Math.round(done / files.length * 100));
    document.getElementById('progressLabel').textContent = `${done}/${files.length} uploaded`;
  }
  hideProgress();
  toast('Upload complete!');
  location.reload();
}

document.getElementById('fileInput').addEventListener('change', e => uploadFiles([...e.target.files]));
document.getElementById('folderInput').addEventListener('change', e => uploadFiles([...e.target.files]));

// Drag & drop
const zone = document.getElementById('dropZone');
zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('drag-over'); });
zone.addEventListener('dragleave', () => zone.classList.remove('drag-over'));
zone.addEventListener('drop', async e => {
  e.preventDefault();
  zone.classList.remove('drag-over');
  const items = [...e.dataTransfer.items];
  const files = [];
  async function traverseEntry(entry, prefix='') {
    if (entry.isFile) {
      await new Promise(res => entry.file(f => {
        Object.defineProperty(f, 'webkitRelativePath', { value: prefix + f.name });
        files.push(f); res();
      }));
    } else if (entry.isDirectory) {
      const reader = entry.createReader();
      await new Promise(res => reader.readEntries(async entries => {
        for (const child of entries) await traverseEntry(child, prefix + entry.name + '/');
        res();
      }));
    }
  }
  for (const item of items) {
    const entry = item.webkitGetAsEntry?.();
    if (entry) await traverseEntry(entry);
  }
  uploadFiles(files);
});
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


@app.route('/mkdir', methods=['POST'])
def mkdir():
    data = request.json
    path = safe_path(data.get('path', '')) / secure_filename(data.get('name', ''))
    try:
        path.mkdir(parents=True, exist_ok=True)
        return jsonify(ok=True)
    except Exception as e:
        return jsonify(ok=False, error=str(e))


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
