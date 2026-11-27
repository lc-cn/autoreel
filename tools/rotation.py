"""自影 · 视频形式轮换：按日期给每个频道排好这一期用哪种形式，方便按「赛道 × 形式」比较数据。

channel.json 里写 "formats": ["classic", "immersive", "kinetic", "quiz"]（可选形式，见 tools/formats.py）。
同一个频道按天依次轮换；不同频道按频道 id 错开，同一天各频道尽量用不同形式（避免当天热点或流量波动混进对比）。
稿子里自己写了 "format" 的，以稿子为准（例如补做、重做某一期）。

    python3 tools/rotation.py <频道id> [YYYY-MM-DD]   # 打印这一期该用的形式和写法要点
"""
import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

NAMES = {"classic": "经典版", "immersive": "实拍沉浸", "kinetic": "大字快剪", "quiz": "答题挑战"}
HINTS = {
    "classic": "按 brief 正常写，shot 类型要有变化。",
    "immersive": "每一段都要给 footage 的 queries（2–3 组英文关键词，写画面里看得见的东西）；画面全是实拍，图表、地图不会显示，数字要在口播里说清楚。",
    "kinetic": "口播会逐个短语变成满屏大字：多用短句，逗号之间不超过 8 个字；每段 1–2 个 **关键词**；不需要实拍和图表。",
    "quiz": "必须写 \"quiz\": {\"question\": 题目（不超过 16 字）, \"options\": [3 个选项，每个不超过 6 字，只有 1 个对，另外 2 个要像真的], \"answer\": 正确选项的序号（从 0 开始）}；"
            "第 1 段 say 以「答案是A，……」开头先揭晓再讲为什么；hook 可以直接写题目；ask 写「你答对了吗？」配 [\"答对了\",\"答错了\"]。",
}


def formats_of(S):
    fs = [f for f in (S.get("formats") or []) if f in NAMES]
    return fs or [S.get("format") if S.get("format") in NAMES else "classic"]


def format_for(S, date):
    """date：datetime.date 或 YYYY-MM-DD。"""
    if isinstance(date, str):
        date = datetime.date.fromisoformat(date)
    fs = formats_of(S)
    off = sum(str(S.get("id", "")).encode()) % len(fs)
    return fs[(date.toordinal() + off) % len(fs)]


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    ch = sys.argv[1]
    date = sys.argv[2] if len(sys.argv) > 2 else datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).date().isoformat()
    S = json.load(open(os.path.join(ROOT, "channels", ch, "channel.json"), encoding="utf-8"))
    S.setdefault("id", ch)
    f = format_for(S, date)
    print(f"{ch} {date}：{f}（{NAMES[f]}）。在 script.json 里写 \"format\": \"{f}\"。")
    print("写法要点：" + HINTS[f])
    print("本频道轮换的形式：" + "、".join(f"{x}（{NAMES[x]}）" for x in formats_of(S)))


if __name__ == "__main__":
    main()
