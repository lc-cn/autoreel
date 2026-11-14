// 自影 · 多平台自动发布 —— 后台（调度、GitHub、通知、登录、保活）
// 流程：每 5 分钟检查一次 → 到点的栏目从 GitHub 中转仓库下载视频 → 依次在抖音、视频号、快手的上传页里自动填写发布
//      → 结果写回仓库 status.json，并按设置发浏览器通知 / Webhook。

import { PLATFORMS, ORDER, channelTag, MAX_ATTEMPTS, JOB_TIMEOUT_MS, CHUNK, DEFAULTS, PRESETS, newChannel, buildVars, buildRequest } from "./shared.js";

// ───────── 存储 / 日志 ─────────
async function getSettings() {
  const { settings } = await chrome.storage.local.get("settings");
  const s = structuredClone(DEFAULTS);
  if (settings) {
    Object.assign(s, settings);
    s.platforms = { ...DEFAULTS.platforms, ...(settings.platforms || {}) };
    s.times = {}; // 发布时间以仓库里各频道的 schedule.publish 为准（在设置页「频道」里改），旧版的本机覆盖不再生效
    s.browserNotify = { ...DEFAULTS.browserNotify, ...(settings.browserNotify || {}) };
    s.channels = Array.isArray(settings.channels) ? settings.channels : [];

    // 旧版单个 Webhook 设置迁移为一个推送渠道
    if (settings.webhook && settings.webhook.url && !settings.channels) {
      const fmt = { wecom: "wecom", feishu: "feishu", dingtalk: "dingtalk" }[settings.webhook.format] || "generic";
      const ch = newChannel(fmt);
      Object.assign(ch, { url: settings.webhook.url, events: { ...ch.events, ...(settings.webhook.events || {}) } });
      s.channels = [ch];
    }
  }
  return s;
}
async function getState() {
  const { state } = await chrome.storage.local.get("state");
  return state || {};
}
async function saveState(state) {
  // 只保留最近 10 天
  const days = Object.keys(state).sort();
  while (days.length > 10) delete state[days.shift()];
  await chrome.storage.local.set({ state });
}
async function log(msg) {
  const line = `[${beijing().stamp}] ${msg}`;
  console.log(line);
  const { logs = [] } = await chrome.storage.local.get("logs");
  logs.push(line);
  await chrome.storage.local.set({ logs: logs.slice(-400) });
}
function beijing(d = new Date()) {
  const f = new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
  const s = f.format(d); // 2026-11-12 19:05:03
  return { date: s.slice(0, 10), hm: s.slice(11, 16), stamp: s };
}

