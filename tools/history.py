"""自影 · 发布记录：每期推送成功后记一行，选题前先查，避免过几天又做同样的题材。

记录放在仓库默认分支的 history/发布记录.jsonl（一行一期，长期保存；中转分支会被插件清理，不能靠它查历史）。
上游同步（sync_upstream.py）不会动这个文件。

    python3 tools/history.py list [--channel ID] [--days 90]     # 列出最近的记录（默认全部频道、90 天）
    python3 tools/history.py check 关键词1 关键词2 ...            # 在全部记录的标题、钩子、话题、各段标题里找这些词
    python3 tools/history.py add <工作目录> <频道> <日期>          # 由 make.py 推送成功后自动调用
"""
import datetime
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FILE = os.path.join(ROOT, "history", "发布记录.jsonl")


def load():
    if not os.path.exists(FILE):
        return []
    out = []
    for line in open(FILE, encoding="utf-8"):
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
    return out


def save(rows):
    os.makedirs(os.path.dirname(FILE), exist_ok=True)
    rows = sorted(rows, key=lambda r: (r.get("date", ""), r.get("channel", "")))
    with open(FILE, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def entry(work, channel, date):
    s = json.load(open(os.path.join(work, "script.json"), encoding="utf-8"))
    meta = {}
    p = os.path.join(work, "发布信息.json")
    if os.path.exists(p):
        meta = json.load(open(p, encoding="utf-8"))
    clean = lambda x: re.sub(r"\*\*|\||\{([^{}|]+)\|[^{}]*\}", lambda m: m.group(1) or "", str(x or "")).strip()
    return {"date": date, "channel": channel, "format": s.get("format") or meta.get("format") or "classic",
            "title": meta.get("title", ""), "topic": clean(s.get("topic")), "hook": clean(s.get("hook")),
            "items": [clean(it.get("title")) for it in s.get("items", [])],
            "quiz": (s.get("quiz") or {}).get("question", ""), "branch": f"clip-{date}-{channel}"}


def add(work, channel, date):
    rows = [r for r in load() if not (r.get("date") == date and r.get("channel") == channel)]
    rows.append(entry(work, channel, date))
    save(rows)


def commit_push():
    """把记录提交到当前分支（默认分支）并推送；失败只提醒，不影响出片。"""
    def g(*a):
        return subprocess.run(["git", "-C", ROOT, *a], capture_output=True, text=True)
    rel = os.path.relpath(FILE, ROOT)
    g("add", rel)
    if not g("diff", "--cached", "--quiet").returncode:
        return "发布记录没有变化"
    br = g("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    r = g("-c", "user.name=autoreel-bot", "-c", "user.email=autoreel-bot@users.noreply.github.com", "commit", "-q", "-m", "autoreel: 发布记录", "--", rel)
    if r.returncode:
        return "发布记录提交失败：" + (r.stderr or r.stdout).strip()[:200]
    for _ in range(3):
        g("pull", "-q", "--rebase", "--autostash", "origin", br)
        r = g("push", "-q", "origin", f"HEAD:{br}")
        if not r.returncode:
            return f"发布记录已推送到 {br}"
    return "发布记录推送失败：" + (r.stderr or r.stdout).strip()[:200]


def _fmt(r):
    return f'{r.get("date")} {r.get("channel"):<10} {r.get("format", ""):<9} | {r.get("title", "")} | ' + "、".join(x for x in r.get("items", []) if x)


def main():
    a = sys.argv[1:]
    if not a:
        raise SystemExit(__doc__)
    if a[0] == "add":
        add(a[1], a[2], a[3]); print(commit_push()); return
    rows = load()
    if a[0] == "list":
        ch = a[a.index("--channel") + 1] if "--channel" in a else None
        days = int(a[a.index("--days") + 1]) if "--days" in a else 90
        since = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
        hit = [r for r in rows if r.get("date", "") >= since and (not ch or r.get("channel") == ch)]
        print(f"最近 {days} 天共 {len(hit)} 期" + (f"（{ch}）" if ch else "（全部频道）") + "：")
        for r in hit:
            print("  " + _fmt(r))
    elif a[0] == "check":
        words = [w for w in a[1:] if w]
        for r in rows:
            text = " ".join([r.get("title", ""), r.get("topic", ""), r.get("hook", ""), r.get("quiz", "")] + r.get("items", []))
            found = [w for w in words if w in text]
            if found:
                print(f"  命中 {'、'.join(found)}：{_fmt(r)}")
        print("（没有命中不代表没做过：换几个同义词再查一次）")
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
