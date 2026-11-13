// 视频号助手：上传 → 描述+话题 → 短标题 → 视频标注「含AI生成内容」→ 合集 → 等上传完成 → 发表
// 发布表单在 iframe（/micro/content/post/create）里；本脚本在所有 frame 运行，由带上传框的那个 frame 执行任务。
(() => {
  const K = window.KB;
  const isTop = window === window.top;
  const fileInput = () => K.$('input[type="file"]');

  // 视频号短标题要求 6~16 字，只允许中英文、数字和少量符号
  function shortTitle(t) {
    let s = (t || "").replace(/[｜|]/g, " ").replace(/[^\u4e00-\u9fa5A-Za-z0-9《》“”"：:+?%° ]/g, "").replace(/\s+/g, " ").trim();
    if (s.length < 6) s = (s + " 今日热点资讯").trim();
    return s.slice(0, 16).trim();
  }
  function dismissDialogs() {
    const c = [...K.deepAll(".changeAccount-dialog button, .common-dialog button")].find((b) => b.innerText.trim() === "取消");
    if (c) K.tap(c);
  }
  const needVerify = () => {
    const d = [...K.deepAll(".weui-desktop-dialog__wrp")].find((x) => K.visible(x) && /验证|扫码/.test(x.innerText));
    return !!d;
  };
  const publishBtn = () => [...K.deepAll("div.form-btns button")].find((b) => b.innerText.trim() === "发表" && K.visible(b));
  const publishReady = () => {
    const b = publishBtn();
    return b && !b.disabled && !b.className.includes("weui-desktop-btn_disabled");
  };

  K.start({
    platform: "channels",
    detect: async () => {
      if (isTop && /login\.html/.test(location.href)) return { needLogin: true };
      if (isTop && K.byText("微信扫码登录")) return { needLogin: true };
      return { hasForm: !!fileInput() };
    },
    prepare: async (i) => {
      // 有时会先落到首页：顶层页面点一下「发表视频」
      if (isTop && i === 4 && !/post\/create/.test(location.href)) {
        const b = [...document.querySelectorAll("button.weui-desktop-btn")].find((x) => x.innerText.includes("发表视频"));
        if (b) K.tap(b);
      }
    },
    run: async (job) => {
      const meta = job.meta;
      await K.progress(`开始上传：${meta.title}`);
      const file = await K.videoFile(job);
      K.setFiles(fileInput(), file);
      await K.sleep(3000);
      dismissDialogs();

      const ed = await K.waitFor(() => K.$("div.input-editor"), 60000);
      if (!ed) throw K.fail("没找到视频描述编辑区（视频号可能改版）", "error");
      await K.focusAndClear(ed);
      await K.type(K.clip(meta.desc || meta.title, 900));
      await K.key("Enter");
      for (const t of (meta.tags || []).slice(0, 5)) {
        await K.type(`#${t}`);
        await K.key("Space");
        await K.sleep(300);
      }
      await K.progress("描述和话题已填写");

      const st = K.$('input[placeholder*="短标题"]');
      if (st) {
        await K.focusAndClear(st);
        await K.type(shortTitle(meta.title));
        await K.progress(`短标题：${shortTitle(meta.title)}`);
      }

      const lab = K.byText("选择视频标注", { exact: true });
      if (lab) {
        K.tap(lab);
        const opt = await K.waitFor(() => K.byText("含AI生成内容", { exact: true }), 5000);
        if (opt) {
          K.tap(opt);
          await K.progress("视频标注：含AI生成内容");
        } else await K.progress("没找到「含AI生成内容」选项（视频画面里已有AI标识）");
      } else await K.progress("没找到「视频标注」入口（视频画面里已有AI标识）");

      if (meta.collection) {
        const trig = K.byText("添加到合集");
        if (trig) {
          K.tap(trig);
          const opt = await K.waitFor(() => [...K.deepAll(".option-list-wrap .option-item")].find((o) => (o.querySelector(".name") || o).innerText.trim() === meta.collection), 5000);
          if (opt) {
            K.tap(opt);
            await K.progress(`已归入合集：${meta.collection}`);
          } else {
            await K.key("Escape");
            await K.progress(`合集里没有「${meta.collection}」，跳过`);
          }
        }
      }

      let retries = 0;
      const ok = await K.waitFor(async () => {
        dismissDialogs();
        await K.verifyGate(needVerify, "视频号");
        if (K.$("div.status-msg.error") && retries < 3) {
          retries++;
          const del = [...K.deepAll("div.media-status-content div.tag-inner")].find((x) => x.innerText.includes("删除"));
          if (del) K.tap(del);
          await K.sleep(1500);
          if (fileInput()) K.setFiles(fileInput(), file);
          await K.progress(`上传出错，第 ${retries} 次重传`);
        }
        return publishReady();
      }, 30 * 60000, 2000);
      if (!ok) throw K.fail("视频上传 30 分钟仍未完成（「发表」按钮一直不可用）");
      await K.progress("视频上传完毕，点「发表」");
      await K.send({ type: "submitted" }); // 发表后此 frame 会被销毁，由后台根据页面跳转判断成功
      K.tap(publishBtn());
      await new Promise(() => {});
    },
  });
})();
