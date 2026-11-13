// 各平台内容脚本共用的工具：等待元素、上传文件、可信输入、进度上报、验证检测
(() => {
  if (window.KB) return;
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const send = (msg) => new Promise((res) => chrome.runtime.sendMessage(msg, (r) => res(r || {})));

  const visible = (el) => {
    if (!el || !el.isConnected) return false;
    const r = el.getBoundingClientRect();
    const st = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && st.visibility !== "hidden" && st.display !== "none";
  };
  // 在文档及所有开放的 shadowRoot 里查找（视频号的表单可能在 shadow DOM 里）
  function deepAll(sel, root = document) {
    const out = [...root.querySelectorAll(sel)];
    for (const el of root.querySelectorAll("*")) if (el.shadowRoot) out.push(...deepAll(sel, el.shadowRoot));
    return out;
  }
  const $ = (sel, root) => deepAll(sel, root)[0] || null;
  // 按文字找元素：exact=true 精确匹配，否则包含；只取最内层、可见的
  function byText(text, { sel = "*", exact = false, root, vis = true } = {}) {
    const cands = deepAll(sel, root).filter((el) => {
      const t = (el.innerText || el.textContent || "").trim();
      if (!(exact ? t === text : t.includes(text))) return false;
      return vis ? visible(el) : true;
    });
    // 取最深的（不含其他候选的那个）
    return cands.filter((el) => !cands.some((o) => o !== el && el.contains(o)))[0] || null;
  }
  async function waitFor(fn, ms = 30000, step = 500) {
    const t0 = Date.now();
    while (Date.now() - t0 < ms) {
      try {
        const v = await fn();
        if (v) return v;
      } catch (_) {}
      await sleep(step);
    }
    return null;
  }
  // 模拟一次完整的鼠标点击（部分组件只认 mousedown/mouseup）
  function tap(el) {
    if (!el) return false;
    el.scrollIntoView({ block: "center", inline: "center" });
    const r = el.getBoundingClientRect();
    const o = { bubbles: true, cancelable: true, composed: true, view: window, clientX: r.left + r.width / 2, clientY: r.top + r.height / 2, button: 0 };
    for (const t of ["pointerover", "pointerenter", "mouseover", "pointerdown", "mousedown", "pointerup", "mouseup"]) {
      el.dispatchEvent(t.startsWith("pointer") ? new PointerEvent(t, { ...o, pointerId: 1, pointerType: "mouse", isPrimary: true }) : new MouseEvent(t, o));
    }
    el.click();
    return true;
  }
  function hover(el) {
    if (!el) return;
    const r = el.getBoundingClientRect();
    const o = { bubbles: true, composed: true, clientX: r.left + r.width / 2, clientY: r.top + r.height / 2 };
    for (const t of ["pointerover", "pointerenter", "mouseover", "mouseenter", "mousemove"]) el.dispatchEvent(new MouseEvent(t, o));
  }
  // 可信输入：交给后台用浏览器调试协议输入，编辑器会当成真人打字
  const type = (text) => send({ type: "insertText", text });
  const key = (k) => send({ type: "key", key: k });
  async function focusAndClear(el) {
    tap(el);
    el.focus();
    await sleep(200);
    if ("value" in el && el.tagName === "INPUT") el.select();
    else document.execCommand("selectAll");
    await key("Delete");
    await sleep(150);
  }

  async function videoFile(job) {
    const parts = [];
    for (let i = 0; i < job.chunks; i++) {
      const { b64 } = await send({ type: "getChunk", i });
      parts.push(Uint8Array.from(atob(b64), (c) => c.charCodeAt(0)));
    }
    return new File(parts, `${job.meta.title.replace(/[\\/:*?"<>|]/g, "")}.mp4`, { type: "video/mp4" });
  }
  function imageFile(b64, name) {
    return new File([Uint8Array.from(atob(b64), (c) => c.charCodeAt(0))], name, { type: "image/jpeg" });
  }
  function setFiles(input, files) {
    const dt = new DataTransfer();
    for (const f of [].concat(files)) dt.items.add(f);
    input.files = dt.files;
    input.dispatchEvent(new Event("input", { bubbles: true, composed: true }));
    input.dispatchEvent(new Event("change", { bubbles: true, composed: true }));
  }

  let PLATFORM = "";
  const progress = (msg) => send({ type: "progress", platform: PLATFORM, msg });

  // 短信 / 滑块验证：通知用户来处理，最多等 10 分钟
  async function verifyGate(detect, where) {
    if (!detect()) return;
    await progress(`需要验证（${where}），已发通知，等待你在窗口里完成`);
    await send({ type: "verify", platform: PLATFORM, msg: `请在自动打开的${where}页面里完成短信/滑块验证，完成后会自动继续。` });
    const ok = await waitFor(() => !detect(), 600000, 2000);
    if (!ok) throw Object.assign(new Error("等待验证超时（10 分钟）"), { code: "failed" });
    await progress("验证已完成，继续");
  }

  // 启动：先向后台报到（是否需要登录 / 表单是否就绪），领到任务就执行
  async function start(def) {
    PLATFORM = def.platform;
    // 只在插件自己打开的任务页里工作
    const { active } = await send({ type: "hello" });
    if (!active) return;
    let stopHeartbeat = null;
    for (let i = 0; i < 80; i++) {
      const st = await def.detect();
      if (st.needLogin || st.hasForm) {
        const r = await send({ type: "ready", platform: PLATFORM, url: location.href, top: window === top, ...st });
        if (r.retry) {
          await sleep(1500);
          continue;
        }
        if (!r.job) return; // 本页不是任务页（或只是保活检查）
        const hb = setInterval(() => send({ type: "progress", platform: PLATFORM, msg: "…" }).catch(() => {}), 25000);
        stopHeartbeat = () => clearInterval(hb);
        try {
          await def.run(r.job);
          stopHeartbeat();
          await send({ type: "result", ok: true, msg: "发布成功" });
        } catch (e) {
          stopHeartbeat();
          await send({ type: "result", ok: false, code: e.code || "failed", msg: e.message || String(e) });
        }
        return;
      }
      if (def.prepare) await def.prepare(i);
      await sleep(1500);
    }
  }
  // 按行截断，避免把一句话切成半截
  function clip(text, n) {
    text = String(text || "").trim();
    if (text.length <= n) return text;
    const cut = text.slice(0, n);
    const i = cut.lastIndexOf("\n");
    return (i > n * 0.5 ? cut.slice(0, i) : cut).trim();
  }
  const fail = (msg, code = "failed") => Object.assign(new Error(msg), { code });

  window.KB = { sleep, send, visible, deepAll, $, byText, waitFor, tap, hover, type, key, focusAndClear, videoFile, imageFile, setFiles, progress, verifyGate, start, fail, clip };
})();