// ───────── 通知：浏览器 + 推送渠道 ─────────
const NOTE_TARGET = {}; // notificationId -> {tabId, windowId} 或 {login: platform}
// info: {platform(key), slot(名称), videoTitle}
async function notify(kind, title, message, target, info = {}) {
  const s = await getSettings();
  if (s.browserNotify[kind] !== false) {
    const id = `ac-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
    const opts = { type: "basic", iconUrl: "icons/128.png", title, message: message.slice(0, 250), priority: 2, requireInteraction: kind === "verify" || kind === "login" };
    if (target) {
      opts.buttons = [{ title: target.login ? "扫码登录" : "去处理" }];
      NOTE_TARGET[id] = target;
    }
    chrome.notifications.create(id, opts);
  }
  const vars = buildVars(kind, { title, message, platform: PLATFORMS[info.platform]?.name || "", platformKey: info.platform || "", slot: info.slot || "", videoTitle: info.videoTitle || "" }, s.textTemplate, beijing().stamp);
  for (const ch of s.channels) if (ch.enabled && ch.events && ch.events[kind]) await sendChannel(ch, vars);
}
async function sendChannel(ch, vars) {
  try {
    const req = buildRequest(ch, vars);
    const r = await fetch(req.url, { method: req.method, headers: req.headers, body: req.body });
    const text = (await r.text()).slice(0, 300);
    if (!r.ok) await log(`推送「${ch.name}」返回 HTTP ${r.status}：${text}`);
    return { ok: r.ok, status: r.status, text };
  } catch (e) {
    await log(`推送「${ch.name}」失败：${e.message || e}`);
    return { ok: false, text: String(e.message || e) };
  }
}
chrome.notifications.onButtonClicked.addListener((id) => openTarget(id));
chrome.notifications.onClicked.addListener((id) => openTarget(id));
async function openTarget(id) {
  const t = NOTE_TARGET[id];
  if (!t) return;
  if (t.login) return startLogin(t.login);
  try {
    await chrome.windows.update(t.windowId, { focused: true, state: "normal" });
    await chrome.tabs.update(t.tabId, { active: true });
  } catch (_) {}
}

// ───────── GitHub 中转仓库 ─────────
async function gh(path, { method = "GET", body, accept = "application/vnd.github+json" } = {}) {
  const s = await getSettings();
  if (!s.repo) throw new Error("还没有在设置里填写 GitHub 仓库");
  if (!s.token) throw new Error("还没有在设置里填写 GitHub 令牌");
  const r = await fetch(`https://api.github.com/repos/${s.repo}/${path}`, {
    method,
    headers: { Authorization: `Bearer ${s.token}`, Accept: accept, "X-GitHub-Api-Version": "2022-11-28", ...(body ? { "Content-Type": "application/json" } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) {
    const e = new Error(`GitHub ${method} ${path} → HTTP ${r.status}`);
    e.status = r.status;
    throw e;
  }
  return r;
}
async function readStatus(tag) {
  try {
    const j = await (await gh(`contents/status.json?ref=${tag}`)).json();
    const txt = new TextDecoder().decode(Uint8Array.from(atob(j.content.replace(/\n/g, "")), (c) => c.charCodeAt(0)));
    return { sha: j.sha, doc: JSON.parse(txt) };
  } catch (_) {
    return { sha: null, doc: null };
  }
}
async function writeStatus(tag, platform, status, detail = "", attempts = 0, key = platform, info = {}) {
  // status.json：顶层 status 保持与旧版一致（以抖音为准），platforms 按账号记录（key 是账号 id；没配账号时是平台名）
  for (let i = 0; i < 3; i++) {
    const { sha, doc } = await readStatus(tag);
    const d = doc || {};
    d.platforms = d.platforms || {};
    if (d.status === "published" && !Object.keys(d.platforms).length) d.platforms.douyin = { status: "published", time: d.time };
    d.platforms[key] = { platform, status, detail: String(detail).slice(-400), attempts, time: beijing().stamp, ...info };
    if (platform === "douyin" || !d.status) Object.assign(d, { status, detail: String(detail).slice(-400), attempts, time: beijing().stamp });
    const content = btoa(String.fromCharCode(...new TextEncoder().encode(JSON.stringify(d, null, 1))));
    try {
      await gh("contents/status.json", { method: "PUT", body: { message: `status: ${platform} ${status}`, branch: tag, content, ...(sha ? { sha } : {}) } });
      await chrome.storage.local.set({ writeDenied: null });
      return;
    } catch (e) {
      if (e.status === 403 || e.status === 404) {
        // 令牌没有写权限：发布不受影响，但云端看不到发布结果、旧分支也清理不了
        await chrome.storage.local.set({ writeDenied: beijing().stamp });
        return log(`写回状态失败：令牌没有仓库写权限（HTTP ${e.status}）。请把令牌的 Contents 权限改成 Read and write`);
      }
      if (e.status !== 409 && e.status !== 422) return log(`写回状态失败（不影响发布）：${e.message}`);
    }
  }
}
async function cleanup(today) {
  // 只删除「clip-日期-频道」格式、并且超过 7 天的分支；其他任何分支（默认分支、你自己的分支）一律不碰
  const cutoff = new Date(Date.parse(today) - 7 * 864e5).toISOString().slice(0, 10);
  try {
    const heads = await (await gh("git/matching-refs/heads/clip-")).json();
    for (const h of heads) {
      const name = h.ref.replace(/^refs\/heads\//, "");
      const m = name.match(/^clip-(\d{4}-\d{2}-\d{2})-[a-z0-9_]+$/);
      if (!m || m[1] >= cutoff) continue;
      try {
        await gh(`git/refs/heads/${name}`, { method: "DELETE" });
        await log(`已删除旧分支 ${name}`);
      } catch (e) {
        await log(`删除 ${name} 失败：${e.message}`);
      }
    }
  } catch (e) {
    await log(`清理旧分支失败：${e.message}`);
  }
}

// ───────── 视频缓存（IndexedDB）─────────
function idb() {
  return new Promise((res, rej) => {
    const r = indexedDB.open("kb", 1);
    r.onupgradeneeded = () => r.result.createObjectStore("files");
    r.onsuccess = () => res(r.result);
    r.onerror = () => rej(r.error);
  });
}
async function idbPut(key, val) {
  const db = await idb();
  await new Promise((res, rej) => {
    const t = db.transaction("files", "readwrite");
    t.objectStore("files").put(val, key);
    t.oncomplete = res;
    t.onerror = () => rej(t.error);
  });
}
async function idbGet(key) {
  const db = await idb();
  return new Promise((res, rej) => {
    const r = db.transaction("files").objectStore("files").get(key);
    r.onsuccess = () => res(r.result);
    r.onerror = () => rej(r.error);
  });
}
async function idbPrune(keep) {
  const db = await idb();
  const keys = await new Promise((res) => {
    const r = db.transaction("files").objectStore("files").getAllKeys();
    r.onsuccess = () => res(r.result);
  });
  const t = db.transaction("files", "readwrite");
  for (const k of keys) if (!keep.some((p) => String(k).startsWith(p))) t.objectStore("files").delete(k);
}
// 下载线路：设置里的镜像（按顺序）→ 直连 GitHub。镜像写法是"前缀"，后面直接拼原始下载地址。
// 下载线路：直连 GitHub（令牌认证，支持续传）和 GitHub API（不支持续传）。
// 按测速结果排序：可用的按速度排前面（不支持续传的降权），测速失败的跳过（只要还有可用线路）。
function buildRoutes(url, rank = {}, { forTest = false } = {}) {
  const list = [];
  if (url) list.push({ key: "direct_auth", name: "直连 GitHub（令牌认证）", url: url.split("?")[0], auth: true });
  list.push({ key: "api", name: "GitHub API", api: true });
  if (forTest) return list;
  const score = (r) => (rank[r.key] == null ? 0 : rank[r.key]);
  let out = list.sort((a, b) => score(b) - score(a));
  if (out.some((r) => score(r) > 0)) out = out.filter((r) => score(r) >= 0);
  return out;
}
async function openRoute(route, tag, item, got, token) {
  if (route.api) return gh(`contents/${item.name}?ref=${tag}`, { accept: "application/vnd.github.raw" });
  const headers = got ? { Range: `bytes=${got}-` } : {};
  if (route.auth) headers.Authorization = `token ${token}`; // 令牌只发给 GitHub，不会发给镜像
  return fetch(route.url, { headers, cache: "no-store" });
}
// 断点续传下载：从国内连 GitHub 下载大文件经常中途断线。
// 用文件的直接下载地址（raw.githubusercontent.com，支持 Range），断了从已下载的位置接着下，并换下一条线路；
// 6 次都失败时把已下载部分存起来，下次检查（5 分钟后）继续。
async function downloadResumable(tag, item) {
  const { routeRank = {} } = await chrome.storage.local.get("routeRank");
  const settings = await getSettings();
  const total = item.size;
  const partial = await idbGet(`${tag}:partial`);
  const parts = partial ? [new Uint8Array(partial)] : [];
  let got = partial ? partial.byteLength : 0;
  if (got) await log(`接着上次的进度继续下载（已有 ${(got / 1048576).toFixed(1)}MB）`);
  let lastMark = Math.floor((got / total) * 4);
  const maxAttempts = 6;
  for (let attempt = 1; attempt <= maxAttempts && got < total; attempt++) {
    try {
      // 每次重新取一次下载地址（私有仓库的地址带临时令牌，会过期）
      const fresh = (await (await gh(`contents?ref=${tag}`)).json()).find((a) => a.name === item.name) || item;
      const rs = buildRoutes(fresh.download_url, routeRank);
      const route = rs[(attempt - 1) % rs.length];
      await log(`下载线路：${route.name}${got ? `（从 ${(got / 1048576).toFixed(1)}MB 处续传）` : ""}`);
      const r = await openRoute(route, tag, item, got, settings.token);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      if (got && r.status === 206) {
        // 续传的这一段必须正好从已下载的位置开始，否则丢弃，换线路
        const m = (r.headers.get("content-range") || "").match(/bytes\s+(\d+)-/);
        if (!m || +m[1] !== got) throw new Error("该线路续传返回的位置不对");
      } else if (got && r.status !== 206) {
        parts.length = 0; // 服务器不支持续传，只能从头下
        got = 0;
      }
      const reader = r.body.getReader();
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        parts.push(value);
        got += value.byteLength;
        const mark = Math.floor((got / total) * 4);
        if (mark > lastMark && mark < 4) {
          lastMark = mark;
          const { running } = await chrome.storage.session.get("running");
          if (running) await setRunning({ ...running, stage: `下载视频 ${mark * 25}%` });
          await log(`下载进度 ${mark * 25}%（${(got / 1048576).toFixed(1)}/${(total / 1048576).toFixed(1)}MB）`);
        }
      }
    } catch (e) {
      await log(`下载中断（第 ${attempt} 次，已下 ${(got / 1048576).toFixed(1)}MB）：${e.message || e}，${attempt < maxAttempts ? "换下一条线路接着下" : "下次检查时继续"}`);
      if (attempt < maxAttempts) await new Promise((r) => setTimeout(r, 2000));
    }
  }
  const buf = new Uint8Array(got);
  let off = 0;
  for (const p of parts) {
    buf.set(p, off);
    off += p.byteLength;
  }
  if (got < total) {
    await idbPut(`${tag}:partial`, buf.buffer);
    throw new Error(`视频下载未完成（${(got / 1048576).toFixed(1)}/${(total / 1048576).toFixed(1)}MB），5 分钟后自动继续`);
  }
  await idbPut(`${tag}:partial`, null);
  return buf.buffer;
}
async function fetchPackage(tag) {
  // 返回 {meta, size}；视频存在 IndexedDB 的 `${tag}:video`
  const cached = await idbGet(`${tag}:meta`);
  if (cached && (await idbGet(`${tag}:video`))) return cached;
  const listing = await (await gh(`contents?ref=${tag}`)).json();
  const names = Object.fromEntries(listing.filter((a) => a.type === "file").map((a) => [a.name, a]));
  if (!names["video.mp4"] || !names["meta.json"]) throw new Error(`分支 ${tag} 缺少 video.mp4 或 meta.json`);
  const meta = await (await gh(`contents/meta.json?ref=${tag}`, { accept: "application/vnd.github.raw" })).json();
  const video = await downloadResumable(tag, names["video.mp4"]);
  await idbPut(`${tag}:video`, video);
  const pkg = { meta, size: video.byteLength };
  await idbPut(`${tag}:meta`, pkg);
  await log(`已下载 ${tag}：${(video.byteLength / 1048576).toFixed(1)}MB · ${meta.title}`);
  return pkg;
}
async function branchExists(tag) {
  try {
    await gh(`branches/${tag}`);
    return true;
  } catch (e) {
    if (e.status === 404) return false;
    throw e;
  }
}

// ───────── 自动化窗口 / 标签页 ─────────
async function workWindow() {
  const { workWin } = await chrome.storage.session.get("workWin");
  if (workWin) {
    try {
      await chrome.windows.get(workWin);
      return workWin;
    } catch (_) {}
  }
  const w = await chrome.windows.create({ url: "about:blank", focused: false, width: 1280, height: 900, state: "normal" });
  await chrome.storage.session.set({ workWin: w.id });
  return w.id;
}
const waiters = {}; // tabId -> {onReady, onResult, onSubmitted}
function waitTab(tabId, kind, ms) {
  return new Promise((resolve) => {
    const timer = setTimeout(() => resolve({ timeout: true }), ms);
    waiters[tabId] = waiters[tabId] || {};
    waiters[tabId][kind] = (v) => {
      clearTimeout(timer);
      delete waiters[tabId][kind];
      resolve(v);
    };
  });
}
// 只有插件自己打开的任务标签页才会执行自动操作；你平时手动打开平台后台不受影响
async function openPlatformTab(p, url) {
  const windowId = await workWindow();
  const tab = await chrome.tabs.create({ windowId, url: "about:blank", active: true });
  const { workTabs = [] } = await chrome.storage.session.get("workTabs");
  await chrome.storage.session.set({ workTabs: [...workTabs.slice(-20), tab.id] });
  await chrome.tabs.update(tab.id, { url });
  // 偶尔（例如插件刚安装、同时打开设置页时）导航会被吞掉：5 秒后还停在空白页就再导航一次
  setTimeout(async () => {
    try {
      const t = await chrome.tabs.get(tab.id);
      if (!t.url || t.url === "about:blank") await chrome.tabs.update(tab.id, { url });
    } catch (_) {}
  }, 5000);
  return tab;
}
async function isWorkTab(tabId) {
  const { workTabs = [] } = await chrome.storage.session.get("workTabs");
  return workTabs.includes(tabId);
}
async function closeTab(tabId) {
  try {
    await chrome.debugger.detach({ tabId });
  } catch (_) {}
  try {
    await chrome.tabs.remove(tabId);
  } catch (_) {}
  delete waiters[tabId];
}

// ───────── 可信键盘输入（chrome.debugger）─────────
// 抖音/视频号/快手的编辑器不认脚本模拟的键盘事件；用调试协议输入文字最稳定（发布期间浏览器顶部会显示"正在调试"提示，属正常）。
const attached = new Set();
async function ensureDebugger(tabId) {
  if (attached.has(tabId)) return;
  try {
    await chrome.debugger.attach({ tabId }, "1.3");
  } catch (e) {
    if (!String(e).includes("Already attached")) throw e;
  }
  attached.add(tabId);
}
chrome.debugger.onDetach.addListener(({ tabId }) => attached.delete(tabId));
const KEYS = { Enter: 13, Escape: 27, Space: 32, Backspace: 8, Delete: 46 };
async function pressKey(tabId, key) {
  await ensureDebugger(tabId);
  const code = KEYS[key];
  const base = { key: key === "Space" ? " " : key, code: key === "Space" ? "Space" : key, windowsVirtualKeyCode: code, nativeVirtualKeyCode: code };
  await chrome.debugger.sendCommand({ tabId }, "Input.dispatchKeyEvent", { type: "keyDown", ...base, ...(key === "Space" || key === "Enter" ? { text: key === "Space" ? " " : "\r" } : {}) });
  await chrome.debugger.sendCommand({ tabId }, "Input.dispatchKeyEvent", { type: "keyUp", ...base });
}
async function insertText(tabId, text) {
  await ensureDebugger(tabId);
  // 换行要按回车，直接插入 \n 在部分编辑器里会被吞掉
  const parts = String(text).split("\n");
  for (let i = 0; i < parts.length; i++) {
    if (parts[i]) await chrome.debugger.sendCommand({ tabId }, "Input.insertText", { text: parts[i] });
    if (i < parts.length - 1) await pressKey(tabId, "Enter");
  }
}

// ───────── 消息（来自内容脚本 / 弹窗 / 设置页）─────────
chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  const tabId = sender.tab && sender.tab.id;
  (async () => {
    switch (msg.type) {
      case "hello":
        return reply({ active: !!tabId && (await isWorkTab(tabId)) });
      case "ready": {
        const w = waiters[tabId] && waiters[tabId].ready;
        if (!w) return reply({ retry: true }); // 后台还没开始等待，内容脚本稍后再报
        const ctx = await getCurrentJob();
        if (msg.needLogin) {
          w({ needLogin: true, url: msg.url });
          return reply({ job: null });
        }
        if (!msg.hasForm) return reply({ job: null });
        w({ ok: true, frameId: sender.frameId });
        return reply({ job: ctx && ctx.tabId === tabId ? ctx.job : null });
      }
      case "progress":
        if (msg.msg !== "…") {
          const { running } = await chrome.storage.session.get("running");
          if (running) await setRunning({ ...running, stage: msg.msg });
        }
        if (msg.msg !== "…") await log(`[${PLATFORMS[msg.platform]?.name || msg.platform}] ${msg.msg}`);
        return reply({});
      case "getChunk": {
        const ctx = await getCurrentJob();
        const buf = await idbGet(`${ctx.tag}:video`);
        const part = new Uint8Array(buf, msg.i * CHUNK, Math.min(CHUNK, buf.byteLength - msg.i * CHUNK));
        let bin = "";
        for (let k = 0; k < part.length; k += 0x8000) bin += String.fromCharCode.apply(null, part.subarray(k, k + 0x8000));
        return reply({ b64: btoa(bin), total: Math.ceil(buf.byteLength / CHUNK) });
      }
      case "insertText":
        await insertText(tabId, msg.text);
        return reply({});
      case "key":
        await pressKey(tabId, msg.key);
        return reply({});
      case "verify": {
        const tab = sender.tab;
        const ctx = await getCurrentJob();
        await notify("verify", `${PLATFORMS[msg.platform].name}需要验证`, msg.msg || "请在弹出的窗口里完成短信/滑块验证，完成后会自动继续。", { tabId: tab.id, windowId: tab.windowId },
          { platform: msg.platform, slot: ctx && ctx.job ? ctx.job.slotName : "", videoTitle: ctx && ctx.job ? ctx.job.meta.title : "" });
        await chrome.windows.update(tab.windowId, { focused: true, state: "normal" });
        return reply({});
      }
      case "submitted": {
        const w = waiters[tabId] && waiters[tabId].submitted;
        if (w) w({ ok: true });
        return reply({});
      }
      case "result": {
        const w = waiters[tabId] && waiters[tabId].result;
        if (w) w(msg);
        else await finishOrphan(tabId, msg); // 后台被系统休眠重启过：按保存的任务收尾
        return reply({});
      }
      // —— 弹窗 / 设置页 ——
      case "refreshChannels":
        return reply({ list: await getChannels(true) });
      case "runNow":
        tick({ manual: true });
        return reply({ ok: true });
      case "login":
        startLogin(msg.platform);
        return reply({ ok: true });
      case "checkLogin":
        keepAlive(true);
        return reply({ ok: true });
      case "testRoutes": {
        // 用最新一期视频的前 2MB 测每条下载线路的速度
        try {
          const heads = await (await gh("git/matching-refs/heads/clip-")).json();
          const tag = heads.map((h) => h.ref.split("/").slice(2).join("/")).sort((a, b) => a.slice(5, 15).localeCompare(b.slice(5, 15))).pop();
          if (!tag) return reply({ error: "仓库里还没有视频分支" });
          const item = (await (await gh(`contents?ref=${tag}`)).json()).find((a) => a.name === "video.mp4");
          const s = await getSettings();
          const out = [];
          const rank = {};
          for (const rt of buildRoutes(item.download_url, {}, { forTest: true })) {
            const t0 = performance.now();
            try {
              const r = await Promise.race([openRoute(rt, tag, item, 0, s.token), new Promise((_, rej) => setTimeout(() => rej(Object.assign(new Error("timeout"), { name: "TimeoutError" })), 60000))]);
              if (!r.ok) throw new Error(`HTTP ${r.status}${r.status === 404 ? "（找不到文件或令牌无权访问）" : r.status === 401 ? "（令牌无效）" : ""}`);
              let n = 0;
              const reader = r.body.getReader();
              while (n < 2097152) {
                const { done, value } = await reader.read();
                if (done) break;
                n += value.byteLength;
              }
              reader.cancel().catch(() => {});
              const mbps = n / 1048576 / ((performance.now() - t0) / 1000);
              out.push({ key: rt.key, name: rt.name, ok: true, mbps, speed: `${mbps.toFixed(2)} MB/s`, resume: !rt.api });
              rank[rt.key] = rt.api ? mbps / 4 : mbps; // 不支持续传的降权
            } catch (e) {
              const m = e.name === "TimeoutError" ? "60 秒内没下完 2MB（网络太慢或连不上）" : /Failed to fetch/.test(String(e)) ? "连接失败（连不上或被中断）" : String(e.message || e);
              out.push({ key: rt.key, name: rt.name, ok: false, error: m });
              rank[rt.key] = -1;
            }
          }
          await chrome.storage.local.set({ routeRank: rank, routeTest: { at: beijing().stamp, results: out } });
          return reply({ ok: true, results: out });
        } catch (e) {
          return reply({ error: String(e.message || e) });
        }
      }
      case "testChannel": {
        const s = await getSettings();
        const vars = buildVars(msg.event || "published", { title: "推送测试：抖音已发布「热点快报」", message: "如果你收到这条消息，说明推送渠道配置正确。", platform: "抖音", platformKey: "douyin", slot: "热点快报", videoTitle: "热点快报11月12日｜示例标题" }, msg.textTemplate || s.textTemplate, beijing().stamp);
        return reply(await sendChannel(msg.channel, vars));
      }
      case "markDone":
      case "republish": {
        // markDone：你已手动发过，插件不再发；republish：清掉今天的记录重新发（会重复发布，弹窗里已二次确认）
        const st = await getState();
        const d = beijing().date;
        const s = await getSettings();
        const slot = ((st[d] = st[d] || {})[msg.slot] = st[d][msg.slot] || {});
        for (const p of ORDER) if (s.platforms[p]) slot[p] = msg.type === "markDone" ? { ...(slot[p] || {}), published: true, manual: true } : { published: false, attempts: 0 };
        await saveState(st);
        const chs = await getChannels();
        await log(`「${(chs.find((x) => x.key === msg.slot) || { name: msg.slot }).name}」${msg.type === "markDone" ? "已标记为已发布，今天不再自动发" : "已重置，准备重新发布"}`);
        await updateBadge();
        if (msg.type === "republish") {
          // 仓库里的 status.json 也会被当作"已发布"，这里跳过它的判断
          await chrome.storage.session.set({ ignoreStatus: channelTag(d, msg.slot) });
          tick({ manual: true });
        }
        return reply({ ok: true });
      }
      case "identify": {
        // 识别当前登录的账号；rebind = 有意换号，覆盖本机记录
        const p = msg.platform, P = PLATFORMS[p];
        const release = await acquire(`识别${P.name}账号`);
        if (!release) return reply({ error: "正在发布中，稍后再试" });
        let tab;
        try {
          tab = await openPlatformTab(p, P.upload);
          const r = await waitTab(tab.id, "ready", 90000);
          if (r.timeout) return reply({ error: "页面没有加载出来，稍后再试" });
          if (r.needLogin) { await setLogin(p, false); return reply({ error: `${P.name}还没登录，先扫码登录` }); }
          await new Promise((x) => setTimeout(x, 2000));
          const ident = await detectIdentity(p, tab.id);
          if (msg.rebind && ident.id) {
            const A = await accountFor(p);
            if (A) await saveIdent(A.id, ident);
            await log(`已重新记录${P.name}账号：${ident.nickname || ident.id}`);
            return reply({ ident, ok: true, rebound: true });
          }
          const chk = await checkIdentity(p, ident);
          return reply({ ident, ok: chk.ok, expect: chk.expect || null, account: chk.A || null });
        } catch (e) {
          return reply({ error: String(e.message || e) });
        } finally {
          if (tab) await closeTab(tab.id);
          await release();
        }
      }
      case "resetToday": {
        const st = await getState();
        const d = st[beijing().date] || {};
        for (const slot of Object.values(d)) for (const p of Object.values(slot)) if (!p.published) Object.assign(p, { attempts: 0, alerted: null });
        await saveState(st);
        return reply({ ok: true });
      }
    }
    reply({});
  })().catch((e) => {
    log(`消息处理出错：${e}`);
    reply({ error: String(e) });
  });
  return true;
});

