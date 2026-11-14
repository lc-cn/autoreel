// 自影 · 设置页「频道」：从仓库拉取频道详情，在插件里编辑，保存时一次提交写回仓库
import { loadRepo, saveFiles, toJSON } from "./repo.js";

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const MOODS = ["平稳", "轻快", "严肃", "沉重", "温暖", "惊讶", "激昂", "悬念"];
const PROVIDERS = { auto: "自动（有火山引擎配置就用，否则 CosyVoice）", cosyvoice: "CosyVoice3 离线配音（免费，较慢）", volcengine: "火山引擎豆包语音（付费，快）", sherpa: "sherpa 轻量配音（最快，音质一般）" };
const RATE_AT_106 = 5.55; // CosyVoice3 在 1.06 倍时实测约 5.55 字/秒（有声部分）

let R = null;        // 仓库里读到的原始数据
let E = null;        // 正在编辑的副本：{ cfg, ch: {id: {json, brief}} }
let cur = null;      // 当前选中的频道 id

// ───── 路径读写 ─────
const get = (o, p) => p.split(".").reduce((x, k) => (x == null ? undefined : x[k]), o);
function set(o, p, v) {
  const ks = p.split(".");
  let x = o;
  ks.slice(0, -1).forEach((k) => { if (typeof x[k] !== "object" || x[k] === null) x[k] = {}; x = x[k]; });
  if (v === undefined || v === "") delete x[ks[ks.length - 1]];
  else x[ks[ks.length - 1]] = v;
}

// ───── 表单定义 ─────
const FIELDS = [
  { sec: "基本信息" },
  { k: "name", label: "频道名", type: "text", help: "最好 4–6 个字，最多 8 个字，显示在画面顶部和封面上" },
  { k: "slogan", label: "口号", type: "text", help: "最多 12 个字，显示在封面和结尾的「关注我」按钮上" },
  { k: "audience", label: "观众", type: "text", help: "写给谁看，AI 按这个决定口吻和选题" },
  { k: "tone", label: "语气人设", type: "text", help: "例如「新闻主播式播报：简洁、客观」「像跟朋友聊天」" },
  { k: "hashtags", label: "固定话题", type: "list", help: "用逗号或空格分隔，第一个是频道的固定话题" },
  { k: "collection", label: "抖音合集名", type: "text" },
  { sec: "时间（北京时间）" },
  { k: "schedule.publish", label: "发布时间", type: "time", help: "插件到这个时间才发布；00:00 表示视频到了就发" },
  { k: "schedule.make", label: "开始制作", type: "time", help: "只是记录。改了要在你的 AI 工具里同步修改定时任务" },
  { k: "schedule.days_ahead", label: "每次多做几天", type: "number", min: 0, max: 3, help: "1 = 每次做今天和明天两期，留一天余量" },
  { sec: "篇幅" },
  { k: "items", label: "每期几段（最少–最多）", type: "range" },
  { k: "say_chars", label: "每段口播字数（最少–最多）", type: "range" },
  { k: "say_total", label: "整期口播总字数（最少–最多）", type: "range" },
  { k: "max_seconds", label: "时长上限（秒）", type: "number", min: 20, max: 180, help: "超过就要求 AI 删稿；语速是固定的" },
  { sec: "画面文字" },
  { k: "hook", label: "开场形式", type: "hook", help: "开场画面的大字显示什么" },
  { k: "hook_unit", label: "开场单位", type: "text", help: "开场形式为「今日 N 条」时用，例如「条热点」「个知识点」" },
  { k: "label", label: "开场标签", type: "text", help: "开场分类标签前的文字，最多 5 个字，例如「本期涉及」" },
  { k: "src", label: "来源前缀", type: "text", help: "画面底部来源说明，例如「信息来源：公开报道」" },
  { k: "deco", label: "装饰英文", type: "deco", help: "画面左下角的两行大号英文，例如 HOT / NEWS" },
  { sec: "配色" },
  { k: "theme", label: "配色方案", type: "palette" },
  { sec: "开场与结尾口播" },
  { k: "intro", label: "开场白模板", type: "text", help: "可用 {name} {date} {n} {topic_say} {categories}" },
  { k: "outro", label: "结尾口播", type: "text" },
  { sec: "配音" },
  { k: "voice.mood", label: "默认语气", type: "mood" },
  { k: "voice.intro_mood", label: "开场语气", type: "mood" },
  { k: "voice.outro_mood", label: "结尾语气", type: "mood" },
  { k: "voice.voice", label: "音色", type: "voice", help: "留空跟随全局设置" },
  { k: "voice.speed", label: "语速倍率", type: "speed", help: "1 为默认；整期统一，不会忽快忽慢" },
];

