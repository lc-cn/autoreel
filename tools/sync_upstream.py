"""自影 · 从上游模板同步更新（你的仓库是用 Use this template 建的，和上游没有共同历史，不能直接 git merge）

用法（在你的仓库根目录运行）：
    python3 tools/sync_upstream.py            # 预览会改什么，不写文件
    python3 tools/sync_upstream.py --apply    # 执行同步（只改工作区，不提交；看过 git diff 再自己提交）
    可选：--repo lc-cn/autoreel --ref master

同步规则：
  框架代码（tools/ extension/ .claude/skills/ docs/ prompts/ assets/ README 等）  用上游版本覆盖；
                                                 上游删掉的文件这里也删掉（tools/voices/ 下你自己加的音色除外）
  autoreel.config.json、channels/*/channel.json  只补上游新增的字段，你已有的值一个都不改
  channels/*/brief.md、inputs/、你自己的频道      完全不碰
  上游新增的频道                                 复制过来，但不会自动启用（要用就加进 config 的 channels）；
                                                 你删掉的内置频道不会被加回来
上次同步到的上游版本和频道列表记在 .autoreel-upstream 里。
"""
import argparse
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRAMEWORK = ["tools/", "extension/", ".claude/skills/autoreel/", ".claude/skills/autoreel-channel/", ".claude/skills/autoreel-setup/",
             "docs/", "prompts/", "schedulers/", "assets/", "AGENTS.md", "README.md", "THIRD_PARTY_NOTICES.md", "LICENSE", ".gitignore"]
KEEP_EXTRA = ["tools/voices/"]  # 本地多出来的文件不删（你自己加的音色）
STAMP = ".autoreel-upstream"


def git(*args, binary=False):
    r = subprocess.run(["git", "-C", ROOT, *args], capture_output=True)
    if r.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} 失败：{r.stderr.decode(errors='replace').strip()}")
    return r.stdout if binary else r.stdout.decode()


def merge_missing(mine, theirs, path, added):
    """把 theirs 里 mine 没有的键补进 mine（递归），返回是否有改动。"""
    changed = False
    for k, v in theirs.items():
        if k not in mine:
            mine[k] = v
            added.append(f"{path}.{k}")
            changed = True
        elif isinstance(mine[k], dict) and isinstance(v, dict):
            changed |= merge_missing(mine[k], v, f"{path}.{k}", added)
    return changed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default="lc-cn/autoreel")
    ap.add_argument("--ref", default="master")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    if git("status", "--porcelain").strip() and a.apply:
        raise SystemExit("工作区有没提交的改动，先提交或暂存再同步。")
    git("fetch", "-q", "--depth=1", f"https://github.com/{a.repo}.git", a.ref)
    up = git("rev-parse", "FETCH_HEAD").strip()
    stamp = {}
    if os.path.exists(os.path.join(ROOT, STAMP)):
        try:
            stamp = json.load(open(os.path.join(ROOT, STAMP)))
        except Exception:
            stamp = {}
    last = stamp.get("commit", "")
    print(f"上游 {a.repo}@{a.ref}：{up[:7]}" + (f"（上次同步 {last[:7]}）" if last else "（第一次同步）"))
    if up == last:
        print("已经是最新，不用同步。")
        return

    theirs = set(git("ls-tree", "-r", "--name-only", "FETCH_HEAD").splitlines())
    mine = set(git("ls-files").splitlines())
    in_fw = lambda f: any(f == p or f.startswith(p) for p in FRAMEWORK)
    plan = {"更新": [], "新增": [], "删除": [], "补字段": [], "新频道": []}

    def blob(f):
        return git("show", f"FETCH_HEAD:{f}", binary=True)

    writes = {}
    for f in sorted(theirs):
        if in_fw(f):
            data = blob(f)
            local = os.path.join(ROOT, f)
            if not os.path.exists(local):
                plan["新增"].append(f); writes[f] = data
            elif open(local, "rb").read() != data:
                plan["更新"].append(f); writes[f] = data
    for f in sorted(mine - theirs):
        if in_fw(f) and not any(f.startswith(p) for p in KEEP_EXTRA):
            plan["删除"].append(f)

    # 配置：只补字段
    json_writes = {}
    cfgs = ["autoreel.config.json"] + sorted(f for f in theirs if f.startswith("channels/") and f.endswith("/channel.json"))
    for f in cfgs:
        local = os.path.join(ROOT, f)
        if not os.path.exists(local):
            continue
        m, t, added = json.load(open(local, encoding="utf-8")), json.loads(blob(f)), []
        if merge_missing(m, t, f, added):
            plan["补字段"] += added
            json_writes[f] = m
    # 新频道：上游这次新加的才复制（你删掉的内置频道不会被加回来；第一次同步不加），不启用
    up_ch = {f.split("/")[1] for f in theirs if f.startswith("channels/") and f.count("/") >= 2}
    known = set(stamp.get("channels", up_ch))
    for ch in sorted(up_ch - known):
        if not os.path.isdir(os.path.join(ROOT, "channels", ch)):
            plan["新频道"].append(ch)
            for f in theirs:
                if f.startswith(f"channels/{ch}/") or f.startswith(f"inputs/{ch}/"):
                    writes[f] = blob(f)

    for k, v in plan.items():
        if v:
            print(f"\n{k}（{len(v)}）：")
            for x in v[:40]:
                print("  " + x)
            if len(v) > 40:
                print(f"  ……还有 {len(v) - 40} 个")
    ext_changed = any(f.startswith("extension/") for f in plan["更新"] + plan["新增"] + plan["删除"])
    if not a.apply:
        print("\n这是预览，没有改任何文件。确认后加 --apply 执行。")
        return

    for f, data in writes.items():
        p = os.path.join(ROOT, f)
        os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
        open(p, "wb").write(data)
    for f in plan["删除"]:
        os.remove(os.path.join(ROOT, f))
    for f, m in json_writes.items():
        with open(os.path.join(ROOT, f), "w", encoding="utf-8") as fh:
            json.dump(m, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
    json.dump({"repo": a.repo, "commit": up, "channels": sorted(up_ch)}, open(os.path.join(ROOT, STAMP), "w"), ensure_ascii=False, indent=1)
    print(f"\n已同步到 {up[:7]}。用 git diff 看一遍，没问题就提交：")
    print(f'  git add -A && git commit -m "同步自影上游 {up[:7]}" && git push')
    if plan["新频道"]:
        print("新频道没有启用，要用的话加进 autoreel.config.json 的 channels。")
    if ext_changed:
        print("⚠️ 浏览器插件有更新：重新下载 extension/ 文件夹替换本地的，然后在 chrome://extensions 里点插件的「重新加载」。")


if __name__ == "__main__":
    sys.exit(main())
