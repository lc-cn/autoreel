#!/bin/bash
# 自影 · 本机定时出片：schedulers/local/run.sh <频道id>
# 由 crontab（Linux）或 launchd（macOS）按时调用；AI 工具命令和密钥写在同目录的 agent.env（不要提交到仓库）。
set -e
CH="$1"
[[ "$CH" =~ ^[a-z0-9_]+$ ]] || { echo "用法：$0 <频道id>"; exit 2; }
cd "$(dirname "$0")/../.."
REPO=$(pwd)
ENVF="$REPO/schedulers/local/agent.env"
[ -f "$ENVF" ] || { echo "缺少 $ENVF，先按 schedulers/local/README.md 创建"; exit 2; }
set -a; . "$ENVF"; set +a
export PATH="$PATH:/usr/local/bin:/opt/homebrew/bin" HYPERFRAMES_NO_TELEMETRY=1 DO_NOT_TRACK=1
mkdir -p "$REPO/schedulers/local/logs"
LOG="$REPO/schedulers/local/logs/$(TZ=Asia/Shanghai date +%F)-$CH.log"
{
  echo "== $(date) 开始 $CH"
  git pull -q --ff-only || echo "git pull 失败，用本地版本继续"
  bash tools/setup.sh >/dev/null
  PROMPT="按仓库 AGENTS.md 的说明，制作 ${CH} 频道（今天，日期按北京时间；channel.json 的 days_ahead 为 1 时连明天一起做），用 tools/make.py 加 --push --notify 推送到 clip-日期-${CH} 分支，已存在的跳过。这是仓库主人安排的每日任务，已授权推送这些分支；brief 要求标记「已做」时，只提交那一个文件到默认分支。不要登录或调用任何视频平台。最后用一段话总结选题、来源和推送结果。"
  export PROMPT
  eval "$AGENT_CMD"
  echo "== $(date) 结束 $CH"
} >> "$LOG" 2>&1
