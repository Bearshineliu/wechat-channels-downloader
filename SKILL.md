---
name: wechat-channels-downloader
description: 下载微信视频号视频为本地 mp4。当用户提供 weixin.qq.com/sph/... 或 channels.weixin.qq.com/finder-preview 链接，或直接给视频号 ID，要求下载/保存/导出/扒下视频号视频时使用。也适用于批量下载多条视频号链接、查询视频号视频真实分辨率与码率。
---

# 微信视频号视频下载

把 `sph` 分享链接解析成腾讯 CDN 上的明文 mp4 并落盘。**无需抓包、不装系统根证书、不改系统代理、不需要微信扫码登录。**

## 何时使用

- 用户发来 `https://weixin.qq.com/sph/xxxx` 或 `channels.weixin.qq.com/finder-preview/pages/sph?id=xxx`，并要下载视频
- 用户给一个裸 ID（如 `AY2J9RANu0`）要求下载
- 批量下载多条视频号链接
- 需要确认某条视频号视频的真实分辨率/码率（是否高清）

## 怎么用

```bash
python <skill_dir>/scripts/wxdl.py "https://weixin.qq.com/sph/AY2J9RANu0"
```

批量：

```bash
python <skill_dir>/scripts/wxdl.py "链接1" "链接2" "链接3"
python <skill_dir>/scripts/wxdl.py --file urls.txt
```

可选参数：

| 参数 | 说明 |
|---|---|
| `--output-dir DIR` | 输出目录，默认 `~/Downloads/视频号下载` |
| `--codec h264` | 默认。同分辨率码率更高，剪映/PR/网页兼容性好 |
| `--codec h265` | 体积更小（约小 30%），但部分 Windows 播放器缺解码器会黑屏 |

**默认用 h264**，因为用户多半是要剪辑。若用户只要存档省空间，改 `--codec h265`。

脚本结束会打印 `RESULT_JSON {...}`，用于取回生成的文件路径。之后用 `present_files` 把 mp4 展示给用户。

## 输出

- `<作者>_<描述前50字>.mp4` —— 完整明文 mp4，`ftyp` 头校验通过
- 同名 `.json` —— 作者、原文案、分辨率、码率、时长、来源链接、下载时间
- 脚本会打印清晰度分档：`1080p 及以上` / `720p` / `XXXp(非高清)`

## 解析链路（原理）

1. `POST https://yuanbao.tencent.com/api/weixin/get_parse_result`
   body: `{"type":"video_channel_url","url":"<sph链接>","scene":1}`
   → `data.wx_export_id`、`data.playable_url`（内含 `token` 与 `eid`）、`author`、`desc`
2. `POST https://channels.weixin.qq.com/finder-preview/api/feed/get_feed_info`
   body: `{"baseReq":{"generalToken":"<token>"},"exportId":"<eid>"}`
   → `data.feedInfo.h264VideoInfo.videoUrl` / `h265VideoInfo.videoUrl`
3. CDN `finder.video.qq.com` 直连下载，就是明文 mp4，无需解密

第 1 步在浏览器上下文里发（playwright + 系统 Edge，profile 存 `.browser-profile/`），自动携带匿名 cookie。

## 排错（按顺序看）

| 症状 | 原因与处理 |
|---|---|
| `permission verification failed` | 直接打 feed 接口没带 token。必须走元宝第 1 步 |
| `此内容暂时无法播放` | **90% 是 exportId 用错**：必须取 `playable_url` 里的 `eid`（约 65 字符），不是 `wx_export_id`（约 57 字符） |
| feed 接口 HTTP 401 | 缺 `Origin: https://channels.weixin.qq.com` 请求头 |
| `元宝解析失败: 未知错误` | 参数格式错。必须是 `{"type":"video_channel_url","url":...,"scene":1}` |
| `No module named playwright` | `python -m pip install -i https://mirrors.aliyun.com/pypi/simple/ playwright` |
| playwright 启动失败 | 本机需有 Edge 或 Chrome；脚本用 `channel="msedge"`，无需 `playwright install` |
| 下载中断/文件头异常 | 该 CDN 地址有时效，重新跑一次即可 |

**装依赖务必用阿里云镜像** `https://mirrors.aliyun.com/pypi/simple/`。默认源和清华源大包会超时（实测 playwright 在默认源卡了 8 分钟未完成，镜像 3 秒装完）。

## 已知限制

- 清晰度由平台决定，接口只返回一档，**没有档位选择参数**。URL 里的 `X-snsvideoflag`、`basedata` 均带 `sign` 签名，改参必然失效。
- 实测普通账号内容常见上限为 576p 或 720p，1080p 多为认证/合作账号。
- 付费、会员、私密、已删除内容无法解析，会返回「此内容暂时无法播放」。
- 单条视频的 token 有效期约数天，过期需重新解析（脚本每次都重新解析，无感）。

## 合规边界

仅用于用户本人作品、已获授权的内容，或做竞品内容拆解参考。下载他人内容用于二次剪辑发布，教育/知识类账号被判搬运的处罚较重，必要时提醒用户。
