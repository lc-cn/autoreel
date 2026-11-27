"""自影 · 数据分析：把作品数据（history/数据.jsonl，插件每晚采集）和发布记录（history/发布记录.jsonl）对上，
按频道、视频形式、频道 × 形式、钩子类型统计，写出周报，并（加 --apply 时）按数据调整各频道视频形式的轮换比例。

只算数字、标出样本量，不下结论；结论由复盘的 AI 按 .claude/skills/autoreel-review/SKILL.md 写进经验库。

    python3 tools/analyze.py                 # 打印周报（最近 7 天对比之前 7 天，形式对比用最近 28 天）
    python3 tools/analyze.py --write         # 同时写进 history/周报/<日期>.md 和 history/分析.json
    python3 tools/analyze.py --write --apply # 再按数据更新 channel.json 的 format_weights，改动记进 history/改进记录.md

判断规则（写死在这里，复盘时不要临时放宽）：
  - 发布不满 2 天的作品数据还在变，不参与比较
  - 两组都至少 MIN_N 期、且差距至少 GAP 个百分点，才算「可信」；否则「待观察」
  - 形式权重：按「留存分 = 5秒完播率 − 2秒跳出率」，每种形式都有 MIN_N 期以上才调整；每种形式至少保留 15%
"""
import datetime
import json
import math
import os
import re
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.environ.get("AUTOREEL_ROOT") or os.path.dirname(HERE))
H = os.path.join(ROOT, "history")
MIN_N, GAP, SETTLE_DAYS = 3, 5.0, 2
NAMES = {"classic": "经典版", "immersive": "实拍沉浸", "kinetic": "大字快剪", "quiz": "答题挑战"}
M = [("plays", "播放量（中位数）"), ("bounce2s", "2秒跳出率"), ("completion5s", "5秒完播率"), ("avg_watch", "平均播放时长（秒）"), ("comments", "评论")]

# 与插件 shared.js 的 metricsFromRaw 相同：先确切字段名，比例换成百分数
EXACT = {"plays": ["play_count", "play_cnt", "vv"], "bounce2s": ["bounce_rate_2s", "bounce_2s_rate"], "completion5s": ["completion_rate_5s", "finish_rate_5s"],
         "completion": ["completion_rate", "finish_rate"], "avg_watch": ["average_play_duration", "avg_play_duration"],
         "likes": ["digg_count", "like_count"], "comments": ["comment_count"], "shares": ["share_count"]}


def from_raw(raw):
    out = {}
    keys = [k for k in raw if "_per_client." not in k]
    for m, names in EXACT.items():
        k = next((x for x in keys if x.split(".")[-1] in names), None)
        if k is not None:
            out[m] = raw[k]
    for m in ("bounce2s", "completion5s", "completion"):
        if isinstance(out.get(m), (int, float)) and out[m] <= 1:
            out[m] = round(out[m] * 100, 2)
    return out


def norm(t):
    return re.sub(r"\s+", "", str(t or ""))


def lines(path):
    if not os.path.exists(path):
        return []
    out = []
    for l in open(path, encoding="utf-8"):
        try:
            out.append(json.loads(l))
        except ValueError:
            pass
    return out


def load(today):
    hist = {norm(h.get("title")): h for h in lines(os.path.join(H, "发布记录.jsonl"))}
    rows = []
    for r in lines(os.path.join(H, "数据.jsonl")):
        h = hist.get(norm(r.get("title")), {})
        date = h.get("date")
        if not date:
            m = re.search(r"(\d{1,2})月(\d{1,2})日", str(r.get("title")))
            if not m:
                continue
            date = f"{today.year}-{int(m[1]):02d}-{int(m[2]):02d}"
        met = dict(r.get("metrics") or {})
        if r.get("raw"):
            met.update(from_raw(r["raw"]))
        name = (re.match(r"^(.+?)\d{1,2}月\d{1,2}日", str(r.get("title"))) or [None, h.get("channel", "其他")])[1]
        rows.append({"title": r.get("title"), "date": date, "channel": h.get("channel") or name, "name": name,
                     "format": h.get("format") or "classic", "hook_type": h.get("hook_type") or "未标注", "seconds": h.get("seconds"), "m": met})
    return rows


