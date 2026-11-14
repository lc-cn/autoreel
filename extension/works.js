// 自影 · 设置页「作品」：最近 7 天每个频道每期的标题、发布状态、文案，可预览视频
import { headOf, listDir, readText, readBlob, clipBranches } from "./repo.js";

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const PLAT = { douyin: "抖音", channels: "视频号", kuaishou: "快手" };
let H = null, rows = [], names = {}, loaded = false, repoName = "";
const acctName = {};

function toast(t) { const el = $("toast"); el.textContent = t; el.classList.add("show"); setTimeout(() => el.classList.remove("show"), 2500); }
const bjDate = (d = new Date()) => new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Shanghai" }).format(d);

function statusPill(st) {
  if (!st) return '<span class="pill">还没发布</span>';
  const t = (st.time || "").slice(11, 16);
  if (st.status === "published") return `<span class="pill ok">已发布 ${esc(t)}</span>`;
  if (st.status === "failed") return `<span class="pill bad">失败 ${esc(t)}</span>`;
  if (st.status === "done") return `<span class="pill ok">已标记完成</span>`;
  return `<span class="pill warn">${esc(st.status)} ${esc(t)}</span>`;
}

async function pool(items, n, fn) {
  let i = 0;
  await Promise.all(Array.from({ length: n }, async () => { while (i < items.length) { const k = i++; await fn(items[k]); } }));
}

async function pull() {
  if (window.__saveRepoToken) await window.__saveRepoToken();
  $("wkState").textContent = "正在读取…";
  $("wkList").innerHTML = "";
  try {
    H = await headOf();
    repoName = H.name;
    const chs = (await listDir("channels", H.head)).filter((d) => d.type === "dir");
    await Promise.all(chs.map(async (d) => {
      try { names[d.name] = JSON.parse((await readText(`channels/${d.name}/channel.json`, H.head)).text).name || d.name; } catch { names[d.name] = d.name; }
    }));
    try { (JSON.parse((await readText("autoreel.config.json", H.head)).text).accounts || []).forEach((a) => (acctName[a.id] = `${PLAT[a.platform] || a.platform}·${a.name}`)); } catch {}
    const since = bjDate(new Date(Date.now() - 7 * 86400000));
    rows = (await clipBranches()).filter((b) => b.date >= since).sort((a, b) => (b.date + b.channel).localeCompare(a.date + a.channel));
    renderList();
    await pool(rows, 6, async (r) => {
      const [meta, st] = await Promise.all([readText("meta.json", r.name), readText("status.json", r.name)]);
      try { r.meta = JSON.parse(meta.text || "{}"); } catch { r.meta = {}; }
      try { r.st = st.text ? JSON.parse(st.text) : null; } catch { r.st = null; }
      renderRow(r);
    });
    const today = bjDate();
    const pub = rows.filter((r) => r.date === today && r.st && r.st.status === "published").length;
    $("wkState").textContent = `最近 7 天 ${rows.length} 期 · 今天已发布 ${pub} 期 · ${new Date().toLocaleTimeString("zh-CN", { hour12: false })} 读取`;
  } catch (e) {
    $("wkState").textContent = "";
    $("wkList").innerHTML = `<div class="err">${esc(e.message)}</div>`;
  }
}

function renderList() {
  if (!rows.length) { $("wkList").innerHTML = '<div class="muted">最近 7 天还没有作品。</div>'; return; }
  let html = "", day = "";
  for (const [i, r] of rows.entries()) {
    if (r.date !== day) { day = r.date; html += `<h3>${esc(day)}${day === bjDate() ? "（今天）" : ""}</h3>`; }
    html += `<div class="wk" id="wk${i}"></div>`;
    r.i = i;
  }
  $("wkList").innerHTML = html;
  rows.forEach(renderRow);
}

function renderRow(r) {
  const el = $(`wk${r.i}`);
  if (!el) return;
  const st = r.st;
  const W = { published: "已发布", failed: "失败", gave_up: "已放弃", need_login: "需要登录", wrong_account: "登错账号", declare: "声明没勾上", error: "出错" };
  const plats = st && st.platforms && Object.keys(st.platforms).length > 1 || (st && st.platforms && !st.platforms.douyin)
    ? Object.entries(st.platforms).map(([k, v]) => `${acctName[k] || PLAT[k] || k}${v.nickname ? `（${v.nickname}）` : ""}：${W[v.status] || v.status}`).join(" · ") : "";
  el.innerHTML = `
    <div class="wk-m"><span class="pill plain brand">${esc(names[r.channel] || r.channel)}</span>
      <b>${esc((r.meta && r.meta.title) || (r.meta ? "（没有标题）" : "读取中…"))}</b>${statusPill(st)}
      ${plats ? `<span class="muted">${esc(plats)}</span>` : ""}
      ${st && st.status === "failed" && (st.help || st.detail) ? `<div class="err">${esc(st.help || st.detail)}</div>` : ""}</div>
    <div class="wk-a"><button class="btn sm" type="button" data-cap>文案</button><button class="btn sm" type="button" data-vid>预览</button>
      <a class="btn sm ghost" href="https://github.com/${esc(repoName)}/tree/${esc(r.name)}" target="_blank">在 GitHub 查看</a></div>
    <div class="wk-x"></div>`;
  el.querySelector("[data-cap]").onclick = async () => {
    const x = el.querySelector(".wk-x");
    if (x.dataset.k === "cap") { x.innerHTML = ""; x.dataset.k = ""; return; }
    x.innerHTML = '<div class="muted">读取中…</div>';
    const t = (await readText("caption.txt", r.name)).text;
    x.innerHTML = `<pre class="cap">${esc(t || "（没有文案）")}</pre>`;
    x.dataset.k = "cap";
  };
  el.querySelector("[data-vid]").onclick = async (ev) => {
    const x = el.querySelector(".wk-x"), b = ev.currentTarget;
    if (x.dataset.k === "vid") { x.innerHTML = ""; x.dataset.k = ""; return; }
    b.textContent = "加载中…";
    try {
      let blob = await cached(`${r.name}:video`);
      if (!blob) blob = await readBlob("video.mp4", r.name, "video/mp4");
      x.innerHTML = `<video controls playsinline src="${URL.createObjectURL(blob instanceof Blob ? blob : new Blob([blob], { type: "video/mp4" }))}"></video>`;
      x.dataset.k = "vid";
    } catch (e) { toast(e.message); }
    b.textContent = "预览";
  };
}

// 插件下载过的视频会缓存在本地（和后台同一个数据库），有就直接用
function cached(key) {
  return new Promise((res) => {
    const rq = indexedDB.open("kb", 1);
    rq.onupgradeneeded = () => rq.result.createObjectStore("files");
    rq.onerror = () => res(null);
    rq.onsuccess = () => {
      try {
        const g = rq.result.transaction("files").objectStore("files").get(key);
        g.onsuccess = () => res(g.result || null);
        g.onerror = () => res(null);
      } catch { res(null); }
    };
  });
}

$("wkPull").onclick = pull;
function onTab() { if ((location.hash || "").slice(1) === "works") { if (!loaded) { loaded = true; pull(); } } }
window.addEventListener("hashchange", onTab);
onTab();
