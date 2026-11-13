"""AutoClip · 检查频道配置并生成预览

用法:
  python3 tools/check_channel.py <频道id>                    只检查
  python3 tools/check_channel.py <频道id> --preview <目录>   检查 + 生成竖横封面和开场画面预览
  python3 tools/check_channel.py <频道id> --preview <目录> --palette 清新森绿,书卷暖棕   用预设配色出预览（不改文件）
  python3 tools/check_channel.py --all                       检查全部频道
  python3 tools/check_channel.py --palettes                  列出配色预设

退出码：0 没有错误（可能有提醒），1 有错误。
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.environ.get("AUTOCLIP_ROOT") or os.path.join(HERE, ".."))
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
HM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
PLACEHOLDERS = {"name", "date", "n", "topic_say", "categories"}


def _lum(rgb):
    def ch(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = rgb
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def _hex_rgb(h):
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


def contrast_with_white(rgb):
    return 1.05 / (_lum(rgb) + 0.05)


def check(cid):
    errs, warns = [], []
    d = os.path.join(ROOT, "channels", cid)
    f = os.path.join(d, "channel.json")
    if not re.fullmatch(r"[a-z0-9_]+", cid):
        errs.append("频道 id 只能用小写字母、数字、下划线")
    if not os.path.exists(f):
        return [f"找不到 {f}"], [], None
    try:
        c = json.load(open(f, encoding="utf-8"))
    except Exception as e:
        return [f"channel.json 不是合法 JSON：{e}"], [], None

    def need(k, typ):
        if k not in c:
            errs.append(f"缺少字段 {k}")
            return False
        if not isinstance(c[k], typ):
            errs.append(f"{k} 类型不对（应为 {typ.__name__ if isinstance(typ, type) else typ}）")
            return False
        return True

    if c.get("id") != cid:
        errs.append(f"id 应为 {cid}（和文件夹名一致），现在是 {c.get('id')}")
    for k in ("name", "slogan", "label", "deco", "src", "intro", "outro", "collection"):
        need(k, str)
    if isinstance(c.get("name"), str) and len(c["name"]) > 8:
        warns.append(f"频道名「{c['name']}」超过 8 个字，画面顶部和封面会被缩小，建议精简")
    if isinstance(c.get("slogan"), str) and len(c["slogan"]) > 12:
        warns.append("口号超过 12 个字，结尾的「关注我 · 每天…」按钮可能放不下")
    if isinstance(c.get("label"), str) and len(c["label"]) > 5:
        warns.append("label 超过 5 个字，开场标签行会拥挤")
    if c.get("hook") not in ("count", "topic", "date"):
        errs.append("hook 必须是 count / topic / date 之一")
    if c.get("hook") == "count" and not c.get("hook_unit"):
        warns.append("hook 为 count 时建议填 hook_unit，例如「条热点」「个知识点」")
    for k in ("intro", "outro"):
        if isinstance(c.get(k), str):
            bad = set(re.findall(r"\{(\w+)\}", c[k])) - PLACEHOLDERS
            if bad:
                errs.append(f"{k} 里有不支持的占位符：{', '.join(bad)}（可用：{', '.join(sorted(PLACEHOLDERS))}）")
    if c.get("hook") == "topic" and isinstance(c.get("intro"), str) and "{topic_say}" not in c["intro"]:
        warns.append("hook 为 topic 的频道，intro 里通常要念出 {topic_say}")
    for k, lo, hi in (("items", 1, 8), ("say_chars", 20, 120), ("say_total", 60, 600)):
        if k == "say_total" and k not in c:
            continue
        v = c.get(k)
        if not (isinstance(v, list) and len(v) == 2 and all(isinstance(x, int) for x in v) and lo <= v[0] <= v[1] <= hi):
            errs.append(f"{k} 应为 [最小, 最大]，范围 {lo}–{hi}")
    ms = c.get("max_seconds")
    if not (isinstance(ms, (int, float)) and 20 <= ms <= 180):
        errs.append("max_seconds 应在 20–180 之间")
    elif isinstance(c.get("items"), list) and isinstance(c.get("say_chars"), list) and len(c["items"]) == 2 and len(c["say_chars"]) == 2:
        chars = c["items"][1] * c["say_chars"][1]
        if isinstance(c.get("say_total"), list) and len(c["say_total"]) == 2:
            chars = min(chars, c["say_total"][1])
        est = (chars + 50) / 5.0 + 3  # 实测约 5 字/秒；开场 + 结尾约 50 字，句间停顿约 3 秒
        if est > ms + 5:
            warns.append(f"按最多条数和字数估算约 {est:.0f} 秒，超过 max_seconds={ms}，写稿时会被迫删减，建议调小字数或条数")
    tags = c.get("hashtags")
    if not (isinstance(tags, list) and 1 <= len(tags) <= 5 and all(isinstance(t, str) and t and not t.startswith("#") for t in tags)):
        errs.append("hashtags 应为 1–5 个不带 # 的话题")
    s = c.get("schedule") or {}
    if not HM.match(str(s.get("publish", ""))):
        errs.append("schedule.publish 应为 HH:MM（北京时间），00:00 表示就绪即发")
    if s.get("make") and not HM.match(str(s["make"])):
        errs.append("schedule.make 应为 HH:MM")
    if s.get("make") and HM.match(str(s.get("publish", ""))) and s.get("publish") != "00:00":
        mk = int(s["make"][:2]) * 60 + int(s["make"][3:])
        pb = int(s["publish"][:2]) * 60 + int(s["publish"][3:])
        if 0 <= pb - mk < 30:
            warns.append("制作时间离发布时间不到 30 分钟；用 CosyVoice 配音时建议提前 45 分钟以上")
    if not isinstance(s.get("days_ahead", 0), int) or not 0 <= s.get("days_ahead", 0) <= 3:
        errs.append("schedule.days_ahead 应为 0–3")
    t = c.get("theme") or {}
    if not isinstance(t.get("flow"), str) or "%" not in t.get("flow", ""):
        errs.append("theme.flow 应为 CSS 渐变色带，例如 \"#3a4fd8 0%, #7b3fd0 50%, #1f9cc4 100%\"")
    for k in ("base", "mark"):
        if not HEX.match(str(t.get(k, ""))):
            errs.append(f"theme.{k} 应为 #RRGGBB")
    g = t.get("glows")
    if not (isinstance(g, list) and len(g) == 4 and all(HEX.match(str(x)) for x in g)):
        errs.append("theme.glows 应为 4 个 #RRGGBB")
    st = t.get("stops")
    if not (isinstance(st, list) and len(st) >= 2 and all(isinstance(x, list) and len(x) == 2 and isinstance(x[1], list) and len(x[1]) == 3 for x in st)):
        errs.append("theme.stops 应为 [[位置0–1, [R,G,B]], …]，至少 2 个")
    else:
        light = [x for x in st if contrast_with_white(x[1]) < 3.0]
        if light:
            warns.append(f"封面渐变里有 {len(light)} 个颜色太浅，白字看不清（对比度 < 3），建议调深")
    if HEX.match(str(t.get("base", ""))) and contrast_with_white(_hex_rgb(t["base"])) < 4.5:
        warns.append("theme.base 偏浅，白色文字对比度不足 4.5，建议调深")
    for k in ("audience", "tone"):
        if not c.get(k):
            warns.append(f"建议填写 {k}（{'目标观众' if k == 'audience' else '口播语气 / 人设'}），出片时 AI 会据此调整用词")

    b = os.path.join(d, "brief.md")
    if not os.path.exists(b):
        errs.append("缺少 brief.md（怎么找方向、怎么写文案）")
    else:
        txt = open(b, encoding="utf-8").read()
        for kw in ("找方向", "写文案"):
            if kw not in txt:
                errs.append(f"brief.md 缺少「{kw}」部分")
        if len(txt) < 200:
            warns.append("brief.md 太短，AI 可能不知道怎么选题，建议写清素材来源、选题标准、不做什么、分段思路")
    cfgf = os.path.join(ROOT, "autoclip.config.json")
    if os.path.exists(cfgf) and cid not in (json.load(open(cfgf, encoding="utf-8")).get("channels") or []):
        warns.append("这个频道还没有在 autoclip.config.json 的 channels 里启用")
    return errs, warns, c


def preview(cid, out, palette=None):
    """生成竖横封面预览（不配音、不渲染视频，几秒钟完成）。palette：用 palettes.json 里的预设临时替换配色。"""
    sys.path.insert(0, HERE)
    os.makedirs(out, exist_ok=True)
    import gen_hf
    from make_cover import render
    c = gen_hf.CHANNELS[cid]
    if palette:
        pal = json.load(open(os.path.join(HERE, "palettes.json"), encoding="utf-8"))[palette]
        c.update({k: v for k, v in pal.items() if k != "mood"})
    n = c["items"][1]
    sample = {"channel": cid, "date": "2026年1月1日", "topic": c.get("sample_topic", "示例话题"),
              "items": [{"tag": f"要点{i + 1}", "title": f"这里是第{i + 1}条|示例标题", "say": "示例口播", "detail": "", "source": ""} for i in range(n)]}
    sample.update(c.get("sample") or {})
    S = gen_hf.series(sample)
    tag = f"_{palette}" if palette else ""
    a, b = os.path.join(out, f"{cid}{tag}_竖封面.jpg"), os.path.join(out, f"{cid}{tag}_横封面.jpg")
    render(sample, 1080, 1440, gen_hf.color, S).save(a, quality=88)
    render(sample, 1440, 1080, gen_hf.color, S).save(b, quality=88)
    return [a, b]


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(2)
    if args[0] == "--palettes":
        for k, v in json.load(open(os.path.join(HERE, "palettes.json"), encoding="utf-8")).items():
            if not k.startswith("_"):
                print(f"{k}：{v['mood']}")
        return
    ids = sorted(x for x in os.listdir(os.path.join(ROOT, "channels")) if not x.startswith((".", "_"))) if args[0] == "--all" else [args[0]]
    bad = False
    for cid in ids:
        errs, warns, _ = check(cid)
        print(f"── {cid}：{'❌ ' + str(len(errs)) + ' 个错误' if errs else '✅ 通过'}{'，' + str(len(warns)) + ' 条提醒' if warns else ''}")
        for e in errs:
            print(f"   错误：{e}")
        for w in warns:
            print(f"   提醒：{w}")
        bad |= bool(errs)
    if "--preview" in args and not bad:
        out = args[args.index("--preview") + 1]
        pals = args[args.index("--palette") + 1].split(",") if "--palette" in args else [None]
        verts = []
        for pal in pals:
            for p in preview(ids[0], out, pal):
                print(f"预览：{p}")
            verts.append((pal, os.path.join(out, f"{ids[0]}{'_' + pal if pal else ''}_竖封面.jpg")))
        if len(verts) > 1:  # 多套配色时拼一张对比图，方便挑选
            from PIL import Image, ImageDraw
            sys.path.insert(0, HERE)
            from make_cover import _f
            w, h = 540, 720
            sheet = Image.new("RGB", (w * len(verts) + 20 * (len(verts) + 1), h + 100), (245, 245, 250))
            d = ImageDraw.Draw(sheet)
            for i, (pal, f) in enumerate(verts):
                x = 20 + i * (w + 20)
                sheet.paste(Image.open(f).resize((w, h)), (x, 20))
                label = f"{i + 1}. {pal}"
                d.text((x + (w - d.textlength(label, font=_f(34))) / 2, h + 38), label, font=_f(34), fill=(30, 30, 50))
            sp = os.path.join(out, f"{ids[0]}_配色对比.jpg")
            sheet.save(sp, quality=88)
            print(f"对比图：{sp}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
