"""自影 · 字数与时长预算，以及几条「频道规则」：写稿后、配音前就能知道这期会不会超时或太短。

make.py（配音前预检）、check_channel.py（频道配置检查）、gen_hf.py / make_cover.py（拼开场和结尾口播、开场目录、
主题小字、发布标题、固定声明）共用这里的函数，保证「检查时算的」和「真正念出来、画出来的」是同一套。

字数怎么数（和 channel.json 的 say_chars / say_total 对应）：
  含标点；不计 `**`、断行用的 `|`（以及全角 `｜`）、空白；`{显示|读法}` 只计显示的部分。

时长怎么估：按念出来的样子（数字转成读法）数「字」和「停顿」，
  每个字约 SEC_PER_CHAR 秒，每处标点停顿约 SEC_PER_PAUSE 秒，每段之间再加 SEC_PER_LINE 秒。
  折合下来，按含标点的字数算整期约每秒 4.6 个字（含开场钩子、结尾互动和关注语）。
  系数用 20 期真实成片（CosyVoice3，女声 / 男声，语速 x1.00）拟合：成片时长误差均方根约 2.7 秒，19 期在 ±4.5 秒以内；
  CosyVoice 每次合成的整体快慢会差 5%–10%（同一份稿子两次配音差了 2.4 秒），所以离上下限留 3 秒余量。
  男声和女声在这批数据里没有稳定的快慢差别。
"""
import math
import re

try:
    import textnorm
except ImportError:  # 从别的目录 import 时
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import textnorm

SEC_PER_CHAR = 0.165   # 每个念出来的字（汉字、数字读法、英文字母）
SEC_PER_PAUSE = 0.46   # 每处标点停顿（句内停顿 + 句末停顿的平均）
SEC_PER_LINE = 0.30    # 开场、每段、结尾之间的间隔（按段数计）
SEC_FIXED = 0.7        # 开头留白、结尾留白
PRECHECK_SLACK = 2.0   # 预检比渲染后的检查（上限 +3 秒）略严，估算本身有 ±3 秒误差

BARS = "|｜丨¦"        # 只用来排版的竖线：配音时去掉
PUNCT = "，。、；：！？,.;:!?…—～~「」『』“”‘’《》〈〉（）()【】·"
CN_NUM = "一二三四五六七八九十"


# ───────── 文字 ─────────
def _outside_braces(text, fn):
    """只对 {显示|读法} 以外的部分调用 fn（读法标记里的 | 不能动）。"""
    parts = re.split(r"(\{[^{}]*\})", text)
    return "".join(p if k % 2 else fn(p) for k, p in enumerate(parts))


def display(text):
    """画面 / 字幕上看到的文字：读法只留显示部分，去掉 ** 和断行竖线、空白。"""
    text = re.sub(r"\{([^{}|]+)\|[^{}]*\}", r"\1", str(text or ""))
    text = text.replace("**", "")
    text = re.sub(f"[{re.escape(BARS)}]", "", text)
    return re.sub(r"\s+", "", text)


def count_chars(text):
    """say_chars / say_total 用的字数：含标点，不计 **、|、｜、空白和 {显示|读法} 的读法部分。"""
    return len(display(text))


def strip_layout(text):
    """配音前去掉纯排版符号：| ｜ 丨 这类竖线。夹在两段文字中间时换成逗号（停顿），旁边已有标点就直接去掉。
    {显示|读法} 里的竖线不动。"""
    def fix(seg):
        out = []
        for k, ch in enumerate(seg):
            if ch not in BARS:
                out.append(ch)
                continue
            prev = "".join(out).rstrip().rstrip("*").rstrip()
            nxt = seg[k + 1:].lstrip().lstrip("*").lstrip()
            if prev and nxt and prev[-1] not in PUNCT + BARS and nxt[0] not in PUNCT + BARS:
                out.append("，")
        return "".join(out)
    return _outside_braces(str(text or ""), fix)


def spoken(text):
    """念出来的样子：读法替换显示、数字转读法、去掉标记和竖线。"""
    text = str(text or "")
    # 拼音注音 {行|háng} 念的还是左边的字；汉字读法 {CPI|消费者价格指数} 念右边
    text = re.sub(r"\{([^{}|]+)\|([^{}]*)\}", lambda m: m[2] if re.search(r"[一-鿿]", m[2]) else m[1], text)
    text = strip_layout(text).replace("**", "")
    text = re.sub(r"\[[a-z_\-]+\]", "", text)
    return textnorm.spoken(re.sub(r"\s+", "", text))


def units(text):
    """(念出来的字数, 停顿数)。连续的标点算一处停顿。"""
    s = spoken(text)
    pauses = len(re.findall(f"[{re.escape(PUNCT)}]+", s))
    chars = len(re.sub(f"[{re.escape(PUNCT)}]", "", s))
    return chars, pauses


