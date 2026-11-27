"""自影 · 分镜镜头：把稿子里每段的 shot 渲染成竖屏画面（HTML + GSAP）。

稿子里每条 item 可以带一个 shot（不写就是 text）：
  text      文字镜头：大序号 + 标签 + 大标题（默认，也是所有镜头失败时的兜底）
  footage   实拍素材：{"type":"footage","query":"英文关键词"}，背景是 Pexels/Pixabay 竖屏视频，上面叠标题
  chart     数据图表：{"type":"chart","kind":"bar|line","unit":"亿元","data":[{"label":"2024","value":12.3}],"highlight":2}
  map       地图标注：{"type":"map","places":[{"name":"北京","lon":116.4,"lat":39.9}],"highlight":["China"]}
  timeline  时间线：  {"type":"timeline","events":[{"year":"1954","text":"彗星客机失事"}]}（2–5 条）
  quote     金句大字：{"type":"quote","text":"……","highlight":"其中要强调的几个字"}（text 里可以用 | 指定换行，否则按词自动断行）
  asset     你的素材：{"type":"asset","file":"inputs/haowu/cup.jpg"}（图片或视频，路径相对仓库根目录）
任何镜头都可以加 "bg":"英文关键词"，用实拍素材当背景（asset 除外）。

画面安全区：横向 80–900（右侧留给抖音的头像、点赞栏），纵向 520–1400（下方 1470 是字幕）。
"""
import html
import json
import os
import shutil
import subprocess

E = html.escape
HERE = os.path.dirname(os.path.abspath(__file__))
T = lambda x: f"{x:.3f}"
X0, X1 = 80, 900  # 内容区左右边界
TYPES = ("text", "footage", "chart", "map", "timeline", "quote", "asset")

CSS = """
      .bgw { position: absolute; left: 0; top: 0; width: 1080px; height: 1920px; overflow: hidden; }
      .bgw .bgv, .bgw .assetimg { position: absolute; left: 0; top: 0; width: 1080px; height: 1920px; object-fit: cover; }
      .veil { position: absolute; inset: 0; background: linear-gradient(180deg, rgba(6,8,24,0.72) 0%, rgba(6,8,24,0.48) 30%, rgba(6,8,24,0.55) 58%, rgba(6,8,24,0.88) 100%); }
      .scene.over .title .tline { text-shadow: 0 6px 24px rgba(0,0,0,0.55); }
      .meta.top { top: 540px; }
      .title.small { top: 640px; }
      .title.small .tline { font-size: 64px; line-height: 1.25; }
      .viz { position: absolute; left: 80px; top: 830px; width: 820px; height: 480px; }
      .viz.map { -webkit-mask-image: radial-gradient(ellipse 54% 52% at 50% 50%, #000 58%, transparent 100%); mask-image: radial-gradient(ellipse 54% 52% at 50% 50%, #000 58%, transparent 100%); }
      .viz svg { width: 100%; height: 100%; overflow: visible; }
      .viz .lbl { font-size: 30px; fill: rgba(255,255,255,0.86); }
      .viz .val { font-size: 34px; font-weight: 700; fill: #fff; }
      .viz .unit { font-size: 26px; fill: rgba(255,255,255,0.7); }
      .tlrow { position: absolute; left: 150px; right: 180px; display: flex; align-items: center; gap: 26px; }
      .tlrow .yr { flex: none; font-size: 40px; font-weight: 900; color: #0a0a18; background: var(--c); padding: 8px 20px; border-radius: 14px; }
      .tlrow .tx { font-size: 42px; font-weight: 700; line-height: 1.3; }
      .tlline { position: absolute; left: 112px; width: 6px; border-radius: 3px; background: rgba(255,255,255,0.35); transform-origin: top center; }
      .tldot { position: absolute; left: 103px; width: 24px; height: 24px; border-radius: 50%; background: var(--c); box-shadow: 0 0 0 6px rgba(255,255,255,0.15); }
      .quote { position: absolute; left: 80px; right: 180px; top: 640px; }
      .quote .qm { font-size: 200px; line-height: 0.8; font-weight: 900; color: var(--c); opacity: 0.85; }
      .quote .qt { font-size: 84px; font-weight: 900; line-height: 1.32; margin-top: 10px; }
      .quote .qt em { font-style: normal; color: var(--c); }
      .quote .ch { display: inline-block; }
      .quote .ql { white-space: nowrap; }
      .hide { display: none !important; }
      .credit { position: absolute; right: 190px; top: 1395px; font-size: 22px; color: rgba(255,255,255,0.7); background: rgba(0,0,0,0.35); padding: 4px 10px; border-radius: 8px; }
"""


