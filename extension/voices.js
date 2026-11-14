// 自影 · 设置页「音色」：试听 tools/voices/ 里的参考录音，设默认音色，上传或录制自己的声音做新音色
import { headOf, listDir, readText, readBlob, saveFiles, blobToBase64 } from "./repo.js";

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const BUILTIN = ["女声", "男声"];
const SCRIPT = "大家好，欢迎收看今天的节目。接下来，我们一起看看这几天大家都在关注的几件事。";
const SR = 24000;
let H = null, cfg = null, voices = [], loaded = false;
let rec = null, made = null; // 录音器；处理好的新音色 {blob, seconds}

function toast(t) { const el = $("toast"); el.textContent = t; el.classList.add("show"); setTimeout(() => el.classList.remove("show"), 2500); }

async function pull() {
  if (window.__saveRepoToken) await window.__saveRepoToken();
  $("vcState").textContent = "正在从仓库拉取…";
  try {
    H = await headOf();
    const c = await readText("autoreel.config.json", H.head);
    cfg = { sha: c.sha, json: JSON.parse(c.text) };
    const dirs = (await listDir("tools/voices", H.head)).filter((d) => d.type === "dir");
    voices = await Promise.all(dirs.map(async (d) => ({ name: d.name, text: (await readText(`tools/voices/${d.name}/prompt.txt`, H.head)).text || "" })));
    $("vcState").textContent = `${H.name} · ${new Date().toLocaleTimeString("zh-CN", { hour12: false })} 拉取`;
    render();
  } catch (e) {
    $("vcState").textContent = "";
    $("vcList").innerHTML = `<div class="err">${esc(e.message)}</div>`;
  }
}

function render() {
  const def = ((cfg.json.voice || {}).cosyvoice || {}).voice || "女声";
  $("vcList").innerHTML = voices.map((v, i) => `
    <div class="vc">
      <div class="vc-m"><b>${esc(v.name)}</b>${v.name === def ? '<span class="pill brand plain">默认</span>' : ""}${BUILTIN.includes(v.name) ? '<span class="pill plain">内置</span>' : ""}
        <div class="muted">${esc(v.text)}</div></div>
      <button class="btn sm" type="button" data-play="${i}">试听</button>
      ${v.name === def ? "" : `<button class="btn sm" type="button" data-def="${i}">设为默认</button>`}
      ${BUILTIN.includes(v.name) ? "" : `<button class="btn sm danger" type="button" data-rm="${i}">删除</button>`}
      <audio data-au="${i}" controls hidden></audio>
    </div>`).join("");
  $("vcList").querySelectorAll("[data-play]").forEach((b) => b.onclick = async () => {
    const v = voices[+b.dataset.play], au = $("vcList").querySelector(`[data-au="${b.dataset.play}"]`);
    b.textContent = "加载中…";
    try {
      if (!au.src) au.src = URL.createObjectURL(await readBlob(`tools/voices/${v.name}/prompt.wav`, H.head, "audio/wav"));
      au.hidden = false;
      au.play();
    } catch (e) { toast(e.message); }
    b.textContent = "试听";
  });
  $("vcList").querySelectorAll("[data-def]").forEach((b) => b.onclick = async () => {
    const v = voices[+b.dataset.def];
    const j = structuredClone(cfg.json);
    ((j.voice = j.voice || {}).cosyvoice = j.voice.cosyvoice || {}).voice = v.name;
    await commit([{ path: "autoreel.config.json", text: JSON.stringify(j, null, 2) + "\n", sha: cfg.sha }], `自影插件：默认音色改为 ${v.name}`, `默认音色已改为「${v.name}」，下一期起生效`);
  });
  $("vcList").querySelectorAll("[data-rm]").forEach((b) => b.onclick = async () => {
    const v = voices[+b.dataset.rm];
    const def = ((cfg.json.voice || {}).cosyvoice || {}).voice;
    if (v.name === def) return toast("这是默认音色，先把别的音色设为默认再删除");
    if (!confirm(`删除音色「${v.name}」？用到它的频道会出错，请先在「频道」页把它们的音色改掉。`)) return;
    const files = (await listDir(`tools/voices/${v.name}`, H.head)).filter((x) => x.type === "file").map((x) => ({ path: x.path, delete: true, sha: x.sha }));
    await commit(files, `自影插件：删除音色 ${v.name}`, "已删除");
  });
}

async function commit(files, msg, ok) {
  try {
    await saveFiles(H.def, files, msg);
    toast(ok);
    await pull();
    return true;
  } catch (e) {
    toast(e.conflict ? "仓库已被修改，请先拉取" : "保存失败");
    alert(e.message);
    return false;
  }
}