async function getCurrentJob() {
  const { job } = await chrome.storage.session.get("job");
  return job || null;
}
async function setCurrentJob(job) {
  await chrome.storage.session.set({ job });
}

// ───────── 单个平台发布 ─────────
async function publishOne(platform, slot, tag, pkg) {
  const P = PLATFORMS[platform];
  const tab = await openPlatformTab(platform, P.upload);
  const job = { platform, slot: slot.key, slotName: slot.name, tag, meta: pkg.meta, size: pkg.size, chunks: Math.ceil(pkg.size / CHUNK) };
  await setCurrentJob({ tabId: tab.id, tag, platform, slot: slot.key, job, started: Date.now() });
  const ready = await waitTab(tab.id, "ready", 120000);
  if (ready.timeout) {
    await closeTab(tab.id);
    return { ok: false, code: "error", msg: "上传页 2 分钟内没有加载出来（可能网络问题或页面改版）" };
  }
  if (ready.needLogin) {
    await closeTab(tab.id);
    return { ok: false, code: "need_login", msg: `${P.name}登录已失效` };
  }
  // 发布前核对账号：账号 ID 对不上就不发（昵称只用来显示）
  const ident = await detectIdentity(platform, tab.id);
  const chk = await checkIdentity(platform, ident);
  if (chk.ok === false) {
    await closeTab(tab.id);
    await setCurrentJob(null);
    return { ok: false, code: "wrong_account", ident, msg: `当前登录的是「${ident.nickname || "另一个账号"}」，不是「${chk.A.name}」${chk.expect.nickname ? `（${chk.expect.nickname}）` : ""}，为避免发错号没有发布` };
  }
  if (!ident.id) await log(`没能读取到${P.name}的账号 ID，这次无法核对账号${ident.err ? `（${ident.err}）` : ""}；可在设置页「发布平台」点「识别账号」排查`);
  // 视频号：点「发表」后表单所在的 iframe 会被销毁，改为监听页面跳转判断成功
  const submitted = platform === "channels" ? waitTab(tab.id, "submitted", JOB_TIMEOUT_MS) : null;
  const resultP = waitTab(tab.id, "result", JOB_TIMEOUT_MS);
  let res;
  if (submitted) {
    res = await Promise.race([resultP, submitted.then(() => watchLeave(tab.id, "/post/create", 90000))]);
  } else {
    res = await resultP;
  }
  if (res.timeout) res = { ok: false, code: "error", msg: "发布超过 40 分钟仍未完成" };
  res.ident = ident;
  await closeTab(tab.id);
  await setCurrentJob(null);
  return res;
}
function watchLeave(tabId, marker, ms) {
  return new Promise((resolve) => {
    const t0 = Date.now();
    const iv = setInterval(async () => {
      try {
        const t = await chrome.tabs.get(tabId);
        if (t.url && !t.url.includes(marker)) {
          clearInterval(iv);
          return resolve({ ok: true, msg: "已发表" });
        }
      } catch (_) {}
      if (Date.now() - t0 > ms) {
        clearInterval(iv);
        resolve({ ok: false, code: "failed", msg: "点了发表但页面没有跳转，请到视频号后台确认" });
      }
    }, 2000);
  });
}
async function finishOrphan(tabId, msg) {
  const ctx = await getCurrentJob();
  if (!ctx || ctx.tabId !== tabId) return;
  const chs = await getChannels();
  await recordResult(ctx.platform, chs.find((s) => s.key === ctx.slot) || { key: ctx.slot, name: ctx.slot }, ctx.tag, ctx.job.meta, msg);
  await closeTab(tabId);
  await setCurrentJob(null);
  await chrome.storage.session.set({ lock: 0, lockOwner: "" });
}