CLOSE = "，。、；：！？,.;:!?…）)」』”’》〉%％"  # 不能出现在行首
OPEN = "（(「『“‘《〈"                           # 不能出现在行尾


def _tokens(text):
    """把一句话切成不能再拆的小块：词语（rjieba 分词，没装就逐字）、整串数字和英文；
    标点并到前一个词，开引号、开括号并到后一个词，换行后行首不会是标点。"""
    import re as _re
    try:
        import rjieba
        cut = lambda x: list(rjieba.cut(x))
    except Exception:  # noqa: BLE001
        cut = lambda x: _re.findall(r"[0-9A-Za-z.%％]+|.", x)
    raw, pos = [], 0  # 数字连同单位整体保留（2026年、240亿、6.3%），其余分词
    for m in _re.finditer(r"[\d][\d.,]*[%％]?[万亿千百]*[年月日号个点时分秒天倍元种岁米度]?", text):
        raw += cut(text[pos:m.start()]) if m.start() > pos else []
        raw.append(m.group())
        pos = m.end()
    raw += cut(text[pos:]) if pos < len(text) else []
    out, pending = [], ""
    for w in raw:
        if not w:
            continue
        if all(c in CLOSE for c in w) and out:
            out[-1] += w
        elif all(c in OPEN for c in w):
            pending += w
        else:
            out.append(pending + w)
            pending = ""
    if pending:
        if out:
            out[-1] += pending
        else:
            out.append(pending)
    return out


def wrap_lines(text, width, max_lines=None):
    """按词断行：每行不超过 width 个字（一个词比 width 还长时才拆开），行数尽量少、各行长度尽量平均。"""
    toks = []
    for w in _tokens(text):
        while len(w) > width:
            toks.append(w[:width])
            w = w[width:]
        if w:
            toks.append(w)
    if not toks:
        return [text]
    L = sum(len(w) for w in toks)
    import math
    k_min = max(1, math.ceil(L / width))
    for k in range(k_min, len(toks) + 1):
        target = L / k
        # dp[j][m]：前 j 个词排成 m 行的最小代价
        INF = float("inf")
        dp = [[(INF, None)] * (k + 1) for _ in range(len(toks) + 1)]
        dp[0][0] = (0, None)
        pre = [0]
        for w in toks:
            pre.append(pre[-1] + len(w))
        for j in range(1, len(toks) + 1):
            for m in range(1, k + 1):
                best = (INF, None)
                for a in range(j - 1, -1, -1):
                    ln = pre[j] - pre[a]
                    if ln > width:
                        break
                    c = dp[a][m - 1][0] + (ln - target) ** 2
                    if c < best[0]:
                        best = (c, a)
                dp[j][m] = best
        if dp[len(toks)][k][0] < INF:
            lines, j, m = [], len(toks), k
            while m:
                a = dp[j][m][1]
                lines.append("".join(toks[a:j]))
                j, m = a, m - 1
            lines = lines[::-1]
            return lines[:max_lines] if max_lines else lines
    return ["".join(toks)]


def _text_parts(i, n, it, split_title, small=False):
    lines = split_title(it["title"])
    tl_html = "".join(f'<div class="tline" id="s{i}-l{k}">' + "".join(f'<span class="ch">{E(c)}</span>' for c in ln) + "</div>" for k, ln in enumerate(lines))
    meta = f'<div class="meta{" top" if small else ""}" id="s{i}-meta"><span class="tag">{E(it["tag"])}</span><span class="idx">{i + 1:02d} / {n:02d}</span></div>'
    title = f'<div class="title{" small" if small else ""}" id="s{i}-title">{tl_html}</div>'
    return meta, title


