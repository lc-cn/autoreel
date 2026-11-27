// 自影 · 设置页「数据」：各频道流量趋势折线图 + 按频道 / 按视频形式汇总 + 每期数据表；自动采集开关
// 数据：仓库 history/数据.jsonl（插件每晚采集的抖音作品数据）；频道、日期、形式：history/发布记录.jsonl（按标题对上）
import { readText } from "./repo.js";
import { metricsFromRaw } from "./shared.js";

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const METRICS = [
  { k: "plays", name: "播放量", fmt: (v) => (v >= 10000 ? (v / 10000).toFixed(1) + "万" : String(Math.round(v))), better: "高" },
  { k: "bounce2s", name: "2秒跳出率", fmt: (v) => v.toFixed(1) + "%", better: "低", pct: true },
  { k: "completion5s", name: "5秒完播率", fmt: (v) => v.toFixed(1) + "%", better: "高", pct: true },
  { k: "completion", name: "完播率", fmt: (v) => v.toFixed(1) + "%", better: "高", pct: true },
  { k: "avg_watch", name: "平均播放时长", fmt: (v) => (v >= 60 ? `${Math.floor(v / 60)}分${Math.round(v % 60)}秒` : `${Math.round(v)}秒`), better: "高" },
  { k: "comments", name: "评论", fmt: (v) => (Number.isInteger(v) ? String(v) : v.toFixed(1)), better: "高" },
];
const RANGES = [["14", "近 14 天"], ["30", "近 30 天"], ["all", "全部"]];
const FORMAT_NAME = { classic: "经典版", immersive: "实拍沉浸", kinetic: "大字快剪", quiz: "答题挑战" };
// 频道颜色固定（按频道，不按排名）；参考配色已通过色盲区分校验，浅色底对比度不足的由图例、线尾标注和表格补足
const ORDER = ["kuaibao", "jiangtou", "lengzhishi", "chengyu", "lishi", "dushu", "haowu"];
const LIGHT = ["#257de0", "#f47230", "#00b894", "#f2a600", "#ee7fac", "#008a17", "#6a4ce2"];
const DARK = ["#338ced", "#e76624", "#00a888", "#d28e05", "#e24d8b", "#0aac23", "#9887ef"];
const dark = () => matchMedia("(prefers-color-scheme: dark)").matches;
const colorOf = (ch) => { const i = ORDER.indexOf(ch); const pal = dark() ? DARK : LIGHT; return pal[i >= 0 ? i : (ORDER.length + [...ch].reduce((a, c) => a + c.charCodeAt(0), 0)) % pal.length]; };

let rows = [], metric = "plays", range = "30", hidden = new Set(), loaded = false;
const norm = (t) => String(t || "").replace(/\s+/g, "");
const parseLines = (t) => (t || "").split("\n").filter(Boolean).map((l) => { try { return JSON.parse(l); } catch (_) { return null; } }).filter(Boolean);

async function pull() {
  if (window.__saveRepoToken) await window.__saveRepoToken();
  $("stState").textContent = "正在读取…";
  try {
    const [d, h] = await Promise.all([readText("history/数据.jsonl"), readText("history/发布记录.jsonl")]);
    const hist = parseLines(h.text);
    const byTitle = new Map(hist.map((x) => [norm(x.title), x]));
    const year = new Date().getFullYear();
    rows = parseLines(d.text).map((r) => {
      const hx = byTitle.get(norm(r.title)) || {};
      let date = hx.date;
      if (!date) { // 记录里没有：从标题「11月22日」推日期
        const m = String(r.title).match(/(\d{1,2})月(\d{1,2})日/);
        if (m) date = `${year}-${String(m[1]).padStart(2, "0")}-${String(m[2]).padStart(2, "0")}`;
      }
      const name = (String(r.title).match(/^(.+?)\d{1,2}月\d{1,2}日/) || [])[1] || hx.channel || "其他";
      // 有原始数字时按最新的对应规则重新计算（旧版插件的对应有误，不用重新采集）；原始数据里没有的指标保留记录里的
      const metrics = { ...(r.metrics || {}) };
      if (r.raw) Object.assign(metrics, metricsFromRaw(r.raw));
      return { ...r, metrics, date, channel: hx.channel || name, chName: name, format: hx.format || "classic" };
    }).filter((r) => r.date);
    $("stState").textContent = rows.length ? `共 ${rows.length} 期，最近一次采集 ${rows.map((r) => r.collected || "").sort().pop() || "—"}` : "还没有数据：开启下面的自动采集，或点「立即采集」";
    loaded = true;
    render();
  } catch (e) {
    $("stState").textContent = "读取失败：" + e.message;
  }
}

