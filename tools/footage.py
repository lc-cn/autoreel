"""自影 · 实拍素材：按关键词从 Pexels / Pixabay 取免版权视频，整理成 1080×1920 竖屏片段。

密钥从环境变量读取（不要写进仓库）：PIXABAY_API_KEY（推荐，免费申请）；PEXELS_API_KEY（Pexels 已停止发放新密钥，有旧密钥的可以继续用），有一个即可。
两家素材都可免费商用、无需署名（以各自许可为准）；我们仍在发布文案末尾注明「画面素材：Pexels / Pixabay」。

用法（被 gen_hf.py 调用）：
    fetch(query, seconds, out_path, cache_dir) -> {"path", "source", "author", "url"} 或 None（找不到 / 没有密钥）
"""
import hashlib
import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request

UA = {"User-Agent": "ziying-autoreel/1.0"}


def _get(url, headers=None, timeout=30):
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _pexels(query, seconds):
    key = os.environ.get("PEXELS_API_KEY")
    if not key:
        return []
    q = urllib.parse.urlencode({"query": query, "orientation": "portrait", "size": "medium", "per_page": 15})
    data = json.loads(_get(f"https://api.pexels.com/videos/search?{q}", {"Authorization": key}))
    out = []
    for v in data.get("videos", []):
        files = [f for f in v.get("video_files", []) if f.get("height", 0) >= 1280 and f.get("width", 0) < f.get("height", 0)]
        files.sort(key=lambda f: abs(f.get("height", 0) - 1920))
        if files:
            out.append({"src": files[0]["link"], "dur": v.get("duration", 0), "source": "Pexels",
                        "author": (v.get("user") or {}).get("name", ""), "url": v.get("url", "")})
    return out


def _pixabay(query, seconds):
    key = os.environ.get("PIXABAY_API_KEY")
    if not key:
        return []
    q = urllib.parse.urlencode({"key": key, "q": query, "per_page": 20, "safesearch": "true"})
    data = json.loads(_get(f"https://pixabay.com/api/videos/?{q}"))
    out = []
    for v in data.get("hits", []):
        vids = v.get("videos", {})
        f = next((vids[k] for k in ("large", "medium") if vids.get(k, {}).get("url") and vids[k].get("height", 0) >= 1080), None)
        if f:
            out.append({"src": f["url"], "dur": v.get("duration", 0), "source": "Pixabay", "author": v.get("user", ""),
                        "url": v.get("pageURL", ""), "portrait": f.get("height", 0) > f.get("width", 0)})
    out.sort(key=lambda x: not x.get("portrait"))  # 竖屏优先
    return out


def _normalize(src, seconds, out):
    """裁成 1080×1920、截取需要的长度、去掉原声；素材比镜头短就放慢补足（最多放慢到 0.6 倍）。"""
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", src],
                               capture_output=True, text=True).stdout.strip() or 0)
    slow = 1.0 if dur >= seconds or dur <= 0 else max(0.6, dur / seconds)
    vf = f"setpts=PTS/{slow:.3f}," if slow < 1 else ""
    vf += "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps=30"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", src, "-t", f"{seconds:.2f}", "-an", "-vf", vf,
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "24", "-pix_fmt", "yuv420p", "-g", "15", out], check=True)
    return out


def fetch(query, seconds, out_path, cache_dir):
    if not query:
        return None
    fake = os.environ.get("AUTOREEL_FAKE_FOOTAGE")  # 仅用于测试：用本地视频代替网络素材
    if fake:
        _normalize(fake, seconds, out_path)
        return {"source": "本地测试素材", "author": "", "url": "", "path": out_path}
    os.makedirs(cache_dir, exist_ok=True)
    tag = hashlib.md5(f"{query}|{seconds:.1f}".encode()).hexdigest()[:12]
    cached = os.path.join(cache_dir, f"{tag}.mp4")
    meta_f = cached + ".json"
    if os.path.exists(cached) and os.path.exists(meta_f):
        _copy(cached, out_path)
        return {**json.load(open(meta_f)), "path": out_path}
    for finder in (_pexels, _pixabay):
        try:
            cands = finder(query, seconds)
        except Exception as e:
            print(f"素材：{finder.__name__[1:]} 搜索「{query}」失败：{e}", file=sys.stderr)
            continue
        cands.sort(key=lambda c: c["dur"] < seconds)  # 够长的优先
        for c in cands[:3]:
            raw = cached + ".raw"
            try:
                open(raw, "wb").write(_get(c["src"], timeout=120))
                _normalize(raw, seconds, cached)
                info = {k: c[k] for k in ("source", "author", "url")}
                json.dump(info, open(meta_f, "w"), ensure_ascii=False)
                _copy(cached, out_path)
                print(f"素材：「{query}」← {c['source']} · {c['author']}", file=sys.stderr)
                return {**info, "path": out_path}
            except Exception as e:
                print(f"素材：下载或处理失败（{e}），换下一个", file=sys.stderr)
            finally:
                if os.path.exists(raw):
                    os.remove(raw)
    return None


def _copy(a, b):
    os.makedirs(os.path.dirname(b), exist_ok=True)
    with open(a, "rb") as f, open(b, "wb") as g:
        g.write(f.read())


def available():
    return bool(os.environ.get("PEXELS_API_KEY") or os.environ.get("PIXABAY_API_KEY") or os.environ.get("AUTOREEL_FAKE_FOOTAGE"))
