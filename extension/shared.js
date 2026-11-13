// AutoClip 插件各部分共用的常量
export const PLATFORMS = {
  douyin: {
    name: "抖音",
    upload: "https://creator.douyin.com/creator-micro/content/upload",
    login: "https://creator.douyin.com/",
    loggedIn: (u) => /creator\.douyin\.com\/creator-micro\//.test(u),
  },
  channels: {
    name: "视频号",
    upload: "https://channels.weixin.qq.com/platform/post/create",
    login: "https://channels.weixin.qq.com/login.html",
    loggedIn: (u) => /channels\.weixin\.qq\.com\/platform/.test(u),
  },
  kuaishou: {
    name: "快手",
    upload: "https://cp.kuaishou.com/article/publish/video",
    login: "https://passport.kuaishou.com/pc/account/login/?sid=kuaishou.web.cp.api&callback=https%3A%2F%2Fcp.kuaishou.com%2Frest%2Finfra%2Fsts%3FfollowUrl%3Dhttps%253A%252F%252Fcp.kuaishou.com%252Farticle%252Fpublish%252Fvideo%26setRootDomain%3Dtrue",
    loggedIn: (u) => /cp\.kuaishou\.com\/(article|profile|statistics)/.test(u),
  },
};
export const ORDER = ["douyin", "channels", "kuaishou"];
// 频道列表不再写死：插件从仓库默认分支读取 autoclip.config.json 和 channels/<id>/channel.json。
// 每期成品的分支名：clip-<日期>-<频道id>
export const channelTag = (date, id) => `clip-${date}-${id}`;
export const MAX_ATTEMPTS = 3;
export const JOB_TIMEOUT_MS = 40 * 60 * 1000;
export const CHUNK = 4 * 1024 * 1024;

// ───────── 消息推送：事件、模板变量、渠道预设 ─────────
export const EVENTS = {
  published: { name: "发布成功", emoji: "✅" },
  failed: { name: "发布失败", emoji: "❌" },
  verify: { name: "需要验证", emoji: "⚠️" },
  login: { name: "登录失效", emoji: "🔑" },
};
export const VARS = [
  ["text", "完整消息（按下方「消息正文模板」生成）"],
  ["title", "通知标题，如「抖音已发布「热点快报」」"],
  ["message", "详细说明 / 协助步骤"],
  ["event", "事件代码：published / failed / verify / login"],
  ["event_name", "事件名称：发布成功 / 发布失败 / 需要验证 / 登录失效"],
  ["emoji", "事件图标：✅ ❌ ⚠️ 🔑"],
  ["platform", "平台名称：抖音 / 视频号 / 快手"],
  ["platform_key", "平台代码：douyin / channels / kuaishou"],
  ["slot", "频道名称，如：热点快报 / 一分钟冷知识"],
  ["video_title", "视频标题"],
  ["date", "日期，如 2026-11-12"],
  ["time", "时间，如 2026-11-12 19:05:03"],
];
export const DEFAULT_TEXT = "{{emoji}} {{title}}\n{{message}}\n—— AutoClip · {{time}}";