def _text_js(i, s, e, with_ghost=True, with_bar=True):
    js = []
    if with_ghost:
        js.append(f'tl.fromTo("#s{i}-ghost", {{x: 160, opacity: 0}}, {{x: 0, opacity: 1, duration: 0.6, ease: "expo.out"}}, {T(s)});')
    js.append(f'tl.fromTo("#s{i}-meta", {{y: 40, opacity: 0}}, {{y: 0, opacity: 1, duration: 0.35, ease: "power3.out"}}, {T(s + 0.05)});')
    js.append(f'tl.fromTo("#scene{i} .title .ch", {{y: 70, opacity: 0, scale: 0.8}}, {{y: 0, opacity: 1, scale: 1, duration: 0.32, ease: "back.out(2)", stagger: 0.035}}, {T(s + 0.12)});')
    if with_bar:
        js.append(f'tl.fromTo("#s{i}-bar", {{scaleX: 0}}, {{scaleX: 1, duration: 0.5, ease: "power2.inOut"}}, {T(s + 0.3)});')
    return js


def _exit_js(i, e, sel):
    return f'tl.to("{sel}", {{y: -60, opacity: 0, duration: 0.2, ease: "power2.in"}}, {T(e - 0.2)});'


class Ctx:
    """一期视频的渲染上下文：素材目录、缓存、字体用字、素材署名。"""

    def __init__(self, proj, repo_root, cache_dir):
        self.proj, self.root, self.cache = proj, repo_root, cache_dir
        self.chars = set()
        self.credits = []
        self.warnings = []
        self.used = []  # 用到的实拍素材：[{file, query, where}]，make.py 按它抽检查帧
        os.makedirs(f"{proj}/assets/media", exist_ok=True)

    def text(self, *xs):
        for x in xs:
            self.chars.update(str(x))

    def footage(self, i, query, seconds):
        try:
            import footage
        except Exception as ex:  # noqa: BLE001
            self.warnings.append(f"素材模块不可用：{ex}")
            return None
        where = "开场" if str(i).split("_")[0] == "h" else f"第 {int(str(i).split('_')[0]) + 1} 段"
        if not footage.available():
            self.warnings.append("没有 PEXELS_API_KEY / PIXABAY_API_KEY，实拍镜头改为文字镜头")
            return None
        r = footage.fetch(query, seconds + 0.6, f"{self.proj}/assets/media/f{i}.mp4", self.cache)
        if not r:
            self.warnings.append(f"{where}没找到「{query}」的素材，改为文字镜头")
            return None
        self.credits.append(f"{r['source']}" + (f" · {r['author']}" if r.get("author") else ""))
        self.used.append({"file": f"assets/media/f{i}.mp4", "query": query, "where": where, "url": r.get("url", "")})
        return f"assets/media/f{i}.mp4"


def _bg_layer(i, s, e, media):
    """背景层放在场景之外（规则：计时的 <video> 不能嵌在另一个计时元素里）。
    外层 div 不计时，只负责缓慢推近；遮罩单独计时。"""
    return (f'<div class="bgw" id="s{i}-bgw">{media}</div>'
            f'<div id="s{i}-veil" class="clip veil" data-start="{T(s)}" data-duration="{T(e - s)}" data-track-index="1"></div>')


def _video_tag(i, src, s, e):
    return f'<video id="s{i}-bgv" class="clip bgv" src="{src}" data-start="{T(s)}" data-duration="{T(e - s)}" data-track-index="1" muted playsinline></video>'


def _bg_video(i, src, s, e):
    return _bg_layer(i, s, e, _video_tag(i, src, s, e))


def numbering(S):
    """频道的分段序号：spoken 念出来并显示（默认）、visual 只在画面显示、none 都不要。"""
    v = (S or {}).get("numbering", "spoken")
    return v if v in ("spoken", "visual", "none") else "spoken"


