#!/usr/bin/env python3
"""
把技能仓库发布到 GitHub。

凭据来源（按优先级）:
  1. 环境变量 GITHUB_TOKEN / GH_TOKEN
  2. 同目录 .pat 文件（已在 .gitignore 中，不会入库）

需要的 PAT 权限: repo + admin:public_key（classic）
                或 fine-grained 的 Contents:write + Administration:public keys:write

用法:
  python publish_github.py                 # 默认仓库名 wechat-channels-downloader
  python publish_github.py --name my-repo  # 自定义
  python publish_github.py --private       # 私有仓库
"""

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
API = "https://api.github.com"
DEFAULT_DESC = "微信视频号视频下载器：把 sph 分享链接解析为明文 mp4，支持批量；同时是一个 Agent Skill"


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
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            raw = r.read().decode() or "{}"
            return r.status, json.loads(raw)
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except Exception:
            return e.code, {}


def sh(cmd, check=True):
    r = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"命令失败: {' '.join(cmd)}\n{r.stderr.strip()}")
    return r


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="wechat-channels-downloader")
    ap.add_argument("--desc", default=DEFAULT_DESC)
    ap.add_argument("--private", action="store_true")
    args = ap.parse_args()

    tok = get_token()
    if not tok:
        print("没找到 PAT。请任选一种方式提供：\n"
              f"  A) 新建文件 {HERE / '.pat'}，只写 token 一行\n"
              "  B) 设置环境变量 GITHUB_TOKEN")
        return 2

    # 1. 校验身份
    code, me = api("GET", "/user", tok)
    if code != 200:
        print(f"PAT 无效或权限不足 (HTTP {code}): {me.get('message')}")
        return 1
    login = me["login"]
    log(f"身份确认: {login}")

    # 2. 本地 git 身份（只作用于本仓库）
    email = me.get("email") or f"{login}@users.noreply.github.com"
    sh(["git", "config", "user.name", login])
    sh(["git", "config", "user.email", email])
    sh(["git", "branch", "-M", "main"], check=False)
    log(f"git 身份: {login} <{email}>")

    # 3. 提交
    staged = sh(["git", "status", "--porcelain"]).stdout.strip()
    if staged:
        sh(["git", "add", "-A"])
        sh(["git", "commit", "-m", "feat: 微信视频号视频下载器（sph 链接 -> 明文 mp4）"])
        log("已创建初始提交")
    else:
        log("工作区已干净，跳过提交")

    # 4. 创建仓库（已存在则复用）
    code, repo = api("POST", "/user/repos", tok, {
        "name": args.name,
        "description": args.desc,
        "private": bool(args.private),
        "has_issues": True,
        "has_wiki": False,
        "auto_init": False,
    })
    if code == 201:
        log(f"仓库已创建: {repo['html_url']}")
    elif code == 422:
        log(f"仓库已存在，复用: https://github.com/{login}/{args.name}")
    else:
        print(f"创建仓库失败 (HTTP {code}): {repo.get('message')}")
        return 1

    # 5. 添加 SSH 公钥（HTTPS 在本机不通，必须走 SSH）
    pub_path = Path.home() / ".ssh" / "id_ed25519.pub"
    if not pub_path.exists():
        print(f"缺少 SSH 公钥 {pub_path}，请先运行 ssh-keygen")
        return 1
    pub = pub_path.read_text(encoding="utf-8").strip()

    code, keys = api("GET", "/user/keys", tok)
    already = False
    if code == 200 and isinstance(keys, list):
        already = any(k.get("key", "").split()[:2] == pub.split()[:2] for k in keys)
    if already:
        log("SSH 公钥已存在于账号中")
    else:
        code, res = api("POST", "/user/keys", tok, {"title": "wxdl-skill", "key": pub})
        if code == 201:
            log("SSH 公钥已添加到 GitHub")
        else:
            print(f"添加公钥失败 (HTTP {code}): {res.get('message')}")
            print("提示: classic PAT 需要勾选 admin:public_key；fine-grained 需 "
                  "'Administration: public keys' 写权限。")
            print("若你无法重新生成 PAT，可手动把下面的公钥贴到 GitHub 设置里，再重跑本脚本：")
            print(f"  {pub}")
            return 1

    # 6. 配置 remote 并推送
    ssh_url = f"git@github.com:{login}/{args.name}.git"
    sh(["git", "remote", "remove", "origin"], check=False)
    sh(["git", "remote", "add", "origin", ssh_url])
    sh(["git", "config", "core.sshCommand", "ssh -o StrictHostKeyChecking=accept-new"])

    log("推送到 GitHub（走 SSH）…")
    r = sh(["git", "push", "-u", "origin", "main"], check=False)
    if r.returncode != 0:
        print(f"推送失败:\n{r.stderr.strip()[:800]}")
        return 1

    print(f"\n完成: https://github.com/{login}/{args.name}")
    print(f"RESULT_URL https://github.com/{login}/{args.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
