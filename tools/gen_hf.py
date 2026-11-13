"""AutoClip · 生成视频工程（配音 + HyperFrames 竖屏工程 + 封面 + 发布文案）
用法: python3 gen_hf.py <script.json> <工程目录>
稿子里的 channel 字段决定用哪个频道（channels/<id>/channel.json）；配音方案见 autoclip.config.json 的 voice。
"""
import sys, os, json, re, html, shutil
import soundfile as sf
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import tts

COLORS = {"国际": "#ff5c5c", "国内": "#ff8a4c", "时政": "#ff8a4c", "外交": "#9a7cff", "财经": "#ffb840",
          "科技": "#40c8ff", "体育": "#4fdc8c", "娱乐": "#ff6eb4", "社会": "#f2d14b", "健康": "#5ee0c8",
          "教育": "#7fa8ff", "环境": "#8ad94f", "军事": "#c0a080", "汽车": "#ff7f9e", "文化": "#d59cff"}
PALETTE = ["#ff5c5c", "#40c8ff", "#4fdc8c", "#ffb840", "#9a7cff", "#ff6eb4"]


# 每个栏目的名字、配色、开场和结尾。画面布局相同，配色和文案不同，一眼能分清栏目。
# ───────── 频道与全局配置 ─────────
# 每个频道一个文件夹：channels/<id>/channel.json（名字、配色、开场结尾、发布时间……）+ brief.md（怎么找方向、写文案）
ROOT = os.path.abspath(os.environ.get("AUTOCLIP_ROOT") or os.path.join(HERE, ".."))
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
    f = os.environ.get("AUTOCLIP_CONFIG") or os.path.join(ROOT, "autoclip.config.json")
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


def color(tag, i=0):
    return COLORS.get(tag, PALETTE[i % len(PALETTE)])