const HELP = {
  need_login: "点通知上的「扫码登录」，或打开插件弹窗点对应平台的「扫码登录」。登录后会自动补发。",
  failed: "稍后会自动重试。若浏览器里出现验证，请直接完成。",
  gave_up: "已重试 3 次。打开插件弹窗点「立即运行」并盯着自动打开的窗口；仍失败请把插件「运行日志」发给 Claude。",
  declare: "AI 声明没有勾上，为避免违规这次没有发布。打开插件弹窗点「立即运行」重试；仍失败请把运行日志发给 Claude。",
  error: "打开插件弹窗点「立即运行」重试；仍失败请把运行日志发给 Claude。",
  wrong_account: "这个 Chrome 里登录的账号和设置的不一致，为避免发错号没有发布。在这个 Chrome 里退出当前账号、扫码登录正确的账号；如果你是有意换号，到设置页「发布平台」点「重新识别」。",
};
async function recordResult(platform, slot, tag, meta, res) {
  setTimeout(updateBadge, 500);
  const P = PLATFORMS[platform];
  const A = await accountFor(platform);
  const key = A ? A.id : platform;
  const who = A && A.id !== platform ? `${P.name}·${A.name}` : P.name;
  const info = { account: A ? A.name : "", nickname: (res.ident && res.ident.nickname) || "" };
  const state = await getState();
  const today = beijing().date;
  const st = (((state[today] = state[today] || {})[slot.key] = state[today][slot.key] || {})[platform] =
    state[today][slot.key][platform] || { published: false, attempts: 0 });
  if (res.ok) {
    st.published = true;
    st.last = beijing().stamp;
    await saveState(state);
    await log(`✅ ${who}「${slot.name}」发布成功：${meta.title}`);
    await writeStatus(tag, platform, "published", "", st.attempts, key, info);
    await notify("published", `${who}已发布「${slot.name}」`, meta.title, null, { platform, slot: slot.name, videoTitle: meta.title });
    return;
  }
  let code = res.code || "failed";
  if (code === "need_login" || code === "wrong_account") st.attempts = Math.max(0, st.attempts - 1); // 登录失效、登错账号不算失败次数
  if (code === "failed" && st.attempts >= MAX_ATTEMPTS) code = "gave_up";
  st.lastError = res.msg;
  await saveState(state);
  await log(`❌ ${who}「${slot.name}」${res.msg}`);
  await writeStatus(tag, platform, code, res.msg, st.attempts, key, info);
  if (st.alerted !== code) {
    st.alerted = code;
    await saveState(state);
    const kind = code === "need_login" || code === "wrong_account" ? "login" : "failed";
    await notify(kind, `${who}「${slot.name}」${code === "need_login" ? "需要重新登录" : code === "wrong_account" ? "登录的不是这个账号" : "发布受阻"}`, `${res.msg}\n${HELP[code] || HELP.error}`, code === "need_login" ? { login: platform } : null, { platform, slot: slot.name, videoTitle: meta.title });
  }
}