def agg(rs):
    out = {"n": len(rs)}
    for k, _ in M:
        v = [r["m"][k] for r in rs if isinstance(r["m"].get(k), (int, float))]
        out[k] = (statistics.median(v) if k == "plays" else statistics.mean(v)) if v else None
    s = [r["m"]["completion5s"] - r["m"]["bounce2s"] for r in rs if isinstance(r["m"].get("completion5s"), (int, float)) and isinstance(r["m"].get("bounce2s"), (int, float))]
    out["score"] = statistics.mean(s) if s else None
    return out


def fmt(k, v):
    if v is None:
        return "—"
    if k in ("bounce2s", "completion5s", "score"):
        return f"{v:.1f}%" if k != "score" else f"{v:+.1f}"
    if k == "avg_watch":
        return f"{v:.1f}"
    return f"{v:.0f}" if k == "plays" else f"{v:.1f}"


def table(title, groups):
    head = "| " + title + " | 期数 | " + " | ".join(n for _, n in M) + " | 留存分 |\n|" + "---|" * (len(M) + 3) + "\n"
    return head + "".join(f"| {g} | {a['n']} | " + " | ".join(fmt(k, a[k]) for k, _ in M) + f" | {fmt('score', a['score'])} |\n" for g, a in groups)


def compare(groups):
    """组内两两比较 2 秒跳出率：返回可信 / 待观察的文字。"""
    ok = [(g, a) for g, a in groups if a["bounce2s"] is not None]
    if len(ok) < 2:
        return "数据不够比较。"
    best = min(ok, key=lambda x: x[1]["bounce2s"])
    worst = max(ok, key=lambda x: x[1]["bounce2s"])
    gap = worst[1]["bounce2s"] - best[1]["bounce2s"]
    sure = best[1]["n"] >= MIN_N and worst[1]["n"] >= MIN_N and gap >= GAP
    return (f"{'**可信**' if sure else '待观察'}：2 秒跳出率最低的是「{best[0]}」（{best[1]['bounce2s']:.1f}%，{best[1]['n']} 期），"
            f"最高的是「{worst[0]}」（{worst[1]['bounce2s']:.1f}%，{worst[1]['n']} 期），差 {gap:.1f} 个百分点"
            + ("。" if sure else f"（可信需要两组都至少 {MIN_N} 期、差距至少 {GAP:.0f} 个百分点）。"))


def weights(rows, ch_ids):
    """按留存分给每个频道的形式算新权重；数据不够的频道不改。"""
    out = {}
    for ch in ch_ids:
        p = os.path.join(ROOT, "channels", ch, "channel.json")
        if not os.path.exists(p):
            continue
        S = json.load(open(p, encoding="utf-8"))
        fs = S.get("formats") or []
        if len(fs) < 2:
            continue
        sc = {}
        for f in fs:
            a = agg([r for r in rows if r["channel"] == ch and r["format"] == f])
            if a["n"] < MIN_N or a["score"] is None:
                sc = None
                break
            sc[f] = a["score"]
        if not sc:
            continue
        top = max(sc.values())
        raw = {f: math.exp((v - top) / 8.0) for f, v in sc.items()}  # 留存分差 8 分，权重约差 2.7 倍
        tot = sum(raw.values())
        out[ch] = {f: round(v / tot, 3) for f, v in raw.items()}
    return out