// ───── 拉取 ─────
async function pull() {
  if (window.__saveRepoToken) await window.__saveRepoToken(); // 刚填的仓库和令牌还没保存时先存上
  $("chState").textContent = "正在从仓库拉取…";
  $("chPull").disabled = $("chSave").disabled = true;
  try {
    R = await loadRepo();
    E = { cfg: structuredClone(R.cfg.json), ch: {} };
    for (const c of R.channels) E.ch[c.id] = { json: structuredClone(c.json), brief: c.brief.text ?? "", broken: c.broken, raw: c.file.text };
    if (!cur || !E.ch[cur]) cur = (E.cfg.channels || [])[0] || (R.channels[0] && R.channels[0].id);
    $("chState").textContent = `${R.name} · ${R.def} · ${new Date().toLocaleTimeString("zh-CN", { hour12: false })} 拉取${R.private ? "" : " · ⚠️ 这是公开仓库"}`;
    render();
  } catch (e) {
    $("chState").textContent = "";
    $("chBody").innerHTML = `<div class="err">${esc(e.message)}</div>`;
  } finally {
    $("chPull").disabled = false;
    updateDirty();
  }
}

// ───── 改动检测 ─────
function changes() {
  if (!R) return [];
  const out = [];
  if (toJSON(E.cfg) !== toJSON(R.cfg.json)) out.push({ path: "autoreel.config.json", text: toJSON(E.cfg), sha: R.cfg.sha, label: "全局配置" });
  for (const c of R.channels) {
    const e = E.ch[c.id];
    if (!e.broken && toJSON(e.json) !== toJSON(c.json)) out.push({ path: `channels/${c.id}/channel.json`, text: toJSON(e.json), sha: c.file.sha, label: `${e.json.name || c.id} 设置`, id: c.id });
    if (e.brief !== (c.brief.text ?? "")) out.push({ path: `channels/${c.id}/brief.md`, text: e.brief.endsWith("\n") ? e.brief : e.brief + "\n", sha: c.brief.sha, label: `${(e.json && e.json.name) || c.id} 写稿规则`, id: c.id });
  }
  return out;
}
function updateDirty() {
  const n = changes().length;
  $("chSave").disabled = !n;
  $("chDirty").textContent = n ? `${n} 个文件有未保存的修改` : (R ? "和仓库一致" : "");
  $("chDirty").className = n ? "pill warn" : "pill ok";
  document.querySelectorAll(".chi").forEach((el) => {
    const id = el.dataset.id;
    el.classList.toggle("dirty", changes().some((c) => c.id === id));
  });
}

