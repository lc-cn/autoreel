import { DEFAULTS, PLATFORMS, EVENTS, VARS, PRESETS, DEFAULT_TEXT, newChannel, buildVars, buildRequest } from "./shared.js";
import { loadRepo, saveFiles, toJSON } from "./repo.js";

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const LETTER = { douyin: "抖", channels: "视", kuaishou: "快" };
const NOTE = { douyin: "创作者中心 creator.douyin.com", channels: "视频号助手 channels.weixin.qq.com", kuaishou: "快手创作者服务平台 cp.kuaishou.com" };
const SAMPLE = { title: "抖音已发布「热点快报」", message: "热点快报11月12日｜渤海超深层获突破", platform: "抖音", platformKey: "douyin", slot: "热点快报", videoTitle: "热点快报11月12日｜渤海超深层获突破" };
let S = null; // 正在编辑的设置
let login = {};
let dirty = false;

function toast(t) {
  const el = $("toast");
  el.textContent = t;
  el.classList.add("show");
  setTimeout(() => el.classList.remove("show"), 2000);
}
function markDirty() {
  dirty = true;
  $("saveState").textContent = "有未保存的修改";
  $("saveState").className = "state dirty";
}
const nowStamp = () => new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }).format(new Date());

// ───── 标签页 ─────
function showTab() {
  const t = (location.hash || "#basic").slice(1);
  document.querySelectorAll("nav a").forEach((a) => a.classList.toggle("on", a.dataset.tab === t));
  document.querySelectorAll(".panel").forEach((p) => p.classList.toggle("on", p.id === `p-${t}`));
  if (t === "logs") renderLogs();
  if (t === "platforms" && S) chrome.runtime.sendMessage({ type: "refreshChannels" }).catch(() => {}).then(loadAccounts).then(async () => {
    if (!dirty) S.acct = ((await chrome.storage.local.get("settings")).settings || {}).acct || {};
    renderPlatforms();
  });
  document.querySelector(".savebar").style.display = ["channels", "studio", "materials", "voices", "works"].includes(t) ? "none" : ""; // 这几页直接读写仓库，有自己的保存按钮
}
window.addEventListener("hashchange", showTab);

// ───── 读取 ─────
async function load() {
  const st = await chrome.storage.local.get(["settings", "login"]);
  const raw = st.settings || {};
  login = st.login || {};
  S = structuredClone(DEFAULTS);
  Object.assign(S, raw);
  S.platforms = { ...DEFAULTS.platforms, ...(raw.platforms || {}) };
  delete S.times; // 发布时间以仓库为准（到「频道」页修改），不再有本机覆盖
  S.browserNotify = { ...DEFAULTS.browserNotify, ...(raw.browserNotify || {}) };
  S.textTemplate = raw.textTemplate || DEFAULT_TEXT;
  S.channels = Array.isArray(raw.channels) ? raw.channels : [];
  if (!raw.channels && raw.webhook && raw.webhook.url) {
    const fmt = { wecom: "wecom", feishu: "feishu", dingtalk: "dingtalk" }[raw.webhook.format] || "generic";
    const ch = newChannel(fmt);
    Object.assign(ch, { url: raw.webhook.url, events: { ...ch.events, ...(raw.webhook.events || {}) } });
    S.channels = [ch];
  }
  $("repo").value = S.repo;
  $("token").value = S.token;
  $("ka").value = S.keepAliveHours;
  delete S.mirrors;
  delete S.mirrorMode;
  renderRoutes();
  $("auto").checked = !S.paused;
  $("autoTxt").textContent = S.paused ? "已暂停" : "已开启";
  $("textTpl").value = S.textTemplate;
  await loadAccounts();
  renderPlatforms();
  renderBrowserEvents();
  renderVars();
  renderPreview();
  renderChannels();
  markReady();
}