def hook_bg(ctx, query, s, e):
    """开场钩子句下面垫一段实拍视频（有素材密钥时）；返回 (背景层 html, js)。没有素材就返回空，开场照常只显示文字。"""
    if not query:
        return "", []
    src = ctx.footage("h", query, e - s)
    if not src:
        return "", []
    return _bg_video("h", src, s, e), [f'tl.fromTo("#sh-bgw", {{scale: 1.0}}, {{scale: 1.1, duration: {T(e - s)}, ease: "none"}}, {T(s)});']


def render(i, n, it, s, e, S, ctx, split_title):
    """返回 (场景 html, 背景层 html, js 列表, 实际镜头类型)。"""
    shot = it.get("shot") or {"type": "text"}
    kind = shot.get("type", "text") if shot.get("type") in TYPES else "text"
    ctx.text(it["tag"], it["title"])
    bg = ""
    if kind == "footage" or (shot.get("bg") and kind != "asset"):
        qs = [q for q in (shot.get("queries") or []) if q][:4]
        if len(qs) >= 2 and e - s >= 4:  # 多组关键词：这一段里每隔几秒换一段实拍，画面不停在一个镜头上
            part = (e - s) / len(qs)
            tags = []
            for k, q in enumerate(qs):
                src_k = ctx.footage(f"{i}_{k}", q, part)
                if src_k:
                    a, b = s + k * part, (s + (k + 1) * part if k < len(qs) - 1 else e)
                    tags.append(f'<video id="s{i}-bgv{k}" class="clip bgv" src="{src_k}" data-start="{T(a)}" data-duration="{T(b - a)}" data-track-index="1" muted playsinline></video>')
            if tags:
                bg = _bg_layer(i, s, e, "".join(tags))
        if not bg:
            src = ctx.footage(i, shot.get("query") or shot.get("bg") or (qs[0] if qs else None), e - s)
            if src:
                bg = _bg_video(i, src, s, e)
        if not bg and kind == "footage":
            kind = "text"
    ctx.bg = None  # asset 镜头可能自己产出背景层
    try:
        fn = {"text": _text, "footage": _footage, "chart": _chart, "map": _map, "timeline": _timeline, "quote": _quote, "asset": _asset}[kind]
        inner, js = fn(i, n, it, shot, s, e, S, ctx, split_title)
    except Exception as ex:  # 任何镜头出错都退回文字镜头，不影响整期视频
        ctx.warnings.append(f"第 {i + 1} 段的 {kind} 镜头生成失败（{ex}），改为文字镜头")
        kind, (inner, js) = "text", _text(i, n, it, shot, s, e, S, ctx, split_title)
    if ctx.bg:
        bg = ctx.bg
    if numbering(S) == "none":  # 不要序号的频道（讲故事类）：隐藏大号序号和「01 / 04」，保留元素给动画用
        inner = inner.replace('class="ghost"', 'class="ghost hide"').replace('class="idx"', 'class="idx hide"')
    over = " over" if bg else ""
    if bg:
        js.append(f'tl.fromTo("#s{i}-bgw", {{scale: 1.0}}, {{scale: 1.08, duration: {T(e - s)}, ease: "none"}}, {T(s)});')
    html_ = f'''
      <div id="scene{i}" class="clip scene c{i}{over}" data-start="{T(s)}" data-duration="{T(e - s)}" data-track-index="2">{inner}
      </div>'''
    js.append(f'tl.fromTo("#pg{i}", {{scaleX: 0}}, {{scaleX: 1, duration: {T(e - s)}, ease: "none"}}, {T(s)});')
    return html_, bg, js, kind


# ───────── 各类镜头 ─────────
def _text(i, n, it, shot, s, e, S, ctx, split_title):
    meta, title = _text_parts(i, n, it, split_title)
    html_ = f'<div class="ghost" id="s{i}-ghost">{i + 1:02d}</div>{meta}{title}<div class="bar" id="s{i}-bar"></div>'
    js = _text_js(i, s, e)
    js.append(f'tl.fromTo("#s{i}-title", {{scale: 1}}, {{scale: 1.04, duration: {T(e - s - 0.6)}, ease: "none"}}, {T(s + 0.5)});')
    js.append(_exit_js(i, e, f"#s{i}-title, #s{i}-meta, #s{i}-ghost, #s{i}-bar"))
    return html_, js


