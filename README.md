<p align="center"><img src="assets/logo.png" width="120" alt="AutoClip"></p>

# AutoClip 自动成片

> **English:** AutoClip is an open-source, fully automated short-video pipeline for Chinese creators: **find a topic → write the script → voice it → render a vertical video → publish**. Claude Code cloud routines do the research and writing, voice it with Volcengine Doubao TTS (the same voices used across Douyin/CapCut) or offline CosyVoice, render with [HyperFrames](https://github.com/heygen-com/hyperframes), then push to a private GitHub repo. A Chrome extension downloads each clip and publishes it to Douyin (WeChat Channels / Kuaishou optional), with QR-code login, session keep-alive, verification prompts and templated webhooks (WeCom, Feishu, DingTalk, OneBot 11/12, Bark, Telegram …). Channels are plain folders, so you can add your own. Docs are in Chinese.

一条从**找方向 → 写文案 → 配音 → 生成视频 → 发作品**全自动跑完的短视频流水线。每个「频道」就是一个文件夹，定义好主题和规则，每天自动出片、自动发布。

## 内置频道示例

| 频道 | 内容 | 素材来源 |
|---|---|---|
| 热点快报 `kuaibao` | 当天 4–6 条要闻速览 | 新闻搜索 |
| 一条讲透 `jiangtou` | 挑一条新闻讲清来龙去脉 | 新闻搜索 |
| 历史上的今天 `lishi` | 这一天的 3 件大事（提前一天备好） | 百科、史料 |
| 一分钟冷知识 `lengzhishi` | 一个知识点讲明白 | 科普资料（至少 2 个来源印证） |
| 一分钟读本书 `dushu` | 一本书的核心观点 | 你的书单 `inputs/dushu/书单.md` + 书评 |
| 好物推荐 `haowu` | 一件产品的看点 | **只用你提供的资料** `inputs/haowu/` |
| 每天一个成语 `chengyu` | 一个成语的出处、故事、用法 | 成语词典、典籍原文 |

想做别的主题？在 Claude Code 里对仓库说一句「**新建一个频道，讲 XX**」，`autoclip-channel` 技能会一步步引导你：调研同类账号和可信来源、定结构和语气、并排比较几套配色、自动校验、试做一期，最后启用并建好定时任务。也可以手动复制一个频道文件夹修改，详见 [docs/新建频道.md](docs/新建频道.md)。

## 工作原理

```
Claude Code 云端定时任务（每个频道每天一次）
  └─ autoclip 技能
       ① 找方向：按频道 brief 搜索 / 读你的素材，事实需有来源
       ② 写文案：统一格式的分段稿（画面标题 / 口播 / 详细说明 / 来源）
       ③ 配音：火山引擎豆包语音（抖音同款音色）或 CosyVoice 离线配音
       ④ 生成视频：HyperFrames 渲染 1080×1920 竖屏，字幕、动效、「内容由AI生成」标识
       ⑤ 封面与发布信息：竖横双封面、标题、正文、话题、合集、AI 声明
  └─ 推送到你的私有仓库 clip-日期-频道 分支
        └─ Chrome 插件「AutoClip」到点自动发布到抖音（视频号 / 快手可选）
              └─ 结果写回仓库，浏览器通知 / Webhook 告诉你
```

- **不需要服务器**：生成在 Claude Code 云端，发布在你自己的 Chrome 里，中间用私有 GitHub 仓库当"信箱"。
- **用你自己的浏览器发布**：登录状态是你自己的，插件只操作它自己打开的窗口。
- **需要你时会叫你**：短信 / 滑块验证、登录失效、发布失败，都会通知你（可推到手机、QQ 群、企业微信群）。

## 配音

| 方案 | 音色 | 成本 | 速度（一分钟视频） |
|---|---|---|---|
| **火山引擎豆包语音** `volcengine` | 抖音、剪映同源的大量音色 | 按量付费，需自己开通 | 几秒 |
| **CosyVoice** `cosyvoice` | 内置「中文女 / 中文男」，或用你自己的录音复刻 | 免费，离线 | 无显卡约 6–8 分钟 |
| sherpa 轻量模型 `sherpa` | Kokoro 等 | 免费，离线 | 几秒 |

默认 `auto`：填了火山引擎就用火山引擎，否则用 CosyVoice。

## 快速开始

完整步骤见 **[docs/部署指南.md](docs/部署指南.md)**：

1. **Use this template → Create a new repository**，**选 Private**。
2. 改 `autoclip.config.json`：启用哪些频道、配音方案。
3. 生成只对这个仓库有 **Contents 读写** 权限的 GitHub 令牌。
4. 在 [Claude Code 网页版](https://claude.ai/code) 用这个仓库为每个频道创建定时任务（指令见 [prompts/定时任务.md](prompts/定时任务.md)）。
5. Chrome 加载 `extension/`，填仓库和令牌，扫码登录抖音。

## 使用前请务必了解

- **内容责任在你**。流水线要求每条事实都有可信来源，但 AI 仍可能出错。建议前几周每天看一眼成片和来源（云端会把视频和来源链接发给你）。
- **AI 内容标识**：画面常驻「内容由AI生成」，发布时勾选平台 AI 声明，请勿去掉。
- **商业内容**：好物类频道只使用你提供的资料，推广内容会标注「广告」；请遵守广告法和平台规则。
- **平台规则**：自动化发布可能不符合部分平台的用户协议，存在限流或封号风险，请自行评估。本项目不提供任何绕过平台风控的手段。
- **声音授权**：用 CosyVoice 复刻音色时，只能使用你本人或已获授权的声音。

## 目录

| 路径 | 内容 |
|---|---|
| `channels/<频道>/` | 频道定义：`channel.json`（设置）+ `brief.md`（找方向、写文案的规则） |
| `inputs/` | 需要你提供素材的频道（书单、产品资料） |
| `.claude/skills/autoclip/` | 出片技能（各频道通用）：找方向 → 写文案 → 自查 → 配音 → 生成视频 → 推送 |
| `.claude/skills/autoclip-channel/` | 频道管理技能：交互式新建、编辑、停用频道 |
| `tools/` | `gen_hf.py` 生成视频工程和文案、`tts.py` 配音、`make_cover.py` 封面、`check_channel.py` 频道检查与预览、`palettes.json` 配色预设、`push_clip.sh` 推送、`setup.sh` 安装 |
| `extension/` | Chrome 插件（Manifest V3） |
| `prompts/` | 定时任务指令模板 |

## 许可

[MIT](LICENSE)。第三方组件见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
