"""自影 · 一条命令出片：稿子（script.json）→ 配音 → 画面工程 → 检查 → 渲染 → 抽帧 → 推送 → 通知

任何 AI 工具（或人）写好 script.json 后都用它出片，不依赖特定的 AI 工具：
    python3 tools/make.py <频道id> <script.json> [--date YYYY-MM-DD] [--push] [--notify]
    python3 tools/make.py <频道id> <script.json> --date YYYY-MM-DD --push-only [--notify]   # 看过检查帧后推送上一次的成片

退出码：
    0  成功（加了 --push 就已推送）
    2  需要改稿：时长超限、文案超长、渲染前检查有错误、有句子没念清楚……原因写在输出和 结果.json 里，改好 script.json 再运行
    1  出错（环境、网络等），看输出的错误信息
工作目录默认 /tmp/autoreel-work/<频道>-<日期>/，成品 out.mp4、抽帧 frames/、结果.json 都在这里。
CosyVoice 在没有显卡的机器上很慢（一分钟视频要 10–20 分钟），AI 工具有命令超时的话，放到后台运行再等它结束。
"""
import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ENV = {**os.environ, "HYPERFRAMES_NO_TELEMETRY": "1", "DO_NOT_TRACK": "1"}
sys.path.insert(0, HERE)
import notify  # noqa: E402
import history  # noqa: E402
import rotation  # noqa: E402


def sh(cmd, cwd=None, check=True):
    r = subprocess.run(cmd, cwd=cwd, env=ENV, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"{' '.join(map(str, cmd[:3]))} 失败：\n{(r.stdout + r.stderr).strip()[-2000:]}")
    return r


def beijing_today():
    return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).strftime("%Y-%m-%d")


def date_of(script):
    m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", script.get("date", ""))
    return f"{m[1]}-{int(m[2]):02d}-{int(m[3]):02d}" if m else beijing_today()


def duration(path):
    r = sh(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path])
    return float(r.stdout.strip() or 0)


def frames(video, proj, out_dir, dur):
    """抽检查帧：开头、中间、结尾，加上每个图表 / 地图 / 时间线镜头的中间。"""
    os.makedirs(out_dir, exist_ok=True)
    pts = [("开头", 1.0), ("中间", dur / 2), ("结尾", max(0, dur - 1))]
    html = open(os.path.join(proj, "index.html"), encoding="utf-8").read()
    for m in re.finditer(r'id="scene(\d+)"[^>]*data-start="([\d.]+)" data-duration="([\d.]+)"', html):
        i, s, d = int(m[1]), float(m[2]), float(m[3])
        pts.append((f"第{i + 1}段", s + d / 2))
    # 每段实拍素材各一帧，文件名带上段落和搜索词，方便核对画面和口播是不是一回事
    try:
        used = json.load(open(os.path.join(proj, "素材.json"), encoding="utf-8"))
    except Exception:
        used = []
    for u in used:
        m = re.search(r'<video[^>]*src="%s"[^>]*data-start="([\d.]+)" data-duration="([\d.]+)"' % re.escape(u["file"]), html)
        if m:
            q = re.sub(r"[^A-Za-z0-9]+", "-", u["query"]).strip("-")[:40]
            pts.append((f"实拍-{u['where'].replace(' ', '')}-{q}", float(m[1]) + float(m[2]) / 2))
    out = []
    for name, t in pts:
        f = os.path.join(out_dir, f"{len(out):02d}-{name}-{t:.1f}s.jpg")
        sh(["ffmpeg", "-loglevel", "error", "-y", "-ss", f"{t:.2f}", "-i", video, "-frames:v", "1", "-vf", "scale=540:-1", f])
        out.append(f)
    return out