// 每个预设：url / method / 内容类型 / 请求头（JSON）/ 消息体模板
export const PRESETS = {
  wecom: { label: "企业微信群机器人", url: "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=你的key", body: '{"msgtype":"text","text":{"content":"{{text}}"}}' },
  feishu: { label: "飞书群机器人", url: "https://open.feishu.cn/open-apis/bot/v2/hook/你的token", body: '{"msg_type":"text","content":{"text":"{{text}}"}}' },
  dingtalk: { label: "钉钉群机器人", url: "https://oapi.dingtalk.com/robot/send?access_token=你的token", body: '{"msgtype":"text","text":{"content":"{{text}}"}}', tip: "安全设置选「自定义关键词」，填：AutoClip" },
  onebot11_group: { label: "OneBot 11 · 群消息", url: "http://127.0.0.1:5700/send_group_msg", headers: '{"Authorization": "Bearer 你的access_token"}', body: '{"group_id": 123456789, "message": "{{text}}"}', tip: "go-cqhttp / NapCat / Lagrange / LLOneBot 等的 HTTP 接口；没设 access_token 就把请求头清空" },
  onebot11_private: { label: "OneBot 11 · 私聊", url: "http://127.0.0.1:5700/send_private_msg", headers: '{"Authorization": "Bearer 你的access_token"}', body: '{"user_id": 123456789, "message": "{{text}}"}' },
  onebot12: { label: "OneBot 12 · 发送消息", url: "http://127.0.0.1:5700/", headers: '{"Authorization": "Bearer 你的access_token"}', body: '{"action": "send_message", "params": {"detail_type": "group", "group_id": "123456789", "message": [{"type": "text", "data": {"text": "{{text}}"}}]}, "echo": "kuaibao"}', tip: "detail_type 可改为 private（配 user_id）或 channel（配 guild_id、channel_id）" },
  bark: { label: "Bark（iPhone 推送）", url: "https://api.day.app/你的key", body: '{"title": "{{title}}", "body": "{{message}}", "group": "AutoClip"}' },
  serverchan: { label: "Server酱（微信推送）", url: "https://sctapi.ftqq.com/你的SendKey.send", body: '{"title": "{{title}}", "desp": "{{message}}\\n\\n{{time}}"}' },
  telegram: { label: "Telegram Bot", url: "https://api.telegram.org/bot你的token/sendMessage", body: '{"chat_id": "你的chat_id", "text": "{{text}}"}' },
  generic: { label: "自定义（通用 JSON）", url: "https://", body: '{"event": "{{event}}", "platform": "{{platform}}", "slot": "{{slot}}", "title": "{{title}}", "message": "{{message}}", "video_title": "{{video_title}}", "time": "{{time}}"}' },
};
export function newChannel(preset = "wecom") {
  const p = PRESETS[preset] || PRESETS.generic;
  return {
    id: Math.random().toString(36).slice(2, 10), name: p.label, preset, enabled: true,
    url: p.url, method: "POST", contentType: "json", headers: p.headers || "", body: p.body,
    events: { published: true, failed: true, verify: true, login: true },
  };
}
// {{变量}}：按内容类型转义（JSON 里放在引号内即可）；{{变量|raw}}：原样插入
export function render(tpl, vars, mode = "json") {
  return String(tpl || "").replace(/\{\{\s*([a-z_]+)\s*(\|\s*raw\s*)?\}\}/g, (_, k, raw) => {
    const v = vars[k] == null ? "" : String(vars[k]);
    if (raw) return v;
    if (mode === "json") return JSON.stringify(v).slice(1, -1);
    if (mode === "form" || mode === "url") return encodeURIComponent(v);
    return v;
  });
}
export function buildVars(kind, info = {}, textTpl = DEFAULT_TEXT, now = "") {
  const ev = EVENTS[kind] || { name: kind, emoji: "🔔" };
  const v = {
    event: kind, event_name: ev.name, emoji: ev.emoji, title: info.title || "", message: info.message || "",
    platform: info.platform || "", platform_key: info.platformKey || "", slot: info.slot || "",
    video_title: info.videoTitle || "", time: now, date: now.slice(0, 10),
  };
  v.text = render(textTpl || DEFAULT_TEXT, v, "text");
  return v;
}
// 生成一次请求（设置页预览和后台发送共用）
export function buildRequest(ch, vars) {
  const ct = { json: "application/json", form: "application/x-www-form-urlencoded", text: "text/plain;charset=utf-8" }[ch.contentType] || "application/json";
  let headers = {};
  if (ch.headers && ch.headers.trim()) headers = JSON.parse(render(ch.headers, vars, "json"));
  const url = render(ch.url, vars, "url");
  const req = { url, method: ch.method || "POST", headers: { ...headers } };
  if (req.method !== "GET") {
    req.headers["Content-Type"] = req.headers["Content-Type"] || ct;
    req.body = render(ch.body, vars, ch.contentType === "form" ? "form" : ch.contentType === "text" ? "text" : "json");
    if (ch.contentType === "json") JSON.parse(req.body); // 模板写错时直接报错
  }
  return req;
}

export const DEFAULTS = {
  repo: "",              // 你的 GitHub 仓库，如 yourname/my-kuaibao
  token: "",
  platforms: { douyin: true, channels: false, kuaishou: false },
  times: {},             // 按频道覆盖发布时间，如 {"kuaibao": "09:30"}；不填就用频道里的 schedule.publish
  channels: [],          // 推送渠道列表，见 newChannel()
  textTemplate: DEFAULT_TEXT,
  browserNotify: { published: true, failed: true, verify: true, login: true },
  keepAliveHours: 6,
  paused: false,
};