def line_seconds(text, speed=1.0):
    c, p = units(text)
    return (c * SEC_PER_CHAR + p * SEC_PER_PAUSE) / max(0.5, float(speed or 1.0)) + SEC_PER_LINE


def seconds(lines, speed=1.0):
    """整期成片时长估算（秒）：lines 是开场、各段、结尾的口播文字。"""
    return sum(line_seconds(t, speed) for t in lines if str(t or "").strip()) + SEC_FIXED


def sec_per_char(speed=1.0, pause_ratio=0.12):
    """按「含标点的字数」折算的平均每字秒数（写稿时好用：多 1 秒 ≈ 多 1/这个数 个字）。"""
    return ((1 - pause_ratio) * SEC_PER_CHAR + pause_ratio * SEC_PER_PAUSE) / max(0.5, float(speed or 1.0))


# ───────── 开场和结尾口播（gen_hf 真正念的就是这些） ─────────
def follow_text(S):
    """结尾「关注我 · 每天…」：口号本身以「每天」开头时不再重复。"""
    sl = S.get("slogan", "")
    return sl if sl.startswith("每天") else "每天" + sl


def categories(items):
    seen = []
    for it in items:
        if it.get("tag") not in seen:
            seen.append(it.get("tag"))
    return seen


def ask_options(data):
    o = [str(x).strip() for x in (data.get("ask_options") or []) if str(x).strip()]
    return o[:2] if len(o) >= 2 else []


def auto_intro(data, S):
    """开场口播：按频道 intro 模板生成。可用 {name} {date} {n} {topic_say} {categories}。"""
    m = re.search(r"(\d+)月(\d+)日", data.get("date", ""))
    day = f"{int(m.group(1))}月{int(m.group(2))}日" if m else ""  # 字幕显示数字，配音时自动转成读法
    cats = categories(data.get("items") or []) or [""]
    joined = cats[0] if len(cats) == 1 else "、".join(cats[:-1]) + "和" + cats[-1]
    return S.get("intro", "{name}，{date}。").format(name=S.get("name", ""), date=day, n=len(data.get("items") or []),
                                                    topic_say=data.get("topic_say") or data.get("topic", ""), categories=joined)


def intro_text(data, S):
    """开场：稿子写了 intro 就用；有钩子句就直接念钩子；都没有才用频道的开场白模板。"""
    return data.get("intro") or (data["hook"] if str(data.get("hook") or "").strip() else auto_intro(data, S))


def _sentence(t):
    t = str(t or "").strip()
    return t if not t or t[-1] in "。！？!?…" else t.rstrip("，,；;：:") + "。"


def outro_text(data, S):
    """结尾：稿子写了 outro 就用；有 ask 时先抛互动问题（和 A/B 选项），再请关注；否则用频道的 outro 模板。
    channel.json 的 disclaimer_say 为 true 时，把 disclaimer 念在关注语前面。"""
    if "outro" in data:
        return data["outro"]
    if str(data.get("ask") or "").strip():
        ask = data["ask"].strip()
        opts = [str(x).strip() for x in (data.get("ask_options") or [])][:2]
        pick = f"{opts[0]}的打A，{opts[1]}的打B。" if len(opts) == 2 else "评论区告诉我。"
        disc = _sentence(S.get("disclaimer")) if S.get("disclaimer_say") else ""
        return f"{ask}{'' if ask[-1:] in '？?。！!' else '。'}{pick}{disc}关注我，{follow_text(S)}。"
    out = S.get("outro", "")
    if S.get("disclaimer_say") and S.get("disclaimer") and display(S["disclaimer"]) not in display(out):
        out = _sentence(S["disclaimer"]) + out
    return out


def numbering(S):
    v = (S or {}).get("numbering", "spoken")
    return v if v in ("spoken", "visual", "none") else "spoken"


def spoken_item(i, say, mode="spoken"):
    """口播不念分类（画面上已有）；频道的分段序号是 spoken 时在前面念「一、二、三……」，否则直接念正文。"""
    say = re.sub(r"^[^，。：:]{1,4}[：:]", "", str(say).strip())
    return f"{CN_NUM[i]}，{say}" if mode == "spoken" and i < len(CN_NUM) else say


def lines(data, S):
    """整期要念的文字：[开场, 第1段, …, 结尾]。"""
    return ([intro_text(data, S)] + [spoken_item(i, it.get("say", ""), numbering(S)) for i, it in enumerate(data.get("items") or [])]
            + [outro_text(data, S)])


# ───────── 预检 ─────────
def _speed(S):
    return float(((S.get("voice") or {}).get("speed")) or 1.0)


