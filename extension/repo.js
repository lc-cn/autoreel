// 自影 · 插件里读写仓库里的频道配置（设置页「频道」用）
// 读：GitHub contents 接口（默认分支）；写：一次提交写入多个文件（git trees + commits），提交前检查远端有没有被改过。

async function settings() {
  const { settings = {} } = await chrome.storage.local.get("settings");
  if (!settings.repo) throw new Error("先在「基本设置」里填写 GitHub 仓库并保存");
  if (!settings.token) throw new Error("先在「基本设置」里填写 GitHub 令牌并保存");
  return settings;
}

async function api(path, { method = "GET", body } = {}) {
  const s = await settings();
  const r = await fetch(`https://api.github.com/repos/${s.repo}${path ? "/" + path : ""}`, {
    method,
    headers: { Authorization: `Bearer ${s.token}`, Accept: "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28", ...(body ? { "Content-Type": "application/json" } : {}) },
    body: body ? JSON.stringify(body) : undefined,
    cache: "no-store",
  });
  if (!r.ok) {
    let msg = "";
    try { msg = (await r.json()).message || ""; } catch {}
    const e = new Error(
      r.status === 401 ? "令牌无效或已过期" :
      r.status === 403 ? `没有权限（令牌需要这个仓库的 Contents 读写权限）${msg ? "：" + msg : ""}` :
      r.status === 404 ? `找不到 ${path || "仓库"}` :
      `GitHub ${method} ${path} → HTTP ${r.status} ${msg}`);
    e.status = r.status;
    throw e;
  }
  return r.status === 204 ? null : r.json();
}

const b64decode = (b64) => new TextDecoder().decode(Uint8Array.from(atob(b64.replace(/\n/g, "")), (c) => c.charCodeAt(0)));

async function getFile(path, ref) {
  try {
    const j = await api(`contents/${encodeURI(path)}${ref ? `?ref=${encodeURIComponent(ref)}` : ""}`);
    return { path, sha: j.sha, text: b64decode(j.content) };
  } catch (e) {
    if (e.status === 404) return { path, sha: null, text: null };
    throw e;
  }
}

// 读取：默认分支、全局配置、所有频道（channel.json + brief.md）
export async function loadRepo() {
  const repo = await api("");
  const def = repo.default_branch;
  const head = (await api(`git/ref/heads/${encodeURIComponent(def)}`)).object.sha;
  const cfg = await getFile("autoreel.config.json", head);
  if (!cfg.text) throw new Error("仓库里没有 autoreel.config.json，确认这是自影仓库");
  const dirs = (await api(`contents/channels?ref=${head}`)).filter((x) => x.type === "dir").map((x) => x.name);
  const channels = await Promise.all(dirs.map(async (id) => {
    const [cj, br] = await Promise.all([getFile(`channels/${id}/channel.json`, head), getFile(`channels/${id}/brief.md`, head)]);
    if (!cj.text) return null;
    let json;
    try { json = JSON.parse(cj.text); } catch (e) { json = null; }
    return { id, file: cj, brief: br, json, broken: !json };
  }));
  let palettes = {};
  try { palettes = JSON.parse((await getFile("tools/palettes.json", head)).text || "{}"); } catch {}
  let voices = ["女声", "男声"];
  try { voices = (await api(`contents/tools/voices?ref=${head}`)).filter((x) => x.type === "dir").map((x) => x.name); } catch {}
  return { private: repo.private, name: repo.full_name, def, head, cfg: { ...cfg, json: JSON.parse(cfg.text) }, channels: channels.filter(Boolean), palettes, voices };
}

