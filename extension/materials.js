// 自影 · 设置页「素材」：管理仓库 inputs/<频道>/ 里给 AI 用的资料（书单、产品资料、图片、视频）
import { headOf, listDir, readText, readBlob, saveFiles, blobToBase64 } from "./repo.js";

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const TEXT = /\.(md|txt|csv|json)$/i, IMG = /\.(jpe?g|png|webp|gif)$/i, VID = /\.(mp4|mov|webm|m4v)$/i;
const MAX_IMG = 10 << 20, MAX_VID = 50 << 20;
const TIPS = {
  dushu: "从上往下做，做完的书 AI 会在后面写「已做」；书单做完了 AI 会自己挑书并追加在末尾。",
  haowu: "AI 只用这里的资料写稿，不会自己编产品信息。图片和视频可以在稿子里用「你的素材」分镜：{\"type\":\"asset\",\"file\":\"inputs/haowu/文件名\"}。",
};
let H = null;          // {def, head, name}
let folders = [];      // [{id, name, files:[{name, path, sha, size, kind, text?, orig?, add?, del?, blob?}]}]
let names = {};        // 频道 id → 名称
let open = null;       // 展开的文件夹
let loaded = false;

function toast(t) { const el = $("toast"); el.textContent = t; el.classList.add("show"); setTimeout(() => el.classList.remove("show"), 2500); }
const kind = (n) => (TEXT.test(n) ? "text" : IMG.test(n) ? "img" : VID.test(n) ? "vid" : "other");
const size = (b) => (b >= 1 << 20 ? (b / (1 << 20)).toFixed(1) + " MB" : Math.max(1, Math.round(b / 1024)) + " KB");

function changes() {
  const out = [];
  for (const f of folders) for (const x of f.files) {
    if (x.del && x.sha) out.push({ path: x.path, delete: true, sha: x.sha, label: `删除 ${x.path}` });
    else if (x.add) out.push({ path: x.path, ...(x.kind === "text" ? { text: x.text } : { blob: x.blob }), sha: null, label: `新增 ${x.path}` });
    else if (x.kind === "text" && x.text != null && x.text !== x.orig) out.push({ path: x.path, text: x.text.endsWith("\n") ? x.text : x.text + "\n", sha: x.sha, label: `修改 ${x.path}` });
  }
  return out;
}
function updateDirty() {
  const n = changes().length;
  $("mtSave").disabled = !n;
  $("mtDirty").textContent = n ? `${n} 处未保存的修改` : (H ? "和仓库一致" : "");
  $("mtDirty").className = n ? "pill warn" : "pill ok";
}

async function pull() {
  if (window.__saveRepoToken) await window.__saveRepoToken();
  $("mtState").textContent = "正在从仓库拉取…";
  try {
    H = await headOf();
    const [dirs, chs] = await Promise.all([listDir("inputs", H.head), listDir("channels", H.head)]);
    names = {};
    await Promise.all(chs.filter((d) => d.type === "dir").map(async (d) => {
      try { names[d.name] = JSON.parse((await readText(`channels/${d.name}/channel.json`, H.head)).text).name || d.name; } catch { names[d.name] = d.name; }
    }));
    folders = await Promise.all(dirs.filter((d) => d.type === "dir").map(async (d) => ({
      id: d.name, name: names[d.name] || d.name,
      files: (await listDir(`inputs/${d.name}`, H.head)).filter((x) => x.type === "file").map((x) => ({ name: x.name, path: x.path, sha: x.sha, size: x.size, kind: kind(x.name) })),
    })));
    if (!open || !folders.find((f) => f.id === open)) open = folders[0] && folders[0].id;
    $("mtState").textContent = `${H.name} · ${H.def} · ${new Date().toLocaleTimeString("zh-CN", { hour12: false })} 拉取`;
    render();
  } catch (e) {
    $("mtState").textContent = "";
    $("mtBody").innerHTML = `<div class="err">${esc(e.message)}</div>`;
  }
  updateDirty();
}