def precheck(data, S):
    """配音前检查字数和预计时长。返回 (problems, warnings, info)；problems 非空就该改稿（make.py 返回 2）。"""
    problems, warnings = [], []
    items = data.get("items") or []
    speed = _speed(S)
    spc = sec_per_char(speed)
    sc = S.get("say_chars") if isinstance(S.get("say_chars"), list) and len(S.get("say_chars")) == 2 else None
    st = S.get("say_total") if isinstance(S.get("say_total"), list) and len(S.get("say_total")) == 2 else None
    it_rng = S.get("items") if isinstance(S.get("items"), list) and len(S.get("items")) == 2 else None
    counts = [count_chars(it.get("say", "")) for it in items]
    total = sum(counts)
    if it_rng and not it_rng[0] <= len(items) <= it_rng[1]:
        warnings.append(f"写了 {len(items)} 段，频道要求 {it_rng[0]}–{it_rng[1]} 段（channel.json 的 items）")
    if sc:
        for i, n in enumerate(counts):
            if n > sc[1]:
                problems.append(f"第 {i + 1} 段 say {n} 字，超过每段上限 {sc[1]} 字（say_chars）：这一段至少删 {n - sc[1]} 字")
            elif n < sc[0]:
                warnings.append(f"第 {i + 1} 段 say 只有 {n} 字，少于每段下限 {sc[0]} 字（say_chars）")
    if st:
        if total > st[1]:
            problems.append(f"正文 say 共 {total} 字，超过整期上限 {st[1]} 字（say_total）：至少删 {total - st[1]} 字")
        elif total < st[0]:
            warnings.append(f"正文 say 共 {total} 字，少于整期下限 {st[0]} 字（say_total）")
    fmt = (S or {}).get("title_format") or DEFAULT_TITLE_FORMAT
    if "{headline}" in fmt and publish_title(data, S) == headline(data)[:TITLE_LIMIT] and fmt.strip() != "{headline}":
        warnings.append(f"headline {len(headline(data))} 字，套上标题格式「{fmt}」超过 {TITLE_LIMIT} 字，发布标题只保留 headline"
                        + ("，而且被截断了" if len(headline(data)) > TITLE_LIMIT else ""))
    ls = lines(data, S)
    est = seconds(ls, speed)
    info = {"say_chars": counts, "say_total": total, "spoken_chars": sum(count_chars(x) for x in ls), "estimate": round(est, 1)}
    hi = S.get("max_seconds")
    lo = S.get("min_seconds")
    if isinstance(hi, (int, float)) and est > hi + PRECHECK_SLACK:
        cut = math.ceil((est - hi) / spc)
        problems.append(f"预计成片约 {est:.0f} 秒（含开场 hook、结尾互动和关注语），超过频道上限 {hi:.0f} 秒：say 一共再删约 {cut} 字")
    if isinstance(lo, (int, float)) and lo <= est < lo + 3:
        warnings.append(f"预计成片约 {est:.0f} 秒，离频道下限 {lo:.0f} 秒不到 3 秒，配音偏快时成片会不够长；最好再加约 {math.ceil((lo + 3 - est) / spc)} 字")
    if isinstance(lo, (int, float)) and est < lo:
        add = math.ceil((lo + 3 - est) / spc)
        problems.append(f"预计成片约 {est:.0f} 秒，短于频道下限 {lo:.0f} 秒（min_seconds）：say 一共再加约 {add} 字"
                        + (f"（整期上限 {st[1]} 字，还能加 {max(0, st[1] - total)} 字）" if st else ""))
    return problems, warnings, info


def channel_range(S, hook_chars=(15, 22), ask_chars=(10, 18)):
    """按频道配置估算成片时长范围：(最短, 最长) 秒。最短 = 最少段数 × 字数下限 + 短 hook 和结尾，最长反之。"""
    speed = _speed(S)
    it = S.get("items") or [1, 1]
    sc = S.get("say_chars") or [0, 0]
    st = S.get("say_total")
    lo_say, hi_say = it[0] * sc[0], it[1] * sc[1]
    if isinstance(st, list) and len(st) == 2:
        lo_say, hi_say = max(lo_say, st[0]), min(hi_say, st[1])
    spc = sec_per_char(speed)
    fol = len("关注我，" + follow_text(S) + "。")
    disc = count_chars(S.get("disclaimer")) if S.get("disclaimer_say") else 0
    num = 2 if numbering(S) == "spoken" else 0  # 「一，」

    def est(n_items, say, hook, ask, opts):
        body = (say + n_items * num + hook + ask + opts + fol + disc) * spc
        return body + (n_items + 2) * SEC_PER_LINE + SEC_FIXED

    return est(it[0], lo_say, hook_chars[0], ask_chars[0], 0), est(it[1], hi_say, hook_chars[1], ask_chars[1], 12)