// ───────── 账号：一个 Chrome 资料里每个平台登录一个账号；仓库 autoreel.config.json 的 accounts 登记所有账号 ─────────
// 本机设置 settings.acct = {平台: 账号 id}，settings.ident = {账号 id: {id, nickname, time}}（id 是平台账号 ID 或登录指纹，用来核对）
async function getAccounts() {
  const { channels } = await chrome.storage.local.get("channels");
  return (channels && channels.accounts) || [];
}
// 这个浏览器在某平台上代表哪个账号：设置里选了就用；仓库里这个平台只有一个账号就自动用它；仓库没登记账号时沿用旧版（账号 = 平台）
async function accountFor(platform, s) {
  s = s || (await getSettings());
  const accounts = await getAccounts();
  if (!accounts.length) return { id: platform, name: PLATFORMS[platform].name, platform, legacy: true };
  const chosen = (s.acct || {})[platform];
  if (chosen === "") return null; // 明确选了「这个浏览器不发」
  if (chosen) return accounts.find((a) => a.id === chosen && a.platform === platform) || null;
  const mine = accounts.filter((a) => a.platform === platform);
  if (mine.length === 1) return mine[0];
  // 没明确选过：本机记录过其中哪个账号的身份，就是哪个（加了第二个号以后，原来的浏览器继续发原来的号）
  const known = mine.filter((a) => (s.ident || {})[a.id]);
  return known.length === 1 ? known[0] : null;
}
const targets = (slot, A) => !!A && (!slot.to || slot.to.includes(A.id) || (A.legacy && slot.to.some((x) => x === A.platform)));