// ───── 校验（和 tools/check_channel.py 的主要规则一致）─────
function validate(id) {
  const c = E.ch[id].json, errs = [], warns = [];
  if (!c) return { errs: ["channel.json 不是合法的 JSON，请在「直接编辑 JSON」里修好"], warns };
  const hm = (v) => /^([01]\d|2[0-3]):[0-5]\d$/.test(v || "");
  if (!c.name) errs.push("频道名不能为空");
  else if (c.name.length > 8) warns.push("频道名超过 8 个字，画面上会被缩小");
  if ((c.slogan || "").length > 12) warns.push("口号超过 12 个字，结尾按钮可能放不下");
  const sc = c.schedule || {};
  if (!hm(sc.publish)) errs.push("发布时间格式应为 HH:MM");
  if (sc.make && !hm(sc.make)) errs.push("开始制作时间格式应为 HH:MM");
  if (hm(sc.make) && hm(sc.publish) && sc.publish !== "00:00") {
    const m = (t) => +t.slice(0, 2) * 60 + +t.slice(3);
    const gap = m(sc.publish) - m(sc.make);
    if ((sc.days_ahead || 0) === 0 && gap < 45) warns.push(`制作只比发布早 ${gap} 分钟，CosyVoice 一期要 15–25 分钟，建议至少提前 45 分钟`);
  }
  for (const k of ["items", "say_chars", "say_total"]) {
    const v = c[k];
    if (!Array.isArray(v) || v.length !== 2 || !(v[0] > 0) || !(v[1] >= v[0])) errs.push(`${FIELDS.find((f) => f.k === k).label} 要填两个数，后一个不小于前一个`);
  }
  if (!(c.max_seconds >= 20)) errs.push("时长上限至少 20 秒");
  if (Array.isArray(c.items) && Array.isArray(c.say_total) && c.max_seconds) {
    const est = (c.say_total[1] + 50) / 4.6 + 3;
    if (est > c.max_seconds + 5) warns.push(`按总字数上限估算约 ${Math.round(est)} 秒，超过时长上限 ${c.max_seconds} 秒，AI 会经常被要求删稿`);
  }
  const v = c.voice || {};
  for (const k of ["mood", "intro_mood", "outro_mood"]) if (v[k] && !MOODS.includes(v[k])) errs.push(`语气「${v[k]}」不在可选范围内`);
  if (v.speed != null && !(v.speed >= 0.8 && v.speed <= 1.25)) errs.push("语速倍率应在 0.8–1.25 之间");
  if (v.voice && R.voices.length && !R.voices.includes(v.voice)) warns.push(`仓库 tools/voices/ 里没有「${v.voice}」这个音色`);
  if (!(c.hashtags || []).length) warns.push("没有固定话题");
  if (!E.ch[id].brief.trim()) errs.push("写稿规则（brief.md）不能为空，AI 靠它找选题和写稿");
  return { errs, warns };
}

// ───── 渲染 ─────
function rateText(f) {
  const v = E.cfg.voice || {};
  const p = v.provider || "auto";
  if (p === "sherpa" || p === "volcengine") return `约 ${f.toFixed(2)} 倍`;
  const base = (v.cosyvoice && v.cosyvoice.speed) || 1.06;
  return `约 ${(RATE_AT_106 * base / 1.06 * f).toFixed(1)} 字/秒`;
}

