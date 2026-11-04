#!/usr/bin/env python3
"""
微信视频号视频下载器

用法:
  python wxdl.py <url|id> [<url|id> ...]
  python wxdl.py --file urls.txt
  python wxdl.py <url> --output-dir "D:/素材" --codec h265

支持的输入:
  https://weixin.qq.com/sph/AY2J9RANu0
  https://channels.weixin.qq.com/finder-preview/pages/sph?id=AY2J9RANu0
  AY2J9RANu0                                    (裸 ID)

链路:
  1. 元宝 get_parse_result  : sph 链接 -> wx_export_id + playable_url(token/eid)
  2. 视频号 get_feed_info   : token/eid -> feedInfo(h264/h265 videoUrl)
  3. CDN 直连下载           : finder.video.qq.com 明文 mp4

依赖: playwright (复用系统 Edge，无需 playwright install)
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0"
)
SKILL_DIR = Path(__file__).resolve().parent.parent
PROFILE = SKILL_DIR / ".browser-profile"
YUANBAO_HOME = "https://yuanbao.tencent.com/"
FEED_API = "https://channels.weixin.qq.com/finder-preview/api/feed/get_feed_info"


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def normalize(raw: str) -> str | None:
    """把各种形态的输入归一成 weixin.qq.com/sph/<id>。"""
    s = raw.strip().strip('"\'',).strip()
    if not s:
        return None
    m = re.search(r"/sph/([A-Za-z0-9_-]{6,})", s)
    if m:
        return f"https://weixin.qq.com/sph/{m.group(1)}"
    m = re.search(r"[?&]id=([A-Za-z0-9_-]{6,})", s)
    if m:
        return f"https://weixin.qq.com/sph/{m.group(1)}"
    if re.fullmatch(r"[A-Za-z0-9_-]{6,}", s):
        return f"https://weixin.qq.com/sph/{s}"
    return None


def yuanbao_parse(page, share_url: str) -> dict:
    """在元宝页面上下文里发请求，自动带登录 cookie；导航中断时返回空。"""
    try:
        raw = page.evaluate(
            """async (u) => {
                const r = await fetch('https://yuanbao.tencent.com/api/weixin/get_parse_result', {
                    method: 'POST',
                    headers: {'content-type': 'application/json'},
                    body: JSON.stringify({type: 'video_channel_url', url: u, scene: 1})
                });
                return await r.text();
            }""",
            share_url,
        )
        return json.loads(raw)
    except Exception:
        return {}


def feed_info(token: str, export_id: str) -> dict:
    req = urllib.request.Request(
        FEED_API,
        data=json.dumps({"baseReq": {"generalToken": token}, "exportId": export_id}).encode(),
        headers={
            "Content-Type": "application/json",
            "User-Agent": UA,
            # Origin 必须带，否则 401
            "Referer": "https://channels.weixin.qq.com/finder-preview/pages/sph",
            "Origin": "https://channels.weixin.qq.com",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8", "ignore"))


def pick_url(info: dict, codec: str) -> str | None:
    """按偏好挑视频地址，失败时回退其它编码。"""
    order = ["h265", "h264"] if codec == "h265" else ["h264", "h265"]
    for c in order:
        node = info.get(f"{c}VideoInfo") or {}
        u = node.get("videoUrl")
        if isinstance(u, str) and u.startswith("http"):
            return u
    u = info.get("videoUrl")
    return u if isinstance(u, str) and u.startswith("http") else None


def download(url: str, dest: Path) -> int:
    req = urllib.request.Request(
        url, headers={"User-Agent": UA, "Referer": "https://channels.weixin.qq.com/", "Accept": "*/*"}
    )
    total = 0
    last = 0
    with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as f:
        while True:
            chunk = r.read(256 * 1024)
            if not chunk:
                break
            f.write(chunk)
            total += len(chunk)
            if total - last >= 10 * 1048576:
                log(f"    {total / 1048576:.1f} MB …")
                last = total
    return total


def probe(path: Path) -> dict:
    """用 ffprobe 读真实规格；没有 ffprobe 时返回空。"""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=codec_name,width,height,bit_rate",
             "-show_entries", "format=duration", "-of", "json", str(path)],
            capture_output=True, text=True, timeout=30,
        ).stdout
        j = json.loads(out)
        st = (j.get("streams") or [{}])[0]
        dur = float((j.get("format") or {}).get("duration") or 0)
        return {
            "codec": st.get("codec_name"),
            "width": st.get("width"),
            "height": st.get("height"),
            "bitrate_kbps": round(int(st.get("bit_rate") or 0) / 1000) or None,
            "duration_sec": round(dur, 1) if dur else None,
        }
    except Exception:
        return {}


def safe_name(author: str, desc: str) -> str:
    s = re.sub(r"[\\/:*?\"<>|#\s]+", "_", f"{author}_{desc}")
    s = re.sub(r"[，。！？、；：（）【】《》「」“”‘’·～~]+", "", s)
    s = re.sub(r"_{2,}", "_", s).strip("._")
    return s[:50] or "video"


def default_out_dir() -> Path:
    d = Path.home() / "Downloads" / "视频号下载"
    try:
        d.mkdir(parents=True, exist_ok=True)
        return d
    except Exception:
        return Path.cwd()


def run_one(page, share_url: str, out_dir: Path, codec: str) -> dict:
    log(f"解析 {share_url}")
    data = {}
    for attempt in range(3):
        resp = yuanbao_parse(page, share_url)
        data = resp.get("data") or {}
        if data.get("wx_export_id"):
            break
        time.sleep(1.5)

    if not data.get("wx_export_id"):
        err = json.dumps(resp, ensure_ascii=False)[:200] if resp else "(空响应)"
        return {"ok": False, "url": share_url, "error": f"元宝解析失败: {err}"}

    playable = data.get("playable_url") or ""
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(playable).query)
    token = (qs.get("token") or [""])[0]
    # 关键: exportId 必须是 playable_url 里的 eid，不是 wx_export_id
    export_id = (qs.get("eid") or [""])[0] or data.get("wx_export_id")

    try:
        feed = feed_info(token, export_id)
    except urllib.error.HTTPError as e:
        return {"ok": False, "url": share_url, "error": f"feed 接口 HTTP {e.code}"}

    info = (feed.get("data") or {}).get("feedInfo") or {}
    if not info:
        emsg = (feed.get("data") or {}).get("errMsg") or feed.get("errMsg")
        return {"ok": False, "url": share_url, "error": f"无 feedInfo: {emsg}"}

    video_url = pick_url(info, codec)
    if not video_url:
        return {"ok": False, "url": share_url, "error": "未找到视频直链"}

    author = ((feed.get("data") or {}).get("authorInfo") or {}).get("nickname") or ""
    desc = (info.get("description") or "").strip()
    dest = out_dir / f"{safe_name(author, desc)}.mp4"
    if dest.exists():
        dest = out_dir / f"{dest.stem}_{int(time.time())%10000}.mp4"

    log(f"下载 -> {dest.name}")
    try:
        size = download(video_url, dest)
    except Exception as e:
        return {"ok": False, "url": share_url, "error": f"下载失败: {e}"}

    head = dest.open("rb").read(12)
    if not (len(head) >= 8 and head[4:8] == b"ftyp"):
        return {"ok": False, "url": share_url, "error": f"文件头异常: {dest}"}

    spec = probe(dest)
    meta = {
        "share_url": share_url,
        "author": author,
        "description": desc,
        "file": str(dest),
        "size_mb": round(size / 1048576, 2),
        **spec,
        "downloaded_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    (dest.with_suffix(".json")).write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    # 竖屏视频要按短边判档位，否则 576x1024 会被误判成 720p
    w = spec.get("width") or 0
    h = spec.get("height") or 0
    short = min(w, h) if w and h else 0
    tier = ("1080p 及以上" if short >= 1080
            else "720p" if short >= 720
            else f"{short}p(非高清)")
    log(f"完成 {size / 1048576:.2f} MB  {spec.get('width')}x{spec.get('height')} "
        f"{spec.get('codec')} {spec.get('bitrate_kbps')}kbps  [{tier}]")
    return {"ok": True, **meta, "tier": tier}


def main() -> int:
    ap = argparse.ArgumentParser(description="微信视频号视频下载")
    ap.add_argument("targets", nargs="*", help="sph 链接 / channels 链接 / 裸 ID")
    ap.add_argument("--file", help="从文本文件读取，每行一个链接")
    ap.add_argument("--output-dir", default=None, help="输出目录（默认 ~/Downloads/视频号下载）")
    ap.add_argument("--codec", choices=["h264", "h265"], default="h264",
                    help="优先编码，默认 h264（兼容剪辑软件，同分辨率码率更高）")
    args = ap.parse_args()

    raw_items = list(args.targets)
    if args.file:
        raw_items += [
            ln for ln in Path(args.file).read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.strip().startswith("#")
        ]
    if not raw_items:
        print("用法: python wxdl.py <sph链接> [更多链接...]")
        return 2

    links = []
    for it in raw_items:
        n = normalize(it)
        if n:
            links.append(n)
        else:
            log(f"跳过无法识别的输入: {it[:60]}")
    if not links:
        print("没有可用链接。")
        return 2

    out_dir = Path(args.output_dir).expanduser() if args.output_dir else default_out_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    log(f"共 {len(links)} 条，输出到 {out_dir}")

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("缺少 playwright，请先执行: "
              "python -m pip install -i https://mirrors.aliyun.com/pypi/simple/ playwright")
        return 3

    results = []
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(PROFILE), channel="msedge", headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            page.goto(YUANBAO_HOME, wait_until="load", timeout=60000)
            page.wait_for_timeout(1500)
        except Exception:
            pass

        for i, link in enumerate(links, 1):
            log(f"--- [{i}/{len(links)}] ---")
            try:
                results.append(run_one(page, link, out_dir, args.codec))
            except Exception as e:
                results.append({"ok": False, "url": link, "error": f"{type(e).__name__}: {e}"})
        ctx.close()

    ok = [r for r in results if r.get("ok")]
    bad = [r for r in results if not r.get("ok")]
    print("\n=== 汇总 ===")
    for r in ok:
        print(f"[OK] {Path(r['file']).name}  {r.get('width')}x{r.get('height')} {r.get('size_mb')}MB")
    for r in bad:
        print(f"[FAIL] {r['url']}  {r.get('error')}")
    print(f"\n成功 {len(ok)} / 失败 {len(bad)}   目录: {out_dir}")

    if ok:
        print("\nRESULT_JSON " + json.dumps({"saved": [r["file"] for r in ok]}, ensure_ascii=False))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