// 识别当前登录的账号：昵称只用来显示，核对靠平台账号 ID（读不到时用登录 cookie 的指纹，只保存哈希）
const ID_COOKIES = { douyin: [["https://creator.douyin.com/", "uid_tt"], ["https://www.douyin.com/", "uid_tt"]], kuaishou: [["https://cp.kuaishou.com/", "userId"]], channels: [] };
async function sha16(t) {
  const b = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(t));
  return [...new Uint8Array(b)].map((x) => x.toString(16).padStart(2, "0")).join("").slice(0, 16);
}
function pageIdentity(platform) {
  // 在平台页面里执行（页面自己的登录状态）
  return (async () => {
    const res = { uid: "", nickname: "", via: "" };
    const pick = (o, ks) => { for (const k of ks) if (o && o[k] != null && String(o[k]).trim() && String(o[k]) !== "0") return String(o[k]).trim(); return ""; };
    const getJSON = async (u) => { try { const r = await fetch(u, { credentials: "include" }); return r.ok ? await r.json() : null; } catch { return null; } };
    if (platform === "douyin") {
      for (const u of ["/web/api/media/user/info/", "/aweme/v1/creator/user/info/"]) {
        const j = await getJSON(u);
        const user = j && (j.user || j.user_info || (j.data && (j.data.user || j.data.user_info || j.data)));
        if (user && typeof user === "object") {
          res.uid = pick(user, ["uid", "user_id", "sec_uid", "unique_id", "short_id"]);
          res.nickname = pick(user, ["nickname", "nick_name", "name"]);
          if (res.uid || res.nickname) { res.via = u; break; }
        }
      }
    }
    if (platform === "channels") {
      const m = (document.body && document.body.innerText || "").match(/sph[A-Za-z0-9_]{6,}/);
      if (m) { res.uid = m[0]; res.via = "page"; }
    }
    if (!res.nickname) {
      const sel = '[class*="nickname"],[class*="nick-name"],[class*="nickName"],[class*="userName"],[class*="user-name"],[class*="username"],[class*="account-name"],[class*="name"]';
      for (const el of document.querySelectorAll(sel)) {
        const r = el.getBoundingClientRect(), t = (el.innerText || "").trim();
        if (r.width && r.height && r.top < 220 && t && t.length <= 24 && !/\n/.test(t) && !/上传|发布|首页|创作|登录|通知|帮助|数据|管理|设置/.test(t)) { res.nickname = t; break; }
      }
    }
    return res;
  })();
}
async function detectIdentity(platform, tabId) {
  const out = { id: "", nickname: "", via: "" };
  try {
    const [r] = await chrome.scripting.executeScript({ target: { tabId }, world: "MAIN", func: pageIdentity, args: [platform] });
    const v = (r && r.result) || {};
    out.nickname = v.nickname || "";
    if (v.uid) Object.assign(out, { id: `${platform}:${v.uid}`, via: v.via || "page", uid: v.uid });
  } catch (e) {
    out.err = String(e.message || e);
  }
  if (!out.id) {
    for (const [url, name] of ID_COOKIES[platform] || []) {
      const c = await chrome.cookies.get({ url, name }).catch(() => null);
      if (c && c.value) { out.id = `${platform}:fp-${await sha16(name + "=" + c.value)}`; out.via = "cookie"; break; }
    }
  }
  return out;
}
// 核对：返回 {ok:true|false|null, expect}；null = 无法核对（没有记录或读不到 ID）
async function checkIdentity(platform, got, { bindIfNew = true } = {}) {
  const s = await getSettings();
  const A = await accountFor(platform, s);
  if (!A) return { ok: null };
  const ident = s.ident || {};
  const expect = ident[A.id] || (A.pid ? { id: A.pid, nickname: A.nickname || "" } : null);
  if (!got.id) return { ok: null, expect, A };
  if (expect && expect.id) {
    const ok = expect.id === got.id;
    if (ok && got.nickname && got.nickname !== expect.nickname) await saveIdent(A.id, got); // 改了昵称也是同一个号，更新显示
    return { ok, expect, A };
  }
  if (bindIfNew) {
    await saveIdent(A.id, got);
    await log(`已记录${PLATFORMS[platform].name}账号「${A.name}」：${got.nickname || "（没读到昵称）"}，以后发布前会核对是不是这个号`);
  }
  return { ok: null, expect: null, A, bound: true };
}
async function saveIdent(acctId, got) {
  const { settings = {} } = await chrome.storage.local.get("settings");
  settings.ident = { ...(settings.ident || {}), [acctId]: { id: got.id, nickname: got.nickname || "", via: got.via || "", time: beijing().stamp } };
  await chrome.storage.local.set({ settings });
}

