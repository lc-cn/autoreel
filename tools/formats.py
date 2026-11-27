"""自影 · 视频形式：同一份稿子，用不同的画面和节奏呈现，方便测试哪种形式更适合哪个赛道。

稿子（script.json）里写 "format"，或在 channel.json 里写默认的 "format"：
  classic    经典版（默认）：顶栏频道名 + 开场目录 + 每段标签、标题、进度条 + 底部字幕
  immersive  实拍沉浸：全屏实拍，没有顶栏、目录和进度条，只有大字幕；适合快报、冷知识
  kinetic    大字快剪：没有背景图，口播的每个短语变成满屏大字，跟着节奏换色、换动作；适合讲透、冷知识
  soft       柔光卡片：暖灰底 + 淡极光、浅色主卡、无描边白卡片、胶囊按钮，黑白主色，浅彩只区分类别（按《柔光卡片设计包》）
  quiz       答题挑战：开场出题 + 选项，倒数 3 秒，揭晓答案后再讲解；适合成语、冷知识
             需要在稿子里写 "quiz": {"question": "…", "options": ["…", "…", "…"], "answer": 0}

gen_hf.build() 遇到 classic 以外的形式时调用这里的 build(fmt, ...)。
"""
import os
import re
import shutil

import scenes as SC

FORMATS = ("classic", "immersive", "kinetic", "quiz", "soft")
T = lambda x: f"{x:.3f}"
QUIZ_GAP = 3.0  # 答题挑战：念完题目后留给观众想的秒数（画面倒数 3、2、1）


def pick(data, S):
    f = (data.get("format") or S.get("format") or "classic").strip()
    return f if f in FORMATS else "classic"


# ───────── 公共部分 ─────────
def _pieces(G, spoken, times, S, skip=()):
    """把逐句时间切成字幕短语：[(文字, 开始, 结束, 行号, 这一行的关键词)]。skip 里的行号不出字幕。"""
    sents = (G.tts.synth.last or {}).get("sents") or []
    if not sents or max(x[0] for x in sents) != len(times) - 1:
        sents = [(li, G.tts.display_text(spoken[li]), a, b) for li, (a, b) in enumerate(times)]
    bold = [set(re.findall(r"\*\*(.+?)\*\*", re.sub(r"\{([^{}|]+)\|[^{}]*\}", r"\1", x))) for x in spoken]
    out = []
    for li, txt, a, b in sents:
        if li in skip:
            continue
        if SC.numbering(S) == "spoken":
            txt = re.sub(r"^[一二三四五六七八九十]，", "", txt)
        if txt.strip():
            out.extend((p, ps, pe, li, bold[li]) for p, ps, pe in G.phrases(txt, a, b + 0.08, bold[li]))
    for j in range(len(out) - 1):  # 一次只显示一组
        p, s, e, li, kw = out[j]
        out[j] = (p, s, min(e, out[j + 1][1]), li, kw)
    return out


def _em(G, p, kw):
    h, hit = G.E(p), False
    for w in sorted(kw, key=len, reverse=True):
        if w and G.E(w) in h:
            h, hit = h.replace(G.E(w), f"<em>{G.E(w)}</em>", 1), True
    return h, hit


def _queries(it):
    sh = it.get("shot") or {}
    qs = [q for q in (sh.get("queries") or []) if q][:4]
    for q in (sh.get("query"), sh.get("bg"), it.get("bg")):
        if q and q not in qs:
            qs.append(q)
    return qs