def _footage(i, n, it, shot, s, e, S, ctx, split_title):
    meta, title = _text_parts(i, n, it, split_title)
    html_ = f'{meta}{title}<div class="bar" id="s{i}-bar"></div>'
    js = _text_js(i, s, e, with_ghost=False)
    js.append(_exit_js(i, e, f"#s{i}-title, #s{i}-meta, #s{i}-bar"))
    return html_, js


def _chart(i, n, it, shot, s, e, S, ctx, split_title):
    data = [d for d in shot.get("data", []) if isinstance(d.get("value"), (int, float))][:7]
    if len(data) < 2:
        raise ValueError("图表至少要 2 个数据点")
    unit = str(shot.get("unit", ""))
    hi = shot.get("highlight", len(data) - 1)
    ctx.text(unit, *(d["label"] for d in data), "0123456789.-%")
    meta, title = _text_parts(i, n, it, split_title, small=True)
    W, H, top, bot = 820, 480, 60, 410
    vmax = max(d["value"] for d in data) or 1
    vmin = min(0, min(d["value"] for d in data))
    span = (vmax - vmin) or 1
    y = lambda v: bot - (v - vmin) / span * (bot - top)
    fmt = lambda v: (f"{v:.1f}".rstrip("0").rstrip(".") if isinstance(v, float) else str(v))
    k = len(data)
    parts = [f'<line x1="0" y1="{y(0):.1f}" x2="{W}" y2="{y(0):.1f}" stroke="rgba(255,255,255,0.35)" stroke-width="3"/>']
    js = _text_js(i, s, e, with_ghost=False, with_bar=False)
    t0 = s + 0.6
    if shot.get("kind", "bar") == "line":
        xs = [40 + j * (W - 80) / (k - 1) for j in range(k)]
        pts = " ".join(f"{xs[j]:.1f},{y(d['value']):.1f}" for j, d in enumerate(data))
        parts.append(f'<polyline id="s{i}-line" points="{pts}" fill="none" stroke="{S["mark"]}" stroke-width="8" stroke-linecap="round" stroke-linejoin="round" pathLength="1" stroke-dasharray="1" stroke-dashoffset="1"/>')
        for j, d in enumerate(data):
            r = 16 if j == hi else 10
            parts.append(f'<circle class="s{i}-dot" cx="{xs[j]:.1f}" cy="{y(d["value"]):.1f}" r="{r}" fill="{S["mark"] if j == hi else "#fff"}"/>')
            parts.append(f'<text class="val s{i}-v" x="{xs[j]:.1f}" y="{y(d["value"]) - 26:.1f}" text-anchor="middle">{E(fmt(d["value"]))}</text>')
            parts.append(f'<text class="lbl" x="{xs[j]:.1f}" y="{bot + 50}" text-anchor="middle">{E(str(d["label"]))}</text>')
        js.append(f'tl.to("#s{i}-line", {{strokeDashoffset: 0, duration: {T(min(1.6, (e - s) * 0.4))}, ease: "power2.inOut"}}, {T(t0)});')
        js.append(f'tl.fromTo(".s{i}-dot", {{scale: 0, transformOrigin: "50% 50%"}}, {{scale: 1, duration: 0.25, ease: "back.out(3)", stagger: 0.12}}, {T(t0 + 0.2)});')
    else:
        bw = min(110, (W - 40) / k * 0.62)
        gap = (W - bw * k) / (k + 1)
        for j, d in enumerate(data):
            x = gap + j * (bw + gap)
            yy = y(d["value"])
            col = S["mark"] if j == hi else "rgba(255,255,255,0.55)"
            parts.append(f'<rect class="s{i}-b" x="{x:.1f}" y="{min(yy, y(0)):.1f}" width="{bw:.1f}" height="{abs(y(0) - yy):.1f}" rx="10" fill="{col}"/>')
            parts.append(f'<text class="val s{i}-v" x="{x + bw / 2:.1f}" y="{min(yy, y(0)) - 18:.1f}" text-anchor="middle">{E(fmt(d["value"]))}</text>')
            parts.append(f'<text class="lbl" x="{x + bw / 2:.1f}" y="{bot + 50}" text-anchor="middle">{E(str(d["label"]))}</text>')
        js.append(f'tl.fromTo(".s{i}-b", {{scaleY: 0, transformOrigin: "50% 100%"}}, {{scaleY: 1, duration: 0.6, ease: "power3.out", stagger: 0.12}}, {T(t0)});')
    if unit:
        parts.append(f'<text class="unit" x="0" y="30">单位：{E(unit)}</text>')
    js.append(f'tl.fromTo(".s{i}-v", {{opacity: 0, y: 12}}, {{opacity: 1, y: 0, duration: 0.3, stagger: 0.12}}, {T(t0 + 0.4)});')
    js.append(_exit_js(i, e, f"#s{i}-title, #s{i}-meta, #s{i}-viz"))
    html_ = f'{meta}{title}<div class="viz" id="s{i}-viz"><svg viewBox="0 0 {W} {H}">{"".join(parts)}</svg></div>'
    return html_, js


