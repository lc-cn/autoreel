"""自影 · Webhook 通知（不依赖任何 AI 工具：企业微信、飞书、钉钉、OneBot 11/12、Bark、Server酱、Telegram、自定义 JSON）

在 autoreel.config.json 里配置，模板写法和浏览器插件一致：
  "notify": [
    {"name": "企业微信", "preset": "wecom", "url": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=${WECOM_KEY}",
     "events": ["made", "failed"]}
  ]
- url、headers、body 里的 ${环境变量} 会在发送时替换。**密钥只放环境变量，不要写进仓库。**
- body 不写就用 preset 的默认模板；{{变量}} 会按 JSON 转义，{{变量|raw}} 原样插入。
- 可用变量：event（made / failed / warn）、emoji、title、message、text（emoji + title + message + 时间）、
  channel（频道 id）、slot（频道名）、video_title、date、time、branch。

命令行：python3 tools/notify.py <event> <title> <message> [--channel id] [--video-title ...]
"""
import argparse
import datetime
import json
import os
import re
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRESETS = {
    "wecom": '{"msgtype":"text","text":{"content":"{{text}}"}}',
    "feishu": '{"msg_type":"text","content":{"text":"{{text}}"}}',
    "dingtalk": '{"msgtype":"text","text":{"content":"{{text}}"}}',
    "onebot11_group": '{"group_id": 123456789, "message": "{{text}}"}',
    "onebot11_private": '{"user_id": 123456789, "message": "{{text}}"}',
    "onebot12": '{"action": "send_message", "params": {"detail_type": "group", "group_id": "123456789", "message": [{"type": "text", "data": {"text": "{{text}}"}}]}}',
    "bark": '{"title": "{{title}}", "body": "{{message}}", "group": "AutoReel"}',
    "serverchan": '{"title": "{{title}}", "desp": "{{message}}\\n\\n{{time}}"}',
    "telegram": '{"chat_id": "${TELEGRAM_CHAT_ID}", "text": "{{text}}"}',
    "generic": '{"event": "{{event}}", "channel": "{{channel}}", "title": "{{title}}", "message": "{{message}}", "video_title": "{{video_title}}", "time": "{{time}}"}',
}
EMOJI = {"made": "🎬", "failed": "❌", "warn": "⚠️"}


def _env(s):
    return re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", lambda m: os.environ.get(m.group(1), ""), s)


def _render(tpl, vars_):
    def rep(m):
        key, raw = m.group(1), m.group(2)
        v = str(vars_.get(key, ""))
        return v if raw else json.dumps(v, ensure_ascii=False)[1:-1]
    return re.sub(r"\{\{\s*(\w+)\s*(\|raw)?\s*\}\}", rep, tpl)


def send(event, title, message, **extra):
    """按配置发送；返回 [(名称, 结果)]。没有配置就什么都不做。"""
    try:
        cfg = json.load(open(os.environ.get("AUTOREEL_CONFIG", os.path.join(ROOT, "autoreel.config.json")), encoding="utf-8"))
    except Exception:
        return []
    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))
    v = {"event": event, "emoji": EMOJI.get(event, "🔔"), "title": title, "message": message,
         "date": now.strftime("%Y-%m-%d"), "time": now.strftime("%Y-%m-%d %H:%M:%S"), **extra}
    v["text"] = f"{v['emoji']} {title}\n{message}\n—— 自影 · {v['time']}"
    out = []
    for n in cfg.get("notify") or []:
        if n.get("enabled") is False or event not in n.get("events", ["made", "failed", "warn"]):
            continue
        name = n.get("name") or n.get("preset") or "webhook"
        try:
            url = _env(n["url"])
            if "${" in n["url"] and not url.split("://", 1)[-1].strip("/"):
                raise ValueError("地址里引用的环境变量没有设置")
            body = _env(_render(n.get("body") or PRESETS.get(n.get("preset", "generic"), PRESETS["generic"]), v))
            headers = {"Content-Type": "application/json; charset=utf-8", "User-Agent": "autoreel"}
            headers.update({k: _env(x) for k, x in (n.get("headers") or {}).items()})
            req = urllib.request.Request(url, data=body.encode("utf-8"), headers=headers, method=n.get("method", "POST"))
            with urllib.request.urlopen(req, timeout=20) as r:
                out.append((name, f"HTTP {r.status}"))
        except Exception as e:
            out.append((name, f"失败：{e}"))
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("event", choices=["made", "failed", "warn"])
    ap.add_argument("title")
    ap.add_argument("message")
    ap.add_argument("--channel", default="")
    ap.add_argument("--video-title", default="")
    a = ap.parse_args()
    res = send(a.event, a.title, a.message, channel=a.channel, video_title=a.video_title)
    for name, r in res:
        print(f"通知 {name}：{r}")
    if not res:
        print("没有配置通知（autoreel.config.json 的 notify），跳过")
    sys.exit(0)