// ───── 平台 ─────
let ACCOUNTS = [];
function acctInfo(k) {
  const mine = ACCOUNTS.filter((a) => a.platform === k);
  const chosen = (S.acct || {})[k];
  const known = mine.filter((a) => (S.ident || {})[a.id]);
  const cur = chosen === "" ? null : chosen ? mine.find((a) => a.id === chosen) : mine.length === 1 ? mine[0] : known.length === 1 ? known[0] : null;
  return { mine, chosen, cur };
}
function identText(a, r) {
  const id = r && r.ident;
  const rec = a && (S.ident || {})[a.id];
  if (r && r.error) return `<span class="err">${esc(r.error)}</span>`;
  if (id) {
    const nm = id.nickname ? `「${esc(id.nickname)}」` : "（没读到昵称）";
    const idt = id.id ? (id.via === "cookie" ? "账号指纹已读取" : `账号 ID ${esc(id.uid || "")}`) : '<span class="err">没读到账号 ID，发布前无法核对</span>';
    const verdict = r.rebound ? '<span class="pill ok">已重新记录</span>' : r.ok === true ? '<span class="pill ok">和记录一致</span>' : r.ok === false ? '<span class="pill bad">不是记录的账号</span>' : id.id ? '<span class="pill brand">已记录</span>' : "";
    return `当前登录${nm} · ${idt} ${verdict}`;
  }
  if (rec) return `已记录：「${esc(rec.nickname || "未知昵称")}」 · ${rec.via === "cookie" ? "按账号指纹核对" : "按账号 ID 核对"} · ${esc((rec.time || "").slice(5, 16))}`;
  return "还没识别过账号；第一次发布或扫码登录时会自动记录";
}
async function loadAccounts() {
  const { channels } = await chrome.storage.local.get("channels");
  ACCOUNTS = (channels && channels.accounts) || [];
  const st = (await chrome.storage.local.get("settings")).settings || {};
  S.ident = st.ident || {};
}
function renderPlatforms() {
  const box = $("platList");
  box.innerHTML = "";
  for (const [k, P] of Object.entries(PLATFORMS)) {
    const on = !!S.platforms[k];
    const l = login[k];
    const status = !on ? '<span class="pill plain">已停用</span>' : !l ? '<span class="pill">未检查</span>' : l.ok ? '<span class="pill ok">已登录</span>' : '<span class="pill bad">登录失效</span>';
    const row = document.createElement("div");
    row.className = `plat${on ? "" : " disabled"}`;
    row.innerHTML = `<span class="badge ${k}">${LETTER[k]}</span><div class="meta"><b>${P.name}</b> ${status}<div>${NOTE[k]}${l && on ? ` · ${l.time.slice(5, 16)} 检查` : ""}</div></div>`;
    const btn = document.createElement("button");
    btn.className = "btn sm";
    btn.type = "button";
    btn.textContent = "扫码登录";
    btn.disabled = !on;
    btn.title = on ? "" : "先开启这个平台";
    btn.onclick = () => chrome.runtime.sendMessage({ type: "login", platform: k });
    const sw = document.createElement("label");
    sw.className = "switch";
    sw.innerHTML = `<input type="checkbox" ${on ? "checked" : ""} aria-label="开启${P.name}" /><span></span>`;
    sw.querySelector("input").onchange = (e) => {
      S.platforms[k] = e.target.checked;
      markDirty();
      renderPlatforms();
    };
    row.append(btn, sw);
    box.appendChild(row);
    if (on) box.appendChild(accountBox(k, P));
  }
}

