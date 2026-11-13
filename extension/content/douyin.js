// 抖音创作者中心：上传 → 标题/正文/话题 → 等上传完成 → AI 声明（核对）→ 合集 → 竖横双封面 → 发布
(() => {
  const K = window.KB;
  const isPublishPage = () => /content\/(publish|post\/video)/.test(location.href);
  // 未登录时会被带到 creator.douyin.com 首页的扫码登录界面
  const needLogin = () => !/creator-micro/.test(location.href) || (!!K.byText("扫码登录") && !K.$("input[type=file]"));
  const needVerify = () => {
    const sms = K.$('input[placeholder*="验证码"], input[placeholder*="短信"]');
    const cap = K.$('[class*="captcha"], [id*="captcha"], .secsdk-captcha-drag-wrapper');
    return (sms && K.visible(sms)) || (cap && K.visible(cap));
  };

  async function fillText(meta) {
    const title = await K.waitFor(() => K.$('input[placeholder*="填写作品标题"]'), 120000);
    if (!title) throw K.fail("没找到标题输入框（抖音可能改版）", "error");
    await K.focusAndClear(title);
    await K.type(meta.title.slice(0, 30));
    const ed = await K.waitFor(() => K.$('div.zone-container[contenteditable="true"]'), 60000);
    if (!ed) throw K.fail("没找到正文编辑区（抖音可能改版）", "error");
    await K.focusAndClear(ed);
    if (meta.desc) await K.type(meta.desc.trim());
    for (const t of (meta.tags || []).slice(0, 5)) {
      await K.type(` #${t}`);
      await K.sleep(900);
      await K.key("Space");
      await K.sleep(300);
    }
    await K.key("Escape");
    await K.progress(`标题、正文已填写，话题 ${Math.min(5, (meta.tags || []).length)} 个`);
  }

  async function waitUploaded(file) {
    const t0 = Date.now();
    let lastPct = null, lastChange = Date.now(), rounds = 0;
    while (Date.now() - t0 < 30 * 60000) {
      await K.verifyGate(needVerify, "抖音");
      if (K.byText("重新上传")) return K.progress("视频上传完成");
      if (K.byText("上传失败")) {
        const inp = K.$("div.progress-div input[type=file], input[type=file]");
        if (inp) K.setFiles(inp, file);
        await K.progress("页面提示上传失败，已重新选择文件");
        lastChange = Date.now();
      }
      const pctEl = [...document.querySelectorAll('[class*="progress"]')].find((e) => /\d\s*%/.test(e.innerText || ""));
      const m = pctEl && (pctEl.innerText || "").match(/(\d+(?:\.\d+)?)\s*%/);
      const pct = m ? m[1] : null;
      if (pct !== lastPct) {
        lastPct = pct;
        lastChange = Date.now();
        if (pct) await K.progress(`上传进度 ${pct}%`);
      }
      if (Date.now() - lastChange > (pct ? 180000 : 600000)) {
        if (++rounds > 2) throw K.fail(`上传一直卡在 ${lastPct || "未显示"}，已重传 2 次`);
        const inp = K.$("div.progress-div input[type=file], input[type=file]");
        if (inp) K.setFiles(inp, file);
        await K.progress(`上传进度长时间不动，第 ${rounds} 次重新选择文件`);
        lastChange = Date.now();
      }
      await K.sleep(2000);
    }
    throw K.fail("上传超过 30 分钟未完成");
  }

  function clearOverlays() {
    document.querySelectorAll(".shepherd-element,.shepherd-modal-overlay-container").forEach((e) => e.remove());
    document.querySelectorAll('[class*="mention-wrapper"]').forEach((e) => (e.closest(".semi-portal") || e).remove());
    document.querySelectorAll(".semi-portal").forEach((e) => {
      if (!e.querySelector(".semi-modal, .semi-modal-content")) e.remove();
    });
    if (document.activeElement && document.activeElement.blur) document.activeElement.blur();
  }

  async function declare(text) {
    for (let i = 0; i < 3; i++) {
      clearOverlays();
      const entry = ["请选择自主声明", "请选择声明类型", "添加自主声明", "自主声明", "作品声明"].map((t) => K.byText(t, { exact: true }) || K.byText(t)).find(Boolean);
      if (entry) K.tap(entry);
      const dlg = await K.waitFor(() => [...document.querySelectorAll(".semi-modal-content")].find((d) => d.innerText.includes("请选择声明类型")), 6000);
      if (dlg) {
        const opt = [...dlg.querySelectorAll("label.semi-radio")].find((l) => l.innerText.includes(text)) || K.byText(text, { root: dlg, exact: true });
        if (opt) K.tap(opt);
        await K.sleep(400);
        const ok = [...dlg.querySelectorAll("button")].find((b) => b.innerText.trim() === "确定");
        if (ok) K.tap(ok);
        await K.sleep(1200);
      }
      const still = [...document.querySelectorAll(".semi-modal-content")].some((d) => d.innerText.includes("请选择声明类型"));
      if (!still && K.byText(text)) return K.progress(`自主声明已确认：${text}`);
      await K.progress(`自主声明第 ${i + 1} 次没选上，重试`);
      await K.key("Escape");
      await K.sleep(800);
    }
    throw K.fail(`自主声明「${text}」三次都没选上，为避免违规本次不发布`, "declare");
  }

  async function collection(name) {
    if (!name) return;
    clearOverlays();
    const trig = document.querySelector('[class*="select-collection-"] .semi-select-selection');
    if (!trig) return K.progress("没找到「添加合集」，跳过");
    K.tap(trig);
    const opt = await K.waitFor(() => [...document.querySelectorAll(".semi-select-option.collection-option")].find((o) => (o.querySelector('[class*="option-title-"]') || o).innerText.trim() === name), 5000);
    if (!opt) {
      await K.key("Escape");
      return K.progress(`合集里没有「${name}」，跳过`);
    }
    K.tap(opt);
    await K.sleep(500);
    await K.progress(`已归入合集：${name}`);
  }

  async function covers(meta) {
    const c = meta.covers;
    if (!c) return K.progress("没有封面图，跳过");
    clearOverlays();
    let modal = null;
    for (let i = 0; i < 5 && !modal; i++) {
      const area = [...document.querySelectorAll('[class*="cover-"]')].find((e) => e.querySelector("img")) || document.querySelector('[class*="cover"]');
      K.hover(area);
      await K.sleep(600);
      const trig = ["选择封面", "编辑封面", "设置封面"].map((t) => K.byText(t, { exact: true })).find(Boolean) || area;
      K.tap(trig);
      modal = await K.waitFor(() => document.querySelector("div.dy-creator-content-modal"), 5000);
    }
    if (!modal) return K.progress("封面弹窗打不开，跳过自定义封面");
    await K.sleep(1500);
    for (const [tab, k] of [["设置竖封面", "portrait"], ["设置横封面", "landscape"]]) {
      if (!c[k]) continue;
      const t = K.byText(tab, { root: modal, exact: true });
      if (t) {
        K.tap(t);
        await K.sleep(1000);
      }
      const inp = modal.querySelector(".semi-upload:has(.semi-upload-drag-area-main-text) input.semi-upload-hidden-input") || [...modal.querySelectorAll("input.semi-upload-hidden-input")].pop();
      if (!inp) {
        await K.progress(`${tab}：没找到上传入口`);
        continue;
      }
      K.setFiles(inp, K.imageFile(c[k], `cover_${k}.jpg`));
      await K.sleep(3500);
      await K.progress(`${tab}：已上传`);
    }
    const finish = () => [...modal.querySelectorAll("button")].find((b) => b.innerText.trim() === "完成");
    await K.waitFor(() => finish() && !finish().className.includes("semi-button-disabled"), 15000);
    for (let i = 0; i < 4 && document.querySelector("div.dy-creator-content-modal"); i++) {
      if (finish()) K.tap(finish());
      await K.sleep(1500);
      for (const n of ["确定", "确认", "仍然完成", "继续"]) {
        const b = [...document.querySelectorAll(".semi-modal-content button")].find((x) => x.innerText.trim() === n);
        if (b && K.visible(b)) {
          K.tap(b);
          await K.sleep(1200);
        }
      }
    }
    if (document.querySelector("div.dy-creator-content-modal")) {
      await K.key("Escape");
      return K.progress("封面弹窗没能正常关闭，已按 Esc");
    }
    await K.progress("竖封面、横封面都已设置");
  }

  async function publish() {
    for (let i = 0; i < 90; i++) {
      clearOverlays();
      await K.verifyGate(needVerify, "抖音");
      if (K.byText("请设置封面后再发布")) {
        const rec = document.querySelector('[class^="recommendCover-"]');
        if (rec) {
          K.tap(rec);
          await K.sleep(1000);
          const ok = [...document.querySelectorAll("button")].find((b) => b.innerText.trim() === "确定");
          if (ok) K.tap(ok);
        }
      }
      const btn = [...document.querySelectorAll("button")].find((b) => b.innerText.trim() === "发布" && K.visible(b));
      if (btn) K.tap(btn);
      if (await K.waitFor(() => /content\/manage/.test(location.href), 3000)) return;
    }
    throw K.fail("点了发布但 3 分钟内没有跳到作品管理页");
  }

  K.start({
    platform: "douyin",
    detect: async () => {
      if (needLogin()) return { needLogin: true };
      const inp = K.$("input.upload-btn-input, div[class^='container'] input[type=file], input[type=file]");
      return { hasForm: !!inp && /content\/upload/.test(location.href) };
    },
    run: async (job) => {
      const meta = job.meta;
      await K.progress(`开始上传：${meta.title}`);
      const file = await K.videoFile(job);
      const inp = K.$("input.upload-btn-input, div[class^='container'] input[type=file], input[type=file]");
      K.setFiles(inp, file);
      if (!(await K.waitFor(async () => (await K.verifyGate(needVerify, "抖音"), isPublishPage()), 120000))) throw K.fail("选择文件后 2 分钟仍未进入发布页");
      await K.sleep(2000);
      await fillText(meta);
      await waitUploaded(file);
      await declare(meta.declaration || "内容由AI生成");
      await collection(meta.collection);
      await covers(meta);
      await publish();
    },
  });
})();
