"""自影 · 生成视频工程（配音 + HyperFrames 竖屏工程 + 封面 + 发布文案）
用法: python3 gen_hf.py <script.json> <工程目录>
稿子里的 channel 字段决定用哪个频道（channels/<id>/channel.json）；配音方案见 autoreel.config.json 的 voice。
"""
import sys, os, json, re, html, shutil
import soundfile as sf
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import tts
import scenes as SC
import budget

COLORS = {"国际": "#ff5c5c", "国内": "#ff8a4c", "时政": "#ff8a4c", "外交": "#9a7cff", "财经": "#ffb840",
          "科技": "#40c8ff", "体育": "#4fdc8c", "娱乐": "#ff6eb4", "社会": "#f2d14b", "健康": "#5ee0c8",
          "教育": "#7fa8ff", "环境": "#8ad94f", "军事": "#c0a080", "汽车": "#ff7f9e", "文化": "#d59cff"}
PALETTE = ["#ff5c5c", "#40c8ff", "#4fdc8c", "#ffb840", "#9a7cff", "#ff6eb4"]


# 每个栏目的名字、配色、开场和结尾。画面布局相同，配色和文案不同，一眼能分清栏目。
# ───────── 频道与全局配置 ─────────
# 每个频道一个文件夹：channels/<id>/channel.json（名字、配色、开场结尾、发布时间……）+ brief.md（怎么找方向、写文案）
ROOT = os.path.abspath(os.environ.get("AUTOREEL_ROOT") or os.path.join(HERE, ".."))
LEGACY = {"kuaibao": "kuaibao", "jiangtou": "jiangtou", "lishi": "lishi"}  # 旧稿子里的 series 字段


def load_channels():
    out = {}
    d = os.path.join(ROOT, "channels")
    for k in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        f = os.path.join(d, k, "channel.json")
        if os.path.exists(f):
            ch = json.load(open(f, encoding="utf-8"))
            ch.update(ch.get("theme") or {})  # 配色字段展开到顶层，渲染时直接用
            ch.setdefault("id", k)
            out[k] = ch
    return out


def load_config():
    f = os.environ.get("AUTOREEL_CONFIG") or os.path.join(ROOT, "autoreel.config.json")
    return json.load(open(f, encoding="utf-8")) if os.path.exists(f) else {}


CHANNELS = load_channels()
CONFIG = load_config()
VOICE = CONFIG.get("voice") or {"provider": "auto"}


def series(data):
    """取稿子所属频道的配置（稿子里的 channel 字段，兼容旧的 series 字段）。"""
    key = data.get("channel") or LEGACY.get(data.get("series") or "", data.get("series")) or "kuaibao"
    if key not in CHANNELS:
        raise SystemExit(f"找不到频道 {key}：请检查 channels/{key}/channel.json")
    return CHANNELS[key]


follow_text = budget.follow_text  # 结尾「关注我 · 每天…」


def color(tag, i=0):
    return COLORS.get(tag, PALETTE[i % len(PALETTE)])