// ───── 账号（在仓库 autoreel.config.json 的 accounts 里登记；新建、改名、删除直接提交到仓库）─────
function accountBox(k, P) {
  const { mine, chosen, cur } = acctInfo(k);
  const ac = document.createElement("div");
  ac.className = "acct";
  const rows = mine.map((a) => {
    const id = (S.ident || {})[a.id];
    const here = cur && cur.id === a.id;
    return `<div class="ar"><b>${esc(a.name)}</b>${here ? '<span class="pill brand plain">本机</span>' : ""}<span class="muted">${esc(a.id)}${id && id.nickname ? ` · 本机识别为「${esc(id.nickname)}」` : ""}</span>
      <span class="sp"></span><button class="btn sm ghost" type="button" data-ren="${esc(a.id)}">改名</button><button class="btn sm ghost danger" type="button" data-del="${esc(a.id)}">删除</button></div>`;
  }).join("");
  ac.innerHTML = `<div class="ah"><b>${P.name}账号</b><span class="sp"></span><button class="btn sm" type="button" data-add="${k}">＋ 添加${P.name}账号</button></div>
    ${mine.length ? rows : `<div class="muted">${ACCOUNTS.length ? `还没有${P.name}账号。` : "还没有登记账号：按旧方式，所有频道都发到这个浏览器登录的号。"}要分账号发布就点右上角添加。</div>`}
    ${mine.length ? `<div class="here"><label>这个浏览器登录的是 <select data-acct="${k}">
        ${mine.map((a) => `<option value="${esc(a.id)}" ${cur && cur.id === a.id ? "selected" : ""}>${esc(a.name)}</option>`).join("")}
        <option value="" ${chosen === "" || (!cur && mine.length !== 1) ? "selected" : ""}>不在这个浏览器发（交给别的 Chrome）</option></select></label>
      <div class="idt" data-idt="${k}">${cur ? identText(cur) : "这个浏览器不发这个平台的任何频道"}</div>
      ${cur ? `<div class="idb"><button class="btn sm" type="button" data-identify="${k}">识别账号</button><button class="btn sm ghost" type="button" data-rebind="${k}">重新识别（有意换号）</button></div>` : ""}</div>` : ""}`;
  const sel = ac.querySelector("select");
  if (sel) sel.onchange = (e) => {
    S.acct = { ...(S.acct || {}), [k]: e.target.value };
    markDirty();
    renderPlatforms();
    toast("记得点下方「保存设置」");
  };
  const run = async (rebind) => {
    if (dirty) return toast("先点「保存设置」，再识别账号");
    if (rebind && !confirm(`用这个 Chrome 当前登录的${P.name}账号，覆盖「${cur.name}」原来的记录？只有你有意换号时才这样做。`)) return;
    const el = ac.querySelector(`[data-idt="${k}"]`);
    el.textContent = "正在打开页面识别……（约 10 秒）";
    const r = await chrome.runtime.sendMessage({ type: "identify", platform: k, rebind });
    await loadAccounts();
    el.innerHTML = identText(cur, r || { error: "没有响应" });
  };
  const b1 = ac.querySelector("[data-identify]"), b2 = ac.querySelector("[data-rebind]");
  if (b1) b1.onclick = () => run(false);
  if (b2) b2.onclick = () => run(true);
  ac.querySelector("[data-add]").onclick = () => addAccount(k, P);
  ac.querySelectorAll("[data-ren]").forEach((b) => b.onclick = () => renameAccount(b.dataset.ren));
  ac.querySelectorAll("[data-del]").forEach((b) => b.onclick = () => deleteAccount(b.dataset.del));
  return ac;
}