def push_and_notify(a, res, W, D, out, finish):
    meta = json.load(open(os.path.join(W, "发布信息.json"), encoding="utf-8"))
    res["title"] = meta.get("title", "")
    if a.push:
        print("④ 推送……", flush=True)
        r = sh(["bash", os.path.join(HERE, "push_clip.sh"), a.channel, D, out, os.path.join(W, "发布信息.json"),
                os.path.join(W, "抖音文案.txt")], cwd=ROOT)
        res["branch"] = f"clip-{D}-{a.channel}"
        res["pushed"] = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "已推送"
        print("   " + res["pushed"])
        try:  # 记进发布记录（默认分支 history/发布记录.jsonl），以后选题先查它，避免重复
            history.add(W, a.channel, D)
            res["history"] = history.commit_push()
        except Exception as e:  # 记录失败不影响已经推送的片子
            res["history"] = f"发布记录没写上：{e}"
        print("   " + res["history"])
    if a.notify:
        dur = res.get("duration") or 0
        msg = f"{res['title']}\n时长 {dur:.0f} 秒" + (f"，已推送 {res.get('branch')}，到点由插件发布" if a.push else "（未推送）")
        for n, r in notify.send("made", f"{res['name']} {D} 已出片", msg, channel=a.channel, slot=res["name"],
                                video_title=res["title"], branch=res.get("branch", "")):
            print(f"通知 {n}：{r}")
    finish(0)