function render() {
  const add = Object.keys(names).filter((id) => !folders.find((f) => f.id === id));
  $("mtBody").innerHTML = (folders.length ? folders.map((f) => `
    <div class="mf ${f.id === open ? "open" : ""}" data-id="${esc(f.id)}">
      <div class="mf-h"><b>${esc(f.name)}</b><span class="muted">inputs/${esc(f.id)}/ · ${f.files.filter((x) => !x.del).length} 个文件</span></div>
      <div class="mf-b">${f.id === open ? folderHTML(f) : ""}</div>
    </div>`).join("") : '<div class="muted">仓库里还没有素材文件夹。</div>') +
    (add.length ? `<div class="add" style="margin-top:14px"><select id="mtNew">${add.map((id) => `<option value="${esc(id)}">${esc(names[id])}（${esc(id)}）</option>`).join("")}</select><button class="btn sm" type="button" id="mtNewBtn">给这个频道加素材文件夹</button></div>` : "");
  $("mtBody").querySelectorAll(".mf-h").forEach((h) => h.onclick = () => { const id = h.parentElement.dataset.id; open = open === id ? null : id; render(); });
  if ($("mtNewBtn")) $("mtNewBtn").onclick = () => {
    const id = $("mtNew").value;
    folders.push({ id, name: names[id], files: [{ name: "资料.md", path: `inputs/${id}/资料.md`, sha: null, kind: "text", add: true, text: `# ${names[id]} · 素材\n\n在这里写给 AI 用的资料。记得在频道的写稿规则（brief.md）里写明「只用 inputs/${id}/ 里的资料」。\n`, orig: "" }] });
    open = id;
    render();
    updateDirty();
  };
  const f = folders.find((x) => x.id === open);
  if (f) bindFolder(f);
}

function folderHTML(f) {
  return `${TIPS[f.id] ? `<p class="help">${esc(TIPS[f.id])}</p>` : ""}
    <div class="files">${f.files.map((x, i) => fileHTML(x, i)).join("")}</div>
    <div class="add" style="margin-top:12px">
      <button class="btn sm" type="button" data-act="upload">上传图片 / 视频</button>
      <button class="btn sm" type="button" data-act="newtext">新建文本</button>
      <input type="file" data-act="file" accept="image/*,video/*" multiple hidden />
    </div>`;
}
function fileHTML(x, i) {
  const st = x.del ? '<span class="pill bad plain">将删除</span>' : x.add ? '<span class="pill warn plain">新增</span>' : "";
  const act = `<button class="btn sm ghost" type="button" data-copy="${i}" title="复制路径，写稿时用">复制路径</button><button class="btn sm ${x.del ? "" : "danger"}" type="button" data-del="${i}">${x.del ? "撤销删除" : "删除"}</button>`;
  if (x.kind === "text") return `<div class="fi txt ${x.del ? "gone" : ""}"><div class="fi-h"><b>${esc(x.name)}</b>${st}<span class="sp"></span>${act}</div>
      ${x.del ? "" : `<textarea data-text="${i}" rows="10" placeholder="加载中…">${x.text != null ? esc(x.text) : ""}</textarea>`}</div>`;
  return `<div class="fi med ${x.del ? "gone" : ""}"><div class="thumb" data-thumb="${i}">${x.kind === "img" ? "图片" : x.kind === "vid" ? "视频" : "文件"}</div>
      <div class="fi-m"><b>${esc(x.name)}</b>${st}<span class="muted">${x.size ? size(x.size) : ""}</span></div><span class="sp"></span>${act}</div>`;
}

