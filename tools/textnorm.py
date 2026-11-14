"""自影 · 口播读法：稿子按字幕的样子写（阿拉伯数字、百分号、日期），配音前自动转成读法。

    spoken("11月12日，前10个月出口9970亿美元，增长6.3%") → "十一月十二日，前十个月出口九千九百七十亿美元，增长百分之六点三"

自动规则（按顺序）：
  {显示|读法}           字幕显示左边，配音念右边，例如 {11.12|十一月十二日}、{CPI|消费者价格指数}；
                        右边是拼音时是多音字标注（{行|háng}），这里不处理，交给 tts.render_text
  2026年 / 2026-11-12    年份逐位念：二零二六年
  11月12日 / 12号        月、日按数值念：十一月十二日
  8:30 / 20:05           八点三十分 / 二十点零五分（整点念「八点」）
  6.3% / 50%             百分之六点三 / 百分之五十
  3-5个 / 3~5            三到五个
  1,234 / 35000 / 9970亿 按数值念，逗号去掉：一千二百三十四 / 三万五千 / 九千九百七十亿
  0.5 / 6.3              零点五 / 六点三
  12 位以上的数字         逐位念（编号、电话）
  常见单位               km→公里  kg→公斤  ℃→摄氏度  m²→平方米 等
"""
import re

D = "零一二三四五六七八九"
UNITS = [("km/h", "公里每小时"), ("km²", "平方公里"), ("m²", "平方米"), ("m³", "立方米"), ("km", "公里"), ("kg", "公斤"),
         ("cm", "厘米"), ("mm", "毫米"), ("ml", "毫升"), ("mL", "毫升"), ("℃", "摄氏度"), ("°C", "摄氏度"), ("GB", "G"), ("TB", "T")]


def digits(s):
    return "".join(D[int(c)] for c in s if c.isdigit())


def _under_10k(n, lead):
    """0 < n < 10000 的读法；lead=True 时 10–19 念「十X」而不是「一十X」。"""
    out, zero = "", False
    for p, name in ((1000, "千"), (100, "百"), (10, "十"), (1, "")):
        q = n // p % 10
        if q:
            if zero:
                out += "零"
            out += ("" if (p == 10 and q == 1 and lead and not out) else D[q]) + name
            zero = False
        elif out:
            zero = True
    return out


def cardinal(n):
    n = int(n)
    if n == 0:
        return "零"
    if n < 0:
        return "负" + cardinal(-n)
    parts, out, first = [], "", True
    for name, p in (("亿", 10 ** 8), ("万", 10 ** 4), ("", 1)):
        parts.append((n // p % (10 ** 4) if p < 10 ** 8 else n // p, name))
    need_zero = False
    for v, name in parts:
        if v == 0:
            if out:
                need_zero = True
            continue
        if out and (need_zero or v < 1000):
            out += "零"
        out += (cardinal(v) if v >= 10 ** 4 else _under_10k(v, first)) + name
        first, need_zero = False, False
    return out


def _liang(s):
    """口语习惯：两千、两万、两亿（二十二万不变）。"""
    return re.sub(r"(?<!十)二(?=[千万亿])", "两", s)


def number(s):
    """'1,234.50' → 一千二百三十四点五零；'0012' 之类以 0 开头的整数逐位念。"""
    s = s.replace(",", "").replace("，", "")
    if "." in s:
        a, b = s.split(".", 1)
        return (_liang(cardinal(a)) if a else "零") + "点" + digits(b)
    if len(s) > 1 and s.startswith("0") or len(s) >= 12:
        return digits(s)
    return _liang(cardinal(s))


LIANG = set("个位次件种只条天年周岁斤吨辆台家项份倍层成名点步道招句")  # 2 后面跟这些量词时念「两」（第2名除外）
NUM = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?"


def spoken(text):
    # 1. 显式读法 {显示|读法}（读法含汉字时）
    text = re.sub(r"\{([^{}|]+)\|([^{}]*[一-鿿][^{}]*)\}", r"\2", text)
    # 2. 日期
    text = re.sub(r"(?<!\d)(\d{4})-(\d{1,2})-(\d{1,2})(?!\d)", lambda m: f"{digits(m[1])}年{cardinal(m[2])}月{cardinal(m[3])}日", text)
    text = re.sub(r"(?<!\d)(\d{4})(?=年)", lambda m: digits(m[1]), text)
    text = re.sub(r"(?<![\d.])(\d{2})(?=年代)", lambda m: cardinal(m[1]), text)
    text = re.sub(r"(?<![\d.])(\d{1,2})(?=月)", lambda m: cardinal(m[1]), text)
    text = re.sub(r"(?<![\d.])(\d{1,2})(?=[日号])", lambda m: cardinal(m[1]), text)
    # 3. 时刻
    def clock(m):
        h, mi = int(m[1]), int(m[2])
        return cardinal(h) + "点" + ("" if mi == 0 else ("零" + D[mi] if mi < 10 else cardinal(mi)) + "分")
    text = re.sub(r"(?<!\d)([01]?\d|2[0-3])[:：]([0-5]\d)(?!\d)", clock, text)
    # 4. 负数、单位
    text = re.sub(r"(?<![\d.])[-−](\d+(?:\.\d+)?)\s*(?=℃|°C)", r"零下\1", text)
    text = re.sub(r"(?:(?<=^)|(?<=[^\d.A-Za-z]))[-−](?=\d)", "负", text)
    for a, b in UNITS:
        text = re.sub(rf"(?<=\d)\s*{re.escape(a)}(?![A-Za-z])", b, text)
    # 5. 百分数、范围
    text = re.sub(rf"({NUM})\s*[%％]", lambda m: "百分之" + number(m[1]), text)
    text = re.sub(rf"({NUM})\s*[-~～—–]\s*(?=\d)", lambda m: number(m[1]) + "到", text)
    text = re.sub(r"(?<=\d)\s*[:：]\s*(?=\d)", "比", text)  # 比分 3:1
    # 6. 其余数字
    def num(m):
        r = number(m[0])
        nxt = m.string[m.end():m.end() + 1]
        if r == "二" and nxt in LIANG and m.string[max(0, m.start() - 1):m.start()] != "第":
            r = "两"
        return r
    text = re.sub(NUM, num, text)
    text = text.replace("+", "加").replace("×", "乘").replace("÷", "除以")
    return text


if __name__ == "__main__":
    import sys
    for line in sys.argv[1:] or ["2026年11月12日上午8:30，前10个月出口9970亿美元，同比增长6.3%，较2025年多出1,234.5亿，约35000人参与，3-5天，比分3:1，气温-3℃到12℃，{11.12|十一月十二日}，120.5km，0.5秒。"]:
        print(spoken(line))