# ───────── 开场目录、主题小字、发布标题、固定声明（gen_hf / make_cover / check_channel 共用） ─────────
AGENDA_MODES = ("full", "tags", "none")
TITLE_LIMIT = 30
TITLE_FIELDS = ("name", "date", "headline", "topic")
DEFAULT_TITLE_FORMAT = "{headline}｜{name}"


def has_hook(data):
    return bool(str((data or {}).get("hook") or "").strip())


def agenda_mode(S, hooked):
    """开场第 1 秒（和封面）列不列出各段：full 标签 + 全部标题；tags 只列标签；none 都不列。
    默认：有钩子句时 tags（不把各段标题、也就是结论提前亮出来），没有钩子句时 full（和以前一样）。"""
    v = (S or {}).get("agenda")
    if v in AGENDA_MODES:
        return v
    return "tags" if hooked else "full"


def topic_badge(data, S):
    """有钩子句时，主题（成语、书名……）以小字标签出现在开场和封面上。channel.json 的 topic_badge：
    true 显示 topic；字符串是模板（可用 {topic}，例如 "今日成语 · {topic}"）；false 不显示。
    默认：hook 为 topic 的频道显示，其他频道不显示。钩子句开头就是 topic 时不重复显示。"""
    if not has_hook(data):
        return ""
    topic = display(data.get("topic") or "")
    if not topic:
        return ""
    v = (S or {}).get("topic_badge", (S or {}).get("hook") == "topic")
    if v is False or v is None:
        return ""
    if display(data.get("hook")).lstrip("《「“").startswith(topic):  # 钩子句开头就是主题（如「刻舟求剑：…」），不重复
        return ""
    if isinstance(v, str) and v.strip():
        try:
            return v.format(topic=topic)
        except (KeyError, IndexError, ValueError):
            return topic
    return topic


def _md(data):
    m = re.search(r"(\d+)月(\d+)日", (data or {}).get("date", ""))
    return f"{int(m.group(1))}月{int(m.group(2))}日" if m else ""


def headline(data):
    return display(data.get("headline") or "") or "、".join(display(it.get("title", "")) for it in (data.get("items") or [])[:2])


def publish_title(data, S, limit=TITLE_LIMIT, no=None):
    """发布标题。channel.json 的 title_format 可用 {headline} {name} {date} {topic} {no}，默认「{headline}｜{name}」。
    title_style 为 number（系列编号）且没写 title_format 时，用「{name} 第{no}期｜{headline}」；no 由调用方按发布记录算好传进来。
    超过 30 字时先去掉 headline 以外的部分（headline 完整最重要），headline 自己超过 30 字才截断。"""
    fmt = (S or {}).get("title_format") or ""
    if not fmt:
        fmt = "{name} 第{no}期｜{headline}" if (S or {}).get("title_style") == "number" and no else DEFAULT_TITLE_FORMAT
    vals = {"name": (S or {}).get("name", ""), "date": _md(data), "headline": headline(data), "topic": display(data.get("topic") or ""),
            "no": no if no else ""}
    try:
        t = fmt.format(**vals)
    except (KeyError, IndexError, ValueError):
        t = DEFAULT_TITLE_FORMAT.format(**vals)
    if len(t) <= limit:
        return t
    return vals["headline"][:limit]


def disclaimer(S):
    """频道级固定声明（例如「价格以购买页面为准」）：写进发布文案，正文画面的来源行也会带上。"""
    return display((S or {}).get("disclaimer") or "")


def main():
    """python3 tools/budget.py <频道id> <script.json>：配音前看字数和预计时长（和 make.py 的预检一样）。退出码 2 表示要改稿。"""
    import json
    import os
    import sys
    if len(sys.argv) != 3:
        print(main.__doc__)
        sys.exit(1)
    root = os.path.abspath(os.environ.get("AUTOREEL_ROOT") or os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    S = json.load(open(os.path.join(root, "channels", sys.argv[1], "channel.json"), encoding="utf-8"))
    data = json.load(open(sys.argv[2], encoding="utf-8"))
    problems, warnings, info = precheck(data, S)
    rng = f"{S['min_seconds']}–{S.get('max_seconds', 90)}" if S.get("min_seconds") else f"≤ {S.get('max_seconds', 90)}"
    print(f"正文 {info['say_total']} 字（每段 {'/'.join(map(str, info['say_chars']))}），整期念 {info['spoken_chars']} 字，"
          f"预计成片约 {info['estimate']:.0f} 秒（频道 {rng} 秒，估算误差约 ±3 秒）")
    print(f"发布标题：{publish_title(data, S)}")
    for p in problems:
        print("  ✗ " + p)
    for w in warnings:
        print("  · " + w)
    sys.exit(2 if problems else 0)


if __name__ == "__main__":
    main()