def main():
    a = sys.argv[1:]
    today = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).date()
    settled = (today - datetime.timedelta(days=SETTLE_DAYS)).isoformat()
    rows = [r for r in load(today) if r["date"] <= settled]
    d7, d14, d28 = [(today - datetime.timedelta(days=n + SETTLE_DAYS)).isoformat() for n in (7, 14, 28)]
    week = [r for r in rows if r["date"] > d7]
    prev = [r for r in rows if d14 < r["date"] <= d7]
    recent = [r for r in rows if r["date"] > d28]
    chans = sorted({r["channel"] for r in rows}, key=lambda c: -len([r for r in rows if r["channel"] == c]))
    name = {r["channel"]: r["name"] for r in rows}
    md = [f"# 自影 · 数据周报 {today}\n",
          f"数据：{len(rows)} 期（只算发布满 {SETTLE_DAYS} 天的）。本周 = {d7[5:]} 之后发布的，上周 = {d14[5:]}～{d7[5:]}；形式和钩子对比用最近 28 天。"
          f"「可信」= 两组都至少 {MIN_N} 期且 2 秒跳出率差至少 {GAP:.0f} 个百分点。留存分 = 5秒完播率 − 2秒跳出率，越高越好。\n"]
    md.append("## 各频道：本周 vs 上周\n")
    g = []
    for c in chans:
        g.append((f"{name[c]} 本周", agg([r for r in week if r["channel"] == c])))
        g.append((f"{name[c]} 上周", agg([r for r in prev if r["channel"] == c])))
    md.append(table("频道", [x for x in g if x[1]["n"]]))
    md.append("\n## 视频形式（最近 28 天）\n")
    fg = [(NAMES.get(f, f), agg([r for r in recent if r["format"] == f])) for f in sorted({r["format"] for r in recent})]
    md.append(table("形式", fg) + "\n" + compare(fg) + "\n")
    md.append("\n## 各频道 × 形式（最近 28 天）\n")
    for c in chans:
        cg = [(NAMES.get(f, f), agg([r for r in recent if r["channel"] == c and r["format"] == f])) for f in sorted({r["format"] for r in recent if r["channel"] == c})]
        if cg:
            md.append(f"\n**{name[c]}**\n\n" + table("形式", cg) + "\n" + compare(cg) + "\n")
    md.append("\n## 钩子类型（最近 28 天）\n")
    hg = [(h, agg([r for r in recent if r["hook_type"] == h])) for h in sorted({r["hook_type"] for r in recent})]
    md.append(table("钩子类型", hg) + "\n" + compare([x for x in hg if x[0] != "未标注"]) + "\n")
    md.append("\n## 2 秒跳出率最低 / 最高的 5 期（最近 28 天，供复盘找共同点）\n")
    rk = sorted([r for r in recent if isinstance(r["m"].get("bounce2s"), (int, float))], key=lambda r: r["m"]["bounce2s"])
    for lab, part in (("最低", rk[:5]), ("最高", rk[-5:][::-1])):
        md.append(f"\n{lab}：\n" + "".join(f"- {r['date'][5:]} {r['name']}（{NAMES.get(r['format'], r['format'])}，钩子：{r['hook_type']}）{r['m']['bounce2s']:.1f}% · 播放 {fmt('plays', r['m'].get('plays'))}：{str(r['title']).split('｜')[-1]}\n" for r in part))
    new_w = weights(recent, chans)
    md.append("\n## 视频形式轮换比例\n\n" + ("".join(f"- {name.get(c, c)}：" + "、".join(f"{NAMES.get(f, f)} {round(w * 100)}%" for f, w in ws.items()) + "（按留存分，每种至少保留 15%）\n" for c, ws in new_w.items())
                                          or f"每个频道的每种形式都要攒够 {MIN_N} 期（发布满 {SETTLE_DAYS} 天）才调整，现在还在平均轮换。\n"))
    report = "".join(md)
    print(report)
    if "--write" in a:
        os.makedirs(os.path.join(H, "周报"), exist_ok=True)
        open(os.path.join(H, "周报", f"{today}.md"), "w", encoding="utf-8").write(report)
        json.dump({"date": str(today), "rows": len(rows), "weights": new_w}, open(os.path.join(H, "分析.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    if "--apply" in a and new_w:
        log = []
        for c, ws in new_w.items():
            p = os.path.join(ROOT, "channels", c, "channel.json")
            S = json.load(open(p, encoding="utf-8"))
            if S.get("format_weights") != ws:
                log.append(f"- {name.get(c, c)}：{S.get('format_weights') or '平均'} → {ws}")
                S["format_weights"] = ws
                json.dump(S, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
                open(p, "a").write("\n")
        if log:
            with open(os.path.join(H, "改进记录.md"), "a", encoding="utf-8") as f:
                f.write(f"\n## {today} 自动调整视频形式比例（按留存分，见 history/周报/{today}.md）\n" + "\n".join(log) + "\n")
            print("\n已更新形式比例：\n" + "\n".join(log))


if __name__ == "__main__":
    main()