function seg(el, items, cur, on) {
  el.innerHTML = items.map(([k, n]) => `<button type="button" data-k="${k}" class="${k === cur ? "on" : ""}">${esc(n)}</button>`).join("");
  el.onclick = (e) => { const b = e.target.closest("button"); if (b) on(b.dataset.k); };
}

function visibleRows() {
  if (range === "all") return rows;
  const since = new Date(Date.now() - (parseInt(range, 10) - 1) * 864e5);
  const s = new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Shanghai" }).format(since);
  return rows.filter((r) => r.date >= s);
}

function render() {
  seg($("stMetric"), METRICS.map((m) => [m.k, m.name]), metric, (k) => { metric = k; render(); });
  seg($("stRange"), RANGES, range, (k) => { range = k; render(); });
  const M = METRICS.find((m) => m.k === metric);
  const data = visibleRows().filter((r) => r.metrics && r.metrics[metric] != null);
  const chans = [...new Set(rows.map((r) => r.channel))].sort((a, b) => (ORDER.indexOf(a) + 99 * (ORDER.indexOf(a) < 0)) - (ORDER.indexOf(b) + 99 * (ORDER.indexOf(b) < 0)));
  const nameOf = Object.fromEntries(rows.map((r) => [r.channel, r.chName]));
  $("stLegend").innerHTML = chans.map((c) => `<span data-c="${esc(c)}" class="${hidden.has(c) ? "off" : ""}" title="点击显示 / 隐藏"><i style="background:${colorOf(c)}"></i>${esc(nameOf[c] || c)}</span>`).join("");
  $("stLegend").onclick = (e) => { const s = e.target.closest("span[data-c]"); if (!s) return; const c = s.dataset.c; hidden.has(c) ? hidden.delete(c) : hidden.add(c); render(); };
  drawChart(data.filter((r) => !hidden.has(r.channel)), chans.filter((c) => !hidden.has(c)), M, nameOf);
  summary(visibleRows(), chans, nameOf);
  table(visibleRows());
}

