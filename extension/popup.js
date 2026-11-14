import { PLATFORMS, DEFAULTS, MAX_ATTEMPTS, channelTag } from "./shared.js";

const $ = (id) => document.getElementById(id);
const send = (m) => chrome.runtime.sendMessage(m);
const bj = () => {
  const s = new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date());
  return { date: s.slice(0, 10), hm: s.slice(11, 16) };
};
const LETTER = { douyin: "抖", channels: "视", kuaishou: "快" };
function toast(t) {
  const el = $("toast");
  el.textContent = t;
  el.classList.add("show");
  setTimeout(() => el.classList.remove("show"), 1800);
}

async function render() {
  const { login = {}, state = {}, logs = [], settings = {}, titles = {}, channels } = await chrome.storage.local.get(["login", "state", "logs", "settings", "titles", "channels"]);
  const SLOTS = (channels && channels.list) || [];
  if (!channels && settings.token && settings.repo && !render.asked) {
    render.asked = true;
    send({ type: "refreshChannels" }); // 第一次打开时读取频道列表
  }
  const enabled = { ...DEFAULTS.platforms, ...(settings.platforms || {}) };
  const times = Object.fromEntries(SLOTS.map((s) => [s.key, (settings.times || {})[s.key] || s.notBefore]));
  const on = Object.keys(PLATFORMS).filter((k) => enabled[k]);
  const off = Object.keys(PLATFORMS).filter((k) => !enabled[k]);
  const { date, hm } = bj();
  const day = state[date] || {};
  // 这个浏览器在各平台代表哪个账号（和后台 accountFor 的规则一致）
  const ACC = (channels && channels.accounts) || [];
  const acctOf = (k) => {
    if (!ACC.length) return { id: k, name: "", legacy: true };
    const ch = (settings.acct || {})[k];
    if (ch === "") return null;
    if (ch) return ACC.find((a) => a.id === ch) || null;
    const mine = ACC.filter((a) => a.platform === k);
    if (mine.length === 1) return mine[0];
    const known = mine.filter((a) => (settings.ident || {})[a.id]);
    return known.length === 1 ? known[0] : null;
  };
  const forMe = (slot, k) => { const A = acctOf(k); return !!A && (!slot.to || slot.to.includes(A.id) || (A.legacy && slot.to.includes(k))); };

  // 顶部：下一条
  const pending = SLOTS.filter((s) => on.some((p) => !((day[s.key] || {})[p] || {}).published));
  const upcoming = pending.find((s) => (times[s.key] || s.notBefore) > hm);
  const nextEl = $("next");
  if (!on.length) nextEl.textContent = "没有开启任何平台";
  else if (!SLOTS.length) nextEl.textContent = "还没有读取到频道";
  else if (!pending.length) nextEl.textContent = `今天 ${SLOTS.length} 条已全部发布 🎉`;
  else if (upcoming) nextEl.textContent = `下一条 ${times[upcoming.key]} · ${upcoming.name}`;
  else nextEl.textContent = `待发：${pending.map((s) => s.name).join("、")}（视频就绪后自动发）`;
  $("pausedTag").innerHTML = settings.paused ? '<span class="chip">已暂停</span>' : "";
  $("autoSwitch").checked = !settings.paused;

  // 正在进行
  const { running } = await chrome.storage.session.get("running");
  $("runbar").hidden = !running;
  if (running) {
    $("runTitle").textContent = `正在发布 ${running.platform}「${running.slot}」`;
    $("runStage").textContent = running.stage || "";
  }
  // 上手检查清单：只列出需要处理的项
  const { lastTick } = await chrome.storage.local.get("lastTick");
  const items = [];
  if (!settings.repo) items.push(["还没有填写 GitHub 仓库", "去设置", "options.html#basic"]);
  if (!settings.token) items.push(["还没有填写 GitHub 令牌", "去设置", "options.html#basic"]);
  for (const k of on) if (!login[k] || !login[k].ok) items.push([`${PLATFORMS[k].name}${login[k] ? "登录已失效" : "还没确认登录"}`, "扫码登录", `login:${k}`]);
  if (settings.token && lastTick && Date.now() - Date.parse(lastTick.replace(" ", "T") + "+08:00") > 20 * 60000) items.push(["超过 20 分钟没有自动检查（电脑睡眠或 Chrome 被关过）", "立即检查", "run"]);
  if (settings.paused) items.push(["自动发布已暂停", "恢复", "resume"]);
  const { writeDenied } = await chrome.storage.local.get("writeDenied");
  if (writeDenied) items.push(["GitHub 令牌没有写权限：发布正常，但结果写不回仓库、旧视频清理不了", "怎么改", "help:token"]);
  const cl = $("checklist");
  cl.hidden = !items.length;
  cl.innerHTML = items.map(([t, b, a]) => `<div class="it"><b>!</b><span>${t}</span><button class="btn sm" data-a="${a}">${b}</button></div>`).join("");
  cl.querySelectorAll("button").forEach((btn) => (btn.onclick = async () => {
    const a = btn.dataset.a;
    if (a.startsWith("options")) chrome.tabs.create({ url: a });
    else if (a.startsWith("login:")) send({ type: "login", platform: a.slice(6) });
    else if (a === "run") $("run").click();
    else if (a === "help:token") alert("打开 GitHub → Settings → Developer settings → Personal access tokens → Fine-grained tokens，\n找到插件用的这个令牌，点 Edit：\n\nRepository permissions → Contents 改成「Read and write」，保存。\n\n令牌本身不变，不需要在插件里重新填写。下一次发布成功后，这条提示会自动消失。");
    else if (a === "resume") {
      settings.paused = false;
      await chrome.storage.local.set({ settings });
    }
  }));

  // 平台账号：只列出已开启的
  const P = $("plats");
  P.innerHTML = "";
  for (const k of on) {
    const s = login[k];
    const pill = !s ? '<span class="pill">未检查</span>' : s.ok ? '<span class="pill ok">已登录</span>' : '<span class="pill bad">登录失效</span>';
    const row = document.createElement("div");
    row.className = "plat";
    const A = acctOf(k), id = A && (settings.ident || {})[A.id];
    const who = A && !A.legacy ? ` · ${A.name}${id && id.nickname ? `（${id.nickname}）` : ""}` : !A ? " · 不在本机发" : id && id.nickname ? `（${id.nickname}）` : "";
    row.innerHTML = `<span class="badge ${k}">${LETTER[k]}</span><div class="meta"><b>${PLATFORMS[k].name}${who.replace(/[<>&"]/g, "")}</b><small>${s ? `${s.time.slice(5, 16)} 检查` : "还没检查过登录状态"}</small></div>${pill}`;
    const b = document.createElement("button");
    b.className = "btn sm";
    b.textContent = s && s.ok ? "重新登录" : "扫码登录";
    b.onclick = () => send({ type: "login", platform: k });
    row.appendChild(b);
    P.appendChild(row);
  }
  if (off.length) {
    const d = document.createElement("div");
    d.className = "off";
    d.innerHTML = `<span>${off.map((k) => PLATFORMS[k].name).join("、")} 已停用，不会有任何自动操作</span><a href="options.html#platforms" target="_blank">开启</a>`;
    P.appendChild(d);
  }
  const okCount = on.filter((k) => login[k] && login[k].ok).length;
  $("loginSub").textContent = on.length ? `${okCount}/${on.length} 已登录` : "";

  // 今天的发布
  $("today").textContent = date;
  const S = $("slots");
  S.innerHTML = "";
  for (const s of SLOTS) {
    const mine = on.filter((k) => forMe(s, k));
    const chips = (mine.length ? mine : on).map((k) => {
      if (!mine.length) return "";
      const r = (day[s.key] || {})[k];
      const name = on.length > 1 ? PLATFORMS[k].name : "";
      if (r && r.published) return `<span class="pill ok">${name || "已发布"}</span>`;
      if (r && r.attempts >= MAX_ATTEMPTS) return `<span class="pill bad" title="${(r.lastError || "").replace(/"/g, "'")}">${name}${name ? " " : ""}已停止</span>`;
      if (r && r.lastError) return `<span class="pill warn" title="${r.lastError.replace(/"/g, "'")}">${name}${name ? " " : ""}失败${r.attempts}次</span>`;
      const due = hm >= (times[s.key] || s.notBefore);
      return `<span class="pill ${due ? "brand" : ""}">${name}${name ? " " : ""}${due ? "等待视频" : "未到时间"}</span>`;
    });
    const tag = channelTag(date, s.key);
    const title = (titles[tag] || "").replace(/^[^｜]*｜/, "");
    const row = document.createElement("div");
    row.className = "slot";
    row.innerHTML = `<time>${times[s.key] === "00:00" ? "就绪即发" : times[s.key]}</time><span class="nm">${s.name}${title ? `<small title="${title.replace(/"/g, "'")}">${title}</small>` : ""}</span><span class="st">${chips.join("") || '<span class="pill plain" title="这个频道没有分配给本机登录的账号，由别的 Chrome 发布">其他浏览器发</span>'}</span><button class="more" title="更多操作" aria-label="更多操作">⋯</button>`;
    row.querySelector(".more").onclick = (e) => openMenu(e, s);
    S.appendChild(row);
  }
  if (!SLOTS.length) S.innerHTML = '<div class="muted" style="padding:8px 0">还没有读取到频道。确认仓库的 autoreel.config.json 里 channels 不为空，然后点「立即运行」。</div>';
  $("today").textContent = `${date}${lastTick ? ` · ${lastTick.slice(11, 16)} 检查过` : ""}`;
  $("logs").textContent = logs.slice(-60).reverse().join("\n") || "暂无日志";
}

