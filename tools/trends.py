"""自影 · 热榜：选题前看看大家此刻在关心什么（百度热搜、今日头条热榜，都是公开页面，不需要登录）。

热榜只是「有人关心」的信号，不是事实来源：选中的题仍然要按 brief 用可信来源核实，热榜上的说法不能直接写进稿子。

    python3 tools/trends.py            # 打印两个热榜的前 30 条
    python3 tools/trends.py 医保 房贷   # 只看包含这些词的条目（判断某个候选题热不热）
"""
import json
import re
import sys
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"}


def _get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as r:
        return r.read().decode("utf-8", "replace")


def baidu():
    html = _get("https://top.baidu.com/board?tab=realtime")
    m = re.search(r"<!--s-data:(.*?)-->", html, re.S)
    data = json.loads(m.group(1))
    out = []
    for card in data.get("data", {}).get("cards", []):
        for it in card.get("content", []):
            if it.get("word"):
                out.append({"title": it["word"], "heat": int(it.get("hotScore") or 0), "desc": (it.get("desc") or "")[:60]})
    return out


def toutiao():
    data = json.loads(_get("https://www.toutiao.com/hot-event/hot-board/?origin=toutiao_pc"))
    return [{"title": it.get("Title", ""), "heat": int(it.get("HotValue") or 0), "desc": it.get("Label", "")} for it in data.get("data", [])]


def main():
    words = sys.argv[1:]
    for name, fn in (("今日头条热榜（与抖音同属字节，最接近抖音的热点）", toutiao), ("百度热搜", baidu)):
        try:
            items = fn()
        except Exception as e:
            print(f"\n{name}：读取失败（{e}），跳过")
            continue
        if words:
            items = [x for x in items if any(w in x["title"] + x["desc"] for w in words)]
        print(f"\n{name}" + (f"（包含 {'、'.join(words)}）" if words else "") + f"：{len(items)} 条")
        for i, x in enumerate(items[:30], 1):
            print(f"  {i:>2}. {x['title']}  （热度 {x['heat']}）" + (f"  {x['desc']}" if x["desc"] and not words else ""))


if __name__ == "__main__":
    main()