function fieldHTML(f, c) {
  const val = get(c, f.k);
  const id = `f_${f.k.replace(/\./g, "_")}`;
  let input;
  switch (f.type) {
    case "list": input = `<input type="text" id="${id}" value="${esc((val || []).join("，"))}" />`; break;
    case "time": input = `<input type="time" id="${id}" value="${esc(val || "")}" />`; break;
    case "number": input = `<input type="number" id="${id}" min="${f.min ?? ""}" max="${f.max ?? ""}" value="${esc(val ?? "")}" />`; break;
    case "range": input = `<span class="rng"><input type="number" id="${id}_0" min="1" value="${esc(val ? val[0] : "")}" /><span>–</span><input type="number" id="${id}_1" min="1" value="${esc(val ? val[1] : "")}" /></span>`; break;
    case "mood": input = `<select id="${id}"><option value="">（不设置）</option>${MOODS.map((m) => `<option ${m === val ? "selected" : ""}>${m}</option>`).join("")}</select>`; break;
    case "voice": input = `<select id="${id}"><option value="">跟随全局（${esc(get(E.cfg, "voice.cosyvoice.voice") || "女声")}）</option>${R.voices.map((m) => `<option ${m === val ? "selected" : ""}>${esc(m)}</option>`).join("")}</select>`; break;
    case "speed": {
      const s = val ?? 1;
      input = `<span class="spd"><input type="range" id="${id}" min="0.85" max="1.2" step="0.01" value="${s}" /><b id="${id}_t">${s.toFixed(2)}× · ${rateText(s)}</b><button class="btn sm" type="button" id="${id}_r">恢复默认</button></span>`;
      break;
    }
    case "hook": {
      const H = { count: "今日 N 条（合集类，如热点快报）", topic: "话题大字（一期讲一个主题）", date: "日期大字（每日一 X、历史上的今天）" };
      input = `<select id="${id}">${Object.entries(H).map(([k, t]) => `<option value="${k}" ${k === (val || "count") ? "selected" : ""}>${esc(t)}</option>`).join("")}</select>`;
      break;
    }
    case "deco": {
      const [a = "", b = ""] = String(val || "").split(/<br\s*\/?>/i).map((x) => x.trim());
      input = `<span class="rng"><input type="text" id="${id}_0" value="${esc(a)}" placeholder="第一行" /><input type="text" id="${id}_1" value="${esc(b)}" placeholder="第二行" /></span>`;
      break;
    }
    case "palette": {
      const names = Object.keys(R.palettes).filter((k) => !k.startsWith("_"));
      const curName = names.find((n) => val && R.palettes[n].flow === val.flow) || "";
      input = `<select id="${id}">${curName ? "" : '<option value="">当前配色（自定义）</option>'}${names.map((n) => `<option value="${esc(n)}" ${n === curName ? "selected" : ""}>${esc(n)}（${esc(R.palettes[n].mood || "")}）</option>`).join("")}</select>
        <div class="pal" id="${id}_pv"></div>`;
      break;
    }
    default: input = `<input type="text" id="${id}" value="${esc(val ?? "")}" />`;
  }
  const wide = ["palette", "speed"].includes(f.type) || ["tone", "intro", "outro"].includes(f.k);
  return `<label class="field${wide ? " wide" : ""}"><span class="label">${esc(f.label)}</span>${input}${f.help ? `<span class="help">${esc(f.help)}</span>` : ""}</label>`;
}