// 读仓库 → 改 → 一次提交；之后刷新插件里的频道和账号缓存
async function repoEdit(change, message, done, after) {
  try {
    const R = await loadRepo();
    const cfg = structuredClone(R.cfg.json);
    cfg.accounts = Array.isArray(cfg.accounts) ? cfg.accounts : [];
    const chs = R.channels.filter((c) => c.json).map((c) => ({ c, json: structuredClone(c.json) }));
    const ok = change(cfg, chs);
    if (ok === false) return;
    const files = [];
    if (toJSON(cfg) !== toJSON(R.cfg.json)) files.push({ path: "autoreel.config.json", text: toJSON(cfg), sha: R.cfg.sha });
    for (const { c, json } of chs) if (toJSON(json) !== toJSON(c.json)) files.push({ path: `channels/${c.id}/channel.json`, text: toJSON(json), sha: c.file.sha });
    if (!files.length) return;
    await saveFiles(R.def, files, message);
    if (after) await after();
    await chrome.runtime.sendMessage({ type: "refreshChannels" }).catch(() => {});
    await loadAccounts();
    renderPlatforms();
    toast(done);
  } catch (e) {
    alert(`没有保存：${e.message}`);
  }
}
async function addAccount(k, P) {
  const n = ACCOUNTS.filter((a) => a.platform === k).length + 1;
  const { cur } = acctInfo(k);
  const name = (prompt(`给新的${P.name}账号起个名字（只在插件和仓库里显示，比如「${P.name}历史号」）`, `${P.name}${n === 1 ? "主号" : "账号" + n}`) || "").trim();
  if (!name) return;
  if (name.length > 16) return toast("名字最多 16 个字");
  await repoEdit((cfg, chs) => {
    if (cfg.accounts.some((a) => a.name === name)) { toast("已经有同名账号"); return false; }
    let i = n, id = `${k}_${i === 1 ? "main" : i}`;
    while (cfg.accounts.some((a) => a.id === id)) id = `${k}_${++i}`;
    // 没单独设置过的频道原本是「发往全部账号」，先固定成现有账号，新账号要在频道里勾选了才会发
    const before = cfg.accounts.map((a) => a.id);
    if (before.length) for (const x of chs) if (!Array.isArray(x.json.publish_to)) x.json.publish_to = [...before];
    cfg.accounts.push({ id, platform: k, name });
  }, `自影插件：新增账号 ${name}`, `已添加「${name}」。到「频道」页给要发到这个号的频道勾选它`, async () => {
    // 本机原来代表的账号固定下来，加了新号以后这个浏览器照常发原来的号
    if (cur && !(S.acct || {})[k]) {
      const { settings = {} } = await chrome.storage.local.get("settings");
      await chrome.storage.local.set({ settings: { ...settings, acct: { ...(settings.acct || {}), [k]: cur.id } } });
      S.acct = { ...(S.acct || {}), [k]: cur.id };
    }
  });
}
async function renameAccount(id) {
  const a = ACCOUNTS.find((x) => x.id === id);
  const name = (prompt("新名字", a ? a.name : "") || "").trim();
  if (!name || (a && name === a.name)) return;
  await repoEdit((cfg) => {
    const x = cfg.accounts.find((y) => y.id === id);
    if (!x) { toast("仓库里没有这个账号了，刷新看看"); return false; }
    x.name = name;
  }, `自影插件：账号改名为 ${name}`, "已改名");
}
async function deleteAccount(id) {
  const a = ACCOUNTS.find((x) => x.id === id);
  await repoEdit((cfg, chs) => {
    const only = chs.filter((x) => Array.isArray(x.json.publish_to) && x.json.publish_to.length === 1 && x.json.publish_to[0] === id);
    if (only.length) { alert(`这些频道只发「${a.name}」：${only.map((x) => x.json.name).join("、")}。先到「频道」页给它们换个账号，或者关掉这些频道，再删除。`); return false; }
    if (!confirm(`删除账号「${a.name}」？勾选了它的频道会去掉这个账号；登录这个号的那个 Chrome 将不再发布。`)) return false;
    cfg.accounts = cfg.accounts.filter((x) => x.id !== id);
    for (const x of chs) if (Array.isArray(x.json.publish_to)) x.json.publish_to = x.json.publish_to.filter((y) => y !== id);
  }, `自影插件：删除账号 ${a ? a.name : id}`, "已删除");
}

// ───── 浏览器通知 ─────
function renderBrowserEvents() {
  $("bnEvents").innerHTML = Object.entries(EVENTS).map(([k, e]) => `<label class="check"><input type="checkbox" data-ev="${k}" ${S.browserNotify[k] !== false ? "checked" : ""}/> ${e.emoji} ${e.name}</label>`).join("");
  $("bnEvents").querySelectorAll("input").forEach((i) => (i.onchange = () => {
    S.browserNotify[i.dataset.ev] = i.checked;
    markDirty();
  }));
}