function bindFolder(f) {
  const box = $("mtBody").querySelector(`.mf[data-id="${CSS.escape(f.id)}"]`);
  // 文本：首次展开时加载
  box.querySelectorAll("textarea[data-text]").forEach(async (ta) => {
    const x = f.files[+ta.dataset.text];
    if (x.text == null) {
      const r = await readText(x.path, H.head);
      x.text = x.orig = r.text ?? "";
      ta.value = x.text;
    }
    ta.oninput = () => { x.text = ta.value; updateDirty(); };
  });
  // 缩略图
  box.querySelectorAll("[data-thumb]").forEach(async (el) => {
    const x = f.files[+el.dataset.thumb];
    if (x.kind !== "img" && x.kind !== "vid") return;
    try {
      if (!x.blob) {
        if (x.size > MAX_VID) return;
        x.blob = await readBlob(x.path, H.head);
      }
      const u = URL.createObjectURL(x.blob);
      el.innerHTML = x.kind === "img" ? `<img src="${u}" alt="" />` : `<video src="${u}" muted preload="metadata"></video>`;
      el.onclick = () => window.open(u);
    } catch { el.textContent = "预览失败"; }
  });
  box.querySelectorAll("[data-del]").forEach((b) => b.onclick = () => {
    const i = +b.dataset.del, x = f.files[i];
    if (x.add) f.files.splice(i, 1); else x.del = !x.del;
    render(); updateDirty();
  });
  box.querySelectorAll("[data-copy]").forEach((b) => b.onclick = async () => {
    await navigator.clipboard.writeText(f.files[+b.dataset.copy].path);
    toast("已复制路径");
  });
  const fileIn = box.querySelector('[data-act="file"]');
  box.querySelector('[data-act="upload"]').onclick = () => fileIn.click();
  fileIn.onchange = () => {
    for (const file of fileIn.files) {
      const k = kind(file.name);
      if (k !== "img" && k !== "vid") { toast(`${file.name}：只支持图片和视频`); continue; }
      if (file.size > (k === "img" ? MAX_IMG : MAX_VID)) { toast(`${file.name} 太大（图片最大 10MB，视频最大 50MB）`); continue; }
      const name = file.name.replace(/[\\/:*?"<>|#%\s]+/g, "-");
      const exist = f.files.find((x) => x.name === name && !x.del);
      if (exist) { toast(`已有同名文件 ${name}，先删除旧的或改个名字`); continue; }
      f.files.push({ name, path: `inputs/${f.id}/${name}`, sha: null, size: file.size, kind: k, add: true, blob: file });
    }
    fileIn.value = "";
    render(); updateDirty();
  };
  box.querySelector('[data-act="newtext"]').onclick = () => {
    let name = prompt("文件名（.md 结尾）", "新资料.md");
    if (!name) return;
    name = name.replace(/[\\/:*?"<>|#%]+/g, "-");
    if (!TEXT.test(name)) name += ".md";
    if (f.files.find((x) => x.name === name && !x.del)) return toast("已有同名文件");
    f.files.push({ name, path: `inputs/${f.id}/${name}`, sha: null, kind: "text", add: true, text: "", orig: "" });
    render(); updateDirty();
  };
}

async function save() {
  const ch = changes();
  if (!ch.length) return;
  if (!confirm(`将提交到仓库 ${H.name} 的 ${H.def} 分支：\n\n${ch.map((c) => "· " + c.label).join("\n")}`)) return;
  $("mtSave").disabled = true;
  $("mtState").textContent = "正在上传…";
  try {
    const files = [];
    for (const c of ch) files.push(c.blob ? { path: c.path, base64: await blobToBase64(c.blob), sha: null } : { path: c.path, text: c.text, delete: c.delete, sha: c.sha });
    await saveFiles(H.def, files, `自影插件：更新素材 ${[...new Set(ch.map((c) => c.path.split("/")[1]))].map((id) => names[id] || id).join("、")}`);
    toast("素材已保存到仓库");
    await pull();
  } catch (e) {
    toast(e.conflict ? "仓库已被修改，请先拉取" : "保存失败");
    alert(e.message);
    $("mtState").textContent = "";
    updateDirty();
  }
}

$("mtPull").onclick = () => { if (changes().length && !confirm("有未保存的修改，重新拉取会丢掉它们。继续吗？")) return; pull(); };
$("mtSave").onclick = save;
window.addEventListener("beforeunload", (e) => { if (changes().length) { e.preventDefault(); e.returnValue = ""; } });
function onTab() { if ((location.hash || "").slice(1) === "materials" && !loaded) { loaded = true; pull(); } }
window.addEventListener("hashchange", onTab);
onTab();