def cn_num(n):
    d = "零一二三四五六七八九"
    if n < 10: return d[n]
    if n < 20: return "十" + (d[n - 10] if n > 10 else "")
    return d[n // 10] + "十" + (d[n % 10] if n % 10 else "")


categories = budget.categories


def auto_intro(data):
    """开场口播：按频道 intro 模板生成。可用 {name} {date} {n} {topic_say} {categories}。"""
    return budget.auto_intro(data, series(data))


def make_caption(data):
    """抖音发布文案：标题 + 本期涉及 + 每条详细说明 + 来源 + 话题标签。"""
    items = data["items"]
    m = re.search(r"(\d+)月(\d+)日", data["date"])
    md = f"{int(m.group(1))}月{int(m.group(2))}日" if m else data["date"]
    circled = "①②③④⑤⑥⑦⑧⑨⑩"
    S = series(data)
    out = [f"【{S['name']}｜{md}】{data.get('headline') or S['slogan']}", "",
           S["label"] + "：" + "｜".join(categories(items)), ""]
    for i, it in enumerate(items):
        mark = circled[i] + " " if SC.numbering(S) != "none" and i < len(circled) else ("▪ " if SC.numbering(S) == "none" else "")
        out.append(f"{mark}【{it['tag']}】{it['title'].replace('|', '')}")
        out.append(it.get("detail") or tts.display_text(it["say"]))
        out.append("")
    srcs = []
    for it in items:
        for x in re.split(r"[、,，/]", it.get("source", "")):
            if x.strip() and x.strip() not in srcs: srcs.append(x.strip())
    kind = S["src"].split("：")[0] if "：" in S["src"] else "信息来源"
    default = S["src"].split("：", 1)[1] if "：" in S["src"] else "公开资料"
    out.append(f"📌 {kind}：" + ("、".join(srcs) if srcs else default) + "（据公开资料整理）")
    if budget.disclaimer(S):  # 频道固定声明单独一行，不会被各段的 source 顶掉
        out.append(f"⚠️ {budget.disclaimer(S)}")
    if data.get("ask"):
        o = ask_options(data)
        out.append(f"💬 {tts.display_text(data['ask'])}" + (f" 评论区打 A（{o[0]}）或 B（{o[1]}）" if o else ""))
    tags = (data.get("hashtags") or S["hashtags"] + categories(items))[:5]
    out.append(" ".join("#" + t.lstrip("#") for t in tags))
    return "\n".join(out)
GSAP = os.environ.get("GSAP_JS") or next((p for p in [os.path.join(HERE, "node_modules", "gsap", "dist", "gsap.min.js"),
        os.path.join(HERE, "..", "hf", "node_modules", "gsap", "dist", "gsap.min.js")] if os.path.exists(p)), "")
FONT_SRC = "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"
E = html.escape


def phrases(text, t0, t1, keep=()):
    """把一句口播按标点切成短语，按字数分配时间（中文无词边界）。"""
    parts = [p for p in re.split(r"(?<=[，。；！？、])", text) if p.strip()]
    merged = []
    for p in parts:  # 太短的短语并到前一个
        if merged and len(merged[-1]) + len(p) <= 15 and (len(p) <= 7 or len(merged[-1]) <= 7):
            merged[-1] += p
        else:
            merged.append(p)
    final = []
    for p in merged:  # 超过 13 字的短语按词语（jieba 分词）拆成均匀的几段，不切断词
        if len(p) <= 13:
            final.append(p); continue
        import rjieba, math
        words = []  # 日期、带单位的数字整体保留，其余用分词切
        NUMX = "".join(re.escape(w) + "|" for w in sorted(keep, key=len, reverse=True) if w) + \
            r"\d+比\d+|(?:\d{4}年)?\d{1,2}月\d{1,2}[日号]|\d{4}年(?:\d{1,2}月)?|\d{1,2}[:：]\d{2}|[\d.,]+[%％]?[万亿千百]*[个月日号年点时分秒天倍元种]?"
        pos = 0
        for m in re.finditer(NUMX, p):
            words += list(rjieba.cut(p[pos:m.start()])) if m.start() > pos else []
            words.append(m.group())
            pos = m.end()
        words += list(rjieba.cut(p[pos:])) if pos < len(p) else []
        parts_n = math.ceil(len(p) / 13); goal = len(p) / parts_n
        cur = ""
        for w in words:
            if cur and (len(cur) + len(w) > 13 or len(cur) >= goal):
                final.append(cur); cur = ""
            cur += w
        if cur:
            if len(cur) <= 3 and final and len(final[-1]) + len(cur) <= 16:  # 尾巴太短就并回前一段
                final[-1] += cur
            else:
                final.append(cur)
    merged = final
    import textnorm
    w = [max(1, len(textnorm.spoken(p))) for p in merged]  # 按念出来的字数分配时间（9970亿 念 7 个字）
    n = sum(w)
    out, t = [], t0
    for p, wp in zip(merged, w):
        d = (t1 - t0) * wp / n
        out.append((p.rstrip("，。、；："), t, t + d)); t += d
    return out


CN_NUM = "一二三四五六七八九十"


spoken_item = budget.spoken_item  # 口播不念分类；numbering 为 spoken 时前面念「一、二、三……」


def split_title(t, n=8):
    """标题超过 n 字时折成两行，断点靠近中间，且不切断数字/英文。"""
    if "|" in t: return [x for x in t.split("|") if x][:2]
    if len(t) <= n: return [t]
    mid = len(t) / 2
    bounds, acc = set(), 0  # 优先断在词语之间（分词），不行再退回逐字
    for w in SC._tokens(t)[:-1]:
        acc += len(w)
        bounds.add(acc)
    ok = [k for k in range(2, len(t) - 1) if not (re.match(r"[0-9A-Za-z.%]", t[k - 1]) and re.match(r"[0-9A-Za-z.%]", t[k]))]
    ok = [k for k in ok if k in bounds] or ok
    k = min(ok, key=lambda k: abs(k - mid)) if ok else int(mid)
    return [t[:k], t[k:]]


ask_options = budget.ask_options


def ask_html(data, follow_top):
    """结尾的互动问题；有二选一选项时显示 A / B 两个大按钮，方便观众直接评论「A」「B」。"""
    if not data.get("ask"):
        return ""
    opts = ask_options(data)
    btns = "".join(f'<span class="opt o{k}"><b>{"AB"[k]}</b>{E(x)}</span>' for k, x in enumerate(opts))
    return (f'<div id="ask" style="top:{follow_top + 140}px">💬 {E(tts.display_text(data["ask"]))}'
            + (f'<div class="opts">{btns}</div><div class="hint">评论区打 A 或 B</div>' if opts else "") + "</div>")


def hook_lines(t, n=10):
    """钩子句断行：用 | 指定；否则不超过 n 字一行，优先在中间附近的逗号、顿号后面断，重点（**…**）不拆开。"""
    if "|" in t:
        return [x for x in t.split("|") if x][:3]
    plain = re.sub(r"\*\*", "", t)
    if len(plain) <= n:
        return [t]
    # 在原文（含 ** 标记）里找断点：标点后面，且不在 ** 里面
    cands, inside, cnt = [], False, 0
    k = 0
    while k < len(t):
        if t.startswith("**", k):
            inside = not inside; k += 2; continue
        cnt += 1
        if t[k] in "，、：；,;" and not inside:
            cands.append((k + 1, cnt))
        k += 1
    mid = len(plain) / 2
    good = [c for c in cands if abs(c[1] - mid) <= max(3, len(plain) / 4) and c[1] <= n + 2 and len(plain) - c[1] <= n + 2]
    if good:
        pos = min(good, key=lambda c: abs(c[1] - mid))[0]
        return [t[:pos], t[pos:]]
    if "**" in t:
        return [t]
    import rjieba
    bounds, acc = [], 0
    for w in rjieba.cut(plain):
        acc += len(w)
        bounds.append(acc)
    ok = [b for b in bounds[:-1] if b <= n + 1 and len(plain) - b <= n + 1] or bounds[:-1] or [int(mid)]
    k = min(ok, key=lambda b: abs(b - mid))
    return [plain[:k], plain[k:]]


def subset_font(chars, out):
    from fontTools.ttLib import TTCollection
    from fontTools import subset
    tmp = out + ".ttf"
    TTCollection(FONT_SRC).fonts[0].save(tmp)
    opts = subset.Options(); opts.flavor = "woff2"
    f = subset.load_font(tmp, opts)
    s = subset.Subsetter(opts); s.populate(text=chars + "0123456789/·：，。ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz %+-.")
    s.subset(f); subset.save_font(f, out, opts); os.remove(tmp)


def build(data, times, dur, proj, spoken):
    items = data["items"]; n = len(items)
    S = series(data)
    m = re.search(r"(\d+)月(\d+)日", data["date"])
    hook = S.get("hook", "count")
    hookline = tts.display_text(data.get("hook") or "").strip()
    if hookline:  # 稿子写了钩子句：开场第一屏就是这句话（大字），2 秒内抓住人
        raw = re.sub(r"\{([^{}|]+)\|[^{}]*\}", r"\1", data["hook"])
        hl = hook_lines(raw)
        longest = max(len(re.sub(r"\*\*", "", x)) for x in hl)
        hook_fs = max(60, min(96, int(800 / max(1, longest))))  # 按最长一行定字号，保证不再自动折行
        hook_big = "<br />".join(re.sub(r"\*\*(.+?)\*\*", r"<em>\1</em>", E(x)) for x in hl)
    elif hook == "topic":
        hook_big = f"<em>{E(data.get('topic', S['name']))[:6]}</em>"
    elif hook == "date":
        hook_big = f"<em>{int(m.group(1))}月{int(m.group(2))}日</em>" if m else "<em>这一天</em>"
    else:
        hook_big = f"今日<em>{cn_num(n)}{E(S.get('hook_unit', '条'))}</em>"
    intro_t, outro_t = times[0], times[-1]
    seg = times[1:1 + n]
    starts = [seg[i][0] - 0.2 for i in range(n)]
    ends = [starts[i + 1] for i in range(n - 1)] + [outro_t[0] - 0.15]
    hook_end = starts[0]
    out_start = ends[-1]
    T = lambda x: f"{x:.3f}"

    cats = categories(items)
    css_colors = "".join(f".c{i}{{--c:{color(it['tag'], i)}}}" for i, it in enumerate(items))
    css_colors += "".join(f".k{j}{{--c:{color(c, items.index(next(x for x in items if x['tag'] == c)))}}}" for j, c in enumerate(cats))
    chips = "".join(f'<span class="chip k{j}" id="hook-chip{j}">{E(c)}</span>' for j, c in enumerate(cats))
    nb = SC.numbering(S) != "none"
    # 开场目录（channel.json 的 agenda）：full 标签 + 全部标题；tags 只列标签；none 都不列。
    # 有钩子句时默认 tags：第 1 秒就把各段标题（往往就是结论）亮出来，观众没有理由看完
    amode = budget.agenda_mode(S, bool(hookline))
    agenda = "".join(f'<li class="ag c{i}" id="ag{i}"><span class="num">{i + 1 if nb else "•"}</span><span class="agt">{E(it["title"].replace("|", ""))}</span></li>' for i, it in enumerate(items)) if amode == "full" else ""
    cover_row = f'<div class="cover"><span class="lab">{E(S["label"])}</span>{chips}</div>' if amode != "none" else ""
    # 有钩子句时 hook 顶替了开场大字，主题（成语、书名……）用小字标签补上（channel.json 的 topic_badge）
    badge = budget.topic_badge(data, S)
    badge_html = f'<div class="tbadge" id="hook-topic">{E(badge)}</div>' if badge else ""
    # 正文画面右下的来源行，带上频道固定声明（channel.json 的 disclaimer）
    disc = budget.disclaimer(S)
    src_line = S["src"] + (f" · {disc}" if disc else "")
    src_fs = max(20, min(28, int(880 / max(1, len(src_line)))))
    follow_top = 580 + n * 104 + (n - 1) * 26 + 80
    hook_js = ""
    if badge:
        hook_js += 'tl.fromTo("#hook-topic", {scale: 0.7, opacity: 0, transformOrigin: "0% 50%"}, {scale: 1, opacity: 1, duration: 0.3, ease: "back.out(2.5)"}, 0.05);\n      '
    if agenda:
        hook_js += f'tl.fromTo("#hook .agenda", {{opacity: 0.0}}, {{opacity: 1, duration: 0.35, ease: "power2.out"}}, {"0.5" if hookline else "0"});\n      '
        hook_js += 'tl.fromTo("#hook .ag .num", {scale: 1}, {scale: 1.18, duration: 0.18, ease: "power2.out", stagger: 0.25, yoyo: true, repeat: 1}, 0.6);\n      '
    if cover_row:
        hook_js += 'tl.fromTo("#hook .chip", {y: 0}, {y: -10, duration: 0.3, ease: "sine.inOut", stagger: 0.12, yoyo: true, repeat: 1}, 0.2);\n      '

    # 分镜：每段按 shot 渲染（文字 / 实拍素材 / 图表 / 地图 / 时间线 / 金句 / 你的素材），失败自动退回文字镜头
    ctx = SC.Ctx(proj, ROOT, os.environ.get("AUTOREEL_CACHE", "/tmp/ziying-footage-cache"))
    scenes, bgs, js, kinds = [], [], [], []
    if hookline:  # 开场垫实拍：稿子写了 hook_bg 就用它，否则借用第一个实拍镜头的关键词
        sh = [(it.get("shot") or {}) for it in items]
        hq = data.get("hook_bg") or next((x.get("query") or x.get("bg") or (x.get("queries") or [None])[0] for x in sh if x.get("type") == "footage" or x.get("bg")), None)
        hb, hj = SC.hook_bg(ctx, hq, 0, hook_end)
        if hb:
            bgs.append(hb); js.extend(hj)
    for i, it in enumerate(items):
        h, bg, sj, kind = SC.render(i, n, it, starts[i], ends[i], S, ctx, split_title)
        scenes.append(h); bgs.append(bg); js.extend(sj); kinds.append(kind)
    build.ctx = ctx
    build.kinds = kinds

    # 字幕：每句切短语，一次只显示一组
    caps, k = [], 0
    sents = (tts.synth.last or {}).get("sents") or []
    if not sents or max(x[0] for x in sents) != len(times) - 1:  # 没有逐句时间时，按整段平均分配
        sents = [(li, tts.display_text(spoken[li]), a, b) for li, (a, b) in enumerate(times)]
    pieces = []
    # 关键词：稿子里用 **…** 标出的词，字幕里高亮放大，出现时配一声轻提示音
    bold = [set(re.findall(r"\*\*(.+?)\*\*", re.sub(r"\{([^{}|]+)\|[^{}]*\}", r"\1", x))) for x in spoken]
    events = [(max(0.0, st - 0.12), "whoosh-short") for st in starts]  # 每段开头一声转场
    first = {}
    for li, txt, a, b in sents:
        first.setdefault(li, a)
        if 1 <= li <= n and a - first[li] > 0.5:  # 同一段里每句换一次镜头感：轻推近
            js.append(f'tl.fromTo("#scene{li - 1}", {{scale: 1.03}}, {{scale: 1, duration: 0.35, ease: "power2.out"}}, {T(a)});')
    popped = set()
    for li, txt, a, b in sents:
        if li == len(times) - 1:  # 结尾页已有"关注我"，不再加字幕
            continue
        if li == 0 and hookline:  # 开场的钩子句已经是大字，不再重复字幕
            continue
        if SC.numbering(S) == "spoken":  # 配音念的「一，」不上字幕，画面上已有序号
            txt = re.sub(r"^[一二三四五六七八九十]，", "", txt)
        if txt.strip():
            pieces.extend((p, ps, pe, li) for p, ps, pe in phrases(txt, a, b + 0.08, bold[li]))
    for j, (p, s, e, li) in enumerate(pieces):
        if j + 1 < len(pieces):
            e = min(e, pieces[j + 1][1])
        html_p, hit = E(p), False
        for w in sorted(bold[li], key=len, reverse=True):
            if w and E(w) in html_p:
                html_p, hit = html_p.replace(E(w), f"<em>{E(w)}</em>", 1), True
        caps.append(f'<div class="clip cap" id="cap{k}" data-start="{T(s)}" data-duration="{T(e - s)}" data-track-index="5"><span>{html_p}</span></div>')
        js.append(f'tl.fromTo("#cap{k} span", {{y: 16, opacity: 0}}, {{y: 0, opacity: 1, duration: 0.12, ease: "power2.out"}}, {T(s)});')
        if hit:
            js.append(f'tl.fromTo("#cap{k} em", {{scale: 1.35}}, {{scale: 1, duration: 0.3, ease: "back.out(3)"}}, {T(s)});')
            if li not in popped:  # 每段最多一声
                events.append((s, "pop")); popped.add(li)
        k += 1
    if data.get("ask"):
        events.append((out_start + 0.3, "chime"))
        if ask_options(data):
            js.append(f'tl.fromTo("#ask .opt", {{scale: 0.6, opacity: 0}}, {{scale: 1, opacity: 1, duration: 0.35, ease: "back.out(2)", stagger: 0.12}}, {T(out_start + 0.6)});')
    build.events = events

    recap = "".join(f'<div class="rc c{i}" id="rc{i}"><span class="rtag">{E(it["tag"])}</span>{E(it["title"].replace("|", ""))}</div>' for i, it in enumerate(items))
    js.append(f'''
      tl.fromTo("#outro .rc", {{x: -80, opacity: 0}}, {{x: 0, opacity: 1, duration: 0.3, ease: "power3.out", stagger: 0.08}}, {T(out_start)});
      tl.fromTo("#follow", {{scale: 0.6, opacity: 0}}, {{scale: 1, opacity: 1, duration: 0.45, ease: "back.out(2.2)"}}, {T(out_start + 0.5)});''')

    progress = "".join(f'<div class="pgs c{i}"><div class="pgf" id="pg{i}"></div></div>' for i in range(n))
    all_text = data["date"] + tts.display_text(data["intro"]) + tts.display_text(data["outro"]) + "💬评论区打A或B" + "".join(ask_options(data)) + "".join(it["tag"] + it["title"] + tts.display_text(it["say"]) for it in items) + "内容由AI生成热点快报今日大热点关注我每天一分钟看懂天下事信息来源公开报道本期涉及条一二三四五六七八九十月日这" + "".join(S[k] for k in ("name", "slogan", "label", "src")) + data.get("topic", "") + badge + disc + "".join(ctx.chars) + "单位："
    os.makedirs(f"{proj}/assets/fonts", exist_ok=True)
    subset_font("".join(sorted(set(all_text))), f"{proj}/assets/fonts/zh.woff2")
    shutil.copy(GSAP, f"{proj}/assets/gsap.min.js")

    page = f'''<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=1080, height=1920" />
    <script src="assets/gsap.min.js"></script>
    <style>
      @font-face {{ font-family: "ZenHei"; src: url("assets/fonts/zh.woff2") format("woff2"); font-weight: 400 900; }}
      * {{ margin: 0; padding: 0; box-sizing: border-box; }}
      html, body {{ width: 1080px; height: 1920px; overflow: hidden; background: #070a1c; }}
      #root {{ position: relative; width: 100%; height: 100%; overflow: hidden; font-family: "ZenHei", sans-serif; color: #fff;
              background: {S["base"]}; }}
      #flow {{ position: absolute; inset: -10%; background: linear-gradient(125deg, {S["flow"]});
              background-size: 300% 300%; }}
      #shade {{ position: absolute; inset: 0; background: linear-gradient(180deg, rgba(8,10,40,0.42) 0%, rgba(8,10,40,0.22) 35%, rgba(8,10,40,0.30) 65%, rgba(8,10,40,0.55) 100%); }}
      {css_colors}
      .glow {{ position: absolute; border-radius: 50%; filter: blur(110px); opacity: 0.65; }}
      #glowA {{ width: 780px; height: 780px; left: -240px; top: -100px; background: {S["glows"][0]}; }}
      #glowB {{ width: 720px; height: 720px; right: -260px; top: 1200px; background: {S["glows"][1]}; }}
      #glowC {{ width: 620px; height: 620px; right: -160px; top: 300px; background: {S["glows"][2]}; opacity: 0.5; }}
      #glowD {{ width: 680px; height: 680px; left: -200px; top: 900px; background: {S["glows"][3]}; opacity: 0.55; }}
      #grid {{ position: absolute; inset: 0; opacity: 0.09;
              background-image: linear-gradient(#fff 1px, transparent 1px), linear-gradient(90deg, #fff 1px, transparent 1px);
              background-size: 90px 90px; }}
      #deco {{ position: absolute; left: 60px; top: 1650px; font-family: "Inter", sans-serif; font-size: 130px; font-weight: 900; line-height: 0.95;
              color: transparent; -webkit-text-stroke: 3px rgba(255,255,255,0.10); letter-spacing: 8px; }}
      #head {{ position: absolute; left: 80px; top: 200px; display: flex; align-items: center; gap: 26px; }}
      #head .mark {{ width: 14px; height: 96px; border-radius: 7px; background: {S["mark"]}; }}
      #head h1 {{ font-size: 84px; font-weight: 900; letter-spacing: 4px; -webkit-text-stroke: 2px #fff; }}
      #head .date {{ font-size: 34px; color: #eef1ff; margin-top: 6px; }}
      #hook {{ position: absolute; left: 80px; right: 180px; top: 500px; }}
      #hook .big {{ font-size: 128px; font-weight: 900; line-height: 1.15; -webkit-text-stroke: 3px #fff; white-space: nowrap; }}
      #hook .cover {{ display: flex; align-items: center; flex-wrap: wrap; gap: 10px; margin-top: 46px; }}
      #hook .lab {{ font-size: 32px; color: #eef1ff; margin-right: 6px; }}
      #hook .agenda {{ list-style: none; margin-top: 56px; }}
      #hook .tbadge {{ display: inline-block; font-size: 40px; font-weight: 800; color: #0a0a18; background: {S["mark"]}; padding: 8px 26px;
                      border-radius: 14px; margin-bottom: 26px; letter-spacing: 2px; box-shadow: 0 4px 16px rgba(0,0,0,0.25); white-space: nowrap; }}
      .ag {{ display: flex; align-items: center; gap: 24px; font-size: 46px; font-weight: 700; padding: 16px 0;
             border-bottom: 2px solid rgba(255,255,255,0.10); white-space: nowrap; }}
      .ag .num {{ flex: none; width: 62px; height: 62px; border-radius: 16px; background: var(--c); color: #0a0a18;
                  text-align: center; line-height: 62px; font-size: 40px; font-weight: 900; }}
      #hook .big em {{ font-style: normal; color: #ffd84a; -webkit-text-stroke: 3px #ffd84a; }}
      #hook .chips {{ display: none; }}
      #hook .big.hookline {{ font-size: 86px; line-height: 1.22; white-space: nowrap; -webkit-text-stroke: 0; text-shadow: 0 4px 18px rgba(0,0,0,0.45); max-width: 900px; }}
      #hook .big.hookline em {{ -webkit-text-stroke: 0; }}
      #hook .big.hookline + .cover {{ margin-top: 30px; }}
      #hook .big.hookline ~ .agenda {{ margin-top: 30px; transform: scale(0.86); transform-origin: left top; }}
      #ask .opts {{ display: flex; gap: 18px; margin-top: 18px; }}
      #ask .opt {{ flex: 1; display: flex; align-items: center; gap: 14px; font-size: 44px; padding: 14px 20px; border-radius: 18px; background: rgba(255,255,255,0.16); }}
      #ask .opt b {{ width: 58px; height: 58px; border-radius: 50%; display: grid; place-items: center; background: #ffd84a; color: #1a1a2e; font-size: 38px; flex: none; }}
      #ask .opt.o1 b {{ background: #5ee0ff; }}
      #ask .hint {{ font-size: 30px; color: rgba(255,255,255,0.75); margin-top: 12px; font-weight: 600; }}
      #ask {{ position: absolute; left: 80px; right: 180px; font-size: 46px; font-weight: 800; color: #fff; line-height: 1.3;
              background: rgba(0,0,0,0.28); border-radius: 22px; padding: 22px 28px; }}
      .chip {{ font-size: 32px; padding: 8px 20px; border-radius: 999px; background: var(--c); color: #0a0a18; font-weight: 700; }}
      .scene {{ position: absolute; inset: 0; }}
      .ghost {{ position: absolute; right: 50px; top: 470px; font-size: 420px; font-weight: 900; line-height: 1; color: transparent;
               -webkit-text-stroke: 4px var(--c); opacity: 0.35; font-family: "ZenHei", sans-serif; }}
      .meta {{ position: absolute; left: 80px; top: 620px; display: flex; align-items: center; gap: 28px; }}
      .tag {{ font-size: 50px; font-weight: 700; padding: 12px 36px; border-radius: 18px; background: var(--c); color: #0a0a18; }}
      .idx {{ font-size: 38px; color: #ffffff; text-shadow: 0 2px 8px rgba(0,0,0,0.35); letter-spacing: 2px; }}
      .title {{ position: absolute; left: 80px; right: 180px; top: 840px; transform-origin: left center; }}
      .tline {{ font-size: 92px; font-weight: 900; line-height: 1.3; white-space: nowrap; -webkit-text-stroke: 2px #fff; }}
      .ch {{ display: inline-block; }}
      .bar {{ position: absolute; left: 80px; top: 1170px; width: 300px; height: 14px; border-radius: 7px; background: var(--c); transform-origin: left center; }}
      #progress {{ position: absolute; left: 80px; right: 180px; top: 1340px; display: flex; gap: 14px; }}
      .pgs {{ flex: 1; height: 10px; border-radius: 5px; background: rgba(255,255,255,0.14); overflow: hidden; }}
      .pgf {{ width: 100%; height: 100%; background: var(--c); transform-origin: left center; transform: scaleX(0); }}
      .cap {{ position: absolute; left: 40px; right: 160px; top: 1430px; text-align: center; overflow: visible; }}
      .cap span {{ display: inline-block; font-size: 64px; font-weight: 800; color: #ffffff; padding: 6px 14px; line-height: 1.25;
                  -webkit-text-stroke: 2px rgba(0,0,0,0.85); paint-order: stroke fill; text-shadow: 0 4px 14px rgba(0,0,0,0.6); }}
      .cap em {{ display: inline-block; font-style: normal; color: #ffd84a; transform-origin: center bottom; }}
      #outro {{ position: absolute; inset: 0; }}
      #recap {{ position: absolute; left: 80px; right: 180px; top: 580px; display: flex; flex-direction: column; gap: 26px; }}
      .rc {{ font-size: 48px; font-weight: 700; display: flex; align-items: center; gap: 24px; padding: 22px 28px; border-radius: 22px;
             background: rgba(255,255,255,0.07); border-left: 10px solid var(--c); }}
      .rtag {{ font-size: 34px; padding: 6px 18px; border-radius: 12px; background: var(--c); color: #0a0a18; }}
      #follow {{ position: absolute; left: 80px; right: 180px; top: 1420px; text-align: center; font-size: 50px; font-weight: 900;
                padding: 22px; border-radius: 999px; background: #ff4646; }}
      #ailabel {{ position: absolute; left: 80px; top: 120px; font-size: 28px; color: rgba(255,255,255,0.92); padding: 6px 18px;
                 border: 2px solid rgba(255,255,255,0.55); border-radius: 12px; background: rgba(0,0,0,0.22); letter-spacing: 2px; }}
{SC.CSS}
      #src {{ position: absolute; right: 180px; top: 1372px; font-size: 28px; color: rgba(255,255,255,0.88); text-shadow: 0 1px 6px rgba(0,0,0,0.4); }}
    </style>
  </head>
  <body>
    <div id="root" data-composition-id="main" data-start="0" data-duration="{T(dur)}" data-width="1080" data-height="1920">
      <audio id="vo" class="clip" data-start="0" data-duration="{T(times[-1][1] + 0.05)}" src="assets/voice.wav"></audio>
      <div id="bg" class="clip" data-start="0" data-duration="{T(dur)}" data-track-index="0" style="position:absolute;inset:0">
        <div id="flow"></div><div class="glow" id="glowA"></div><div class="glow" id="glowB"></div>
        <div class="glow" id="glowC"></div><div class="glow" id="glowD"></div><div id="shade"></div><div id="grid"></div>
        <div id="deco" data-layout-ignore>{S["deco"]}</div>
      </div>
      {"".join(bgs)}
      <div id="ailabel" class="clip" data-start="0" data-duration="{T(dur)}" data-track-index="4">内容由AI生成</div>
      <div id="head" class="clip" data-start="0" data-duration="{T(dur)}" data-track-index="1">
        <div class="mark"></div><div><h1>{S["name"]}</h1><div class="date">{E(data["date"])} · {E(S["slogan"])}</div></div>
      </div>
      <div id="hook" class="clip" data-start="0" data-duration="{T(hook_end)}" data-track-index="2">
        {badge_html}<div class="big{" hookline" if hookline else ""}" id="hook-big"{f' style="font-size:{hook_fs}px"' if hookline else ""}>{hook_big}</div>
        {cover_row}
        {f'<ol class="agenda">{agenda}</ol>' if agenda else ""}
      </div>
      {"".join(scenes)}
      <div id="progress" class="clip" data-start="{T(starts[0])}" data-duration="{T(out_start - starts[0])}" data-track-index="3">{progress}</div>
      <div id="src" class="clip" data-start="{T(starts[0])}" data-duration="{T(out_start - starts[0])}" data-track-index="3" style="font-size:{src_fs}px">{E(src_line)}</div>
      <div id="outro" class="clip" data-start="{T(out_start)}" data-duration="{T(dur - out_start)}" data-track-index="2">
        <div id="recap">{recap}</div>
        {ask_html(data, follow_top)}
        <div id="follow" style="top:{follow_top}px">关注我 · {E(follow_text(S))}</div>
      </div>
      {"".join(caps)}
    </div>
    <script>
      const tl = gsap.timeline({{ paused: true }});
      // 流动背景：渐变色带缓慢平移 + 4 团光晕往复漂移（有限次数，可逐帧复现）
      tl.fromTo("#flow", {{backgroundPosition: "0% 30%"}}, {{backgroundPosition: "100% 70%", duration: {T(dur / 2)}, ease: "sine.inOut", yoyo: true, repeat: 1}}, 0);
      tl.fromTo("#glowA", {{x: 0, y: 0, scale: 1}}, {{x: 380, y: 420, scale: 1.25, duration: 7, ease: "sine.inOut", yoyo: true, repeat: {int(dur // 7)}}}, 0);
      tl.fromTo("#glowB", {{x: 0, y: 0, scale: 1}}, {{x: -360, y: -480, scale: 1.2, duration: 8, ease: "sine.inOut", yoyo: true, repeat: {int(dur // 8)}}}, 0);
      tl.fromTo("#glowC", {{x: 0, y: 0}}, {{x: -420, y: 380, duration: 9, ease: "sine.inOut", yoyo: true, repeat: {int(dur // 9)}}}, 0);
      tl.fromTo("#glowD", {{x: 0, y: 0}}, {{x: 460, y: -300, duration: 6.5, ease: "sine.inOut", yoyo: true, repeat: {int(dur // 6.5)}}}, 0);
      tl.fromTo("#deco", {{x: 0}}, {{x: -120, duration: {T(dur)}, ease: "none"}}, 0);
      tl.fromTo("#grid", {{y: 0}}, {{y: -180, duration: {T(dur)}, ease: "none"}}, 0);
      tl.fromTo("#hook-big", {{scale: 1}}, {{scale: 1.06, duration: {T(hook_end)}, ease: "none"}}, 0);
      {hook_js}
      tl.to("#hook", {{opacity: 0, y: -60, duration: 0.2, ease: "power2.in"}}, {T(hook_end - 0.2)});
      {"".join(js)}
      window.__timelines["main"] = tl;
    </script>
  </body>
</html>
'''
    open(f"{proj}/index.html", "w").write(page)


def main():
    src, proj = sys.argv[1], sys.argv[2]
    data = json.load(open(src, encoding="utf-8"))
    S = series(data)
    target = float(S.get("max_seconds", 90)) + 10  # 正常语速读完即可；超出上限时由写稿环节删短
    # 开场：有钩子句就直接念钩子（频道名和日期只在画面顶部显示），没有才用频道的开场白模板
    # 结尾：有 ask 就先抛互动问题，再请关注；拼法和 make.py 的时长预检共用 budget.py
    data["intro"] = budget.intro_text(data, S)
    data["outro"] = budget.outro_text(data, S)
    vs = S.get("voice") or {}  # 频道的配音语气：mood 默认语气，intro_mood / outro_mood 开场和结尾
    lines = ([{"text": data["intro"], "mood": data.get("intro_mood") or vs.get("intro_mood", "轻快")}]
             + [{"text": spoken_item(i, it["say"], SC.numbering(S)), "mood": it.get("mood") or vs.get("mood", "平稳"), "pace": it.get("pace") or vs.get("pace")}
                for i, it in enumerate(data["items"])]
             + [{"text": data["outro"], "mood": data.get("outro_mood") or vs.get("outro_mood", "温暖")}])
    voice = json.loads(json.dumps(VOICE))  # 频道可以单独指定音色
    if vs.get("voice"):
        voice.setdefault("cosyvoice", {})["voice"] = vs["voice"]
    if vs.get("speed"):  # 频道语速倍率，1 为默认
        voice["speed_factor"] = float(vs["speed"])
    if vs.get("volc_speaker"):
        voice.setdefault("volcengine", {})["speaker"] = vs["volc_speaker"]
    audio, sr, times, speed = tts.synth(lines, voice, target)
    lines = [ln["text"] for ln in lines]
    dur = round(len(audio) / sr + 0.5, 2)
    os.makedirs(f"{proj}/assets", exist_ok=True)
    sf.write(f"{proj}/assets/voice.wav", audio, sr)
    build(data, times, dur, proj, lines)
    # 混音：背景音乐（人声出现时自动压低）+ 转场和关键词音效
    try:
        import mix as MX
        bg = MX.background(vs.get("bgm", VOICE.get("bgm", "auto")), vs.get("mood", "平稳"), len(audio) / sr, sr, ROOT)
        mixed = MX.mix(audio, sr, getattr(build, "events", []), bg)
        sf.write(f"{proj}/assets/voice.wav", tts._master(mixed), sr)
        print(f"混音：背景音乐{'（' + str(vs.get('bgm', 'auto')) + '）' if bg is not None else '无'}，音效 {len(getattr(build, 'events', []))} 处")
    except Exception as e:  # 混音出问题就用纯配音，不影响出片
        print(f"提醒：混音失败，用纯配音（{e}）")
    if not os.path.exists(f"{proj}/hyperframes.json"):
        json.dump({"name": "autoreel"}, open(f"{proj}/hyperframes.json", "w"))
    cap = make_caption(data)
    cap_path = os.path.join(os.path.dirname(os.path.abspath(src)), "抖音文案.txt")
    open(cap_path, "w").write(cap)
    # 发布信息（浏览器插件用）：标题≤30字（格式见 budget.publish_title）；正文=文案去掉最后一行话题；话题单独传
    tags = [t.lstrip("#") for t in (data.get("hashtags") or S["hashtags"] + categories(data["items"]))]
    ctx = getattr(build, "ctx", None)
    if ctx and ctx.credits:  # 实拍素材署名：写进文案（来源行之后）
        lines_ = cap.split("\n")
        lines_.insert(len(lines_) - 1, "🎬 画面素材：" + "、".join(dict.fromkeys(ctx.credits)) + "（免版权素材）")
        cap = "\n".join(lines_)
        open(cap_path, "w").write(cap)
    if ctx:  # 实拍素材清单（make.py 按它给每段实拍抽检查帧，核对画面和口播）
        json.dump(ctx.used, open(f"{proj}/素材.json", "w"), ensure_ascii=False, indent=1)
    for w in dict.fromkeys(ctx.warnings if ctx else []):  # 同一条提醒只打印一次
        print(f"提醒：{w}")
    if ctx:
        print("分镜：" + " / ".join(f"{i + 1}.{k}" for i, k in enumerate(build.kinds)))
    meta = {"title": budget.publish_title(data, S),  # channel.json 的 title_format，默认「headline｜频道名」 "desc": cap.rsplit("\n", 1)[0], "tags": tags[:5],
            "declaration": (CONFIG.get("publish") or {}).get("declaration", "内容由AI生成"), "collection": S.get("collection", S["name"]),
            "channel": S["id"]}
    # 竖封面 3:4 + 横封面 4:3（JPEG，base64 内嵌在发布信息里，插件解出来上传）
    try:
        from make_cover import covers
        meta["covers"] = covers(data, color, S)
    except Exception as e:
        print(f"封面生成失败（不影响视频，抖音会用默认封面）：{e!r}")
    json.dump(meta, open(os.path.join(os.path.dirname(cap_path), "发布信息.json"), "w"), ensure_ascii=False, indent=1)
    rep = (tts.synth.last or {}).get("report") or {}
    json.dump(rep, open(os.path.join(os.path.dirname(cap_path), "配音检查.json"), "w"), ensure_ascii=False, indent=1)
    print(f"工程已生成: {proj}  时长 {dur}s  语速 x{speed:.2f}")
    print(f"抖音文案: {cap_path}  （{len(cap)} 字，抖音上限约1000字）")


if __name__ == "__main__":
    main()