// ───── 模板变量 ─────
let lastFocus = null;
document.addEventListener("focusin", (e) => {
  if (e.target.matches("textarea, input[type=url], input[type=text]")) lastFocus = e.target;
});
function insertVar(name) {
  const el = lastFocus && lastFocus.isConnected ? lastFocus : $("textTpl");
  const tok = `{{${name}}}`;
  const a = el.selectionStart ?? el.value.length, b = el.selectionEnd ?? el.value.length;
  el.value = el.value.slice(0, a) + tok + el.value.slice(b);
  el.focus();
  el.selectionStart = el.selectionEnd = a + tok.length;
  el.dispatchEvent(new Event("input", { bubbles: true }));
}
function renderVars() {
  $("varChips").innerHTML = VARS.filter(([k]) => k !== "text").map(([k, d]) => `<button class="var" type="button" title="${esc(d)}" data-v="${k}">{{${k}}}</button>`).join("");
  $("varChips").querySelectorAll(".var").forEach((b) => (b.onclick = () => insertVar(b.dataset.v)));
  $("varTable").innerHTML = VARS.map(([k, d]) => `<tr><td>{{${k}}}</td><td>${esc(d)}</td></tr>`).join("");
}
function renderPreview() {
  const v = buildVars("published", SAMPLE, S.textTemplate, nowStamp());
  $("textPreview").textContent = v.text;
}
$("textTpl").addEventListener("input", (e) => {
  S.textTemplate = e.target.value;
  markDirty();
  renderPreview();
  document.querySelectorAll(".ch.open").forEach((c) => c._preview && c._preview());
});