function drawChart(data, chans, M, nameOf) {
  const box = $("stChart");
  if (!data.length) { box.innerHTML = `<p class="muted" style="padding:30px 0;text-align:center">${loaded ? `这段时间还没有「${M.name}」数据` : ""}</p>`; return; }
  const W = 900, H = 320, L = 52, R = 96, T = 14, B = 30;
  const dates = [...new Set(data.map((r) => r.date))].sort();
  const d0 = new Date(dates[0]), d1 = new Date(dates[dates.length - 1]);
  const span = Math.max(1, (d1 - d0) / 864e5);
  const x = (d) => L + ((new Date(d) - d0) / 864e5 / span) * (W - L - R);
  const vmax = Math.max(...data.map((r) => r.metrics[M.k]));
  const top = M.pct ? Math.min(100, Math.ceil(vmax / 10) * 10 || 10) : niceMax(vmax);
  const y = (v) => T + (1 - v / top) * (H - T - B);
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => f * top);
  let svg = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="各频道${esc(M.name)}趋势">`;
  for (const t of ticks) svg += `<line class="grid" x1="${L}" x2="${W - R}" y1="${y(t)}" y2="${y(t)}"/><text class="ax" x="${L - 8}" y="${y(t) + 4}" text-anchor="end">${esc(M.fmt(t))}</text>`;
  const step = Math.max(1, Math.ceil(dates.length / 8));
  dates.forEach((d, i) => { if (i % step === 0 || i === dates.length - 1) svg += `<text class="ax" x="${x(d)}" y="${H - 8}" text-anchor="middle">${d.slice(5).replace("-", "/")}</text>`; });
  const ends = [];
  for (const c of chans) {
    const pts = data.filter((r) => r.channel === c).sort((a, b) => a.date.localeCompare(b.date));
    if (!pts.length) continue;
    const col = colorOf(c);
    if (pts.length > 1) svg += `<path d="${pts.map((p, i) => `${i ? "L" : "M"}${x(p.date).toFixed(1)},${y(p.metrics[M.k]).toFixed(1)}`).join("")}" fill="none" stroke="${col}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>`;
    for (const p of pts) svg += `<circle cx="${x(p.date).toFixed(1)}" cy="${y(p.metrics[M.k]).toFixed(1)}" r="4" fill="${col}" stroke="var(--surface)" stroke-width="2"/>`;
    const last = pts[pts.length - 1];
    ends.push({ y: y(last.metrics[M.k]), x: x(last.date), name: nameOf[c] || c });
  }
  // 线尾标注频道名（避免互相压住）；超过 4 条线时只靠上面的图例，标注会挤成一团
  if (ends.length > 4) ends.length = 0;
  ends.sort((a, b) => a.y - b.y);
  for (let i = 1; i < ends.length; i++) if (ends[i].y - ends[i - 1].y < 13) ends[i].y = ends[i - 1].y + 13;
  for (const e of ends) svg += `<text class="lbl" x="${e.x + 8}" y="${e.y + 4}">${esc(e.name)}</text>`;
  svg += `<line class="cross" id="stCross" x1="0" x2="0" y1="${T}" y2="${H - B}" style="display:none"/><rect x="${L}" y="${T}" width="${W - L - R}" height="${H - T - B}" fill="transparent" id="stHit"/></svg><div class="st-tip" id="stTip"></div>`;
  box.innerHTML = svg;
  const svgEl = box.querySelector("svg"), tip = $("stTip"), cross = $("stCross");
  $("stHit").onmousemove = (ev) => {
    const r = svgEl.getBoundingClientRect();
    const px = ((ev.clientX - r.left) / r.width) * W;
    const d = dates.reduce((a, b) => (Math.abs(x(b) - px) < Math.abs(x(a) - px) ? b : a));
    const items = data.filter((p) => p.date === d).sort((a, b) => b.metrics[M.k] - a.metrics[M.k]);
    cross.setAttribute("x1", x(d)); cross.setAttribute("x2", x(d)); cross.style.display = "";
    tip.innerHTML = `<b>${esc(d)}</b><br>` + items.map((p) => `<i style="background:${colorOf(p.channel)}"></i>${esc(nameOf[p.channel] || p.channel)}（${esc(FORMAT_NAME[p.format] || p.format)}）：<b>${esc(M.fmt(p.metrics[M.k]))}</b><br><span class="muted">${esc(String(p.title).replace(/^.+?｜/, ""))}</span>`).join("<br>");
    tip.style.display = "block";
    const left = ((x(d) / W) * r.width) + 12;
    tip.style.left = Math.min(left, r.width - tip.offsetWidth - 4) + "px";
    tip.style.top = "8px";
  };
  $("stHit").onmouseleave = () => { tip.style.display = "none"; cross.style.display = "none"; };
}

function niceMax(v) {
  if (v <= 0) return 10;
  const p = Math.pow(10, Math.floor(Math.log10(v)));
  for (const m of [1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10]) if (m * p >= v) return m * p;
  return 10 * p;
}