function openMenu(e, slot) {
  document.querySelectorAll(".menu").forEach((m) => m.remove());
  const m = document.createElement("div");
  m.className = "menu";
  m.innerHTML = `<button data-a="markDone">标记为已发布（今天不再发）</button><button data-a="republish" class="danger">重新发布</button>`;
  const r = e.target.getBoundingClientRect();
  m.style.top = `${r.bottom + 4}px`;
  m.style.right = `${document.body.clientWidth - r.right}px`;
  document.body.appendChild(m);
  m.querySelectorAll("button").forEach((b) => (b.onclick = async () => {
    m.remove();
    if (b.dataset.a === "republish" && !confirm(`确定重新发布今天的「${slot.name}」吗？\n如果它已经发出去了，抖音上会出现两条。`)) return;
    await send({ type: b.dataset.a, slot: slot.key });
    toast(b.dataset.a === "markDone" ? `「${slot.name}」已标记为已发布` : `正在重新发布「${slot.name}」`);
  }));
  setTimeout(() => document.addEventListener("click", function off(ev) {
    if (!m.contains(ev.target)) {
      m.remove();
      document.removeEventListener("click", off);
    }
  }), 0);
}

$("openSettings").onclick = () => chrome.runtime.openOptionsPage();
$("run").onclick = async () => {
  await send({ type: "runNow" });
  toast("已开始检查，到点的视频会自动发布");
};
$("check").onclick = async () => {
  await send({ type: "checkLogin" });
  toast("正在检查已开启平台的登录状态");
};
$("reset").onclick = async () => {
  await send({ type: "resetToday" });
  toast("已重置今天的失败次数");
};
$("autoSwitch").onchange = async (e) => {
  const { settings = {} } = await chrome.storage.local.get("settings");
  settings.paused = !e.target.checked;
  await chrome.storage.local.set({ settings });
  toast(settings.paused ? "已暂停自动发布和登录检查" : "已恢复自动发布");
};
chrome.storage.onChanged.addListener(render);
render();
