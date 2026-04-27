"""
文章审阅台 - 逐篇审核模式

主流程：
- 自动读取最近 output 下的文章
- 逐篇展示
- 好文章 → 范文库
- 差文章 → 错误示范
- 跳过 → 不处理

保留一个手动粘贴入口作为备用。
"""

import json
import os
import re
import threading
import webbrowser
from datetime import datetime

import bootstrap_shared
from flask import Flask, jsonify, request

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
EX_DIR = os.path.join(BASE_DIR, "prompts", "examples")
NEG_DIR = os.path.join(BASE_DIR, "prompts", "negatives")
NEG_FILE = os.path.join(NEG_DIR, "issues.jsonl")
REVIEW_STATE_FILE = os.path.join(NEG_DIR, "review_state.json")
MAX_POOL = 5
SEP = "\n---\n"

PLATFORM_LABELS = {
    "zhihu": "知乎",
    "sohu": "搜狐号",
    "baijiahao": "百家号",
    "toutiao": "头条号",
}
MODE_LABELS = {
    "info": "查资料型",
    "light_exp": "轻体验型",
    "other_exp": "转述型",
    "exp": "就诊经历",
    "hesitate": "纠结型",
    "short": "随手记",
}


def _ex_path(platform: str, mode: str) -> str:
    return os.path.join(EX_DIR, f"{platform}_{mode}.txt")


def _load_pool(platform: str, mode: str) -> list:
    path = _ex_path(platform, mode)
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()
    return [e.strip() for e in raw.split(SEP) if e.strip()]


def _save_pool(platform: str, mode: str, examples: list):
    os.makedirs(EX_DIR, exist_ok=True)
    path = _ex_path(platform, mode)
    with open(path, "w", encoding="utf-8") as f:
        f.write(SEP.join(examples))


def clean_article(text: str) -> str:
    return re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL).strip()


def read_meta_block(text: str) -> dict:
    result = {}
    m = re.search(r"<!--(.*?)-->", text, re.DOTALL)
    if not m:
        return result
    block = m.group(1)
    for key in (
        "mode", "platform", "profile", "style", "trigger",
        "first_draft_score", "final_score", "retries", "passed",
        "ab_group", "ab_model_key", "ab_model_label",
    ):
        mm = re.search(rf"{key}:\s*(.+)", block)
        if mm:
            result[key] = mm.group(1).strip()
    return result


