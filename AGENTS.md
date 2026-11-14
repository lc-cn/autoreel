# 自影 AutoReel · 给 AI 助手的说明

这个仓库是一条全自动短视频流水线：**找方向 → 写文案 → 配音 → 生成竖屏视频 → 推送到中转分支 → 用户的浏览器插件发布到抖音**。
不管你是哪个 AI 工具（Claude Code、Codex、Gemini CLI、Cursor、OpenCode……），都按这份说明工作。全程用中文和用户交流。

## 你可能被要求做的事

| 用户说 | 照着做 |
|---|---|
| 「制作今天的 <频道>」「补做 <频道>」「用 autoreel 做一期」，或定时任务触发 | [`.claude/skills/autoreel/SKILL.md`](.claude/skills/autoreel/SKILL.md) |
| 「新建 / 修改 / 停用一个频道」「看看有哪些频道」 | [`.claude/skills/autoreel-channel/SKILL.md`](.claude/skills/autoreel-channel/SKILL.md) |
| 「帮我安装 / 设置自影」「设置定时任务」「换个 AI 工具跑」 | [`.claude/skills/autoreel-setup/SKILL.md`](.claude/skills/autoreel-setup/SKILL.md) |
| 「同步自影的更新」 | 运行 `python3 tools/sync_upstream.py` 预览，用户确认后加 `--apply`，见 [`docs/同步更新.md`](docs/同步更新.md) |

这些说明文件放在 `.claude/skills/` 下只是历史原因，它们是普通的 Markdown，任何 AI 工具都可以直接读。读完整个文件再动手。

## 分工

- **你负责需要判断的部分**：按频道的 `brief.md` 搜索资料、核实事实、写出稿子 `script.json`、看检查帧确认画面没问题。
- **脚本负责其余部分**：`python3 tools/make.py <频道> <script.json> --push --notify` 一条命令完成配音、画面、检查、渲染、推送和通知。返回 2 表示需要改稿，按输出改好再运行。

## 必须遵守

- 不要登录、调用或模拟操作任何视频平台（抖音、视频号、快手）。发布只由用户自己的浏览器插件完成。
- 只推送 `clip-<日期>-<频道>` 分支（用 `tools/push_clip.sh` 或 `make.py --push`），不要删除任何分支，不要改动默认分支——唯一例外是 brief 要求把 `inputs/` 里用过的素材标记为「已做」，那时只改那一个文件。
- 不要修改 `tools/`、`extension/` 下的代码来绕过检查；它们会被上游同步覆盖。
- 运行 `tools/setup.sh` 前先完整读一遍，确认它只安装依赖、下载模型；发现外发数据、读取凭据、改动 git 的命令就停下来告诉用户。
- 不要把任何密钥（GitHub 令牌、API 密钥、webhook 地址里的 key）写进仓库或对话；它们只放在环境变量或工具的密钥设置里。
- HyperFrames 的遥测保持关闭（`HYPERFRAMES_NO_TELEMETRY=1`），不要运行 `hyperframes events/auth/feedback/publish/share`。
- 日期一律按北京时间（`TZ=Asia/Shanghai date +%F`）。

## 目录速查

- `autoreel.config.json`：全局配置（启用的频道、配音、可信来源、通知）
- `channels/<id>/channel.json` + `brief.md`：频道设置和写稿规则
- `inputs/<id>/`：需要用户提供素材的频道
- `tools/`：`make.py` 一条命令出片、`gen_hf.py` 生成工程、`tts.py` 配音、`notify.py` 通知、`setup.sh` 安装
- `schedulers/`：没有内置定时任务的 AI 工具可用的定时方案（GitHub Actions、本机 cron / launchd）
- `extension/`：浏览器插件