// ───── 推送渠道 ─────
function renderChannels() {
  const box = $("chList");
  box.innerHTML = "";
  if (!S.channels.length) box.innerHTML = '<div class="muted" style="margin-top:10px">还没有推送渠道。在下面选择一种类型添加。</div>';
  S.channels.forEach((ch, idx) => box.appendChild(channelCard(ch, idx)));
}
function channelCard(ch, idx) {
  const el = document.createElement("div");
  el.className = "ch";
  const preset = PRESETS[ch.preset] || PRESETS.generic;
  el.innerHTML = `
    <div class="ch-h">
      <label class="switch" title="启用 / 停用"><input type="checkbox" class="en" ${ch.enabled ? "checked" : ""} /><span></span></label>
      <span class="nm">${esc(ch.name)}</span><span class="tp">${ch.name === preset.label ? "" : esc(preset.label)}</span><span class="sp"></span>
      <button class="btn sm test" type="button">发送测试</button>
      <button class="btn sm ghost tog" type="button">编辑</button>
    </div>
    <div class="ch-b">
      ${preset.tip ? `<div class="help muted" style="margin-top:10px">💡 ${esc(preset.tip)}</div>` : ""}
      <div class="grid2">
        <label class="field"><span class="label">名称</span><input type="text" data-k="name" value="${esc(ch.name)}" /></label>
        <label class="field"><span class="label">推送事件</span><span class="evs">${Object.entries(EVENTS).map(([k, e]) => `<label class="check"><input type="checkbox" data-ev="${k}" ${ch.events[k] ? "checked" : ""}/> ${e.name}</label>`).join("")}</span></label>
      </div>
      <label class="field"><span class="label">地址</span><input type="url" data-k="url" value="${esc(ch.url)}" /></label>
      <div class="grid2">
        <label class="field"><span class="label">请求方式</span><select data-k="method"><option>POST</option><option>PUT</option><option>GET</option></select></label>
        <label class="field"><span class="label">内容类型</span><select data-k="contentType"><option value="json">JSON</option><option value="form">表单（x-www-form-urlencoded）</option><option value="text">纯文本</option></select></label>
      </div>
      <label class="field"><span class="label">请求头（JSON，可留空）</span><textarea data-k="headers" rows="2" placeholder='{"Authorization": "Bearer xxx"}'>${esc(ch.headers)}</textarea></label>
      <label class="field"><span class="label">消息体模板</span><textarea data-k="body" rows="5">${esc(ch.body)}</textarea></label>
      <div class="vars">${VARS.map(([k, d]) => `<button class="var" type="button" title="${esc(d)}" data-v="${k}">{{${k}}}</button>`).join("")}</div>
      <label class="field"><span class="label">预览（示例事件：发布成功）</span><div class="preview pv"></div></label>
      <div class="err"></div><div class="res"></div>
      <div style="display:flex;gap:8px;margin-top:12px"><button class="btn sm danger del" type="button">删除此渠道</button></div>
    </div>`;
  el.querySelector('[data-k="method"]').value = ch.method || "POST";
  el.querySelector('[data-k="contentType"]').value = ch.contentType || "json";
  const preview = () => {
    const vars = buildVars("published", SAMPLE, S.textTemplate, nowStamp());
    try {
      const r = buildRequest(ch, vars);
      el.querySelector(".pv").textContent = `${r.method} ${r.url}\n${Object.entries(r.headers).map(([a, b]) => `${a}: ${b}`).join("\n")}${r.body ? `\n\n${r.body}` : ""}`;
      el.querySelector(".err").textContent = "";
    } catch (e) {
      el.querySelector(".pv").textContent = "";
      el.querySelector(".err").textContent = `模板有误：${e.message}（JSON 里的变量要写在引号内，例如 "{{text}}"）`;
    }
  };
  el._preview = preview;
  el.querySelector(".ch-h").onclick = (e) => {
    if (e.target.closest(".switch, .test")) return;
    el.classList.toggle("open");
    el.querySelector(".tog").textContent = el.classList.contains("open") ? "收起" : "编辑";
    if (el.classList.contains("open")) preview();
  };
  el.querySelector(".en").onchange = (e) => {
    ch.enabled = e.target.checked;
    markDirty();
  };
  el.querySelectorAll("[data-k]").forEach((inp) => inp.addEventListener("input", () => {
    ch[inp.dataset.k] = inp.value;
    if (inp.dataset.k === "name") el.querySelector(".nm").textContent = inp.value;
    markDirty();
    preview();
  }));
  el.querySelectorAll("[data-ev]").forEach((i) => (i.onchange = () => {
    ch.events[i.dataset.ev] = i.checked;
    markDirty();
  }));
  el.querySelectorAll(".var").forEach((b) => (b.onclick = () => insertVar(b.dataset.v)));
  el.querySelector(".del").onclick = () => {
    if (!confirm(`删除推送渠道「${ch.name}」？`)) return;
    S.channels.splice(idx, 1);
    markDirty();
    renderChannels();
  };
  el.querySelector(".test").onclick = async () => {
    const res = el.querySelector(".res");
    if (!(await grant([ch]))) return (res.textContent = "没有授权访问该地址，无法发送");
    res.textContent = "发送中…";
    const r = await chrome.runtime.sendMessage({ type: "testChannel", channel: ch, textTemplate: S.textTemplate });
    res.innerHTML = r && r.ok ? `<span class="pill ok">发送成功</span> <span class="muted">${esc((r.text || "").slice(0, 160))}</span>` : `<span class="pill bad">发送失败${r && r.status ? ` · HTTP ${r.status}` : ""}</span> <span class="muted">${esc((r && r.text) || "")}</span>`;
    if (!el.classList.contains("open")) el.querySelector(".ch-h").click();
  };
  return el;
}
$("presetSel").innerHTML = Object.entries(PRESETS).map(([k, p]) => `<option value="${k}">${esc(p.label)}</option>`).join("");
$("addCh").onclick = () => {
  const ch = newChannel($("presetSel").value);
  S.channels.push(ch);
  markDirty();
  renderChannels();
  const cards = document.querySelectorAll(".ch");
  cards[cards.length - 1].querySelector(".ch-h").click();
};