def _read_state() -> dict:
    if not os.path.exists(REVIEW_STATE_FILE):
        return {}
    try:
        with open(REVIEW_STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _write_state(state: dict):
    os.makedirs(NEG_DIR, exist_ok=True)
    with open(REVIEW_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def _set_review_state(path: str, status: str, note: str = ""):
    state = _read_state()
    state[path] = {
        "status": status,
        "note": note,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    _write_state(state)


def _get_review_state(path: str) -> dict:
    return _read_state().get(path, {})


def _latest_output_dirs() -> list:
    if not os.path.exists(OUTPUT_DIR):
        return []
    dirs = []
    for name in os.listdir(OUTPUT_DIR):
        full = os.path.join(OUTPUT_DIR, name)
        if os.path.isdir(full):
            dirs.append(full)
    return sorted(dirs, key=os.path.getmtime, reverse=True)


def _collect_articles() -> list:
    articles = []
    if not os.path.exists(OUTPUT_DIR):
        return articles

    latest_dirs = _latest_output_dirs()[:3]
    for root_dir in latest_dirs:
        for root, _, files in os.walk(root_dir):
            for name in files:
                if not name.lower().endswith(".txt"):
                    continue
                path = os.path.join(root, name)
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        raw = f.read()
                except Exception:
                    continue
                meta = read_meta_block(raw)
                body = clean_article(raw)
                if not body.strip():
                    continue
                lines = body.splitlines()
                title = lines[0].strip() if lines else "(无标题)"
                content = "\n".join(lines[1:]).strip() if len(lines) > 1 else body
                rel_path = os.path.relpath(path, BASE_DIR).replace("\\", "/")
                state = _get_review_state(rel_path)
                platform = meta.get("platform") or _guess_platform_from_name(name)
                mode = meta.get("mode", "")
                articles.append({
                    "id": rel_path,
                    "path": rel_path,
                    "title": title,
                    "content": content,
                    "platform": platform,
                    "platform_label": PLATFORM_LABELS.get(platform, platform or "未知"),
                    "mode": mode,
                    "mode_label": MODE_LABELS.get(mode, mode or "未识别"),
                    "meta": meta,
                    "status": state.get("status", "pending"),
                    "note": state.get("note", ""),
                    "updated_at": state.get("updated_at", ""),
                })
    articles.sort(key=lambda x: x["path"], reverse=True)
    return articles


def _guess_platform_from_name(name: str) -> str:
    lower = name.lower()
    for platform in PLATFORM_LABELS:
        if lower.startswith(platform):
            return platform
    return ""


def get_stats() -> dict:
    stats = {"pools": [], "neg_count": 0, "review": {"pending": 0, "good": 0, "bad": 0, "skip": 0}}
    for p in PLATFORM_LABELS:
        for m in MODE_LABELS:
            pool = _load_pool(p, m)
            if pool:
                stats["pools"].append({
                    "key": f"{p}_{m}",
                    "label": f"{PLATFORM_LABELS[p]} · {MODE_LABELS[m]}",
                    "count": len(pool),
                    "max": MAX_POOL,
                })
    if os.path.exists(NEG_FILE):
        with open(NEG_FILE, "r", encoding="utf-8") as f:
            stats["neg_count"] = sum(1 for l in f if l.strip())

    for item in _collect_articles():
        stats["review"][item["status"] if item["status"] in stats["review"] else "pending"] += 1
    return stats


def save_review(article_id: str, action: str, note: str = ""):
    articles = {item["id"]: item for item in _collect_articles()}
    item = articles.get(article_id)
    if not item:
        return False, "未找到对应文章"

    platform = item.get("platform", "")
    mode = item.get("mode", "")
    article_text = f"{item['title']}\n\n{item['content']}".strip()
    cleaned = clean_article(article_text)

    if action == "good":
        if not platform or not mode:
            return False, "该文章缺少平台或模式信息，暂时无法加入范文库"
        pool = _load_pool(platform, mode)
        if cleaned not in pool:
            pool.append(cleaned)
        if len(pool) > MAX_POOL:
            pool = pool[-MAX_POOL:]
        _save_pool(platform, mode, pool)
        _set_review_state(article_id, "good", note)
        label = f"{PLATFORM_LABELS.get(platform, platform)} · {MODE_LABELS.get(mode, mode)}"
        return True, f"✓ 已加入范文库：{label}"

    if action == "bad":
        if not note.strip():
            return False, "差文章请至少写一个简短原因"
        os.makedirs(NEG_DIR, exist_ok=True)
        record = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "article_id": article_id,
            "platform": platform,
            "mode": mode,
            "note": note.strip(),
            "title": item["title"],
            "preview": cleaned[:180],
        }
        with open(NEG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        _set_review_state(article_id, "bad", note)
        return True, "✗ 已记入错误示范"

    if action == "skip":
        _set_review_state(article_id, "skip", note)
        return True, "已跳过这篇文章"

    return False, "未知操作"


@app.route("/")
def index():
    return HTML


@app.route("/stats")
def route_stats():
    return jsonify(get_stats())


@app.route("/articles")
def route_articles():
    status = request.args.get("status", "all")
    items = _collect_articles()
    if status != "all":
        items = [x for x in items if x["status"] == status]
    return jsonify({"articles": items})


@app.route("/review", methods=["POST"])
def route_review():
    data = request.json or {}
    article_id = data.get("article_id", "").strip()
    action = data.get("action", "").strip()
    note = data.get("note", "").strip()
    ok, msg = save_review(article_id, action, note)
    return jsonify({"ok": ok, "msg": msg})


@app.route("/pool")
def route_pool():
    platform = request.args.get("platform", "")
    mode = request.args.get("mode", "")
    pool = _load_pool(platform, mode)
    return jsonify({"examples": pool})


@app.route("/manual_save", methods=["POST"])
def route_manual_save():
    data = request.json or {}
    platform = data.get("platform", "").strip()
    mode = data.get("mode", "").strip()
    rating = data.get("rating", "good")
    note = data.get("note", "").strip()
    article = data.get("article", "").strip()

    if not article:
        return jsonify({"ok": False, "msg": "请先粘贴文章"})
    if not platform or not mode:
        return jsonify({"ok": False, "msg": "请选择平台和模式"})

    cleaned = clean_article(article)
    if rating == "good":
        pool = _load_pool(platform, mode)
        if cleaned not in pool:
            pool.append(cleaned)
        if len(pool) > MAX_POOL:
            pool = pool[-MAX_POOL:]
        _save_pool(platform, mode, pool)
        return jsonify({"ok": True, "msg": "✓ 已手动加入范文库"})

    if not note:
        return jsonify({"ok": False, "msg": "差文章请填写原因"})
    os.makedirs(NEG_DIR, exist_ok=True)
    record = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "platform": platform,
        "mode": mode,
        "note": note,
        "preview": cleaned[:180],
    }
    with open(NEG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return jsonify({"ok": True, "msg": "✗ 已手动记入错误示范"})


HTML = r"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<title>文章审阅台</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;background:#f4f7fb;color:#1d2433;font-size:14px;min-height:100vh}
.topbar{background:#fff;border-bottom:1px solid #e8edf5;padding:16px 22px;display:flex;justify-content:space-between;align-items:center;position:sticky;top:0;z-index:10}
.topbar h1{font-size:18px;font-weight:700}.topbar p{font-size:12px;color:#7a8499;margin-top:4px}
.wrap{max-width:1480px;margin:0 auto;padding:18px}
.summary{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:16px}
.card{background:#fff;border-radius:14px;box-shadow:0 4px 18px rgba(29,36,51,.06)}
.mini{padding:16px}.mini .k{font-size:12px;color:#7a8499}.mini .v{font-size:24px;font-weight:700;margin-top:8px}
.layout{display:grid;grid-template-columns:340px 1fr 320px;gap:16px}
.panel{padding:16px}
.panel h2{font-size:12px;color:#7a8499;text-transform:uppercase;letter-spacing:.08em;margin-bottom:12px}
.toolbar{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px}
.btn{border:0;border-radius:10px;padding:10px 14px;cursor:pointer;font-size:13px;font-family:inherit}
.btn.primary{background:#4f8cff;color:#fff}.btn.ghost{background:#eef4ff;color:#355dca}.btn.good{background:#eaf8ef;color:#1f8f46}.btn.bad{background:#fff0f1;color:#cf334d}.btn.skip{background:#f1f4f8;color:#556070}
.list{display:flex;flex-direction:column;gap:10px;max-height:760px;overflow:auto}
.item{border:1px solid #e8edf5;border-radius:12px;padding:12px;cursor:pointer;transition:.15s;background:#fff}
.item:hover{border-color:#b8caf7}.item.active{border-color:#4f8cff;box-shadow:0 0 0 3px rgba(79,140,255,.1)}
.item .title{font-size:14px;font-weight:700;line-height:1.5;color:#1d2433}
.item .meta{margin-top:8px;font-size:12px;color:#7a8499;line-height:1.7}
.badge{display:inline-block;padding:2px 8px;border-radius:999px;font-size:12px;margin-right:6px}
.badge.pending{background:#eef4ff;color:#355dca}.badge.good{background:#eaf8ef;color:#1f8f46}.badge.bad{background:#fff0f1;color:#cf334d}.badge.skip{background:#f1f4f8;color:#556070}
.viewer{padding:18px}.viewer .article-title{font-size:24px;font-weight:800;line-height:1.5;color:#172033}
.viewer .article-meta{margin-top:10px;font-size:13px;color:#71809a;line-height:1.8}
.viewer .article-body{margin-top:18px;white-space:pre-wrap;line-height:1.9;font-size:15px;color:#2d3546;max-height:590px;overflow:auto;padding-right:6px}
.note{width:100%;margin-top:12px;border:1.5px solid #e2e8f3;border-radius:12px;padding:12px;font-size:13px;line-height:1.7;resize:vertical;min-height:88px;font-family:inherit}
.note:focus{outline:none;border-color:#4f8cff}
.sideblock{padding:16px}
.pool-list{display:flex;flex-direction:column;gap:8px;max-height:240px;overflow:auto}
.pool-item{padding:10px 12px;border-radius:10px;background:#f7f9fc;font-size:13px;color:#556070;display:flex;justify-content:space-between;gap:8px}
.toast{position:fixed;right:24px;bottom:24px;background:#111827;color:#fff;padding:12px 18px;border-radius:10px;opacity:0;transform:translateY(8px);transition:.2s;pointer-events:none;max-width:320px;line-height:1.6}
.toast.show{opacity:1;transform:translateY(0)}
.empty{padding:36px 12px;text-align:center;color:#9aa6bd}
.tabs{display:flex;gap:8px;margin-bottom:12px}
.tab{padding:8px 12px;border-radius:999px;background:#eef4ff;color:#355dca;cursor:pointer;font-size:12px}.tab.active{background:#4f8cff;color:#fff}
.manual{margin-top:16px;border-top:1px solid #edf1f7;padding-top:16px}
.select, .textarea{width:100%;border:1.5px solid #e2e8f3;border-radius:10px;padding:10px 12px;font-size:13px;font-family:inherit;background:#fff}
.select:focus,.textarea:focus{outline:none;border-color:#4f8cff}
.textarea{min-height:90px;resize:vertical;line-height:1.7}
.row{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:8px}
.helper{font-size:12px;color:#7a8499;line-height:1.7;margin-top:8px}
</style>
</head>
<body>
<div class="topbar">
  <div>
    <h1>文章审阅台</h1>
    <p>逐篇判断：好文章进范文库，差文章进错误示范，不想标就跳过。</p>
  </div>
  <div class="toolbar">
    <button class="btn ghost" onclick="refreshAll()">刷新文章</button>
    <button class="btn ghost" onclick="toggleManual()">手动粘贴入口</button>
  </div>
</div>

<div class="wrap">
  <div class="summary">
    <div class="card mini"><div class="k">待处理</div><div class="v" id="pendingCnt">0</div></div>
    <div class="card mini"><div class="k">已收范文</div><div class="v" id="goodCnt">0</div></div>
    <div class="card mini"><div class="k">已记错误</div><div class="v" id="badCnt">0</div></div>
    <div class="card mini"><div class="k">已跳过</div><div class="v" id="skipCnt">0</div></div>
  </div>

  <div class="layout">
    <div class="card panel">
      <h2>文章列表</h2>
      <div class="tabs">
        <div class="tab active" data-status="all" onclick="switchTab(this)">全部</div>
        <div class="tab" data-status="pending" onclick="switchTab(this)">待处理</div>
        <div class="tab" data-status="good" onclick="switchTab(this)">已收好文</div>
        <div class="tab" data-status="bad" onclick="switchTab(this)">已记错误</div>
        <div class="tab" data-status="skip" onclick="switchTab(this)">已跳过</div>
      </div>
      <div id="articleList" class="list"><div class="empty">加载中...</div></div>
    </div>

    <div class="card viewer">
      <div id="viewerEmpty" class="empty">左侧选择一篇文章开始审阅</div>
      <div id="viewerMain" style="display:none">
        <div class="article-title" id="articleTitle"></div>
        <div class="article-meta" id="articleMeta"></div>
        <div class="toolbar" style="margin-top:16px">
          <button class="btn good" onclick="reviewCurrent('good')">好文章</button>
          <button class="btn bad" onclick="reviewCurrent('bad')">差文章</button>
          <button class="btn skip" onclick="reviewCurrent('skip')">跳过</button>
        </div>
        <textarea id="reviewNote" class="note" placeholder="备注：好文章可写亮点；差文章建议写问题点；跳过可不填。"></textarea>
        <div class="article-body" id="articleBody"></div>
      </div>
    </div>

    <div class="card sideblock">
      <h2>范文库现状</h2>
      <div id="poolList" class="pool-list"><div class="empty">加载中...</div></div>
      <div class="helper">好文章会按平台 + 模式自动进入对应范文库。差文章会写入错误示范记录。</div>

      <div id="manualBox" class="manual" style="display:none">
        <h2>手动粘贴备用</h2>
        <textarea id="manualArticle" class="textarea" placeholder="粘贴文章全文..."></textarea>
        <div class="row">
          <select id="manualPlatform" class="select">
            <option value="">选择平台</option>
            <option value="zhihu">知乎</option>
            <option value="sohu">搜狐号</option>
            <option value="baijiahao">百家号</option>
            <option value="toutiao">头条号</option>
          </select>
          <select id="manualMode" class="select">
            <option value="">选择模式</option>
            <option value="info">info · 查资料型</option>
            <option value="light_exp">light_exp · 轻体验型</option>
            <option value="other_exp">other_exp · 转述型</option>
            <option value="exp">exp · 就诊经历</option>
            <option value="hesitate">hesitate · 纠结型</option>
            <option value="short">short · 随手记</option>
          </select>
        </div>
        <div class="row">
          <select id="manualRating" class="select">
            <option value="good">好文章</option>
            <option value="bad">差文章</option>
          </select>
          <input id="manualNote" class="select" placeholder="原因或亮点（差文章建议必填）" />
        </div>
        <button class="btn primary" style="width:100%;margin-top:10px" onclick="manualSave()">手动保存</button>
      </div>
    </div>
  </div>
</div>

<div class="toast" id="toast"></div>

<script>
let articles = [];
let currentArticle = null;
let currentStatus = 'all';

function showToast(msg, type='ok') {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.style.background = type === 'err' ? '#dc2626' : '#111827';
  t.classList.add('show');
  clearTimeout(t._timer);
  t._timer = setTimeout(() => t.classList.remove('show'), 3000);
}

function statusLabel(status) {
  if (status === 'good') return '已收好文';
  if (status === 'bad') return '已记错误';
  if (status === 'skip') return '已跳过';
  return '待处理';
}

function switchTab(el) {
  document.querySelectorAll('.tab').forEach(x => x.classList.remove('active'));
  el.classList.add('active');
  currentStatus = el.dataset.status;
  loadArticles();
}

function renderArticles() {
  const box = document.getElementById('articleList');
  if (!articles.length) {
    box.innerHTML = '<div class="empty">当前筛选下没有文章</div>';
    return;
  }
  box.innerHTML = articles.map(item => `
    <div class="item ${currentArticle && currentArticle.id===item.id ? 'active' : ''}" onclick="selectArticle('${escapeAttr(item.id)}')">
      <div><span class="badge ${item.status}">${statusLabel(item.status)}</span></div>
      <div class="title">${escapeHtml(item.title)}</div>
      <div class="meta">${escapeHtml(item.platform_label)} · ${escapeHtml(item.mode_label)}<br>${escapeHtml(item.path)}</div>
    </div>
  `).join('');
}

function escapeHtml(s) {
  return (s || '').replace(/[&<>\"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
}
function escapeAttr(s) {
  return (s || '').replace(/\\/g, '\\\\').replace(/'/g, "\\'");
}

function selectArticle(id) {
  currentArticle = articles.find(x => x.id === id) || null;
  renderArticles();
  if (!currentArticle) return;
  document.getElementById('viewerEmpty').style.display = 'none';
  document.getElementById('viewerMain').style.display = 'block';
  document.getElementById('articleTitle').textContent = currentArticle.title;
  document.getElementById('articleMeta').textContent = `${currentArticle.platform_label} · ${currentArticle.mode_label} · ${currentArticle.path}`;
  document.getElementById('articleBody').textContent = currentArticle.content;
  document.getElementById('reviewNote').value = currentArticle.note || '';
}

function loadArticles() {
  fetch('/articles?status=' + currentStatus)
    .then(r => r.json())
    .then(data => {
      articles = data.articles || [];
      if (currentArticle) {
        currentArticle = articles.find(x => x.id === currentArticle.id) || null;
      }
      renderArticles();
      if (currentArticle) {
        selectArticle(currentArticle.id);
      } else {
        document.getElementById('viewerEmpty').style.display = 'block';
        document.getElementById('viewerMain').style.display = 'none';
      }
    });
}

function loadStats() {
  fetch('/stats').then(r => r.json()).then(data => {
    document.getElementById('pendingCnt').textContent = data.review.pending || 0;
    document.getElementById('goodCnt').textContent = data.review.good || 0;
    document.getElementById('badCnt').textContent = data.review.bad || 0;
    document.getElementById('skipCnt').textContent = data.review.skip || 0;

    const poolList = document.getElementById('poolList');
    if (!data.pools.length) {
      poolList.innerHTML = '<div class="empty">还没有范文</div>';
    } else {
      poolList.innerHTML = data.pools.map(p => `
        <div class="pool-item"><span>${escapeHtml(p.label)}</span><strong>${p.count}/${p.max}</strong></div>
      `).join('');
    }
  });
}

function reviewCurrent(action) {
  if (!currentArticle) {
    showToast('请先选择文章', 'err');
    return;
  }
  const note = document.getElementById('reviewNote').value.trim();
  fetch('/review', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({article_id: currentArticle.id, action, note})
  }).then(r => r.json()).then(data => {
    if (!data.ok) {
      showToast(data.msg, 'err');
      return;
    }
    showToast(data.msg, 'ok');
    refreshAll(currentArticle.id, action);
  });
}

function refreshAll(lastId, action) {
  loadStats();
  loadArticles();
}

function toggleManual() {
  const box = document.getElementById('manualBox');
  box.style.display = box.style.display === 'none' ? 'block' : 'none';
}

function manualSave() {
  const article = document.getElementById('manualArticle').value.trim();
  const platform = document.getElementById('manualPlatform').value;
  const mode = document.getElementById('manualMode').value;
  const rating = document.getElementById('manualRating').value;
  const note = document.getElementById('manualNote').value.trim();
  if (!article) return showToast('请先粘贴文章', 'err');
  if (!platform || !mode) return showToast('请选择平台和模式', 'err');
  fetch('/manual_save', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({article, platform, mode, rating, note})
  }).then(r => r.json()).then(data => {
    if (!data.ok) return showToast(data.msg, 'err');
    showToast(data.msg, 'ok');
    document.getElementById('manualArticle').value = '';
    document.getElementById('manualNote').value = '';
    loadStats();
  });
}

document.addEventListener('keydown', function(e) {
  if (!currentArticle) return;
  if (e.target && ['TEXTAREA', 'INPUT', 'SELECT'].includes(e.target.tagName)) return;
  if (e.key === '1') reviewCurrent('good');
  if (e.key === '2') reviewCurrent('bad');
  if (e.key === '3') reviewCurrent('skip');
});

loadStats();
loadArticles();
setInterval(loadStats, 8000);
</script>
</body>
</html>"""


if __name__ == "__main__":
    os.makedirs(EX_DIR, exist_ok=True)
    os.makedirs(NEG_DIR, exist_ok=True)
    port = 5050

    def _open():
        webbrowser.open(f"http://localhost:{port}")

    threading.Timer(0.5, _open).start()
    print(f"审阅台已启动 → http://localhost:{port}")
    app.run(port=port, debug=False, use_reloader=False)