// ───────── 频道列表（从仓库读取，缓存 30 分钟）─────────
async function getChannels(force = false) {
  const { channels } = await chrome.storage.local.get("channels");
  if (!force && channels && "accounts" in channels && Date.now() - channels.at < 30 * 60000) return channels.list; // 旧版缓存没有账号信息，直接重读
  try {
    const raw = (p) => gh(`contents/${p}`, { accept: "application/vnd.github.raw" }).then((r) => r.json()); // 不带 ref = 仓库默认分支
    const cfg = await raw("autoreel.config.json");
    const list = [];
    for (const id of cfg.channels || []) {
      try {
        const ch = await raw(`channels/${id}/channel.json`);
        list.push({ key: id, name: ch.name || id, notBefore: (ch.schedule && ch.schedule.publish) || "00:00", to: Array.isArray(ch.publish_to) ? ch.publish_to : null });
      } catch (e) {
        await log(`读取频道 ${id} 失败：${e.message}`);
      }
    }
    const accounts = (Array.isArray(cfg.accounts) ? cfg.accounts : []).filter((a) => a && a.id && PLATFORMS[a.platform]);
    await chrome.storage.local.set({ channels: { at: Date.now(), list, accounts } });
    return list;
  } catch (e) {
    if (channels) return channels.list; // 网络不好时先用上次的
    await log(`读取频道配置失败：${e.message}`);
    return [];
  }
}

// ───────── 当前进度（弹窗实时显示）+ 图标角标 ─────────
async function setRunning(r) {
  await chrome.storage.session.set({ running: r ? { ...r, at: beijing().stamp } : null });
  await updateBadge();
}
async function updateBadge() {
  const { running } = await chrome.storage.session.get("running");
  if (running) {
    chrome.action.setBadgeBackgroundColor({ color: "#5b4bff" });
    return chrome.action.setBadgeText({ text: "…" });
  }
  const s = await getSettings();
  const { date, hm } = beijing();
  const day = (await getState())[date] || {};
  const SLOTS = await getChannels();
  const acc = {};
  for (const p of ORDER) acc[p] = s.platforms[p] ? await accountFor(p, s) : null;
  const bad = SLOTS.some((sl) => hm >= (s.times[sl.key] || sl.notBefore) && ORDER.some((p) => {
    const r = s.platforms[p] && targets(sl, acc[p]) && (day[sl.key] || {})[p];
    return r && !r.published && (r.attempts >= MAX_ATTEMPTS || r.alerted === "need_login" || r.alerted === "declare" || r.alerted === "wrong_account");
  }));
  chrome.action.setBadgeBackgroundColor({ color: "#e5484d" });
  chrome.action.setBadgeText({ text: bad ? "!" : "" });
}

// ───────── 任务锁 + 保持后台不被 Chrome 休眠 ─────────
// Chrome 会在后台脚本"闲置"约 30 秒后把它停掉；下载大视频时没有其他事件，可能被中途停掉。
// 任务期间每 20 秒调用一次扩展接口并刷新锁的时间：后台保持活跃，锁超过 3 分钟没刷新就视为失效（不会一直卡住）。
const LOCK_STALE_MS = 3 * 60000;
async function acquire(owner) {
  const { lock, lockOwner } = await chrome.storage.session.get(["lock", "lockOwner"]);
  if (lock && Date.now() - lock < LOCK_STALE_MS) return null;
  if (lock) await log(`上一个任务（${lockOwner || "未知"}）已中断，自动解除占用`);
  await chrome.storage.session.set({ lock: Date.now(), lockOwner: owner });
  const iv = setInterval(() => {
    chrome.runtime.getPlatformInfo(() => {});
    chrome.storage.session.set({ lock: Date.now() });
  }, 20000);
  return async () => {
    clearInterval(iv);
    await chrome.storage.session.set({ lock: 0, lockOwner: "" });
  };
}

// 仓库 status.json 里这个账号是否已发布过。旧版（还没有账号时）按平台名记录的「已发布」，
// 算在这个平台的第一个账号（原来那个号）头上，升级后不会重复发
async function alreadyPublished(doc, A, p) {
  if (!doc || !A) return false;
  const pl = doc.platforms || {};
  if (pl[A.id] && pl[A.id].status === "published") return true;
  const first = (await getAccounts()).find((a) => a.platform === p);
  const isOrig = A.legacy || (first && first.id === A.id);
  if (!isOrig) return false;
  if (pl[p] && pl[p].status === "published" && !pl[p].platform) return true;
  return p === "douyin" && doc.status === "published" && !Object.keys(pl).some((k) => k !== "douyin");
}