// ───── 下载线路 ─────
const ROUTES = [["direct_auth", "直连 GitHub（令牌认证）", "支持断点续传"], ["api", "GitHub API", "不支持续传，速度通常更快"]];
async function renderRoutes() {
  const { routeTest, routeRank = {} } = await chrome.storage.local.get(["routeTest", "routeRank"]);
  const res = Object.fromEntries(((routeTest && routeTest.results) || []).map((x) => [x.key, x]));
  const order = ROUTES.slice().sort((a, b) => (routeRank[b[0]] ?? 0) - (routeRank[a[0]] ?? 0)).map((r) => r[0]);
  $("routeList").innerHTML = ROUTES.map(([k, t, n]) => {
    const r = res[k];
    const pill = !r ? '<span class="pill">未测速</span>' : r.ok ? `<span class="pill ok">${r.speed}</span>` : `<span class="pill bad">不可用</span><span class="muted" style="font-size:12px">${esc(r.error)}</span>`;
    const first = routeTest && order[0] === k && r && r.ok ? '<span class="pill brand plain">优先使用</span>' : "";
    return `<div class="mopt" style="cursor:default"><span><span class="t">${t}</span> <span class="n">${n}</span></span><span class="r">${first}${pill}</span></div>`;
  }).join("");
  $("routeTestAt").textContent = routeTest ? `上次测速：${routeTest.at.slice(5, 16)}` : "还没有测过速，建议测一次";
}
$("testRoutes").onclick = async () => {
  await saveRepoToken();
  $("routeTestAt").textContent = "测速中，每条线路最多 60 秒…";
  const r = await chrome.runtime.sendMessage({ type: "testRoutes" });
  if (!r || r.error) {
    await renderRoutes();
    return toast((r && r.error) || "测速失败");
  }
  await renderRoutes();
  toast(r.results.some((x) => x.ok) ? "测速完成，插件会优先用更合适的线路" : "两条线路都不可用，请把测速结果截图发给 Claude");
};

// ───── 备份与迁移 ─────
$("exportCfg").onclick = async () => {
  const { settings = {} } = await chrome.storage.local.get("settings");
  const out = { ...settings, _kuaibao: 1 };
  if (!$("exportTok").checked) delete out.token;
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([JSON.stringify(out, null, 2)], { type: "application/json" }));
  a.download = `AutoReel-设置-${nowStamp().slice(0, 10)}.json`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
};
$("importCfg").onclick = () => $("importFile").click();
$("importFile").onchange = async (e) => {
  const f = e.target.files[0];
  if (!f) return;
  try {
    const cfg = JSON.parse(await f.text());
    if (!cfg._kuaibao) throw new Error("不是本插件导出的设置文件");
    delete cfg._kuaibao;
    const { settings = {} } = await chrome.storage.local.get("settings");
    if (!cfg.token) cfg.token = settings.token || ""; // 文件里没有令牌就保留现在的
    await chrome.storage.local.set({ settings: cfg });
    await load();
    toast("设置已导入；推送渠道第一次发送前可能需要重新授权地址");
  } catch (err) {
    toast(`导入失败：${err.message}`);
  }
  e.target.value = "";
};

// 推送地址需要逐个授权（浏览器会弹窗确认一次）
async function grant(chs, extra = []) {
  const origins = [...new Set(chs.filter((c) => c.enabled !== false && /^https?:\/\//.test(c.url)).map((c) => {
    try {
      return new URL(c.url.replace(/\{\{[^}]+\}\}/g, "x")).origin + "/*";
    } catch (_) {
      return null;
    }
  }).filter(Boolean)), ...extra];
  if (!origins.length) return true;
  return chrome.permissions.request({ origins });
}