const avg = (xs) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null);
function aggTable(groups, label) {
  const cols = METRICS.map((m) => `<th class="n">${esc(m.name)}（均）</th>`).join("");
  return `<table class="st-tbl"><tr><th>${label}</th><th class="n">期数</th>${cols}</tr>` + groups.map(([name, rs]) =>
    `<tr><td>${esc(name)}</td><td class="n">${rs.length}</td>` + METRICS.map((m) => { const v = avg(rs.map((r) => (r.metrics || {})[m.k]).filter((x) => x != null)); return `<td class="n">${v == null ? "—" : esc(m.fmt(v))}</td>`; }).join("") + "</tr>").join("") + "</table>";
}
function summary(rs, chans, nameOf) {
  $("stSummary").innerHTML = aggTable(chans.map((c) => [nameOf[c] || c, rs.filter((r) => r.channel === c)]), "频道");
  const fm = [...new Set(rs.map((r) => r.format))];
  const pairs = [];
  for (const c of chans) for (const f of fm) { const g = rs.filter((r) => r.channel === c && r.format === f); if (g.length) pairs.push([`${nameOf[c] || c} · ${FORMAT_NAME[f] || f}`, g]); }
  $("stFormats").innerHTML = aggTable(fm.map((f) => [FORMAT_NAME[f] || f, rs.filter((r) => r.format === f)]), "形式") +
    `<p class="muted" style="margin:10px 0 0">频道 × 形式（每组期数少于 3 时，差异多半是偶然）</p>` + aggTable(pairs, "组合");
}
function table(rs) {
  const sorted = [...rs].sort((a, b) => b.date.localeCompare(a.date));
  $("stTable").innerHTML = `<table class="st-tbl"><tr><th>日期</th><th>频道</th><th>形式</th><th>标题</th>${METRICS.map((m) => `<th class="n">${esc(m.name)}</th>`).join("")}</tr>` +
    sorted.map((r) => `<tr><td>${esc(r.date.slice(5))}</td><td>${esc(r.chName)}</td><td>${esc(FORMAT_NAME[r.format] || r.format)}</td><td class="t">${esc(String(r.title).replace(/^.+?｜/, ""))}</td>` +
      METRICS.map((m) => { const v = (r.metrics || {})[m.k]; return `<td class="n">${v == null ? "—" : esc(m.fmt(v))}</td>`; }).join("") + "</tr>").join("") + "</table>";
}

// ───── 采集开关 / 立即采集 ─────
async function initCollect() {
  const { settings = {}, statsLast } = await chrome.storage.local.get(["settings", "statsLast"]);
  $("statsOn").checked = settings.statsCollect !== false;
  showLast(statsLast);
  $("statsOn").onchange = async (e) => {
    const { settings: cur = {} } = await chrome.storage.local.get("settings");
    cur.statsCollect = e.target.checked;
    await chrome.storage.local.set({ settings: cur });
  };
  $("statsNow").onclick = async () => {
    $("statsNow").disabled = true;
    $("statsLast").textContent = "采集中…（约 1 分钟，会打开一个抖音窗口）";
    const r = await chrome.runtime.sendMessage({ type: "collectStats" }).catch((e) => ({ error: String(e) }));
    $("statsNow").disabled = false;
    showLast(r);
    if (r && !r.error) pull();
  };
}
function showLast(r) {
  if (!r) return ($("statsLast").textContent = "还没有采集过");
  $("statsLast").textContent = r.error ? `上次 ${r.time || ""}：${r.error}` : `上次 ${r.time}：${r.n ? `读到 ${r.n} 期（${r.source}）` : "没读到数据，诊断信息已写进仓库"}`;
}

// ───── 发布后自动评论 ─────
async function initComment() {
  const { settings = {} } = await chrome.storage.local.get("settings");
  $("commentOn").checked = !!settings.autoComment;
  $("commentOn").onchange = async (e) => {
    const { settings: cur = {} } = await chrome.storage.local.get("settings");
    cur.autoComment = e.target.checked;
    await chrome.storage.local.set({ settings: cur });
  };
  $("commentNow").onclick = async () => {
    if (!confirm("会以你的抖音账号，在最近发布成功的一期作品下发一条评论（本期结尾的互动问题）。确定吗？")) return;
    $("commentNow").disabled = true;
    $("commentLast").textContent = "正在发…（约半分钟，会打开一个抖音窗口）";
    const r = await chrome.runtime.sendMessage({ type: "commentNow" }).catch((e) => ({ error: String(e) }));
    $("commentNow").disabled = false;
    $("commentLast").textContent = !r ? "没有结果" : r.error ? r.error : r.ok ? (r.already ? "这期已经评论过了" : "已发出，记得去 App 里置顶") : `没发成：${r.reason}`;
  };
}
initComment();

window.addEventListener("hashchange", () => { if (location.hash === "#stats" && !loaded) pull(); });
if (location.hash === "#stats") pull();
$("stPull").onclick = pull;
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => loaded && render());
initCollect();