def _map(i, n, it, shot, s, e, S, ctx, split_title):
    places = [p for p in shot.get("places", []) if "lon" in p and "lat" in p][:5]
    if not places and not shot.get("highlight"):
        raise ValueError("地图至少要 1 个地点（带经纬度）或 1 个高亮国家")
    W, H = 820, 480
    req = {"width": W, "height": H, "places": places, "highlight": shot.get("highlight", []), "zoom": shot.get("zoom", 1), "pad": 70}
    out = subprocess.run(["node", os.path.join(HERE, "mapsvg.mjs")], input=json.dumps(req), capture_output=True, text=True, cwd=HERE, timeout=60)
    if out.returncode:
        raise RuntimeError(out.stderr[-300:])
    m = json.loads(out.stdout)
    ctx.text(*(p["name"] for p in places))
    meta, title = _text_parts(i, n, it, split_title, small=True)
    parts = [f'<path d="{m["land"]}" fill="rgba(255,255,255,0.10)" stroke="rgba(255,255,255,0.28)" stroke-width="1.2"/>']
    for h in m["hi"]:
        parts.append(f'<path class="s{i}-hi" d="{h["d"]}" fill="{S["mark"]}" fill-opacity="0.55" stroke="{S["mark"]}" stroke-width="2"/>')
    placed = []  # 标签防重叠：和已放的标签太近就换到上方或下方
    for j, p in enumerate(m["pins"]):
        lx = p["x"] + 26 if p["x"] < W - 200 else p["x"] - 26
        anchor = "start" if p["x"] < W - 200 else "end"
        ly = p["y"] + 12
        for dy in (0, -44, 44, -88, 88):
            if all(abs((p["y"] + 12 + dy) - qy) > 40 or abs(lx - qx) > 170 for qx, qy in placed):
                ly = p["y"] + 12 + dy
                break
        placed.append((lx, ly))
        parts.append(f'<circle class="s{i}-ring" cx="{p["x"]}" cy="{p["y"]}" r="22" fill="none" stroke="#fff" stroke-width="3"/>')
        parts.append(f'<circle class="s{i}-pin" cx="{p["x"]}" cy="{p["y"]}" r="11" fill="#fff"/>')
        parts.append(f'<text class="val s{i}-pl" x="{lx:.1f}" y="{ly:.1f}" text-anchor="{anchor}" style="paint-order: stroke; stroke: rgba(0,0,0,0.55); stroke-width: 6px">{E(p["name"])}</text>')
    js = _text_js(i, s, e, with_ghost=False, with_bar=False)
    t0 = s + 0.5
    js.append(f'tl.fromTo("#s{i}-viz svg", {{opacity: 0, scale: 0.94, transformOrigin: "50% 50%"}}, {{opacity: 1, scale: 1, duration: 0.6, ease: "power2.out"}}, {T(t0)});')
    js.append(f'tl.fromTo("#s{i}-viz svg", {{scale: 1}}, {{scale: 1.06, duration: {T(max(0.5, e - t0 - 0.8))}, ease: "none"}}, {T(t0 + 0.6)});')
    if m["hi"]:
        js.append(f'tl.fromTo(".s{i}-hi", {{opacity: 0}}, {{opacity: 1, duration: 0.5, stagger: 0.15}}, {T(t0 + 0.3)});')
    if m["pins"]:
        js.append(f'tl.fromTo(".s{i}-pin", {{scale: 0, transformOrigin: "50% 50%"}}, {{scale: 1, duration: 0.3, ease: "back.out(3)", stagger: 0.3}}, {T(t0 + 0.6)});')
        js.append(f'tl.fromTo(".s{i}-ring", {{scale: 0.4, opacity: 1, transformOrigin: "50% 50%"}}, {{scale: 1.8, opacity: 0, duration: 1.0, ease: "power2.out", stagger: 0.3}}, {T(t0 + 0.7)});')
        js.append(f'tl.fromTo(".s{i}-pl", {{opacity: 0, x: -10}}, {{opacity: 1, x: 0, duration: 0.3, stagger: 0.3}}, {T(t0 + 0.8)});')
    js.append(_exit_js(i, e, f"#s{i}-title, #s{i}-meta, #s{i}-viz"))
    html_ = f'{meta}{title}<div class="viz map" id="s{i}-viz"><svg viewBox="0 0 {W} {H}">{"".join(parts)}</svg></div>'
    return html_, js


