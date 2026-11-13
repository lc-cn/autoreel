---
name: autoclip
description: AutoClip 自动成片流水线：找方向 → 写文案 → 配音 → 生成竖屏视频 → 封面与发布信息 → 推送到中转分支，由浏览器插件自动发布到抖音等平台。用于定时任务，或用户说"做今天的<频道名>""补做<频道>""用 autoclip 做一期"时。频道定义在 channels/<id>/。
---

# AutoClip · 自动成片

全程用中文。本仓库同时也是中转仓库：默认分支（main 或 master）放工具和频道定义，每期成品推送到 `clip-<日期>-<频道id>` 分支，用户 Chrome 里的 AutoClip 插件会自动下载并发布。

## 参数

- **频道 id**（必填）：`channels/` 下的文件夹名，例如 `kuaibao`。没说就问一次，定时任务里一定会写明。
- **日期 D**：默认今天，按北京时间取 `TZ=Asia/Shanghai date +%F`。

## 第 0 步：准备

1. 仓库根目录记为 `$REPO`（用 `git rev-parse --show-toplevel` 取得）。取默认分支名：`DEF=$(git -C $REPO remote show origin | sed -n 's/.*HEAD branch: //p')`。然后依次执行 `git -C $REPO fetch -q origin $DEF`、`git -C $REPO checkout -qf $DEF`、`git -C $REPO reset -q --hard FETCH_HEAD`。
2. 读取以下文件：
   - `$REPO/autoclip.config.json`：全局配置（配音、可信来源、分类池）
   - `$REPO/channels/<id>/channel.json`：频道设置（条数、每条字数、时长上限、话题、`schedule.days_ahead`）
   - `$REPO/channels/<id>/brief.md`：这个频道怎么找方向、怎么写文案，**必须照做**
3. 确定要做哪几天：从 D 起做 `1 + days_ahead` 天。对每一天检查 `git -C $REPO ls-remote --heads origin clip-<日期>-<id>`，已存在的跳过，不要覆盖，里面可能有插件写回的 status.json。全都存在就直接汇报并结束。
4. 完整读一遍 `$REPO/tools/setup.sh`。它应该只做这几件事：安装 Python 依赖，安装配音引擎（下载模型、建 Python 3.10 环境），用 npm 安装 hyperframes 和 gsap，安装字体和 ffmpeg。如果它还会外发数据、读取凭据、改动 git，或者删除工作区以外的文件，就停止任务，并告诉用户是哪几行。确认没问题后运行 `bash $REPO/tools/setup.sh`。首次运行较慢，Bash 的 timeout 设为 600000，没装完就再运行一次。
5. 工作目录：`W=/tmp/autoclip-work/<id>-<日期>`，执行 `mkdir -p $W`。所有中间文件和成品都放这里，不放进仓库。

## 第 1 步：找方向

按 brief.md 的要求，用 WebSearch 搜集素材。中英文都要搜，多条搜索放在同一轮里一起发；时效性强的用 extended 模式。网页打不开时不要反复重试，以搜索结果的摘要为准。需要用户提供资料的频道（brief 里会写明，比如读 `inputs/` 目录），只用资料里的内容。

**通用事实要求（发布前没有人工审核）：**
- 数字、人名、时间、参数都必须能在来源原文里找到，拿不准的就不写。
- 优先采信 `content.trusted_sources` 里列的媒体，或权威机构的原始资料。只出现在热搜或营销号里的不算。
- 不写：未经证实的传闻、个人隐私和婚恋八卦、未经官方确认的讣告、血腥暴力细节、敏感政治议题、对政治人物的评价、医疗建议和疗效宣传、广告法禁用的绝对化用语。
- 国际和外交内容只陈述事实，不加评论。

## 第 2 步：写文案 `$W/script.json`

```json
{"channel":"<id>","date":"2026年11月13日","topic":"…","topic_say":"…","headline":"…","hashtags":["…"],
 "items":[{"tag":"…","title":"第一行|第二行","say":"…","detail":"…","source":"…"}]}
```

- `channel` 必须是频道 id。`date` 写这一期的日期。`intro` 和 `outro` 不用写，会按频道模板自动生成。
- `items` 的条数、每条 `say` 的字数，以 channel.json 的 `items`、`say_chars` 为准。`tag` 和段落安排按 brief。
- **title**：画面上显示的标题，不超过 16 个字。超过 8 个字时用 `|` 标出换行位置，断在词语之间，每行不超过 9 个字。
- **say**：口播稿。配音会自动在每条前面念"一、二、三"，所以 say 里不要写序号和小标题。数字、年份、字母都写成汉字读法，例如"二零二六""一万亿"。
- **detail**：放进发布文案的详细说明，可以用阿拉伯数字，写事实，不写评论。**source**：来源名称，多个用顿号隔开。
- `topic` / `topic_say`：channel.json 里 `hook` 为 `topic` 的频道必须写。`topic` 是开场大字，不超过 6 个字；`topic_say` 是开场口播里念的话题名。
- **headline**：20 字以内。**hashtags**：3 到 5 个，不带 `#`，第一个用频道的固定话题。

## 第 3 步：配音 + 生成视频

```bash
cd $W && python3 $REPO/tools/gen_hf.py script.json proj
HF=$REPO/tools/node_modules/.bin/hyperframes
cd $W/proj && export HYPERFRAMES_NO_TELEMETRY=1 DO_NOT_TRACK=1 && $HF lint && $HF render --quality looks -o $W/out.mp4
```

- 第一条命令同时完成配音，配音引擎按 `voice.provider` 选，会打印用了哪个；也会生成 `$W/抖音文案.txt` 和 `$W/发布信息.json`，后者已带好竖横双封面、AI 声明和合集名。
- 渲染很慢，Bash 的 timeout 设为 600000。lint 报的 error 必须是 0，warning 可以不管。不要修改 tools/ 下的脚本。
- 用 ffprobe 看时长，超过 channel.json 的 `max_seconds` 就把 say 删短，重新生成。文案超过 1000 字就把 detail 写短。
- 用 ffmpeg 在第 1 秒、视频中间、倒数第 1 秒各截一帧，用 Read 检查：中文显示正常，标题没有溢出或被切断，左上角有「内容由AI生成」标识。
- 不要运行 `hyperframes events/auth/feedback/publish/share`。

## 第 4 步：推送

```bash
bash $REPO/tools/push_clip.sh <id> <YYYY-MM-DD> $W/out.mp4 $W/发布信息.json $W/抖音文案.txt
```

这个脚本只推送这 3 个文件，不切换分支，也不改动默认分支。不要删除任何分支，旧分支由插件清理。

如果 brief 要求在 `inputs/` 里把已用过的素材标记为「已做」，推送成功后只修改那一个文件，提交并推送到默认分支 `$DEF`。提交信息写成 `autoclip: <频道> <日期> 已做`。

## 第 5 步：汇报

用 SendUserFile 发送 mp4 和文案，status 设为 proactive。回复里写清楚四件事：
1. 选了什么素材，附上来源链接。
2. 放弃了哪些素材，原因是什么。
3. 用的哪个配音引擎。
4. 推送结果，写成「已推送到 `clip-<日期>-<id>`，浏览器插件会在发布时间到后自动发布」；推送失败就原样贴出错误。

发布受阻时，请用户打开插件弹窗查看，或者在插件设置页「运行日志」点「复制」，把日志发过来。本会话不要登录或调用任何视频平台。