def cn_num(n):
    d = "零一二三四五六七八九"
    if n < 10: return d[n]
    if n < 20: return "十" + (d[n - 10] if n > 10 else "")
    return d[n // 10] + "十" + (d[n % 10] if n % 10 else "")


def categories(items):
    seen = []
    for it in items:
        if it["tag"] not in seen: seen.append(it["tag"])
    return seen


def auto_intro(data):
    """开场口播：按频道 intro 模板生成。可用 {name} {date} {n} {topic_say} {categories}。"""
    S = series(data)
    m = re.search(r"(\d+)月(\d+)日", data.get("date", ""))
    day = f"{cn_num(int(m.group(1)))}月{cn_num(int(m.group(2)))}日" if m else ""
    cats = categories(data["items"])
    joined = cats[0] if len(cats) == 1 else "、".join(cats[:-1]) + "和" + cats[-1]
    return S.get("intro", "{name}，{date}。").format(name=S["name"], date=day, n=cn_num(len(data["items"])),
                                                    topic_say=data.get("topic_say") or data.get("topic", ""), categories=joined)


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
        out.append(f"{circled[i]} 【{it['tag']}】{it['title'].replace('|', '')}")
        out.append(it.get("detail") or it["say"])
        out.append("")
    srcs = []
    for it in items:
        for x in re.split(r"[、,，/]", it.get("source", "")):
            if x.strip() and x.strip() not in srcs: srcs.append(x.strip())
    kind = S["src"].split("：")[0] if "：" in S["src"] else "信息来源"
    default = S["src"].split("：", 1)[1] if "：" in S["src"] else "公开资料"
    out.append(f"📌 {kind}：" + ("、".join(srcs) if srcs else default) + "（据公开资料整理）")
    tags = (data.get("hashtags") or S["hashtags"] + categories(items))[:5]
    out.append(" ".join("#" + t.lstrip("#") for t in tags))
    return "\n".join(out)
GSAP = os.environ.get("GSAP_JS") or next((p for p in [os.path.join(HERE, "node_modules", "gsap", "dist", "gsap.min.js"),
        os.path.join(HERE, "..", "hf", "node_modules", "gsap", "dist", "gsap.min.js")] if os.path.exists(p)), "")
FONT_SRC = "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"
E = html.escape


def phrases(text, t0, t1):
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
        words = rjieba.cut(p)
        parts_n = math.ceil(len(p) / 13); goal = len(p) / parts_n
        cur = ""
        for w in words:
            if cur and (len(cur) + len(w) > 13 or len(cur) >= goal):
                final.append(cur); cur = ""
            cur += w
        if cur: final.append(cur)
    merged = final
    n = sum(len(p) for p in merged)
    out, t = [], t0
    for p in merged:
        d = (t1 - t0) * len(p) / n
        out.append((p.rstrip("，。、；："), t, t + d)); t += d
    return out


CN_NUM = "一二三四五六七八九十"


def spoken_item(i, say):
    """口播不念分类（画面上已有），只念序号：一、二、三……"""
    say = re.sub(r"^[^，。：:]{1,4}[：:]", "", say.strip())
    return f"{CN_NUM[i]}，{say}"


def split_title(t, n=8):
    """标题超过 n 字时折成两行，断点靠近中间，且不切断数字/英文。"""
    if "|" in t: return [x for x in t.split("|") if x][:2]
    if len(t) <= n: return [t]
    mid = len(t) / 2
    ok = [k for k in range(2, len(t) - 1) if not (re.match(r"[0-9A-Za-z.%]", t[k - 1]) and re.match(r"[0-9A-Za-z.%]", t[k]))]
    k = min(ok, key=lambda k: abs(k - mid)) if ok else int(mid)
    return [t[:k], t[k:]]


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
    if hook == "topic":
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
    agenda = "".join(f'<li class="ag c{i}" id="ag{i}"><span class="num">{i + 1}</span><span class="agt">{E(it["title"].replace("|", ""))}</span></li>' for i, it in enumerate(items))
    follow_top = 580 + n * 104 + (n - 1) * 26 + 80

    scenes, js = [], []
    for i, it in enumerate(items):
        s, e = starts[i], ends[i]
        lines = split_title(it["title"])
        tl_html = "".join(f'<div class="tline" id="s{i}-l{k}">' + "".join(f'<span class="ch">{E(c)}</span>' for c in ln) + "</div>" for k, ln in enumerate(lines))
        scenes.append(f'''
      <div id="scene{i}" class="clip scene c{i}" data-start="{T(s)}" data-duration="{T(e - s)}" data-track-index="2">
        <div class="ghost" id="s{i}-ghost">0{i + 1}</div>
        <div class="meta" id="s{i}-meta"><span class="tag">{E(it["tag"])}</span><span class="idx">0{i + 1} / 0{n}</span></div>
        <div class="title" id="s{i}-title">{tl_html}</div>
        <div class="bar" id="s{i}-bar"></div>
      </div>''')
        js.append(f'''
      tl.fromTo("#s{i}-ghost", {{x: 160, opacity: 0}}, {{x: 0, opacity: 1, duration: 0.6, ease: "expo.out"}}, {T(s)});
      tl.fromTo("#s{i}-meta", {{y: 40, opacity: 0}}, {{y: 0, opacity: 1, duration: 0.35, ease: "power3.out"}}, {T(s + 0.05)});
      tl.fromTo("#scene{i} .ch", {{y: 70, opacity: 0, scale: 0.8}}, {{y: 0, opacity: 1, scale: 1, duration: 0.32, ease: "back.out(2)", stagger: 0.035}}, {T(s + 0.12)});
      tl.fromTo("#s{i}-bar", {{scaleX: 0}}, {{scaleX: 1, duration: 0.5, ease: "power2.inOut"}}, {T(s + 0.3)});
      tl.fromTo("#s{i}-title", {{scale: 1}}, {{scale: 1.04, duration: {T(e - s - 0.6)}, ease: "none"}}, {T(s + 0.5)});
      tl.to("#s{i}-title, #s{i}-meta, #s{i}-ghost, #s{i}-bar", {{y: -60, opacity: 0, duration: 0.2, ease: "power2.in"}}, {T(e - 0.2)});
      tl.fromTo("#pg{i}", {{scaleX: 0}}, {{scaleX: 1, duration: {T(e - s)}, ease: "none"}}, {T(s)});''')

    # 字幕：每句切短语，一次只显示一组
    caps, k = [], 0
    for li, (a, b) in enumerate(times[:-1]):  # 结尾页已有"关注我"，不再加字幕
        say = spoken[li]
        for p, s, e in phrases(say, a, b + 0.1):
            caps.append(f'<div class="clip cap" id="cap{k}" data-start="{T(s)}" data-duration="{T(e - s)}" data-track-index="5"><span>{E(p)}</span></div>')
            js.append(f'tl.fromTo("#cap{k} span", {{y: 16, opacity: 0}}, {{y: 0, opacity: 1, duration: 0.12, ease: "power2.out"}}, {T(s)});')
            k += 1

    recap = "".join(f'<div class="rc c{i}" id="rc{i}"><span class="rtag">{E(it["tag"])}</span>{E(it["title"].replace("|", ""))}</div>' for i, it in enumerate(items))
    js.append(f'''
      tl.fromTo("#outro .rc", {{x: -80, opacity: 0}}, {{x: 0, opacity: 1, duration: 0.3, ease: "power3.out", stagger: 0.08}}, {T(out_start)});
      tl.fromTo("#follow", {{scale: 0.6, opacity: 0}}, {{scale: 1, opacity: 1, duration: 0.45, ease: "back.out(2.2)"}}, {T(out_start + 0.5)});''')

    progress = "".join(f'<div class="pgs c{i}"><div class="pgf" id="pg{i}"></div></div>' for i in range(n))
    all_text = data["date"] + data["intro"] + data["outro"] + "".join(it["tag"] + it["title"] + it["say"] for it in items) + "内容由AI生成热点快报今日大热点关注我每天一分钟看懂天下事信息来源公开报道本期涉及条一二三四五六七八九十月日这" + "".join(S[k] for k in ("name", "slogan", "label", "src")) + data.get("topic", "")
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
      .ag {{ display: flex; align-items: center; gap: 24px; font-size: 46px; font-weight: 700; padding: 16px 0;
             border-bottom: 2px solid rgba(255,255,255,0.10); white-space: nowrap; }}
      .ag .num {{ flex: none; width: 62px; height: 62px; border-radius: 16px; background: var(--c); color: #0a0a18;
                  text-align: center; line-height: 62px; font-size: 40px; font-weight: 900; }}
      #hook .big em {{ font-style: normal; color: #ffd84a; -webkit-text-stroke: 3px #ffd84a; }}
      #hook .chips {{ display: none; }}
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
      .cap {{ position: absolute; left: 50px; right: 170px; top: 1470px; text-align: center; overflow: visible; }}
      .cap span {{ display: inline-block; font-size: 54px; font-weight: 700; color: #ffe678; padding: 14px 34px; border-radius: 22px;
                  background: rgba(0,0,0,0.38); -webkit-text-stroke: 1px #ffe678; }}
      #outro {{ position: absolute; inset: 0; }}
      #recap {{ position: absolute; left: 80px; right: 180px; top: 580px; display: flex; flex-direction: column; gap: 26px; }}
      .rc {{ font-size: 48px; font-weight: 700; display: flex; align-items: center; gap: 24px; padding: 22px 28px; border-radius: 22px;
             background: rgba(255,255,255,0.07); border-left: 10px solid var(--c); }}
      .rtag {{ font-size: 34px; padding: 6px 18px; border-radius: 12px; background: var(--c); color: #0a0a18; }}
      #follow {{ position: absolute; left: 80px; right: 180px; top: 1420px; text-align: center; font-size: 50px; font-weight: 900;
                padding: 22px; border-radius: 999px; background: #ff4646; }}
      #ailabel {{ position: absolute; left: 80px; top: 120px; font-size: 28px; color: rgba(255,255,255,0.92); padding: 6px 18px;
                 border: 2px solid rgba(255,255,255,0.55); border-radius: 12px; background: rgba(0,0,0,0.22); letter-spacing: 2px; }}
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
      <div id="ailabel" class="clip" data-start="0" data-duration="{T(dur)}" data-track-index="4">内容由AI生成</div>
      <div id="head" class="clip" data-start="0" data-duration="{T(dur)}" data-track-index="1">
        <div class="mark"></div><div><h1>{S["name"]}</h1><div class="date">{E(data["date"])} · {E(S["slogan"])}</div></div>
      </div>
      <div id="hook" class="clip" data-start="0" data-duration="{T(hook_end)}" data-track-index="2">
        <div class="big" id="hook-big">{hook_big}</div>
        <div class="cover"><span class="lab">{S["label"]}</span>{chips}</div>
        <ol class="agenda">{agenda}</ol>
      </div>
      {"".join(scenes)}
      <div id="progress" class="clip" data-start="{T(starts[0])}" data-duration="{T(out_start - starts[0])}" data-track-index="3">{progress}</div>
      <div id="src" class="clip" data-start="{T(starts[0])}" data-duration="{T(out_start - starts[0])}" data-track-index="3">{S["src"]}</div>
      <div id="outro" class="clip" data-start="{T(out_start)}" data-duration="{T(dur - out_start)}" data-track-index="2">
        <div id="recap">{recap}</div>
        <div id="follow" style="top:{follow_top}px">关注我 · 每天{E(S["slogan"])}</div>
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
      tl.fromTo("#hook .chip", {{y: 0}}, {{y: -10, duration: 0.3, ease: "sine.inOut", stagger: 0.12, yoyo: true, repeat: 1}}, 0.2);
      tl.fromTo("#hook .ag .num", {{scale: 1}}, {{scale: 1.18, duration: 0.18, ease: "power2.out", stagger: 0.25, yoyo: true, repeat: 1}}, 0.6);
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
    data["intro"] = data.get("intro") or auto_intro(data)
    data.setdefault("outro", S["outro"])
    lines = [data["intro"]] + [spoken_item(i, it["say"]) for i, it in enumerate(data["items"])] + [data["outro"]]
    audio, sr, times, speed = tts.synth(lines, VOICE, target, min_speed=float(VOICE.get("min_speed", 1.05)))
    dur = round(len(audio) / sr + 0.5, 2)
    os.makedirs(f"{proj}/assets", exist_ok=True)
    sf.write(f"{proj}/assets/voice.wav", audio, sr)
    build(data, times, dur, proj, lines)
    if not os.path.exists(f"{proj}/hyperframes.json"):
        json.dump({"name": "autoclip"}, open(f"{proj}/hyperframes.json", "w"))
    cap = make_caption(data)
    cap_path = os.path.join(os.path.dirname(os.path.abspath(src)), "抖音文案.txt")
    open(cap_path, "w").write(cap)
    # 发布信息（浏览器插件用）：标题≤30字；正文=文案去掉最后一行话题；话题单独传
    m = re.search(r"(\d+)月(\d+)日", data["date"])
    md = f"{int(m.group(1))}月{int(m.group(2))}日" if m else ""
    head = data.get("headline") or "、".join(it["title"].replace("|", "") for it in data["items"][:2])
    tags = [t.lstrip("#") for t in (data.get("hashtags") or S["hashtags"] + categories(data["items"]))]
    meta = {"title": f"{S['name']}{md}｜{head}"[:30], "desc": cap.rsplit("\n", 1)[0], "tags": tags[:5],
            "declaration": (CONFIG.get("publish") or {}).get("declaration", "内容由AI生成"), "collection": S.get("collection", S["name"]),
            "channel": S["id"]}
    # 竖封面 3:4 + 横封面 4:3（JPEG，base64 内嵌在发布信息里，插件解出来上传）
    try:
        from make_cover import covers
        meta["covers"] = covers(data, color, S)
    except Exception as e:
        print(f"封面生成失败（不影响视频，抖音会用默认封面）：{e!r}")
    json.dump(meta, open(os.path.join(os.path.dirname(cap_path), "发布信息.json"), "w"), ensure_ascii=False, indent=1)
    print(f"工程已生成: {proj}  时长 {dur}s  语速 x{speed:.2f}")
    print(f"抖音文案: {cap_path}  （{len(cap)} 字，抖音上限约1000字）")


if __name__ == "__main__":
    main()