def _timeline(i, n, it, shot, s, e, S, ctx, split_title):
    ev = [x for x in shot.get("events", []) if x.get("year") and x.get("text")][:5]
    if len(ev) < 2:
        raise ValueError("时间线至少要 2 个事件")
    for x in ev:
        ctx.text(x["year"], x["text"])
    meta, title = _text_parts(i, n, it, split_title, small=True)
    top, step = 840, min(120, 440 / len(ev))
    rows = [f'<div class="tlline" id="s{i}-tll" style="top:{top + 20}px;height:{step * (len(ev) - 1) + 10:.0f}px"></div>']
    for j, x in enumerate(ev):
        yy = top + j * step
        rows.append(f'<div class="tldot s{i}-td" style="top:{yy + 10:.0f}px"></div>')
        rows.append(f'<div class="tlrow s{i}-tr" style="top:{yy - 14:.0f}px"><span class="yr">{E(x["year"])}</span><span class="tx">{E(x["text"])}</span></div>')
    js = _text_js(i, s, e, with_ghost=False, with_bar=False)
    t0, span = s + 0.6, max(0.6, (e - s - 1.4))
    js.append(f'tl.fromTo("#s{i}-tll", {{scaleY: 0}}, {{scaleY: 1, duration: {T(span)}, ease: "none"}}, {T(t0)});')
    st = span / max(1, len(ev) - 1) if len(ev) > 1 else 0.3
    js.append(f'tl.fromTo(".s{i}-td", {{scale: 0, transformOrigin: "50% 50%"}}, {{scale: 1, duration: 0.25, ease: "back.out(3)", stagger: {T(st)}}}, {T(t0)});')
    js.append(f'tl.fromTo(".s{i}-tr", {{opacity: 0, x: 40}}, {{opacity: 1, x: 0, duration: 0.35, ease: "power3.out", stagger: {T(st)}}}, {T(t0 + 0.05)});')
    js.append(_exit_js(i, e, f"#s{i}-title, #s{i}-meta, #s{i}-tll, .s{i}-td, .s{i}-tr"))
    return "".join([meta, title] + rows), js


QUOTE_MAX = 40   # 金句最多 40 个字
QUOTE_W = 9      # 84px 大字在 820px 宽的内容区里一行放 9 个字


def quote_lines(raw):
    """金句断行：text 里写了 | 就按 | 断；否则按词自动断，每行不超过 9 个字，不在词中间断。
    返回 (各行文字, 字号)。超过 40 个字的部分不显示。"""
    raw = str(raw)
    if "|" in raw:
        lines = [x.strip() for x in raw.split("|") if x.strip()]
    else:
        lines = wrap_lines(raw.strip(), QUOTE_W)
        if len(lines) > 4:  # 太长就小一号字、一行多放几个，最多 4–5 行
            lines = wrap_lines(raw.strip(), 11)
    out, left = [], QUOTE_MAX
    for ln in lines:
        if left <= 0:
            break
        out.append(ln[:left])
        left -= len(ln)
    longest = max((len(x) for x in out), default=1)
    return out, max(56, min(84, int(800 / max(1, longest))))