def main():
    ap = argparse.ArgumentParser(description="自影 · 一条命令出片")
    ap.add_argument("channel")
    ap.add_argument("script")
    ap.add_argument("--date", help="这一期的日期 YYYY-MM-DD，默认取稿子里的 date")
    ap.add_argument("--work", help="工作目录，默认 /tmp/autoreel-work/<频道>-<日期>")
    ap.add_argument("--push", action="store_true", help="成功后推送到 clip-<日期>-<频道> 分支")
    ap.add_argument("--push-only", action="store_true", help="不重新出片，把工作目录里上一次成功的成片推送出去（看过检查帧之后用）")
    ap.add_argument("--notify", action="store_true", help="按 autoreel.config.json 的 notify 发 webhook 通知")
    a = ap.parse_args()

    ch_dir = os.path.join(ROOT, "channels", a.channel)
    if not os.path.isfile(os.path.join(ch_dir, "channel.json")):
        raise SystemExit(f"没有这个频道：{a.channel}")
    S = json.load(open(os.path.join(ch_dir, "channel.json"), encoding="utf-8"))
    data = json.load(open(a.script, encoding="utf-8"))
    if data.get("channel", a.channel) != a.channel:
        raise SystemExit(f"稿子里的 channel 是 {data.get('channel')}，和命令里的 {a.channel} 不一致")
    data["channel"] = a.channel
    D = a.date or date_of(data)
    early = []
    S.setdefault("id", a.channel)
    if not data.get("format"):  # 没写形式就按轮换表来（见 tools/rotation.py）
        data["format"] = rotation.format_for(S, D)
    if data["format"] == "quiz":
        q = data.get("quiz") or {}
        if not str(q.get("question", "")).strip() or len(q.get("options") or []) < 2 or not 0 <= int(q.get("answer", -1)) < len(q.get("options") or []):
            early.append("这一期是答题挑战（format: quiz），需要写 quiz：{\"question\": 题目, \"options\": [3 个选项], \"answer\": 正确选项序号}，写法见 python3 tools/rotation.py " + a.channel)
    if not str(data.get("hook", "")).strip() and data["format"] != "quiz":
        early.append("缺少 hook（钩子句）：开场第一句要直接抛出最抓人的内容，观众 2 秒内就决定划不划走，写法见 autoreel 技能")
    W = a.work or f"/tmp/autoreel-work/{a.channel}-{D}"
    os.makedirs(W, exist_ok=True)
    json.dump(data, open(os.path.join(W, "script.json"), "w"), ensure_ascii=False, indent=1)
    res = {"channel": a.channel, "name": S.get("name", a.channel), "date": D, "work": W, "problems": [], "warnings": [], "format": data.get("format")}

    def finish(code):
        json.dump(res, open(os.path.join(W, "结果.json"), "w"), ensure_ascii=False, indent=1)
        print("\n结果：" + {0: "成功", 1: "出错", 2: "需要改稿"}[code])
        for p in res["problems"]:
            print("  ✗ " + p)
        for w in res["warnings"]:
            print("  · " + w)
        print(f"详情：{W}/结果.json")
        if a.notify and code != 0:
            ev = "failed" if code == 1 else "warn"
            for n, r in notify.send(ev, f"{res['name']} {D} 没有出片", "；".join(res["problems"])[:500], channel=a.channel):
                print(f"通知 {n}：{r}")
        sys.exit(code)

    if a.push_only:  # 推送上一次（不带 --push）出好的片子
        try:
            prev = json.load(open(os.path.join(W, "结果.json"), encoding="utf-8"))
        except Exception:
            prev = {}
        out = os.path.join(W, "out.mp4")
        if prev.get("ok") is not True or not os.path.exists(out):
            res["problems"].append(f"{W} 里没有成功出好的片子：先不带 --push 运行一次，看过检查帧再用 --push-only")
            finish(2)
        res.update({k: prev[k] for k in ("duration", "frames", "title", "voice", "footage") if k in prev})
        res["warnings"] = prev.get("warnings", [])
        a.push = True
        push_and_notify(a, res, W, D, out, finish)
    if early:
        res["problems"] += early
        finish(2)
    if not str(data.get("ask", "")).strip():
        res["warnings"].append("没有 ask（互动问题）：结尾只请关注，评论会少")
    try:
        # 1. 配音 + 画面工程 + 文案 + 发布信息
        proj = os.path.join(W, "proj")
        shutil.rmtree(proj, ignore_errors=True)
        print("① 配音、生成画面工程……（CosyVoice 较慢，请耐心等待）", flush=True)
        r = sh([sys.executable, os.path.join(HERE, "gen_hf.py"), "script.json", "proj"], cwd=W)
        log = r.stdout + r.stderr
        print("\n".join(l for l in log.splitlines() if re.match(r"(配音|分镜|提醒|工程|抖音文案|清晰度)", l.strip())))
        for l in log.splitlines():
            if l.startswith("提醒："):
                (res["problems"] if ("没念清楚" in l or "请把 say 删短" in l or "多出了" in l) else res["warnings"]).append(l[3:])
        rep = os.path.join(W, "配音检查.json")
        if os.path.exists(rep):
            res["voice"] = json.load(open(rep, encoding="utf-8"))
        cap = open(os.path.join(W, "抖音文案.txt"), encoding="utf-8").read()
        if len(cap) > 1000:
            res["problems"].append(f"文案 {len(cap)} 字，超过抖音约 1000 字的上限：把 detail 写短")

        # 2. 渲染前检查
        hf = os.path.join(HERE, "node_modules", ".bin", "hyperframes")
        r = sh([hf, "lint"], cwd=proj, check=False)
        m = re.search(r"(\d+) error", r.stdout + r.stderr)
        if not m or int(m[1]) > 0:
            res["problems"].append("渲染前检查有错误：\n" + (r.stdout + r.stderr).strip()[-1500:])
        if res["problems"]:
            finish(2)

        # 3. 渲染、时长、抽帧
        print("② 渲染视频……", flush=True)
        out = os.path.join(W, "out.mp4")
        sh([hf, "render", "--quality", "looks", "-o", out], cwd=proj)
        dur = duration(out)
        res["duration"] = round(dur, 1)
        lim = float(S.get("max_seconds", 90))
        if dur > lim + 3:
            res["problems"].append(f"成片 {dur:.0f} 秒，超过频道上限 {lim:.0f} 秒：把 say 删短（语速是固定的）")
            finish(2)
        res["frames"] = frames(out, proj, os.path.join(W, "frames"), dur)
        print("③ 检查帧（请逐张查看：中文正常、标题没被切断、左上角有「内容由AI生成」、图表地图和口播一致）：")
        for f in res["frames"]:
            print("   " + f)

        try:
            res["footage"] = json.load(open(os.path.join(proj, "素材.json"), encoding="utf-8"))
        except Exception:
            pass
        if res.get("footage"):
            print("   有实拍画面：文件名带「实拍」的检查帧，要逐张核对画面内容和这一段口播说的是不是一回事")
        res["ok"] = True

        # 4. 推送
        push_and_notify(a, res, W, D, out, finish)
    except SystemExit:
        raise
    except Exception as e:
        res["problems"].append(str(e))
        finish(1)


if __name__ == "__main__":
    main()