// ───────── 调度 ─────────
async function tick({ manual = false } = {}) {
  const s = await getSettings();
  await chrome.storage.local.set({ lastTick: beijing().stamp });
  if (s.paused && !manual) return;
  if (!s.token || !s.repo) return;
  const release = await acquire(manual ? "手动运行" : "定时发布");
  if (!release) {
    if (manual) await log("上一个任务还在进行中，这次先跳过");
    return;
  }
  try {
    const { date: today, hm } = beijing();
    const state = await getState();
    const tags = [];
    const SLOTS = await getChannels(manual);
    if (!SLOTS.length && manual) await log("仓库的 autoreel.config.json 里没有启用任何频道");
    for (const slot of SLOTS) {
      if (hm < (s.times[slot.key] || slot.notBefore)) continue;
      const tag = channelTag(today, slot.key);
      tags.push(tag);
      const acc = {};
      for (const p of ORDER) acc[p] = s.platforms[p] ? await accountFor(p, s) : null;
      const todo = ORDER.filter((p) => {
        if (!s.platforms[p] || !targets(slot, acc[p])) return false;
        const st = state[today]?.[slot.key]?.[p];
        return !(st && st.published) && !(st && st.attempts >= MAX_ATTEMPTS && !manual);
      });
      if (!todo.length) continue;
      if (!(await branchExists(tag))) {
        if (manual) await log(`还没有「${slot.name}」的视频（${tag}），稍后再查`);
        continue;
      }
      // 已在旧版 Mac 程序或别处发布过的，以仓库 status.json 为准，避免重复发
      const { ignoreStatus } = await chrome.storage.session.get("ignoreStatus");
      const { doc } = ignoreStatus === tag ? { doc: null } : await readStatus(tag);
      await log(`「${slot.name}」视频已就绪，开始下载（${tag}）`);
      await setRunning({ slot: slot.name, platform: PLATFORMS[todo[0]].name, stage: "下载视频" });
      const pkg = await fetchPackage(tag);
      const { titles = {} } = await chrome.storage.local.get("titles");
      titles[tag] = pkg.meta.title;
      await chrome.storage.local.set({ titles: Object.fromEntries(Object.entries(titles).slice(-12)) });
      for (const p of todo) {
        const done = await alreadyPublished(doc, acc[p], p);
        const st0 = await getState();
        const rec = (((st0[today] = st0[today] || {})[slot.key] = st0[today][slot.key] || {})[p] = st0[today][slot.key][p] || { published: false, attempts: 0 });
        if (done) {
          rec.published = true;
          await saveState(st0);
          continue;
        }
        if (rec.attempts >= MAX_ATTEMPTS && manual) rec.attempts = 0;
        rec.attempts += 1;
        await saveState(st0);
        await log(`开始发布 ${PLATFORMS[p].name}${acc[p].legacy ? "" : "·" + acc[p].name}「${slot.name}」（第 ${rec.attempts} 次）：${pkg.meta.title}`);
        await setRunning({ slot: slot.name, platform: PLATFORMS[p].name, stage: "打开上传页" });
        let res;
        try {
          res = await publishOne(p, slot, tag, pkg);
        } catch (e) {
          res = { ok: false, code: "error", msg: String(e) };
        }
        await recordResult(p, slot, tag, pkg.meta, res);
      }
    }
    await idbPrune(tags);
    if (tags.length) await cleanup(today);
  } catch (e) {
    await log(`调度出错：${e.message || e}`);
    if (manual) await notify("failed", "自动发布出错", String(e.message || e));
  } finally {
    await setRunning(null);
    await release();
  }
}

// ───────── 登录（插件内弹出扫码窗口）/ 保活 ─────────
async function startLogin(platform) {
  const P = PLATFORMS[platform];
  if (!P || !(await getSettings()).platforms[platform]) return log(`${P ? P.name : platform}已在设置中停用，不打开登录窗口`);
  const w = await chrome.windows.create({ url: P.login, type: "popup", width: 520, height: 760, focused: true });
  const tabId = w.tabs[0].id;
  await log(`打开${P.name}扫码登录窗口`);
  const listener = async (id, info, tab) => {
    if (id !== tabId || !info.url) return;
    if (P.loggedIn(info.url)) {
      chrome.tabs.onUpdated.removeListener(listener);
      await setLogin(platform, true);
      await new Promise((r) => setTimeout(r, 2500)); // 等页面把用户信息加载出来
      const ident = await detectIdentity(platform, tabId);
      const chk = await checkIdentity(platform, ident);
      const nm = ident.nickname ? `「${ident.nickname}」` : "";
      await log(`${P.name}登录成功${nm}${ident.id ? "" : "（没读到账号 ID，发布前将无法核对账号）"}`);
      if (chk.ok === false) {
        await notify("login", `${P.name}登录的不是「${chk.A.name}」`, `刚登录的是${nm || "另一个账号"}，和这个浏览器设置的账号${chk.expect.nickname ? `（${chk.expect.nickname}）` : ""}不一致，插件不会用它发布。请退出后扫码登录正确的账号；有意换号就到设置页「发布平台」点「重新识别」。`, { login: platform }, { platform });
      } else chrome.notifications.create({ type: "basic", iconUrl: "icons/128.png", title: `${P.name}登录成功${nm}`, message: "登录状态已保存，插件会自动保持登录。" });
      setTimeout(() => chrome.windows.remove(w.id).catch(() => {}), 2500);
      tick(); // 登录后立即补发
    }
  };
  chrome.tabs.onUpdated.addListener(listener);
}
async function setLogin(platform, ok) {
  const { login = {} } = await chrome.storage.local.get("login");
  login[platform] = { ok, time: beijing().stamp };
  await chrome.storage.local.set({ login });
}
async function keepAlive(force = false) {
  const s = await getSettings();
  const { lastKeepAlive = 0 } = await chrome.storage.local.get("lastKeepAlive");
  if (!force && (s.paused || Date.now() - lastKeepAlive < s.keepAliveHours * 3600e3)) return;
  if (!ORDER.some((p) => s.platforms[p])) return;
  const release = await acquire("登录检查");
  if (!release) return; // 正在发布，下次再检查
  await chrome.storage.local.set({ lastKeepAlive: Date.now() });
  try {
  for (const p of ORDER) {
    if (!s.platforms[p]) continue;
    const P = PLATFORMS[p];
    const tab = await openPlatformTab(p, P.upload);
    await setCurrentJob({ tabId: tab.id, probe: true });
    const r = await waitTab(tab.id, "ready", 90000);
    await closeTab(tab.id);
    await setCurrentJob(null);
    const ok = !r.timeout && !r.needLogin;
    await setLogin(p, ok);
    await log(`${P.name}登录状态：${ok ? "正常" : r.timeout ? "页面未加载（稍后重试）" : "已失效"}`);
    if (r.needLogin) await notify("login", `${P.name}登录已失效`, "点「扫码登录」用 App 扫码即可，插件之后会自动保持登录。", { login: p }, { platform: p });
  }
  } finally {
    await release();
  }
}

// ───────── 定时器 ─────────
chrome.runtime.onInstalled.addListener(async () => {
  getChannels(true).catch(() => {}); // 安装、更新、重新加载后立即按新版重读仓库的频道和账号
  chrome.alarms.create("tick", { periodInMinutes: 5 });
  chrome.alarms.create("keepalive", { periodInMinutes: 60 });
  const { settings } = await chrome.storage.local.get("settings");
  if (!settings || !settings.token) chrome.runtime.openOptionsPage();
});
chrome.runtime.onStartup.addListener(() => {
  chrome.alarms.create("tick", { periodInMinutes: 5 });
  chrome.alarms.create("keepalive", { periodInMinutes: 60 });
  setTimeout(() => tick(), 20000);
});
// 后台每次启动都确认定时器存在（防止被清掉后再也不触发）
(async () => {
  if (!(await chrome.alarms.get("tick"))) chrome.alarms.create("tick", { periodInMinutes: 5 });
  if (!(await chrome.alarms.get("keepalive"))) chrome.alarms.create("keepalive", { periodInMinutes: 60 });
})();
chrome.alarms.onAlarm.addListener((a) => {
  updateBadge();
  if (a.name === "tick") tick();
  if (a.name === "keepalive") keepAlive();
});

// 供自动化测试调用（不影响正常使用）
self.__kb = { tick, publishOne, keepAlive, fetchPackage, recordResult, beijing, idbPut, newChannel, startLogin, accountFor, targets, detectIdentity, checkIdentity, getChannels, alreadyPublished };