def _quote(i, n, it, shot, s, e, S, ctx, split_title):
    lines, fs = quote_lines(shot.get("text") or it["title"].replace("|", ""))
    text = "".join(lines)
    hl = str(shot.get("highlight") or "")
    ctx.text(text, "“”")
    a = text.find(hl) if hl else -1
    body, k = "", 0
    for ln in lines:
        row = ""
        for ch in ln:
            inner = f'<span class="ch">{E(ch)}</span>'
            row += f"<em>{inner}</em>" if a >= 0 and a <= k < a + len(hl) else inner
            k += 1
        body += f'<div class="ql">{row}</div>'
    meta = f'<div class="meta top" id="s{i}-meta"><span class="tag">{E(it["tag"])}</span><span class="idx">{i + 1:02d} / {n:02d}</span></div>'
    html_ = f'{meta}<div class="quote" id="s{i}-q"><div class="qm">“</div><div class="qt" style="font-size:{fs}px">{body}</div></div>'
    js = [f'tl.fromTo("#s{i}-meta", {{y: 40, opacity: 0}}, {{y: 0, opacity: 1, duration: 0.35, ease: "power3.out"}}, {T(s + 0.05)});',
          f'tl.fromTo("#s{i}-q .qm", {{scale: 0.4, opacity: 0, transformOrigin: "0% 100%"}}, {{scale: 1, opacity: 0.85, duration: 0.4, ease: "back.out(2)"}}, {T(s + 0.1)});',
          f'tl.fromTo("#s{i}-q .ch", {{opacity: 0, y: 30}}, {{opacity: 1, y: 0, duration: 0.25, ease: "power2.out", stagger: {T(min(0.06, max(0.02, (e - s - 1.2) / max(1, len(text)) / 2)))}}}, {T(s + 0.3)});',
          f'tl.fromTo("#s{i}-q", {{scale: 1}}, {{scale: 1.04, duration: {T(e - s - 0.6)}, ease: "none", transformOrigin: "0% 50%"}}, {T(s + 0.5)});',
          _exit_js(i, e, f"#s{i}-q, #s{i}-meta")]
    return html_, js


def _asset(i, n, it, shot, s, e, S, ctx, split_title):
    f = shot.get("file", "")
    src = os.path.normpath(os.path.join(ctx.root, f))
    if not f or not src.startswith(os.path.normpath(ctx.root)) or not os.path.exists(src):
        raise FileNotFoundError(f"找不到素材文件 {f}")
    ext = os.path.splitext(src)[1].lower()
    meta, title = _text_parts(i, n, it, split_title)
    if ext in (".mp4", ".mov", ".m4v", ".webm"):
        dst = f"{ctx.proj}/assets/media/a{i}.mp4"
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", src, "-t", f"{e - s + 0.6:.2f}", "-an", "-vf",
                        "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps=30", "-c:v", "libx264", "-preset", "veryfast",
                        "-crf", "22", "-pix_fmt", "yuv420p", "-g", "15", dst], check=True)
        media = _video_tag(i, f"assets/media/a{i}.mp4", s, e)
    elif ext in (".jpg", ".jpeg", ".png", ".webp"):
        dst = f"{ctx.proj}/assets/media/a{i}{ext}"
        shutil.copy(src, dst)
        media = f'<img id="s{i}-bgi" class="clip assetimg" src="assets/media/a{i}{ext}" alt="" data-start="{T(s)}" data-duration="{T(e - s)}" data-track-index="1" />'
    else:
        raise ValueError(f"不支持的素材格式 {ext}")
    ctx.bg = _bg_layer(i, s, e, media)
    html_ = f'{meta}{title}<div class="bar" id="s{i}-bar"></div>'
    js = _text_js(i, s, e, with_ghost=False)
    js.append(_exit_js(i, e, f"#s{i}-title, #s{i}-meta, #s{i}-bar"))
    return html_, js
