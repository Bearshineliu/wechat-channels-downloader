#!/usr/bin/env python3
"""
通过 GitHub Contents API 上传文件（绕开 git push，适用于本机 github.com:443 不通、仅有 api 可达的环境）。

只上传 git 已跟踪的文件，天然排除 .browser-profile / downloads。

用法:
  GITHUB_TOKEN=xxx python publish_via_api.py
  GITHUB_TOKEN=xxx python publish_via_api.py --repo Bearshineliu/wechat-channels-downloader
"""

import argparse
import base64
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
API = "https://api.github.com"


def log(m):
    print(f"[*] {m}", flush=True)


def get_token() -> str:
    for k in ("GITHUB_TOKEN", "GH_TOKEN"):
        if os.environ.get(k):
            return os.environ[k].strip()
    p = HERE / ".pat"
    if p.exists():
        return p.read_text(encoding="utf-8").strip()
    return ""


def api(method, path, tok, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        API + path, data=data, method=method,
        headers={
            "Authorization": f"token {tok}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "wxdl-publish",
            "Content-Type": "application/json",
        })
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except Exception:
            return e.code, {}


def tracked_files() -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=HERE, capture_output=True, text=True).stdout
    return [ln.strip() for ln in out.splitlines() if ln.strip()]


def get_sha(repo, path, tok) -> str | None:
    code, res = api("GET", f"/repos/{repo}/contents/{path}", tok)
    if code == 200 and isinstance(res, dict):
        return res.get("sha")
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=None, help="owner/name")
    args = ap.parse_args()

    tok = get_token()
    if not tok:
        print("缺 PAT")
        return 2

    code, me = api("GET", "/user", tok)
    if code != 200:
        print(f"PAT 无效 (HTTP {code})")
        return 1
    login = me["login"]

    repo = args.repo or f"{login}/{HERE.name}"
    files = tracked_files()
    if not files:
        print("没有可上传的文件")
        return 2

    log(f"仓库 {repo}，共 {len(files)} 个文件")

    # 确认默认分支
    code, info = api("GET", f"/repos/{repo}", tok)
    if code != 200:
        print(f"仓库不可访问 (HTTP {code}): {info.get('message')}")
        return 1
    branch = info.get("default_branch") or "main"
    log(f"默认分支: {branch}")

    ok, bad = 0, []
    for rel in files:
        p = HERE / rel
        if not p.is_file():
            continue
        raw = p.read_bytes()
        body = {
            "message": f"add {rel}",
            "content": base64.b64encode(raw).decode(),
            "branch": branch,
        }
        existing = get_sha(repo, rel, tok)
        if existing:
            body["sha"] = existing
        code, res = api("PUT", f"/repos/{repo}/contents/{rel}", tok, body)
        if code in (200, 201):
            ok += 1
            log(f"  ✓ {rel} ({len(raw)} B)")
        else:
            bad.append((rel, code, res.get("message")))
            log(f"  ✗ {rel} HTTP {code} {res.get('message')}")

    print(f"\n上传完成 {ok} 个，失败 {len(bad)} 个")
    print(f"RESULT_URL https://github.com/{repo}")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