// ───── 基本设置输入 ─────
["ka"].forEach((id) => $(id).addEventListener("input", markDirty));
$("auto").onchange = () => {
  $("autoTxt").textContent = $("auto").checked ? "已开启" : "已暂停";
  markDirty();
};
// ───── 仓库和令牌：填完就自动保存（不用先点「保存设置」，测速、频道页就能用）─────
const normRepo = (v) => v.trim().replace(/^https:\/\/github\.com\//, "").replace(/\.git$/, "").replace(/\/$/, "");
let markReady;
const ready = new Promise((r) => (markReady = r)); // 设置页把已保存的值填进输入框之后才允许自动保存
async function saveRepoToken() {
  await ready;
  const repo = normRepo($("repo").value), token = $("token").value.trim();
  const { settings = {} } = await chrome.storage.local.get("settings");
  if (!repo || !token) return false; // 只在两项都填了时自动保存，绝不用空值覆盖
  if (settings.repo === repo && settings.token === token) return false;
  await chrome.storage.local.set({ settings: { ...settings, repo, token } });
  if (S) Object.assign(S, { repo, token });
  $("repo").value = repo;
  return true;
}
window.__saveRepoToken = saveRepoToken; // 频道页拉取前也会调用
for (const id of ["repo", "token"]) {
  $(id).addEventListener("change", async () => {
    if (await saveRepoToken()) {
      toast("仓库和令牌已保存");
      if ($("repo").value && $("token").value) chrome.runtime.sendMessage({ type: "refreshChannels" }).catch(() => {});
    }
  });
}
// 生成令牌：打开 GitHub 的细粒度令牌页面，预填名称、说明、有效期和 Contents 读写权限
$("genTok").onclick = () => {
  const repo = normRepo($("repo").value);
  const owner = repo.includes("/") ? repo.split("/")[0] : "";
  const q = new URLSearchParams({
    name: `自影 AutoReel${repo ? " · " + repo.split("/")[1] : ""}`.slice(0, 40),
    description: `自影 AutoReel 浏览器插件读写中转仓库${repo ? " " + repo : ""} 用。Repository access 请选 Only select repositories，只勾选这个仓库。`,
    expires_in: "366",
    contents: "write",
  });
  if (owner) q.set("target_name", owner);
  chrome.tabs.create({ url: `https://github.com/settings/personal-access-tokens/new?${q}` });
  toast(repo ? `在打开的页面里：Repository access 选「Only select repositories」，勾选 ${repo}，再点 Generate token` : "先填好仓库，生成的令牌可以只给这个仓库用");
};

$("showTok").onclick = () => {
  const t = $("token");
  t.type = t.type === "password" ? "text" : "password";
  $("showTok").textContent = t.type === "password" ? "显示" : "隐藏";
};

// ───── 保存 ─────
$("save").onclick = async () => {
  for (const ch of S.channels) {
    try {
      buildRequest(ch, buildVars("published", SAMPLE, S.textTemplate, nowStamp()));
    } catch (e) {
      location.hash = "#notify";
      return toast(`渠道「${ch.name}」的模板有误，请检查`);
    }
  }
  if (!(await grant(S.channels))) toast("部分推送地址没有授权，这些渠道将无法发送");
  S.repo = normRepo($("repo").value);
  S.token = $("token").value.trim();

  S.keepAliveHours = Math.max(1, Math.min(24, parseInt($("ka").value, 10) || 6));
  S.paused = !$("auto").checked;
  const out = { ...S };
  delete out.webhook; // 旧版字段，已迁移为推送渠道
  out.ident = ((await chrome.storage.local.get("settings")).settings || {}).ident || {}; // 账号记录由后台维护，以存储里最新的为准
  await chrome.storage.local.set({ settings: out });
  dirty = false;
  $("saveState").textContent = `已保存 · ${nowStamp().slice(11, 16)}`;
  $("saveState").className = "state";
  toast("设置已保存");
};
window.addEventListener("beforeunload", (e) => {
  if (dirty) e.preventDefault();
});

// ───── 日志 ─────
async function renderLogs() {
  const { logs = [] } = await chrome.storage.local.get("logs");
  $("logAll").textContent = logs.slice().reverse().join("\n") || "暂无日志";
}
$("copyLog").onclick = async () => {
  const { logs = [] } = await chrome.storage.local.get("logs");
  await navigator.clipboard.writeText(logs.slice(-200).join("\n"));
  toast("已复制最近 200 行，可以直接发给 Claude");
};
$("clearLog").onclick = async () => {
  if (!confirm("清空运行日志？")) return;
  await chrome.storage.local.set({ logs: [] });
  renderLogs();
};
chrome.storage.onChanged.addListener(async (c) => {
  if (c.login) {
    login = c.login.newValue || {};
    if (S) renderPlatforms();
  }
  if ((c.channels || c.settings) && S) { // 频道页保存了账号、后台记录了账号身份 → 刷新「发布平台」
    await loadAccounts();
    if (c.settings && !dirty) S.acct = (c.settings.newValue || {}).acct || {}; // 没有未保存的修改时，跟存储保持一致
    renderPlatforms();
  }
  if (c.logs && location.hash === "#logs") renderLogs();
});

await load();
showTab();