def _footage(ctx, key, qs, s, e, js):
    """一段时间里轮流放几段实拍（每段一个不计时的外框负责缓慢推近）。返回 html，找不到素材返回 ""。"""
    qs = qs[:max(1, min(len(qs), int((e - s) // 2.5) or 1))]
    part = (e - s) / max(1, len(qs))
    out = []
    for k, q in enumerate(qs):
        a, b = s + k * part, (s + (k + 1) * part if k < len(qs) - 1 else e)
        src = ctx.footage(f"{key}_{k}", q, b - a)
        if not src:
            continue
        fid = f"fw{key}_{k}"
        out.append(f'<div class="fw" id="{fid}"><video id="v{key}_{k}" class="clip fv" src="{src}" data-start="{T(a)}" data-duration="{T(b - a)}" data-track-index="1" muted playsinline></video></div>')
        z0, z1 = (1.0, 1.12) if k % 2 == 0 else (1.12, 1.0)
        js.append(f'tl.fromTo("#{fid}", {{scale: {z0}}}, {{scale: {z1}, duration: {T(b - a)}, ease: "none"}}, {T(a)});')
    return "".join(out)


def _ask_block(G, data, S, top):
    """结尾：互动问题大字 + A/B 选项 + 关注我。"""
    ask = G.tts.display_text(data.get("ask") or "").strip()
    opts = G.ask_options(data)
    btns = "".join(f'<div class="opt o{k}"><b>{"AB"[k]}</b>{G.E(x)}</div>' for k, x in enumerate(opts))
    return (f'<div class="askq" style="top:{top}px">{G.E(ask)}</div>'
            + (f'<div class="opts" style="top:{top + 260}px">{btns}</div><div class="hint" style="top:{top + 400}px">评论区打 A 或 B</div>' if opts else
               f'<div class="hint" style="top:{top + 220}px">评论区告诉我</div>')
            + f'<div class="follow" style="top:{top + 500}px">关注我 · {G.E(G.follow_text(S))}</div>')


BASE_CSS = """
      @font-face { font-family: "ZenHei"; src: url("assets/fonts/zh.woff2") format("woff2"); font-weight: 400 900; }
      * { margin: 0; padding: 0; box-sizing: border-box; }
      html, body { width: 1080px; height: 1920px; overflow: hidden; background: #05060f; }
      #root { position: relative; width: 100%; height: 100%; overflow: hidden; font-family: "ZenHei", sans-serif; color: #fff; background: #05060f; }
      #ailabel { position: absolute; left: 60px; top: 110px; font-size: 26px; color: rgba(255,255,255,0.9); padding: 5px 16px;
                 border: 2px solid rgba(255,255,255,0.5); border-radius: 12px; background: rgba(0,0,0,0.25); letter-spacing: 2px; }
      .fw { position: absolute; left: 0; top: 0; width: 1080px; height: 1920px; overflow: hidden; }
      .fw .fv { position: absolute; left: 0; top: 0; width: 1080px; height: 1920px; object-fit: cover; }
      .askq { position: absolute; left: 70px; right: 170px; font-size: 76px; font-weight: 900; line-height: 1.3; text-align: center; text-shadow: 0 6px 26px rgba(0,0,0,0.6); }
      .opts { position: absolute; left: 70px; right: 170px; display: flex; gap: 24px; }
      .opt { flex: 1; display: flex; align-items: center; justify-content: center; gap: 16px; font-size: 52px; font-weight: 800; padding: 22px 16px; border-radius: 24px; background: rgba(255,255,255,0.16); }
      .opt b { width: 70px; height: 70px; border-radius: 50%; display: grid; place-items: center; background: #ffd84a; color: #14142a; font-size: 44px; flex: none; }
      .opt.o1 b { background: #5ee0ff; }
      .hint { position: absolute; left: 70px; right: 170px; text-align: center; font-size: 34px; font-weight: 700; color: rgba(255,255,255,0.8); }
      .follow { position: absolute; left: 70px; right: 170px; text-align: center; font-size: 42px; font-weight: 900; padding: 18px 10px; border-radius: 999px; background: #ff4646; white-space: nowrap; }
      /* 字库只有常规体：大字用同色描边加粗 */
      .askq, .opt, .follow, #hook, .ltt, .kw span, .qq, .qo span, .ett, .cd span { -webkit-text-stroke: 0.045em currentColor; }
      .ltag, .etag, .badge, .sg span { -webkit-text-stroke: 0.03em currentColor; }
"""


def _page(G, data, S, ctx, dur, times, css, body, js, extra_text=""):
    texts = (data["date"] + G.tts.display_text(data.get("intro", "")) + G.tts.display_text(data.get("outro", ""))
             + "".join(it["tag"] + it["title"] + G.tts.display_text(it["say"]) for it in data["items"])
             + G.tts.display_text(data.get("ask") or "") + "".join(G.ask_options(data)) + G.follow_text(S) + S["name"]
             + "内容由AI生成关注我评论区打A或B告诉我答案是想一想" + "".join(ctx.chars) + extra_text)
    os.makedirs(f"{ctx.proj}/assets/fonts", exist_ok=True)
    G.subset_font("".join(sorted(set(texts))), f"{ctx.proj}/assets/fonts/zh.woff2")
    shutil.copy(G.GSAP, f"{ctx.proj}/assets/gsap.min.js")
    page = f'''<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=1080, height=1920" />
    <script src="assets/gsap.min.js"></script>
    <style>{BASE_CSS}{css}
    </style>
  </head>
  <body>
    <div id="root" data-composition-id="main" data-start="0" data-duration="{T(dur)}" data-width="1080" data-height="1920">
      <audio id="vo" class="clip" data-start="0" data-duration="{T(times[-1][1] + 0.05)}" src="assets/voice.wav"></audio>
{body}
      <div id="ailabel" class="clip" data-start="0" data-duration="{T(dur)}" data-track-index="9">内容由AI生成</div>
    </div>
    <script>
      const tl = gsap.timeline({{ paused: true }});
      {"".join(js)}
      window.__timelines["main"] = tl;
    </script>
  </body>
</html>
'''
    open(f"{ctx.proj}/index.html", "w").write(page)


def _layout(data, times):
    n = len(data["items"])
    seg = times[1:1 + n]
    starts = [seg[i][0] - 0.2 for i in range(n)]
    ends = [starts[i + 1] for i in range(n - 1)] + [times[-1][0] - 0.15]
    return n, starts, ends, starts[0], ends[-1]


def build(fmt, G, data, times, dur, proj, spoken):
    S = G.series(data)
    ctx = SC.Ctx(proj, G.ROOT, os.environ.get("AUTOREEL_CACHE", "/tmp/ziying-footage-cache"))
    fn = {"immersive": _immersive, "kinetic": _kinetic, "quiz": _quiz, "soft": _soft}[fmt]
    events, kinds = fn(G, S, ctx, data, times, dur, spoken)
    return ctx, events, kinds


# ───────── 实拍沉浸 ─────────
def _immersive(G, S, ctx, data, times, dur, spoken):
    items = data["items"]
    n, starts, ends, hook_end, out_start = _layout(data, times)
    js, body, events, kinds = [], [], [], []
    # 底层：频道主色的暗色渐变（找不到实拍时露出来）
    body.append(f'<div id="base" class="clip" data-start="0" data-duration="{T(dur)}" data-track-index="0"></div>')
    hq = data.get("hook_bg") or next((q for it in items for q in _queries(it)), None)
    body.append(_footage(ctx, "h", [hq] if hq else [], 0, hook_end, js) if hq else "")
    for i, it in enumerate(items):
        ctx.text(it["tag"], it["title"])
        f = _footage(ctx, str(i), _queries(it), starts[i], ends[i], js)
        kinds.append("footage" if f else "title")
        body.append(f)
        # 段落小标题：左上角一闪而过，告诉观众现在讲什么，不挡画面
        title = G.E(it["title"].replace("|", ""))
        big = "" if f else " big"  # 没有实拍时，标题放大居中，当作标题卡
        body.append(f'<div id="lt{i}" class="clip lt{big}" data-start="{T(starts[i])}" data-duration="{T(min(ends[i] - starts[i], 3.2 if f else ends[i] - starts[i]))}" data-track-index="4"><span class="ltag">{G.E(it["tag"])}</span><span class="ltt">{title}</span></div>')
        js.append(f'tl.fromTo("#lt{i}", {{x: -60, opacity: 0}}, {{x: 0, opacity: 1, duration: 0.3, ease: "power3.out"}}, {T(starts[i] + 0.1)});')
        if f:
            js.append(f'tl.to("#lt{i}", {{opacity: 0, duration: 0.3}}, {T(starts[i] + 2.8)});')
        # 段与段之间白闪一下，像剪辑点
        body.append(f'<div id="fl{i}" class="clip flash" data-start="{T(starts[i])}" data-duration="0.2" data-track-index="8"></div>')
        js.append(f'tl.fromTo("#fl{i}", {{opacity: 0.55}}, {{opacity: 0, duration: 0.2, ease: "power2.out"}}, {T(starts[i])});')
        events.append((max(0.0, starts[i] - 0.1), "whoosh-short"))
    body.append(f'<div id="shade" class="clip" data-start="0" data-duration="{T(dur)}" data-track-index="3"></div>')
    # 开场钩子：大字居中，逐行砸下来
    hook = re.sub(r"\{([^{}|]+)\|[^{}]*\}", r"\1", data.get("hook") or data["intro"])
    lines = G.hook_lines(hook, 9)
    longest = max(len(re.sub(r"\*\*", "", x)) for x in lines)
    fs = max(70, min(118, int(860 / max(1, longest))))
    hl = "".join(f'<div class="hl">{re.sub(r"[*][*](.+?)[*][*]", r"<em>\1</em>", G.E(x))}</div>' for x in lines)
    body.append(f'<div id="hook" class="clip" data-start="0" data-duration="{T(hook_end)}" data-track-index="5" style="font-size:{fs}px">{hl}</div>')
    js.append(f'tl.fromTo("#hook .hl", {{y: 80, scale: 1.25, opacity: 0}}, {{y: 0, scale: 1, opacity: 1, duration: 0.32, ease: "back.out(2)", stagger: 0.22}}, 0.05);')
    js.append(f'tl.to("#hook", {{opacity: 0, scale: 0.92, duration: 0.2}}, {T(hook_end - 0.2)});')
    events.append((0.05, "whoosh-short"))
    # 字幕：大、居中偏下，关键词变黄弹一下
    popped = set()
    for k, (p, s, e, li, kw) in enumerate(_pieces(G, spoken, times, S, skip={0, len(times) - 1})):
        h, hit = _em(G, p, kw)
        body.append(f'<div class="clip cap" id="cap{k}" data-start="{T(s)}" data-duration="{T(e - s)}" data-track-index="6"><span>{h}</span></div>')
        js.append(f'tl.fromTo("#cap{k} span", {{y: 24, opacity: 0}}, {{y: 0, opacity: 1, duration: 0.14, ease: "power2.out"}}, {T(s)});')
        if hit:
            js.append(f'tl.fromTo("#cap{k} em", {{scale: 1.5}}, {{scale: 1, duration: 0.32, ease: "back.out(3)"}}, {T(s)});')
            if li not in popped:
                events.append((s, "pop")); popped.add(li)
    # 结尾
    body.append(f'<div id="outro" class="clip" data-start="{T(out_start)}" data-duration="{T(dur - out_start)}" data-track-index="7">{_ask_block(G, data, S, 620)}</div>')
    js.append(f'tl.fromTo("#outro .askq", {{y: 60, opacity: 0}}, {{y: 0, opacity: 1, duration: 0.35, ease: "power3.out"}}, {T(out_start + 0.05)});')
    js.append(f'tl.fromTo("#outro .opt", {{scale: 0.6, opacity: 0}}, {{scale: 1, opacity: 1, duration: 0.35, ease: "back.out(2)", stagger: 0.12}}, {T(out_start + 0.5)});')
    js.append(f'tl.fromTo("#outro .follow", {{scale: 0.6, opacity: 0}}, {{scale: 1, opacity: 1, duration: 0.4, ease: "back.out(2)"}}, {T(out_start + 0.9)});')
    if data.get("ask"):
        events.append((out_start + 0.3, "chime"))
    css = f"""
      #base {{ position: absolute; inset: 0; background: radial-gradient(ellipse at 50% 35%, {S["glows"][0]}55 0%, {S["base"]} 55%, #04050c 100%); }}
      #shade {{ position: absolute; inset: 0; background: linear-gradient(180deg, rgba(0,0,0,0.55) 0%, rgba(0,0,0,0.05) 22%, rgba(0,0,0,0.05) 50%, rgba(0,0,0,0.6) 72%, rgba(0,0,0,0.75) 100%); }}
      #hook {{ position: absolute; left: 70px; right: 170px; top: 640px; font-weight: 900; line-height: 1.25; text-shadow: 0 8px 30px rgba(0,0,0,0.75), 0 2px 6px rgba(0,0,0,0.8); }}
      #hook .hl {{ white-space: nowrap; }}
      #hook em, .cap em {{ font-style: normal; color: #ffd84a; display: inline-block; }}
      .lt {{ position: absolute; left: 60px; top: 190px; display: flex; align-items: center; gap: 18px; }}
      .ltag {{ font-size: 34px; font-weight: 800; padding: 6px 18px; border-radius: 10px; background: {S["mark"]}; color: #0b0b16; }}
      .ltt {{ font-size: 40px; font-weight: 800; text-shadow: 0 3px 12px rgba(0,0,0,0.7); white-space: nowrap; }}
      .lt.big {{ top: 640px; flex-direction: column; align-items: flex-start; gap: 30px; }}
      .lt.big .ltt {{ font-size: 96px; font-weight: 900; }}
      .flash {{ position: absolute; inset: 0; background: #fff; }}
      .cap {{ position: absolute; left: 40px; right: 150px; top: 1180px; text-align: center; }}
      .cap span {{ display: inline-block; font-size: 76px; font-weight: 900; line-height: 1.25; color: #fff;
                  -webkit-text-stroke: 3px rgba(0,0,0,0.9); paint-order: stroke fill; text-shadow: 0 6px 20px rgba(0,0,0,0.7); }}
      #outro {{ position: absolute; inset: 0; background: rgba(0,0,0,0.55); }}
"""
    _page(G, data, S, ctx, dur, times, css, "\n".join(body), js)
    return events, kinds


# ───────── 大字快剪 ─────────
def _kinetic(G, S, ctx, data, times, dur, spoken):
    items = data["items"]
    n, starts, ends, hook_end, out_start = _layout(data, times)
    js, body, events = [], [], []
    accent = S["mark"]
    # 每句换一块底色：深、主色、浅、黄 轮换；浅底配深字
    BGS = [("#0b0d1a", "#ffffff", "#ffd84a"), (accent, "#0b0d1a", "#ffffff"), ("#f4f1ea", "#14142a", "#e0242f"), ("#ffd84a", "#14142a", "#e0242f"), (S["base"], "#ffffff", "#ffd84a")]
    pcs = _pieces(G, spoken, times, S, skip={len(times) - 1})
    # 底色块：按句子（行号 + 句子开头）切换
    sents = (G.tts.synth.last or {}).get("sents") or [(li, "", a, b) for li, (a, b) in enumerate(times)]
    blocks = [(a, li) for li, _t, a, _b in sents if li != len(times) - 1]
    blocks.sort()
    css_bg = []
    for j, (a, li) in enumerate(blocks):
        b = blocks[j + 1][0] if j + 1 < len(blocks) else out_start
        if b - a < 0.05:
            continue
        bg, fg, hi = BGS[j % len(BGS)]
        body.append(f'<div id="bk{j}" class="clip bk" data-start="{T(a)}" data-duration="{T(b - a)}" data-track-index="0" style="background:{bg}"></div>')
        js.append(f'tl.fromTo("#bk{j}", {{clipPath: "inset(0 0 100% 0)"}}, {{clipPath: "inset(0 0 0% 0)", duration: 0.18, ease: "power3.out"}}, {T(a)});')
        css_bg.append((a, b, fg, hi))

    def colors_at(t):
        for a, b, fg, hi in css_bg:
            if a - 0.01 <= t < b:
                return fg, hi
        return "#ffffff", "#ffd84a"

    def wrap(p, kw):
        marked = p
        for w in sorted(kw, key=len, reverse=True):
            if w and w in marked and f"**{w}**" not in marked:
                marked = marked.replace(w, f"**{w}**", 1)
        n_ = 6 if len(p) > 6 else 7
        ls = [marked]
        while any(len(x.replace("**", "")) > n_ for x in ls) and len(ls) < 3:
            j = max(range(len(ls)), key=lambda i_: len(ls[i_].replace("**", "")))
            ls[j:j + 1] = G.hook_lines(ls[j], n_)[:2] if len(G.hook_lines(ls[j], n_)) > 1 else [ls[j]]
            if len(ls) == 1 or all(len(x.replace("**", "")) <= n_ for x in ls):
                break
        ls = [x for x in ls if x.replace("**", "")]
        longest = max(len(x.replace("**", "")) for x in ls)
        h = "<br />".join(re.sub(r"[*][*](.+?)[*][*]", r"<em>\1</em>", G.E(x)) for x in ls)
        return h, ("<em>" in h), longest

    MOVES = ['{scale: 1.7, opacity: 0}', '{x: -260, opacity: 0}', '{y: 220, opacity: 0}', '{rotation: -8, scale: 0.6, opacity: 0}', '{x: 260, opacity: 0}']
    popped = set()
    for k, (p, s, e, li, kw) in enumerate(pcs):
        h, hit, L = wrap(p, kw)
        fs = max(96, min(200, int(840 / max(1, L))))  # 按最长一行定字号：短语越短字越大
        if re.search(r"\d", p) and L <= 6:
            fs = min(220, int(fs * 1.15))
        fg, hi = colors_at(s)
        align = ("left", "center", "left", "center", "left")[k % 5]
        body.append(f'<div class="clip kw" id="kw{k}" data-start="{T(s)}" data-duration="{T(max(0.12, e - s))}" data-track-index="5" style="text-align:{align}"><span style="font-size:{fs}px;color:{fg};--hi:{hi}">{h}</span></div>')
        js.append(f'tl.from("#kw{k} span", {{...{MOVES[k % len(MOVES)]}, duration: 0.16, ease: "power3.out"}}, {T(s)});')
        if hit:
            js.append(f'tl.fromTo("#kw{k} em", {{scale: 1.6}}, {{scale: 1, duration: 0.3, ease: "back.out(3)"}}, {T(s + 0.05)});')
            if li not in popped:
                events.append((s, "pop")); popped.add(li)
    # 段落标签：顶部小字，告诉观众讲到哪一步
    for i, it in enumerate(items):
        ctx.text(it["tag"])
        fg, _ = colors_at(starts[i] + 0.3)
        body.append(f'<div id="sg{i}" class="clip sg" data-start="{T(starts[i])}" data-duration="{T(ends[i] - starts[i])}" data-track-index="6"><span style="border-color:{fg};color:{fg}">{G.E(it["tag"])}</span></div>')
        events.append((max(0.0, starts[i] - 0.08), "whoosh-short"))
    body.append(f'<div id="outro" class="clip" data-start="{T(out_start)}" data-duration="{T(dur - out_start)}" data-track-index="7">{_ask_block(G, data, S, 620)}</div>')
    js.append(f'tl.fromTo("#outro .askq", {{scale: 1.4, opacity: 0}}, {{scale: 1, opacity: 1, duration: 0.3, ease: "power3.out"}}, {T(out_start + 0.05)});')
    js.append(f'tl.fromTo("#outro .opt", {{y: 80, opacity: 0}}, {{y: 0, opacity: 1, duration: 0.3, ease: "back.out(2)", stagger: 0.1}}, {T(out_start + 0.45)});')
    js.append(f'tl.fromTo("#outro .follow", {{scale: 0.6, opacity: 0}}, {{scale: 1, opacity: 1, duration: 0.4, ease: "back.out(2)"}}, {T(out_start + 0.9)});')
    if data.get("ask"):
        events.append((out_start + 0.3, "chime"))
    css = f"""
      .bk {{ position: absolute; inset: 0; }}
      .kw {{ position: absolute; left: 70px; right: 170px; top: 620px; height: 700px; display: flex; flex-direction: column; justify-content: center; }}
      .kw span {{ display: block; font-weight: 900; line-height: 1.18; letter-spacing: 2px; white-space: nowrap; }}
      .kw em {{ font-style: normal; color: var(--hi); display: inline-block; }}
      .sg {{ position: absolute; left: 70px; top: 200px; }}
      .sg span {{ display: inline-block; font-size: 38px; font-weight: 800; padding: 6px 22px; border: 3px solid; border-radius: 999px; }}
      #outro {{ position: absolute; inset: 0; background: #0b0d1a; }}
"""
    _page(G, data, S, ctx, dur, times, css, "\n".join(body), js)
    return events, ["kinetic"] * n


# ───────── 答题挑战 ─────────
def quiz_intro(G, data):
    """答题挑战的开场口播：题目 + 选项（念完后留 3 秒让观众想）。"""
    q = data.get("quiz") or {}
    opts = [str(x).strip() for x in q.get("options") or []][:3]
    head = (data.get("hook") or q.get("question") or "").strip()
    read = "".join(f"{'ABC'[k]}，{x}。" for k, x in enumerate(opts))
    return f"{head}{'' if head[-1:] in '？?。！!' else '？'}{read}你选哪个？"


def _quiz(G, S, ctx, data, times, dur, spoken):
    items = data["items"]
    q = data.get("quiz") or {}
    opts = [str(x).strip() for x in q.get("options") or []][:3]
    ans = int(q.get("answer", 0)) if opts else 0
    n, starts, ends, hook_end, out_start = _layout(data, times)
    js, body, events, kinds = [], [], [], []
    reveal = starts[0]
    cd0 = reveal - QUIZ_GAP  # 倒数开始
    question = G.tts.display_text(q.get("question") or data.get("hook") or "")
    ctx.text(question, "".join(opts), "ABC✓", S["name"])
    body.append(f'<div id="base" class="clip" data-start="0" data-duration="{T(dur)}" data-track-index="0"></div>')
    # 讲解阶段的实拍背景（暗一些）
    for i, it in enumerate(items):
        f = _footage(ctx, str(i), _queries(it), starts[i], ends[i], js)
        kinds.append("footage" if f else "title")
        body.append(f)
    body.append(f'<div id="shade" class="clip" data-start="{T(reveal)}" data-duration="{T(out_start - reveal)}" data-track-index="2"></div>')
    # 题目 + 选项：开场到揭晓后 1.5 秒；揭晓后整块缩到顶部，变成「答案卡」
    cards = "".join(f'<div class="qo" id="qo{k}"><b>{"ABC"[k]}</b><span>{G.E(x)}</span><i class="ok" id="ok{k}">✓</i></div>' for k, x in enumerate(opts))
    qend = out_start
    body.append(f'<div id="quiz" class="clip" data-start="0" data-duration="{T(qend)}" data-track-index="5"><div class="badge">{G.E(S["name"])} · 小测验</div><div class="qq">{"<br />".join(G.E(x) for x in G.hook_lines(question, 10))}</div><div class="qos">{cards}</div></div>')
    js.append('tl.fromTo("#quiz .qq", {y: 60, opacity: 0}, {y: 0, opacity: 1, duration: 0.35, ease: "power3.out"}, 0.05);')
    js.append('tl.fromTo("#quiz .qo", {x: -120, opacity: 0}, {x: 0, opacity: 1, duration: 0.3, ease: "back.out(1.8)", stagger: 0.18}, 0.6);')
    # 倒数 3、2、1
    for j in range(3):
        a = cd0 + j
        body.append(f'<div id="cd{j}" class="clip cd" data-start="{T(a)}" data-duration="1.000" data-track-index="6"><span>{3 - j}</span></div>')
        js.append(f'tl.fromTo("#cd{j} span", {{scale: 1.8, opacity: 0}}, {{scale: 1, opacity: 1, duration: 0.25, ease: "back.out(2)"}}, {T(a)});')
        js.append(f'tl.to("#cd{j} span", {{opacity: 0, duration: 0.2}}, {T(a + 0.78)});')
        events.append((a, "click-soft"))
    body.append(f'<div id="ring" class="clip" data-start="{T(cd0)}" data-duration="{T(QUIZ_GAP)}" data-track-index="6"><svg viewBox="0 0 200 200"><circle cx="100" cy="100" r="88" class="rbg"/><circle id="rfg" cx="100" cy="100" r="88" class="rfg"/></svg></div>')
    js.append(f'tl.fromTo("#rfg", {{strokeDashoffset: 0}}, {{strokeDashoffset: 553, duration: {T(QUIZ_GAP)}, ease: "none"}}, {T(cd0)});')
    # 揭晓：正确选项变绿打勾，其他变暗
    for k in range(len(opts)):
        if k == ans:
            js.append(f'tl.to("#qo{k}", {{backgroundColor: "#22c55e", scale: 1.06, duration: 0.25, ease: "back.out(2)"}}, {T(reveal)});')
            js.append(f'tl.fromTo("#ok{k}", {{scale: 0, opacity: 0}}, {{scale: 1, opacity: 1, duration: 0.3, ease: "back.out(3)"}}, {T(reveal + 0.1)});')
        else:
            js.append(f'tl.to("#qo{k}", {{opacity: 0.3, duration: 0.25}}, {T(reveal)});')
    events.append((reveal, "chime"))
    js.append(f'tl.to("#quiz", {{y: -240, scale: 0.62, duration: 0.45, ease: "power3.inOut"}}, {T(reveal + 1.4)});')
    js.append(f'tl.to("#quiz .qo:not(#qo{ans})", {{opacity: 0, duration: 0.3}}, {T(reveal + 1.4)});')
    # 讲解：每段标题 + 字幕
    for i, it in enumerate(items):
        ctx.text(it["tag"], it["title"])
        a = starts[i] + (1.6 if i == 0 else 0.1)
        if a < ends[i] - 0.3:
            body.append(f'<div id="et{i}" class="clip et" data-start="{T(a)}" data-duration="{T(ends[i] - a)}" data-track-index="4"><span class="etag">{G.E(it["tag"])}</span><div class="ett">{G.E(it["title"].replace("|", ""))}</div></div>')
            js.append(f'tl.fromTo("#et{i}", {{y: 40, opacity: 0}}, {{y: 0, opacity: 1, duration: 0.3, ease: "power3.out"}}, {T(a)});')
        if i:
            events.append((max(0.0, starts[i] - 0.1), "whoosh-short"))
    popped = set()
    for k, (p, s, e, li, kw) in enumerate(_pieces(G, spoken, times, S, skip={0, len(times) - 1})):
        h, hit = _em(G, p, kw)
        body.append(f'<div class="clip cap" id="cap{k}" data-start="{T(s)}" data-duration="{T(e - s)}" data-track-index="6"><span>{h}</span></div>')
        js.append(f'tl.fromTo("#cap{k} span", {{y: 20, opacity: 0}}, {{y: 0, opacity: 1, duration: 0.12, ease: "power2.out"}}, {T(s)});')
        if hit:
            js.append(f'tl.fromTo("#cap{k} em", {{scale: 1.4}}, {{scale: 1, duration: 0.3, ease: "back.out(3)"}}, {T(s)});')
            if li not in popped:
                events.append((s, "pop")); popped.add(li)
    body.append(f'<div id="outro" class="clip" data-start="{T(out_start)}" data-duration="{T(dur - out_start)}" data-track-index="7">{_ask_block(G, data, S, 620)}</div>')
    js.append(f'tl.fromTo("#outro .askq", {{y: 60, opacity: 0}}, {{y: 0, opacity: 1, duration: 0.35, ease: "power3.out"}}, {T(out_start + 0.05)});')
    js.append(f'tl.fromTo("#outro .opt", {{scale: 0.6, opacity: 0}}, {{scale: 1, opacity: 1, duration: 0.35, ease: "back.out(2)", stagger: 0.12}}, {T(out_start + 0.5)});')
    js.append(f'tl.fromTo("#outro .follow", {{scale: 0.6, opacity: 0}}, {{scale: 1, opacity: 1, duration: 0.4, ease: "back.out(2)"}}, {T(out_start + 0.9)});')
    if data.get("ask"):
        events.append((out_start + 0.3, "chime"))
    css = f"""
      #base {{ position: absolute; inset: 0; background: linear-gradient(160deg, {S["base"]} 0%, #0a0b18 70%); }}
      #shade {{ position: absolute; inset: 0; background: rgba(5,6,15,0.62); }}
      #quiz {{ position: absolute; left: 70px; right: 170px; top: 420px; transform-origin: center top; }}
      .badge {{ display: inline-block; font-size: 34px; font-weight: 800; padding: 8px 22px; border-radius: 999px; background: {S["mark"]}; color: #0b0b16; }}
      .qq {{ font-size: 80px; font-weight: 900; line-height: 1.3; margin-top: 40px; white-space: nowrap; }}
      .qos {{ margin-top: 60px; display: flex; flex-direction: column; gap: 28px; }}
      .qo {{ position: relative; display: flex; align-items: center; gap: 28px; font-size: 60px; font-weight: 800; padding: 26px 32px; border-radius: 26px; background: rgba(255,255,255,0.12); border: 3px solid rgba(255,255,255,0.25); }}
      .qo b {{ width: 84px; height: 84px; border-radius: 50%; display: grid; place-items: center; background: #ffd84a; color: #14142a; font-size: 50px; flex: none; }}
      .qo .ok {{ position: absolute; right: 32px; font-style: normal; font-size: 70px; font-weight: 900; opacity: 0; }}
      .cd {{ position: absolute; left: 0; right: 100px; top: 1390px; text-align: center; }}
      .cd span {{ display: inline-block; font-size: 150px; font-weight: 900; color: #ffd84a; line-height: 200px; width: 200px; }}
      #ring {{ position: absolute; left: 390px; top: 1390px; width: 200px; height: 200px; }}
      #ring svg {{ width: 100%; height: 100%; }}
      .rbg {{ fill: none; stroke: rgba(255,255,255,0.15); stroke-width: 12; }}
      .rfg {{ fill: none; stroke: #ffd84a; stroke-width: 12; stroke-linecap: round; stroke-dasharray: 553; }}
      .et {{ position: absolute; left: 70px; right: 170px; top: 760px; }}
      .etag {{ display: inline-block; font-size: 36px; font-weight: 800; padding: 6px 20px; border-radius: 10px; background: {S["mark"]}; color: #0b0b16; }}
      .ett {{ font-size: 88px; font-weight: 900; line-height: 1.25; margin-top: 24px; text-shadow: 0 6px 24px rgba(0,0,0,0.6); }}
      .cap {{ position: absolute; left: 40px; right: 150px; top: 1330px; text-align: center; }}
      .cap span {{ display: inline-block; font-size: 70px; font-weight: 900; line-height: 1.25; color: #fff;
                  -webkit-text-stroke: 3px rgba(0,0,0,0.9); paint-order: stroke fill; text-shadow: 0 6px 20px rgba(0,0,0,0.7); }}
      .cap em {{ font-style: normal; color: #ffd84a; display: inline-block; }}
      #outro {{ position: absolute; inset: 0; background: linear-gradient(160deg, {S["base"]} 0%, #0a0b18 70%); }}
"""
    _page(G, data, S, ctx, dur, times, css, "\n".join(body), js, extra_text=question + "".join(opts))
    return events, kinds


# ───────── 柔光卡片（按《柔光卡片设计包》1.1.0 改成竖屏视频）─────────
# 黑白主色；浅彩只区分类别（同一个标签在每一期颜色都一样）；字只用 ink / muted；图标色只画图形；不用蓝紫色。
SOFT = {"bg": "#F7F5F3", "surface": "#FFFFFF", "sunken": "#F3F0ED", "ink": "#1D1A18", "muted": "#5F5852", "track": "rgba(29,26,24,.12)",
        "tint": ["#FDEDE4", "#FCEBF1", "#F1F5DF", "#E3F4F1", "#FCF4DC"], "accent": ["#E0602F", "#D2497A", "#6E8C24", "#1E9184", "#B07A0A"],
        "hero": "linear-gradient(135deg,#FCE3D6 0%,#F9DDE8 100%)", "hero2": "linear-gradient(135deg,#DDF2EA 0%,#FBF0D2 100%)",
        "aurora": ["#FDE3D7", "#DCF2E6", "#FCF1D2", "#FBE1EC"],
        "shadow": "0 6px 24px rgba(60,40,30,.08), 0 2px 6px rgba(60,40,30,.05)"}
EASE_IN = "cubic-bezier(.2,0,0,1)"


def _cat(tag):
    """标签 → 分类色序号（0–4），按文字固定，同一个标签每期颜色一样。"""
    return sum(ord(c) for c in str(tag)) % 5


def _soft_chart(shot, cat):
    data = [d for d in (shot.get("data") or []) if isinstance(d.get("value"), (int, float))][:6]
    if len(data) < 2:
        return ""
    hi = shot.get("highlight", len(data) - 1)
    W, H, top, bot = 760, 450, 60, 370
    vmax = max(d["value"] for d in data) or 1
    k = len(data)
    bw = min(120, (W - 40) / k * 0.6)
    fmtv = lambda v: (f"{v:.1f}".rstrip("0").rstrip(".") if isinstance(v, float) else str(v))
    parts = [f'<line x1="0" y1="{bot}" x2="{W}" y2="{bot}" stroke="{SOFT["track"]}" stroke-width="3"/>']
    for j, d in enumerate(data):
        cx = 20 + (j + 0.5) * (W - 40) / k
        h = max(6, d["value"] / vmax * (bot - top))
        col = SOFT["accent"][cat]
        op = "1" if j == hi else ".55"  # 当前 / 重点用实色，其他 55%
        parts.append(f'<rect class="sbar" x="{cx - bw / 2:.1f}" y="{bot - h:.1f}" width="{bw:.1f}" height="{h:.1f}" rx="14" fill="{col}" fill-opacity="{op}" style="transform-origin:{cx:.1f}px {bot}px"/>')
        parts.append(f'<text x="{cx:.1f}" y="{bot - h - 18:.1f}" text-anchor="middle" class="sval">{fmtv(d["value"])}</text>')
        parts.append(f'<text x="{cx:.1f}" y="{bot + 50}" text-anchor="middle" class="slbl">{html_escape(d["label"])}</text>')
    unit = html_escape(str(shot.get("unit", "")))
    return f'<svg viewBox="0 0 {W} {H}" class="schart">{"".join(parts)}</svg>' + (f'<div class="sunit">单位：{unit}</div>' if unit else "")


def html_escape(x):
    import html
    return html.escape(str(x))


def _soft(G, S, ctx, data, times, dur, spoken):
    items = data["items"]
    n, starts, ends, hook_end, out_start = _layout(data, times)
    js, body, events, kinds = [], [], [], []
    E = G.E
    cats = [_cat(it["tag"]) for it in items]
    for it in items:
        ctx.text(it["tag"], it["title"])
    # 背景：暖灰底 + 顶部极光（缓慢漂移）
    au = SOFT["aurora"]
    body.append(f'<div id="bg" class="clip" data-start="0" data-duration="{T(dur)}" data-track-index="0"><div id="aurora"></div></div>')
    js.append(f'tl.fromTo("#aurora", {{x: -40}}, {{x: 40, duration: {T(dur)}, ease: "sine.inOut"}}, 0);')
    # 顶部：频道名胶囊（主色黑） + 日期 + 段落进度（ink 进度、track 轨道）
    m = re.search(r"(\d+)月(\d+)日", data["date"])
    md = f"{int(m.group(1))}月{int(m.group(2))}日" if m else ""
    body.append(f'<div id="top" class="clip" data-start="0" data-duration="{T(out_start)}" data-track-index="6"><span class="pchip">{E(S["name"])}</span><span class="tdate">{E(md)}</span></div>')
    prog = "".join(f'<div class="ptrack"><div class="pfill" id="pf{i}"></div></div>' for i in range(n))
    body.append(f'<div id="prog" class="clip" data-start="{T(starts[0])}" data-duration="{T(out_start - starts[0])}" data-track-index="6">{prog}</div>')
    for i in range(n):
        js.append(f'tl.fromTo("#pf{i}", {{scaleX: 0}}, {{scaleX: 1, duration: {T(ends[i] - starts[i])}, ease: "none"}}, {T(starts[i])});')
    # 开场：主卡（杏→粉）放钩子句 + 本期几件事（白卡列表，左边浅彩圆块）
    hook = re.sub(r"\{([^{}|]+)\|[^{}]*\}", r"\1", data.get("hook") or data["intro"])
    hl = G.hook_lines(hook, 9)
    longest = max(len(re.sub(r"\*\*", "", x)) for x in hl)
    fs = max(68, min(100, int(820 / max(1, longest))))
    hook_html = "<br />".join(re.sub(r"[*][*](.+?)[*][*]", r"<em>\1</em>", E(x)) for x in hl)
    rows = "".join(f'<div class="arow" id="ar{i}"><span class="tile" style="background:{SOFT["tint"][cats[i]]}">{i + 1}</span><span class="atit">{E(it["title"].replace("|", ""))}</span></div>' for i, it in enumerate(items))
    body.append(f'<div id="hook" class="clip" data-start="0" data-duration="{T(hook_end)}" data-track-index="5"><div class="hero"><div class="hcap">{E("今天说 %d 件事" % n if SC.numbering(S) != "none" else S.get("slogan", ""))}</div><div class="hbig" style="font-size:{fs}px">{hook_html}</div></div><div class="card alist">{rows}</div></div>')
    js.append(f'tl.fromTo("#hook .hero", {{y: 24, opacity: 0}}, {{y: 0, opacity: 1, duration: 0.28, ease: "{EASE_IN}"}}, 0.05);')
    js.append(f'tl.fromTo("#hook .arow", {{y: 24, opacity: 0}}, {{y: 0, opacity: 1, duration: 0.28, ease: "{EASE_IN}", stagger: 0.12}}, 0.6);')
    js.append(f'tl.fromTo("#hook .hbig em", {{backgroundSize: "0% 26%"}}, {{backgroundSize: "100% 26%", duration: 0.4, ease: "power2.out"}}, 0.45);')
    js.append(f'tl.to("#hook", {{opacity: 0, y: -24, duration: 0.18}}, {T(hook_end - 0.18)});')
    events.append((0.05, "whoosh-short"))
    # 每段：标题行（浅彩圆块 + 标签胶囊）+ 大标题 + 内容卡（实拍 / 图表 / 主卡）
    for i, it in enumerate(items):
        s0, e0 = starts[i], ends[i]
        c = cats[i]
        sh = it.get("shot") or {}
        media, kind = "", "card"
        qs = _queries(it)
        if sh.get("type") == "chart":
            media = _soft_chart(sh, c)
            kind = "chart" if media else "card"
        if not media and qs:
            part = (e0 - s0) / max(1, min(len(qs), 3))
            vids = []
            for k, q in enumerate(qs[:3]):
                a, b = s0 + k * part, (s0 + (k + 1) * part if k < min(len(qs), 3) - 1 else e0)
                src = ctx.footage(f"{i}_{k}", q, b - a)
                if src:
                    vids.append(f'<video id="v{i}_{k}" class="clip mv" src="{src}" data-start="{T(a)}" data-duration="{T(b - a)}" data-track-index="2" muted playsinline></video>')
            if vids:
                media, kind = "".join(vids), "footage"
        kinds.append(kind)
        if kind == "footage":  # 实拍放在圆角卡片里（卡片不计时，靠透明度出现和消失）
            body.append(f'<div class="mcard" id="mc{i}">{media}</div>')
            js.append(f'tl.fromTo("#mc{i}", {{y: 24, opacity: 0}}, {{y: 0, opacity: 1, duration: 0.28, ease: "{EASE_IN}"}}, {T(s0)});')
            js.append(f'tl.to("#mc{i}", {{opacity: 0, duration: 0.18}}, {T(e0 - 0.18)});')
            js.append(f'tl.fromTo("#mc{i} .mv", {{scale: 1}}, {{scale: 1.08, duration: {T(e0 - s0)}, ease: "none"}}, {T(s0)});')
            inner = ""
        elif kind == "chart":
            inner = f'<div class="card ccard">{media}</div>'
        else:
            kw = re.findall(r"\*\*(.+?)\*\*", re.sub(r"\{([^{}|]+)\|[^{}]*\}", r"\1", it.get("say", "")))
            word = (kw[0] if kw else it["tag"])
            inner = f'<div class="hero2 qcard"><span class="tile big" style="background:{SOFT["tint"][c]}"><i style="background:{SOFT["accent"][c]}"></i></span><div class="qt">{E(word)}</div></div>'
        head = f'<div class="shead"><span class="tile" style="background:{SOFT["tint"][c]}">{i + 1}</span><span class="tag">{E(it["tag"])}</span></div>'
        ttl = "<br />".join(E(x) for x in it["title"].split("|"))
        body.append(f'<div id="sc{i}" class="clip seg" data-start="{T(s0)}" data-duration="{T(e0 - s0)}" data-track-index="4">{head}<div class="stitle">{ttl}</div>{inner}</div>')
        js.append(f'tl.fromTo("#sc{i} .shead, #sc{i} .stitle", {{y: 24, opacity: 0}}, {{y: 0, opacity: 1, duration: 0.28, ease: "{EASE_IN}", stagger: 0.08}}, {T(s0 + 0.05)});')
        if kind == "chart":
            js.append(f'tl.fromTo("#sc{i} .ccard", {{y: 24, opacity: 0}}, {{y: 0, opacity: 1, duration: 0.28, ease: "{EASE_IN}"}}, {T(s0 + 0.2)});')
            js.append(f'tl.fromTo("#sc{i} .sbar", {{scaleY: 0}}, {{scaleY: 1, duration: 0.5, ease: "power3.out", stagger: 0.1}}, {T(s0 + 0.4)});')
        elif kind == "card":
            js.append(f'tl.fromTo("#sc{i} .qcard", {{y: 24, opacity: 0}}, {{y: 0, opacity: 1, duration: 0.28, ease: "{EASE_IN}"}}, {T(s0 + 0.2)});')
        js.append(f'tl.to("#sc{i} .shead, #sc{i} .stitle", {{opacity: 0, duration: 0.18}}, {T(e0 - 0.18)});')
        events.append((max(0.0, s0 - 0.1), "whoosh-short"))
    # 字幕：白色胶囊卡片，ink 字；关键词下面一条图标色的底线（图标色只画图形，不给字上色）
    popped = set()
    for k, (p, s0, e0, li, kw) in enumerate(_pieces(G, spoken, times, S, skip={0, len(times) - 1})):
        h, hit = _em(G, p, kw)
        ci = cats[min(max(li - 1, 0), n - 1)]
        body.append(f'<div class="clip cap" id="cap{k}" data-start="{T(s0)}" data-duration="{T(e0 - s0)}" data-track-index="7"><span style="--acc:{SOFT["accent"][ci]}">{h}</span></div>')
        js.append(f'tl.fromTo("#cap{k} span", {{y: 12, opacity: 0}}, {{y: 0, opacity: 1, duration: 0.12, ease: "power2.out"}}, {T(s0)});')
        if hit:
            js.append(f'tl.fromTo("#cap{k} em", {{backgroundSize: "0% 30%"}}, {{backgroundSize: "100% 30%", duration: 0.3, ease: "power2.out"}}, {T(s0 + 0.05)});')
            if li not in popped:
                events.append((s0, "pop")); popped.add(li)
    # 结尾：主卡（薄荷→奶黄）放互动问题；选项是胶囊，字母是黑色圆块；关注是唯一的实心主按钮（黑）
    ask = G.tts.display_text(data.get("ask") or "").strip()
    opts = G.ask_options(data)
    obtn = "".join(f'<div class="sopt"><b>{"AB"[k]}</b>{E(x)}</div>' for k, x in enumerate(opts))
    body.append(f'<div id="outro" class="clip" data-start="{T(out_start)}" data-duration="{T(dur - out_start)}" data-track-index="5"><div class="hero2 ocard"><div class="hcap">评论区{"打 A 或 B" if opts else "告诉我"}</div><div class="oq">{"<br />".join(E(x) for x in G.hook_lines(ask, 10))}</div>{f'<div class="sopts">{obtn}</div>' if opts else ""}</div><div class="sfollow">关注我 · {E(G.follow_text(S))}</div></div>')
    js.append(f'tl.fromTo("#outro .ocard", {{y: 24, opacity: 0}}, {{y: 0, opacity: 1, duration: 0.28, ease: "{EASE_IN}"}}, {T(out_start + 0.05)});')
    js.append(f'tl.fromTo("#outro .sopt", {{y: 24, opacity: 0}}, {{y: 0, opacity: 1, duration: 0.28, ease: "{EASE_IN}", stagger: 0.1}}, {T(out_start + 0.45)});')
    js.append(f'tl.fromTo("#outro .sfollow", {{scale: 0.96, opacity: 0}}, {{scale: 1, opacity: 1, duration: 0.28, ease: "{EASE_IN}"}}, {T(out_start + 0.8)});')
    if data.get("ask"):
        events.append((out_start + 0.3, "chime"))
    ink, mu = SOFT["ink"], SOFT["muted"]
    css = f"""
      #root {{ background: {SOFT["bg"]}; color: {ink}; }}
      #bg {{ position: absolute; inset: 0; background: {SOFT["bg"]}; overflow: hidden; }}
      #aurora {{ position: absolute; left: -80px; right: -80px; top: 0; height: 1000px;
        background: radial-gradient(45% 70% at 6% 0%, {au[0]} 0, transparent 70%), radial-gradient(40% 60% at 40% 0%, {au[1]} 0, transparent 70%),
                    radial-gradient(45% 70% at 72% 0%, {au[2]} 0, transparent 70%), radial-gradient(35% 60% at 100% 10%, {au[3]} 0, transparent 70%); }}
      #ailabel {{ color: {mu}; border: 0; background: {SOFT["sunken"]}; border-radius: 999px; padding: 6px 18px; }}
      #top {{ position: absolute; left: 60px; top: 190px; display: flex; align-items: center; gap: 22px; }}
      .pchip {{ font-size: 38px; font-weight: 600; padding: 10px 30px; border-radius: 999px; background: {ink}; color: #fff; -webkit-text-stroke: .02em currentColor; }}
      .tdate {{ font-size: 34px; color: {mu}; font-variant-numeric: tabular-nums; }}
      #prog {{ position: absolute; left: 60px; right: 170px; top: 300px; display: flex; gap: 12px; }}
      .ptrack {{ flex: 1; height: 10px; border-radius: 999px; background: {SOFT["track"]}; overflow: hidden; }}
      .pfill {{ width: 100%; height: 100%; background: {ink}; transform-origin: left center; transform: scaleX(0); }}
      .card {{ background: {SOFT["surface"]}; border-radius: 56px; box-shadow: {SOFT["shadow"]}; }}
      .hero {{ background: {SOFT["hero"]}; border-radius: 56px; padding: 56px 52px; }}
      .hero2 {{ background: {SOFT["hero2"]}; border-radius: 56px; }}
      .hcap {{ font-size: 34px; color: {mu}; }}
      #hook {{ position: absolute; left: 60px; right: 170px; top: 380px; }}
      .hbig {{ font-weight: 900; line-height: 1.3; margin-top: 18px; white-space: nowrap; -webkit-text-stroke: .03em currentColor; }}
      .hbig em, .cap em {{ font-style: normal; background-image: linear-gradient({SOFT["accent"][0]}, {SOFT["accent"][0]}); background-repeat: no-repeat; background-position: 0 92%; background-size: 100% 26%; }}
      .cap em {{ background-image: linear-gradient(var(--acc), var(--acc)); }}
      .alist {{ margin-top: 28px; padding: 18px 40px; }}
      .arow {{ display: flex; align-items: center; gap: 28px; padding: 22px 0; border-bottom: 2px solid #ECE7E3; }}
      .arow:last-child {{ border-bottom: 0; }}
      .tile {{ flex: none; width: 84px; height: 84px; border-radius: 999px; display: grid; place-items: center; font-size: 40px; font-weight: 600; color: {ink}; font-variant-numeric: tabular-nums; }}
      .tile.big {{ width: 132px; height: 132px; }}
      .tile i {{ width: 44px; height: 44px; border-radius: 14px; display: block; }}
      .atit {{ font-size: 46px; font-weight: 500; white-space: nowrap; -webkit-text-stroke: .015em currentColor; }}
      .seg {{ position: absolute; left: 60px; right: 170px; top: 380px; }}
      .shead {{ display: flex; align-items: center; gap: 22px; }}
      .tag {{ font-size: 38px; padding: 10px 28px; border-radius: 999px; background: {SOFT["sunken"]}; color: {ink}; }}
      .stitle {{ font-size: 88px; font-weight: 900; line-height: 1.25; margin-top: 30px; white-space: nowrap; -webkit-text-stroke: .03em currentColor; }}
      .mcard {{ position: absolute; left: 60px; right: 170px; top: 720px; height: 620px; border-radius: 56px; overflow: hidden; box-shadow: {SOFT["shadow"]}; opacity: 0; background: {SOFT["sunken"]}; }}
      .mcard .mv {{ position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; }}
      .ccard {{ position: absolute; left: 0; right: 0; top: 340px; padding: 36px 40px 30px; }}
      .schart {{ width: 100%; height: auto; display: block; }}
      .sval {{ font-size: 40px; font-weight: 600; fill: {ink}; font-variant-numeric: tabular-nums; }}
      .slbl {{ font-size: 32px; fill: {mu}; }}
      .sunit {{ font-size: 28px; color: {mu}; margin-top: 4px; }}
      .qcard {{ position: absolute; left: 0; right: 0; top: 340px; padding: 56px 52px; display: flex; align-items: center; gap: 36px; }}
      .qt {{ font-size: 84px; font-weight: 900; line-height: 1.25; -webkit-text-stroke: .03em currentColor; }}
      .cap {{ position: absolute; left: 60px; right: 170px; top: 1370px; text-align: center; }}
      .cap span {{ display: inline-block; font-size: 56px; font-weight: 600; line-height: 1.35; padding: 18px 40px; border-radius: 999px; background: {SOFT["surface"]}; color: {ink}; box-shadow: {SOFT["shadow"]}; -webkit-text-stroke: .02em currentColor; }}
      #outro {{ position: absolute; inset: 0; }}
      .ocard {{ position: absolute; left: 60px; right: 170px; top: 420px; padding: 60px 52px; }}
      .oq {{ font-size: 76px; font-weight: 900; line-height: 1.3; margin-top: 18px; white-space: nowrap; -webkit-text-stroke: .03em currentColor; }}
      .sopts {{ display: flex; gap: 24px; margin-top: 44px; }}
      .sopt {{ flex: 1; display: flex; align-items: center; gap: 20px; font-size: 52px; font-weight: 500; padding: 20px 26px; border-radius: 999px; background: rgba(255,255,255,.72); }}
      .sopt b {{ width: 76px; height: 76px; border-radius: 999px; display: grid; place-items: center; background: {ink}; color: #fff; font-size: 44px; flex: none; }}
      .sfollow {{ position: absolute; left: 60px; right: 170px; top: 1120px; text-align: center; font-size: 46px; font-weight: 600; padding: 26px; border-radius: 999px; background: {ink}; color: #fff; -webkit-text-stroke: .02em currentColor; }}
"""
    _page(G, data, S, ctx, dur, times, css, "\n".join(body), js, extra_text="今天说件事评论区打A或B告诉我单位：" + md + S.get("slogan", "") + "0123456789")
    return events, kinds
