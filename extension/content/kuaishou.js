// 快手创作者服务平台：上传 → 描述+话题（最多 3 个）→ 等上传完成 → AI 声明（如有）→ 合集（如有）→ 发布 → 确认
(() => {
  const K = window.KB;
  const fileInput = () => K.$('input[type="file"][accept*="video"]') || K.$('input[type="file"]');
  const needLogin = () => /passport\.kuaishou\.com/.test(location.href) || (!!K.byText("立即登录") && !fileInput());
  const needVerify = () => {
    const cap = K.$('[class*="captcha"], [id*="captcha"]');
    const sms = K.$('input[placeholder*="验证码"]');
    return (cap && K.visible(cap)) || (sms && K.visible(sms));
  };
  function closeGuides() {
    const know = [...document.querySelectorAll("button")].find((b) => b.innerText.trim() === "我知道了" && K.visible(b));
    if (know) K.tap(know);
    for (const t of ["跳过", "下一步", "完成", "知道了"]) {
      const b = [...document.querySelectorAll('div[role="alertdialog"] button')].find((x) => x.innerText.trim() === t);
      if (b) K.tap(b);
    }
    document.querySelectorAll("#react-joyride-portal, .react-joyride__spotlight, .react-joyride__overlay").forEach((e) => e.remove());
  }
  function descEditor() {
    const lab = K.byText("描述", { sel: "span,div,label" });
    if (lab) {
      let p = lab.parentElement;
      for (let i = 0; i < 4 && p; i++, p = p.parentElement) {
        const ed = p.querySelector('[contenteditable="true"]');
        if (ed) return ed;
      }
    }
    return K.$('div[contenteditable="true"]');
  }

  K.start({
    platform: "kuaishou",
    detect: async () => {
      if (needLogin()) return { needLogin: true };
      return { hasForm: /article\/publish\/video/.test(location.href) && !!fileInput() };
    },
    run: async (job) => {
      const meta = job.meta;
      await K.progress(`开始上传：${meta.title}`);
      const file = await K.videoFile(job);
      K.setFiles(fileInput(), file);
      await K.sleep(3000);
      closeGuides();

      const ed = await K.waitFor(() => (closeGuides(), descEditor()), 90000);
      if (!ed) throw K.fail("没找到描述编辑区（快手可能改版）", "error");
      await K.focusAndClear(ed);
      // 快手描述上限约 500 字：放标题 + 正文前段
      const text = K.clip(`${meta.title}\n${(meta.desc || "").trim()}`, 480);
      await K.type(text);
      await K.key("Enter");
      for (const t of (meta.tags || []).slice(0, 3)) {
        await K.type(`#${t} `);
        await K.sleep(1500);
      }
      await K.progress("描述和话题已填写");

      // 等上传完成：先等"上传中"出现（或 15 秒），再等它消失
      await K.waitFor(() => K.byText("上传中"), 15000);
      let retries = 0;
      const done = await K.waitFor(async () => {
        closeGuides();
        await K.verifyGate(needVerify, "快手");
        if (K.byText("上传失败") && retries < 3) {
          retries++;
          const inp = K.$('div.progress-div [class^="upload-btn-input"]') || fileInput();
          if (inp) K.setFiles(inp, file);
          await K.progress(`上传失败，第 ${retries} 次重传`);
          return false;
        }
        return !K.byText("上传中");
      }, 30 * 60000, 2000);
      if (!done) throw K.fail("视频上传 30 分钟仍未完成");
      await K.progress("视频上传完成");

      // AI 内容声明（不同账号界面不一样，找得到就选）
      const decl = ["作品声明", "添加声明", "内容声明"].map((t) => K.byText(t)).find(Boolean);
      if (decl) {
        K.tap(decl);
        const opt = await K.waitFor(() => K.byText("AI生成") || K.byText("由AI生成") || K.byText("人工智能"), 4000);
        if (opt) {
          K.tap(opt);
          await K.progress("已选择 AI 生成内容声明");
          const ok = [...document.querySelectorAll(".ant-modal button, button")].find((b) => ["确定", "确认"].includes(b.innerText.trim()) && K.visible(b));
          if (ok) K.tap(ok);
        } else {
          await K.key("Escape");
          await K.progress("声明里没有 AI 选项（视频画面里已有AI标识）");
        }
      } else await K.progress("没找到声明入口（视频画面里已有AI标识）");

      if (meta.collection) {
        const lab = K.byText("合集", { sel: "span,div,label", exact: true });
        const sel = lab && lab.parentElement && lab.parentElement.parentElement && lab.parentElement.parentElement.querySelector(".ant-select-selector");
        if (sel) {
          K.tap(sel);
          const opt = await K.waitFor(() => document.querySelector(`div.ant-select-item-option[label="${meta.collection}"]`) || [...document.querySelectorAll("div.ant-select-item-option")].find((o) => o.innerText.trim() === meta.collection), 4000);
          if (opt) {
            K.tap(opt);
            await K.progress(`已归入合集：${meta.collection}`);
          } else {
            await K.key("Escape");
            await K.progress(`合集里没有「${meta.collection}」，跳过`);
          }
        }
      }

      for (let i = 0; i < 60; i++) {
        closeGuides();
        await K.verifyGate(needVerify, "快手");
        const confirm = [...document.querySelectorAll("div.ant-modal-confirm-centered button.ant-btn-primary")].find(K.visible);
        if (confirm) K.tap(confirm);
        else {
          const btn = K.byText("发布", { exact: true, sel: "button,div,span" });
          if (btn) K.tap(btn);
        }
        await K.sleep(1500);
        const c2 = [...document.querySelectorAll("div.ant-modal-confirm-centered button.ant-btn-primary")].find(K.visible) || K.byText("确认发布", { exact: true });
        if (c2) K.tap(c2);
        if (await K.waitFor(() => /article\/manage\/video/.test(location.href), 4000)) return;
      }
      throw K.fail("点了发布但没有跳到作品管理页");
    },
  });
})();