// ───── 新音色：处理成 24kHz 单声道 WAV，去掉首尾静音 ─────
async function processAudio(blob) {
  const ac = new AudioContext();
  const src = await ac.decodeAudioData(await blob.arrayBuffer());
  ac.close();
  const off = new OfflineAudioContext(1, Math.ceil(src.duration * SR), SR);
  const node = off.createBufferSource();
  node.buffer = src;
  node.connect(off.destination);
  node.start();
  const out = (await off.startRendering()).getChannelData(0);
  // 去首尾静音（保留 0.15 秒）
  let peak = 0;
  for (const v of out) peak = Math.max(peak, Math.abs(v));
  if (peak < 0.01) throw new Error("几乎没有声音，检查麦克风或文件");
  const thr = peak * 0.05, keep = Math.round(SR * 0.15);
  let a = 0, b = out.length - 1;
  while (a < b && Math.abs(out[a]) < thr) a++;
  while (b > a && Math.abs(out[b]) < thr) b--;
  const pcm = out.subarray(Math.max(0, a - keep), Math.min(out.length, b + keep));
  const gain = 0.9 / peak;
  const buf = new ArrayBuffer(44 + pcm.length * 2), dv = new DataView(buf);
  const w = (o, s) => [...s].forEach((c, i) => dv.setUint8(o + i, c.charCodeAt(0)));
  w(0, "RIFF"); dv.setUint32(4, 36 + pcm.length * 2, true); w(8, "WAVE"); w(12, "fmt ");
  dv.setUint32(16, 16, true); dv.setUint16(20, 1, true); dv.setUint16(22, 1, true); dv.setUint32(24, SR, true);
  dv.setUint32(28, SR * 2, true); dv.setUint16(32, 2, true); dv.setUint16(34, 16, true); w(36, "data"); dv.setUint32(40, pcm.length * 2, true);
  for (let i = 0; i < pcm.length; i++) dv.setInt16(44 + i * 2, Math.max(-1, Math.min(1, pcm[i] * gain)) * 0x7fff, true);
  return { blob: new Blob([buf], { type: "audio/wav" }), seconds: pcm.length / SR };
}

async function useAudio(blob) {
  $("nvInfo").textContent = "处理中…";
  try {
    made = await processAudio(blob);
    $("nvAudio").src = URL.createObjectURL(made.blob);
    $("nvAudio").hidden = false;
    const s = made.seconds;
    $("nvInfo").innerHTML = s < 3 ? `<span class="err">只有 ${s.toFixed(1)} 秒，太短了，至少 5 秒</span>` : s > 20 ? `<span class="err">${s.toFixed(1)} 秒，太长了，最多 20 秒（5–15 秒最好）</span>` : `✓ ${s.toFixed(1)} 秒，听一下有没有杂音、读得是否自然`;
  } catch (e) {
    made = null;
    $("nvInfo").innerHTML = `<span class="err">${esc(e.message)}</span>`;
  }
  check();
}

function check() {
  const name = $("nvName").value.trim();
  const ok = made && made.seconds >= 3 && made.seconds <= 20 && /^[\p{L}\p{N}_-]{1,12}$/u.test(name) && !voices.find((v) => v.name === name) && $("nvText").value.trim().length >= 8 && $("nvConsent").checked;
  $("nvSave").disabled = !ok;
}

$("nvText").value = SCRIPT;
$("nvFile").onchange = () => { if ($("nvFile").files[0]) useAudio($("nvFile").files[0]); };
$("nvUpload").onclick = () => $("nvFile").click();
$("nvRec").onclick = async () => {
  if (rec) { rec.stop(); return; }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
    const chunks = [];
    rec = new MediaRecorder(stream);
    rec.ondataavailable = (e) => chunks.push(e.data);
    rec.onstop = () => {
      stream.getTracks().forEach((t) => t.stop());
      rec = null;
      $("nvRec").textContent = "重新录音";
      $("nvRec").classList.remove("danger");
      useAudio(new Blob(chunks, { type: chunks[0] && chunks[0].type }));
    };
    rec.start();
    $("nvRec").textContent = "停止录音";
    $("nvRec").classList.add("danger");
    $("nvInfo").textContent = "录音中……按正常说话的语气，把上面的文字完整读一遍";
  } catch (e) {
    toast("没有拿到麦克风权限");
  }
};
["nvName", "nvText"].forEach((id) => $(id).addEventListener("input", check));
$("nvConsent").onchange = check;
$("nvSave").onclick = async () => {
  const name = $("nvName").value.trim();
  const files = [
    { path: `tools/voices/${name}/prompt.wav`, base64: await blobToBase64(made.blob), sha: null },
    { path: `tools/voices/${name}/prompt.txt`, text: $("nvText").value.trim() + "\n", sha: null },
  ];
  $("nvSave").disabled = true;
  if (await commit(files, `自影插件：新增音色 ${name}`, `音色「${name}」已保存，可以在「频道」页给频道选用`)) {
    made = null; $("nvAudio").hidden = true; $("nvName").value = ""; $("nvInfo").textContent = ""; $("nvConsent").checked = false;
  }
  check();
};
$("vcPull").onclick = pull;
function onTab() { if ((location.hash || "").slice(1) === "voices" && !loaded) { loaded = true; pull(); } }
window.addEventListener("hashchange", onTab);
onTab();
