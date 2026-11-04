# 微信视频号视频下载器

把视频号的 `sph` 分享链接解析成腾讯 CDN 上的**明文 mp4** 并下载到本地。

不需要抓包、不安装系统根证书、不修改系统代理、不需要微信扫码登录。

> 本仓库同时是一个 **Agent Skill**，可直接放进 `~/.workbuddy/skills/` 供 AI 助手自动调用。

## 原理

视频号没有公开下载接口，但分享链接可以被换成带时效签名的播放凭证：

```
sph 分享链接
   │
   ├─(1) 元宝解析接口 ──> wx_export_id + playable_url(内含 token / eid)
   │
   ├─(2) 视频号 feed 接口 ──> feedInfo.h264VideoInfo.videoUrl
   │
   └─(3) CDN 直连 ──> finder.video.qq.com 上的明文 mp4（无需解密）
```

第 1 步在浏览器上下文里发起，需要携带元宝的匿名 cookie；第 2 步必须带 `Origin` 头，
且 `exportId` 要用 `playable_url` 里的 `eid`（约 65 字符），**不是** `wx_export_id`（约 57 字符）——
用错会返回「此内容暂时无法播放」。

## 安装

```bash
python -m pip install -i https://mirrors.aliyun.com/pypi/simple/ playwright
```

只用系统已有的 Edge / Chrome（`channel="msedge"`），**不需要** `playwright install` 下载浏览器内核。

首次运行会生成 `.browser-profile/`（浏览器配置目录）。元宝接口用匿名 cookie 即可解析。

## 用法

```bash
python scripts/wxdl.py "https://weixin.qq.com/sph/AY2J9RANu0"
python scripts/wxdl.py "链接1" "链接2" "链接3"
python scripts/wxdl.py --file urls.txt
python scripts/wxdl.py AY2J9RANu0 --codec h265 --output-dir "D:/素材"
```

| 参数 | 说明 |
|---|---|
| `--output-dir DIR` | 输出目录，默认 `~/Downloads/视频号下载` |
| `--codec h264` | 默认。同分辨率码率更高，剪映 / PR / 网页兼容性好 |
| `--codec h265` | 体积小约 30%，但部分 Windows 播放器缺解码器会黑屏 |
| `--file urls.txt` | 批量，每行一个链接，`#` 开头为注释 |

输入支持三种形态：

- `https://weixin.qq.com/sph/XXXXXXXX`
- `https://channels.weixin.qq.com/finder-preview/pages/sph?id=XXXXXXXX`
- 裸 ID：`XXXXXXXX`

## 输出

```
<作者>_<描述前50字>.mp4     完整明文 mp4，ftyp 头已校验
<作者>_<描述前50字>.json    作者、原文案、分辨率、码率、时长、来源链接
```

脚本结束会打印清晰度分档（`1080p 及以上` / `720p` / `xxxp(非高清)`）。
分档按 `min(width, height)` 判断，竖屏视频不会误判。

## 已知限制

- **清晰度由平台决定**，接口只返回一档，没有档位选择参数。URL 里的 `X-snsvideoflag`、
  `basedata` 均带 `sign` 签名，改参必然失效。实测普通账号内容常见上限为 576p / 720p。
- 付费、会员专享、私密、已删除内容无法解析。
- 播放凭证有效期约数天，脚本每次都重新解析，无感。
- 平台接口可能随时变更，失效时请对照 `SKILL.md` 里的排错表排查。

## 免责声明

本项目仅供技术研究与**个人合法用途**：下载本人作品、已获授权的内容，或做竞品内容结构分析。

- 请勿用于侵犯他人著作权、批量搬运、二次分发。
- 下载他人内容前须取得权利人许可，相关法律责任由使用者自行承担。
- 请遵守微信 / 腾讯的服务条款，不要高频请求。

## License

MIT