// 写入：files = [{path, text | base64 | delete:true, sha}]（sha 是读取时的版本，用来发现冲突；新文件 sha 为 null）
export async function saveFiles(def, files, message) {
  const head = (await api(`git/ref/heads/${encodeURIComponent(def)}`)).object.sha;
  const changed = [];
  for (const f of files) {
    const now = await getFile(f.path, head);
    if ((now.sha || null) !== (f.sha || null)) changed.push(f.path);
  }
  if (changed.length) {
    const e = new Error(`这些文件在你编辑期间被别人改过（可能是 AI 在标记「已做」或同步更新）：${changed.join("、")}。请先「从仓库拉取」，再重新修改。`);
    e.conflict = true;
    throw e;
  }
  const base = await api(`git/commits/${head}`);
  const entries = [];
  for (const f of files) {
    if (f.delete) entries.push({ path: f.path, mode: "100644", type: "blob", sha: null });
    else if (f.base64 != null) {
      const b = await api("git/blobs", { method: "POST", body: { content: f.base64, encoding: "base64" } });
      entries.push({ path: f.path, mode: "100644", type: "blob", sha: b.sha });
    } else entries.push({ path: f.path, mode: "100644", type: "blob", content: f.text });
  }
  const tree = await api("git/trees", { method: "POST", body: { base_tree: base.tree.sha, tree: entries } });
  const commit = await api("git/commits", { method: "POST", body: { message, tree: tree.sha, parents: [head] } });
  try {
    await api(`git/refs/heads/${encodeURIComponent(def)}`, { method: "PATCH", body: { sha: commit.sha, force: false } });
  } catch (e) {
    if (e.status === 422) {
      const c = new Error("保存时仓库刚好有新的提交，请「从仓库拉取」后再保存。");
      c.conflict = true;
      throw c;
    }
    throw e;
  }
  return commit.sha;
}

// 和 Python 端（json.dump(indent=2, ensure_ascii=False)）一致的格式
export const toJSON = (obj) => JSON.stringify(obj, null, 2) + "\n";

// 列目录：[{name, path, type: "file"|"dir", sha, size}]，不存在返回 []
export async function listDir(path, ref) {
  try {
    return await api(`contents/${encodeURI(path)}${ref ? `?ref=${encodeURIComponent(ref)}` : ""}`);
  } catch (e) {
    if (e.status === 404) return [];
    throw e;
  }
}

// 读文本文件（不存在返回 {text: null, sha: null}）
export const readText = getFile;

// 读二进制文件，返回 Blob（音频、图片、视频预览用；单个文件最大 100MB）
export async function readBlob(path, ref, type = "") {
  const s = await settings();
  const r = await fetch(`https://api.github.com/repos/${s.repo}/contents/${encodeURI(path)}${ref ? `?ref=${encodeURIComponent(ref)}` : ""}`, {
    headers: { Authorization: `Bearer ${s.token}`, Accept: "application/vnd.github.raw", "X-GitHub-Api-Version": "2022-11-28" },
    cache: "no-store",
  });
  if (!r.ok) throw new Error(`读取 ${path} 失败：HTTP ${r.status}`);
  const b = await r.blob();
  return type ? new Blob([b], { type }) : b;
}

// 默认分支和最新提交
export async function headOf() {
  const repo = await api("");
  const def = repo.default_branch;
  return { def, head: (await api(`git/ref/heads/${encodeURIComponent(def)}`)).object.sha, name: repo.full_name, private: repo.private };
}

// 成品分支 clip-日期-频道
export async function clipBranches() {
  const refs = await api("git/matching-refs/heads/clip-");
  return refs.map((r) => {
    const name = r.ref.replace("refs/heads/", "");
    const m = name.match(/^clip-(\d{4}-\d{2}-\d{2})-([a-z0-9_]+)$/);
    return m ? { name, date: m[1], channel: m[2], sha: r.object.sha } : null;
  }).filter(Boolean);
}

export const blobToBase64 = (blob) => new Promise((res, rej) => {
  const fr = new FileReader();
  fr.onload = () => res(String(fr.result).split(",")[1]);
  fr.onerror = rej;
  fr.readAsDataURL(blob);
});
