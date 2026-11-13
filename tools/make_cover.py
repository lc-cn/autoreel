"""热点快报封面：竖封面 3:4（1080×1440）和横封面 4:3（1440×1080），配色与视频一致。
用法（单独测试）：python3 make_cover.py today.json 输出目录
"""
import base64
import io
import json
import re
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONT = "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"
STOPS = [(0.0, (58, 79, 216)), (0.3, (123, 63, 208)), (0.6, (31, 156, 196)), (1.0, (208, 74, 140))]


def _f(size):
    return ImageFont.truetype(FONT, size)


def _lerp(stops, t):
    for (t0, c0), (t1, c1) in zip(stops, stops[1:]):
        if t <= t1:
            k = (t - t0) / (t1 - t0)
            return tuple(int(a + (b - a) * k) for a, b in zip(c0, c1))
    return stops[-1][1]


def _background(w, h, stops=STOPS):
    # 斜向渐变 + 柔光 + 暗角，与视频背景同色系
    small = Image.new("RGB", (64, 64))
    px = small.load()
    for y in range(64):
        for x in range(64):
            px[x, y] = _lerp(stops, (x + y) / 126)
    img = small.resize((w, h), Image.BICUBIC)
    glow = Image.new("RGB", (w, h), (0, 0, 0))
    d = ImageDraw.Draw(glow)
    d.ellipse((-w * 0.25, -h * 0.1, w * 0.5, h * 0.45), fill=(91, 124, 255))
    d.ellipse((w * 0.6, h * 0.6, w * 1.3, h * 1.2), fill=(255, 95, 162))
    glow = glow.filter(ImageFilter.GaussianBlur(min(w, h) // 6))
    img = Image.blend(img, glow, 0.35)
    shade = Image.new("RGB", (w, h), (8, 10, 40))
    mask = Image.linear_gradient("L").resize((w, h)).point(lambda v: int(60 + v * 0.45))
    img = Image.composite(shade, img, mask)
    grid = ImageDraw.Draw(img, "RGBA")
    for x in range(0, w, 90):
        grid.line((x, 0, x, h), fill=(255, 255, 255, 18))
    for y in range(0, h, 90):
        grid.line((0, y, w, y), fill=(255, 255, 255, 18))
    return img


def _fit(d, text, size, max_w, min_size=28):
    while size > min_size and d.textlength(text, font=_f(size)) > max_w:
        size -= 2
    return _f(size)


def _hex(c):
    return tuple(int(c[i:i + 2], 16) for i in (1, 3, 5))


def render(data, w, h, color_of, S=None):
    S = S or {"name": "热点快报", "slogan": "一分钟看懂天下事", "stops": STOPS, "mark": "#ff4646"}
    img = _background(w, h, S["stops"])
    d = ImageDraw.Draw(img, "RGBA")
    pad = int(w * 0.075)
    m = re.search(r"(\d+)月(\d+)日", data.get("date", ""))
    md = f"{int(m.group(1))}月{int(m.group(2))}日" if m else data.get("date", "")
    items = data["items"]
    landscape = w > h
    # 标题区：红色竖条 + 「热点快报」 + 日期
    top = int(h * (0.08 if landscape else 0.07))
    big = int(h * (0.12 if landscape else 0.085))
    d.rounded_rectangle((pad, top + 6, pad + 14, top + big + 6), 7, fill=_hex(S["mark"]))
    name = S["name"]
    big = min(big, int((w - 2 * pad - 40) / (len(name) + 2.6)))  # 栏目名较长时缩小
    d.text((pad + 40, top), name, font=_f(big), fill="white", stroke_width=2, stroke_fill="white")
    tw = d.textlength(name, font=_f(big))
    date_f = _f(int(big * 0.42))
    d.text((pad + 70 + tw, top + big * 0.45), md, font=date_f, fill=(255, 216, 74))
    # 今日N条
    y = top + big + int(h * 0.04)
    hook = S.get("hook", "count")
    if hook == "topic":
        sub = f"{data.get('topic', '')} · 分 {len(items)} 点讲清楚"
    elif hook == "date":
        sub = f"这一天的 {len(items)} 件大事 · {S['slogan']}"
    else:
        sub = f"今日 {len(items)} {S.get('hook_unit', '条')} · {S['slogan']}"
    d.text((pad, y), sub, font=_f(int(big * 0.36)), fill=(238, 241, 255))
    y += int(big * 0.36) + int(h * 0.04)
    # 条目列表：序号圆 + 分类色 + 标题
    rows = items[:6]
    avail = h - y - int(h * 0.07)
    row_h = min(int(avail / max(len(rows), 1)), int(h * (0.13 if landscape else 0.125)))
    y += max(0, (avail - row_h * len(rows)) // 2)  # 列表在剩余空间里垂直居中
    fs = int(row_h * 0.42)
    for i, it in enumerate(rows):
        c = _hex(color_of(it.get("tag", ""), i))
        cy = y + i * row_h + row_h // 2
        r = int(row_h * 0.3)
        d.rounded_rectangle((pad - 12, cy - row_h * 0.42, w - pad + 12, cy + row_h * 0.42), 18, fill=(255, 255, 255, 30))
        d.ellipse((pad + 8, cy - r, pad + 8 + 2 * r, cy + r), fill=c)
        n = str(i + 1)
        nf = _f(int(r * 1.2))
        d.text((pad + 8 + r - d.textlength(n, font=nf) / 2, cy - r * 0.68), n, font=nf, fill=(20, 20, 40))
        x = pad + 8 + 2 * r + 24
        tag = it.get("tag", "")
        if tag:
            tf = _f(int(fs * 0.7))
            tl = d.textlength(tag, font=tf)
            d.rounded_rectangle((x, cy - fs * 0.5, x + tl + 24, cy + fs * 0.5), 10, fill=c + (230,))
            d.text((x + 12, cy - fs * 0.42), tag, font=tf, fill=(20, 20, 40))
            x += tl + 44
        title = it["title"].replace("|", "")
        f = _fit(d, title, fs, w - pad - x)
        d.text((x, cy - f.size * 0.55), title, font=f, fill="white")
    foot = f"关注我 · 每天{S['slogan']}"
    ff = _f(int(h * 0.026))
    d.text(((w - d.textlength(foot, font=ff)) / 2, h - int(h * 0.055)), foot, font=ff, fill=(238, 241, 255, 200))
    return img


def b64jpeg(img):
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=90)
    return base64.b64encode(buf.getvalue()).decode()


def covers(data, color_of, S=None):
    """返回 {"portrait": base64, "landscape": base64}（JPEG）。"""
    return {"portrait": b64jpeg(render(data, 1080, 1440, color_of, S)),
            "landscape": b64jpeg(render(data, 1440, 1080, color_of, S))}


if __name__ == "__main__":
    import os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from gen_hf import color, series
    data = json.load(open(sys.argv[1]))
    out = sys.argv[2]
    os.makedirs(out, exist_ok=True)
    render(data, 1080, 1440, color, series(data)).save(f"{out}/cover_portrait.jpg", quality=90)
    render(data, 1440, 1080, color, series(data)).save(f"{out}/cover_landscape.jpg", quality=90)
    print("ok")
