#!/bin/bash
# 把一期成品推送到中转分支 clip-<日期>-<频道>（不切换分支、不动工作区，已存在就跳过）。
# 用法：tools/push_clip.sh <频道id> <日期 YYYY-MM-DD> <视频.mp4> <发布信息.json> <文案.txt>
set -e
CH="$1"; D="$2"; V="$3"; M="$4"; C="$5"
[[ "$CH" =~ ^[a-z0-9_]+$ ]] || { echo "频道 id 只能是小写字母、数字、下划线：$CH"; exit 2; }
[[ "$D" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] || { echo "日期格式不对：$D"; exit 2; }
B="clip-$D-$CH"
for f in "$V" "$M" "$C"; do [ -s "$f" ] || { echo "文件不存在或为空：$f"; exit 2; }; done
cd "$(git rev-parse --show-toplevel)"
if git ls-remote --exit-code --heads origin "$B" >/dev/null 2>&1; then echo "远端已有 $B，跳过（不覆盖）"; exit 0; fi
tree=$(printf "100644 blob %s\tcaption.txt\n100644 blob %s\tmeta.json\n100644 blob %s\tvideo.mp4\n" \
  "$(git hash-object -w "$C")" "$(git hash-object -w "$M")" "$(git hash-object -w "$V")" | git mktree)
commit=$(git -c user.name="autoreel-bot" -c user.email="autoreel-bot@users.noreply.github.com" commit-tree "$tree" -m "$B")
git push origin "$commit:refs/heads/$B"
echo "已推送 $B（$(du -h "$V" | cut -f1)）"
