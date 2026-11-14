# 用 GitHub Actions 定时出片

适合：你用的 AI 工具没有定时任务功能，或者不想开着电脑。GitHub 的服务器按时启动，调用你选的 AI 工具命令行写稿，再用 `tools/make.py` 出片推送。

## 步骤

1. 把 [`autoreel.yml`](autoreel.yml) 复制到你仓库的 `.github/workflows/autoreel.yml`。
2. 按文件里标着「要改的地方」的 4 处修改：
   - **cron**：每个频道一行，**UTC 时间**（北京时间减 8 小时）。比发布时间至少早 1 小时，GitHub 高峰期会延迟。
   - **CHANNEL_OF**：cron 和频道 id 的对应关系，字符串要和上面完全一致。
   - **AGENT_INSTALL / AGENT_CMD**：你的 AI 工具的安装和运行命令（文件里有 Claude Code、Codex、Gemini CLI、OpenCode 的写法，以各自官方文档为准）。
   - **密钥**：只保留用得到的那几行。
3. 仓库 **Settings → Secrets and variables → Actions → New repository secret**，添加你的 AI 工具的 API 密钥（如 `ANTHROPIC_API_KEY`、`OPENAI_API_KEY`、`GEMINI_API_KEY`），需要实拍素材再加 `PEXELS_API_KEY` / `PIXABAY_API_KEY`，需要通知再加 `notify` 里引用的变量。
4. 提交后到 **Actions** 页面，选「自影定时出片」→ **Run workflow**，填一个频道 id 手动跑一次，确认能出片、能推送。

## 费用和时长

- 公开仓库免费；**私有仓库每月有免费分钟数**（按你的 GitHub 套餐），超出要付费。
- 标准机器没有显卡，CosyVoice 配音一期要 15–25 分钟，加上安装和渲染，一期约 30–40 分钟（第一次下载模型更久，之后有缓存）。每天 3 期一个月约 3000 分钟。
- 想省时间：换成火山引擎配音（几秒钟），一期约 10 分钟。

## 常见问题

- **没按时运行**：GitHub 的定时任务在高峰期会延迟，仓库 60 天没有活动也会自动停用定时任务（Actions 页面会提示，点一下重新启用）。
- **推送失败**：确认文件里有 `permissions: contents: write`，并且仓库 Settings → Actions → General → Workflow permissions 允许读写。