function bindField(f, id) {
  const fid = `f_${f.k.replace(/\./g, "_")}`;
  const c = () => E.ch[id].json;
  const done = () => { showChecks(id); updateDirty(); renderList(); };
  if (f.type === "range") {
    const h = () => {
      const a = $(`${fid}_0`).value, b = $(`${fid}_1`).value;
      set(c(), f.k, a === "" && b === "" ? undefined : [Number(a), Number(b)]);
      done();
    };
    $(`${fid}_0`).oninput = $(`${fid}_1`).oninput = h;
    return;
  }
  if (f.type === "deco") {
    const h = () => {
      const a = $(`${fid}_0`).value.trim(), b = $(`${fid}_1`).value.trim();
      set(c(), f.k, a || b ? [a, b].filter(Boolean).join("<br />") : undefined);
      done();
    };
    $(`${fid}_0`).oninput = $(`${fid}_1`).oninput = h;
    return;
  }
  const el = $(fid);
  if (f.type === "palette") {
    const pv = () => palettePreview($(`${fid}_pv`), c());
    pv();
    el.onchange = () => {
      const p = R.palettes[el.value];
      if (p) c().theme = { flow: p.flow, base: p.base, glows: [...p.glows], mark: p.mark, stops: structuredClone(p.stops) };
      pv();
      done();
    };
    return;
  }
  if (f.type === "speed") {
    const h = (v) => {
      $(`${fid}_t`).textContent = `${v.toFixed(2)}× · ${rateText(v)}`;
      set(c(), f.k, Math.abs(v - 1) < 0.005 ? undefined : Math.round(v * 100) / 100);
      done();
    };
    el.oninput = () => h(Number(el.value));
    $(`${fid}_r`).onclick = () => { el.value = 1; h(1); };
    return;
  }
  el.oninput = el.onchange = () => {
    let v = el.value;
    if (f.type === "number") v = v === "" ? undefined : Number(v);
    if (f.type === "list") v = v.split(/[，,\s#]+/).map((x) => x.trim()).filter(Boolean);
    set(c(), f.k, v);
    done();
  };
}

function renderList() {
  const on = new Set(E.cfg.channels || []);
  $("chList").innerHTML = R.channels.map((c) => {
    const j = E.ch[c.id].json || {};
    return `<div class="chi ${c.id === cur ? "on" : ""}" data-id="${esc(c.id)}">
      <label class="switch" title="启用"><input type="checkbox" data-en="${esc(c.id)}" ${on.has(c.id) ? "checked" : ""} /><span></span></label>
      <div class="nm"><b>${esc(j.name || c.id)}</b><span>${esc(c.id)} · ${esc(get(j, "schedule.publish") || "--:--")} 发布</span></div><i class="dot"></i></div>`;
  }).join("");
  $("chList").querySelectorAll(".chi").forEach((el) => el.addEventListener("click", (ev) => {
    if (ev.target.closest(".switch")) return;
    cur = el.dataset.id;
    render();
  }));
  $("chList").querySelectorAll("input[data-en]").forEach((el) => el.addEventListener("change", () => {
    const list = R.channels.map((c) => c.id).filter((id) => (id === el.dataset.en ? el.checked : (E.cfg.channels || []).includes(id)));
    // 保持原来的顺序，新启用的排到后面
    const old = (E.cfg.channels || []).filter((id) => list.includes(id));
    E.cfg.channels = [...old, ...list.filter((id) => !old.includes(id))];
    updateDirty();
  }));
  updateDirty();
}

function palettePreview(el, c) {
  const t = c.theme || {};
  const glows = (t.glows || []).map((g, i) => `radial-gradient(circle at ${[20, 80, 30, 75][i % 4]}% ${[25, 30, 80, 75][i % 4]}%, ${g}88, transparent 45%)`).join(",");
  el.innerHTML = `<div class="pv" style="background:${glows ? glows + "," : ""}linear-gradient(135deg, ${t.flow || "#333, #555"})">
    <i style="background:${esc(t.mark || "#fff")}"></i><b>${esc(c.name || "")}</b><span>${esc(c.slogan || "")}</span></div>
    <div class="sw">${[t.base, ...(t.glows || []), t.mark].filter(Boolean).map((x) => `<span style="background:${esc(x)}" title="${esc(x)}"></span>`).join("")}</div>`;
}

function renderContent() {
  const ct = E.cfg.content || (E.cfg.content = {});
  const pb = E.cfg.publish || (E.cfg.publish = {});
  $("gContent").innerHTML = `
    <label class="field"><span class="label">可信来源</span><textarea id="g_src" rows="2">${esc((ct.trusted_sources || []).join("，"))}</textarea>
      <span class="help">AI 找资料时优先采信这些媒体和机构；只出现在热搜或营销号里的不算。用逗号分隔。</span></label>
    <label class="field"><span class="label">分类池</span><textarea id="g_cat" rows="2">${esc((ct.categories || []).join("，"))}</textarea>
      <span class="help">热点类频道每条新闻打的分类标签从这里选，也决定选题覆盖面。用逗号分隔。</span></label>
    <label class="field"><span class="label">AI 内容声明</span><input type="text" id="g_decl" value="${esc(pb.declaration || "内容由AI生成")}" />
      <span class="help">画面常驻的标识文字和发布时的声明，平台要求标注，请不要删掉。</span></label>`;
  const list = (v) => v.split(/[，,、\s]+/).map((x) => x.trim()).filter(Boolean);
  $("g_src").oninput = () => { ct.trusted_sources = list($("g_src").value); updateDirty(); };
  $("g_cat").oninput = () => { ct.categories = list($("g_cat").value); updateDirty(); };
  $("g_decl").oninput = () => { pb.declaration = $("g_decl").value.trim() || "内容由AI生成"; updateDirty(); };
}

function renderGlobal() {
  renderContent();
  const v = E.cfg.voice || (E.cfg.voice = {});
  const cv = v.cosyvoice || (v.cosyvoice = {});
  const s = cv.speed ?? 1.06;
  $("gVoice").innerHTML = `
    <div class="grid2">
      <label class="field"><span class="label">配音引擎</span><select id="g_provider">${Object.entries(PROVIDERS).map(([k, t]) => `<option value="${k}" ${k === (v.provider || "auto") ? "selected" : ""}>${esc(t)}</option>`).join("")}</select></label>
      <label class="field"><span class="label">默认音色（CosyVoice）</span><select id="g_voice">${R.voices.map((m) => `<option ${m === (cv.voice || "女声") ? "selected" : ""}>${esc(m)}</option>`).join("")}</select></label>
    </div>
    <label class="field"><span class="label">基础语速（CosyVoice）</span><span class="spd"><input type="range" id="g_speed" min="0.9" max="1.25" step="0.01" value="${s}" /><b id="g_speed_t">${s.toFixed(2)}× · 约 ${(RATE_AT_106 * s / 1.06).toFixed(1)} 字/秒</b><button class="btn sm" type="button" id="g_speed_r">恢复 1.06</button></span>
      <span class="help">所有频道的基础语速；单个频道可以在下面再设倍率。资讯类短视频常见 5–6 字/秒。</span></label>
    <label class="check" style="margin-top:10px"><input type="checkbox" id="g_qc" ${v.qc !== false ? "checked" : ""} /> 清晰度检查（配音后用语音识别逐段比对，没念清楚的自动重做）</label>`;
  $("g_provider").onchange = () => { v.provider = $("g_provider").value; updateDirty(); render(); };
  $("g_voice").onchange = () => { cv.voice = $("g_voice").value; updateDirty(); };
  const sp = (x) => { cv.speed = Math.round(x * 100) / 100; $("g_speed").value = x; $("g_speed_t").textContent = `${x.toFixed(2)}× · 约 ${(RATE_AT_106 * x / 1.06).toFixed(1)} 字/秒`; updateDirty(); };
  $("g_speed").oninput = () => sp(Number($("g_speed").value));
  $("g_speed_r").onclick = () => sp(1.06);
  $("g_qc").onchange = () => { v.qc = $("g_qc").checked; updateDirty(); };
}

function showChecks(id) {
  const { errs, warns } = validate(id);
  $("chChecks").innerHTML = errs.length || warns.length
    ? errs.map((e) => `<div class="err">✗ ${esc(e)}</div>`).join("") + warns.map((w) => `<div class="wrn">· ${esc(w)}</div>`).join("")
    : '<div class="okk">✓ 检查通过</div>';
}

function render() {
  renderList();
  renderGlobal();
  const e = E.ch[cur];
  if (!e) { $("chBody").innerHTML = '<div class="muted">仓库里还没有频道。</div>'; return; }
  if (e.broken) {
    $("chBody").innerHTML = `<div class="err">channels/${esc(cur)}/channel.json 不是合法的 JSON，插件不能安全地编辑它。请在仓库里修好，或者让 AI 帮你修。</div>`;
    return;
  }
  const c = e.json;
  let html = "", open = false;
  for (const f of FIELDS) {
    if (f.sec) { html += `${open ? "</div>" : ""}<h3>${esc(f.sec)}</h3><div class="grid2">`; open = true; continue; }
    html += fieldHTML(f, c);
  }
  html += "</div>";
  html += `<h3>写稿规则 <span class="muted">channels/${esc(cur)}/brief.md</span></h3>
    <p class="help">AI 每次找选题、写稿都照这里做：去哪找素材、选什么不选什么、每段怎么写、画面偏好。</p>
    <textarea id="f_brief" rows="16">${esc(e.brief)}</textarea>
    <details class="adv"><summary>直接编辑 JSON（其他字段：配色、开场形式、装饰文字等）</summary>
      <textarea id="f_json" rows="18"></textarea>
      <div style="display:flex;gap:8px;margin-top:8px"><button class="btn sm" type="button" id="f_json_apply">应用</button><span class="help" id="f_json_msg"></span></div>
    </details>`;
  $("chBody").innerHTML = html;
  for (const f of FIELDS) if (!f.sec) bindField(f, cur);
  $("f_brief").oninput = () => { e.brief = $("f_brief").value; showChecks(cur); updateDirty(); };
  const adv = $("chBody").querySelector("details.adv");
  adv.addEventListener("toggle", () => { if (adv.open) $("f_json").value = toJSON(e.json); });
  $("f_json_apply").onclick = () => {
    try {
      const j = JSON.parse($("f_json").value);
      if (j.id !== cur) throw new Error(`id 必须是 ${cur}`);
      e.json = j;
      render();
      toast("已应用，记得保存到仓库");
    } catch (err) {
      $("f_json_msg").textContent = `不能应用：${err.message}`;
    }
  };
  showChecks(cur);
}

function toast(t) {
  const el = $("toast");
  el.textContent = t;
  el.classList.add("show");
  setTimeout(() => el.classList.remove("show"), 2500);
}

// ───── 保存 ─────
async function save() {
  const files = changes();
  if (!files.length) return;
  const ids = [...new Set(files.filter((f) => f.id).map((f) => f.id))];
  for (const id of ids) {
    const { errs } = validate(id);
    if (errs.length) { cur = id; render(); return toast(`「${E.ch[id].json.name || id}」还有错误，改好再保存`); }
  }
  const notes = [];
  for (const id of ids) {
    const was = R.channels.find((c) => c.id === id).json, now = E.ch[id].json;
    if (get(was, "schedule.make") !== get(now, "schedule.make")) notes.push(`「${now.name}」的制作时间改了：记得在你的 AI 工具里同步修改定时任务`);
  }
  const newly = (E.cfg.channels || []).filter((id) => !(R.cfg.json.channels || []).includes(id));
  if (newly.length) notes.push(`新启用了 ${newly.join("、")}：还要在你的 AI 工具里为它建定时任务（或对 AI 说「帮我设置自影的定时任务」）`);
  const msg = `自影插件：修改 ${files.map((f) => f.label).join("、")}`;
  if (!confirm(`将提交到仓库 ${R.name} 的 ${R.def} 分支：\n\n${files.map((f) => "· " + f.path).join("\n")}\n\n提交说明：${msg}${notes.length ? "\n\n注意：\n" + notes.join("\n") : ""}`)) return;
  $("chSave").disabled = true;
  $("chState").textContent = "正在保存到仓库…";
  try {
    await saveFiles(R.def, files.map(({ path, text, sha }) => ({ path, text, sha })), msg);
    toast("已保存到仓库，下一期制作就会用上");
    await chrome.runtime.sendMessage({ type: "refreshChannels" }).catch(() => {});
    await pull();
    if (notes.length) setTimeout(() => alert(notes.join("\n\n")), 300);
  } catch (e) {
    $("chState").textContent = "";
    toast(e.conflict ? "仓库已被修改，请先拉取" : "保存失败");
    alert(e.message);
    updateDirty();
  }
}

// ───── 入口 ─────
$("chPull").onclick = () => {
  if (changes().length && !confirm("有未保存的修改，重新拉取会丢掉它们。继续吗？")) return;
  pull();
};
$("chSave").onclick = save;
window.addEventListener("beforeunload", (e) => { if (changes().length) { e.preventDefault(); e.returnValue = ""; } });
let loaded = false;
function onTab() {
  if ((location.hash || "").slice(1) === "channels" && !loaded) { loaded = true; pull(); }
}
window.addEventListener("hashchange", onTab);
onTab();
