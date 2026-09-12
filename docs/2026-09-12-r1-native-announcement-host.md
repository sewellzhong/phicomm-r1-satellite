# v103 主动播报主机实现记录

日期：2026-09-12

## 结论

v103 已在 Android 端实现固定 ESPHome 2026.8.0 `VoiceAssistantAnnounceRequest` 主动播报协议，
并仅新增 `ANNOUNCE` 能力位。实现复用 v102 已验证的有界 HTTP/WAV 播放器、原厂播放输出、
背压、完整排空和资源释放路径；没有声明尚未实现的 `TIMERS`、`START_CONVERSATION`、
`SPEAKER` 或媒体控制能力。

本轮只完成代码和主机测试，没有连接 HA、ADB 或 R1，没有安装 APK。主动播报在真实 HA/R1
上仍为待验证，计时器仍为待实现；不能将本记录写成实机功能通过。

## 行为边界

- 只接受来自已完成 Noise PSK 认证连接的标准播报请求。
- 语音会话或其他播放忙碌时明确回报失败，不抢占或混合当前回答。
- 支持 `preannounce_media_id` 后接 `media_id`，前一段必须完整排空并释放后才启动后一段；
  切换期间不向采集线程发布瞬时空闲状态。
- 空媒体、尚未支持的 `start_conversation`、非法 URL、HTTP/WAV、播放或资源释放失败均不
  回报成功。断线会停止当前播报，不保留或补播过期内容。
- 仅接受现有播放器允许的 HTTP(S) URL 和 PCM S16LE、16 kHz、单声道 WAV；重定向、
  user-info、fragment、超时、大小和缓冲限制沿用 v102 门槛。
- 诊断状态新增播报活动、请求、完成和失败计数，不保存播报文字、URL 或音频。

## 自动检查

`python3 tools/dev/prepare.py` 在显式使用本机 Android SDK 后通过。完整
`bash tools/dev/check.sh` 通过：

- 公开扫描 403 个文件、0 发现，secret scan 0；
- Android 单元测试 198 项、0 失败，lint 和 hostcheck APK 构建成功；
- hostcheck APK SHA-256：`fbf9d6f3c6afdbc2ed00392f8a587b1be8067e5ffaaae60b09157a1b7c94d8c1`；
- 原生工具 35 项、恢复 73 项及合成演练、原厂音频 117 项、HA 51 项与固定 HA 2026.8.2
  配置加载检查全部通过。

新增测试覆盖前置提示音与正文顺序、排空后成功、忙碌/空媒体/主动对话拒绝、URL 与播放
失败关闭、无关消息不误消费及断线停止。

## 待验证与下一步

以指定提交构建设备签名 APK 后，使用固定合成 WAV 和真实 HA 协议调用自动核对：能力位、
前置音与正文顺序、首次写入、排空、成功/失败回报、忙碌拒绝、断线释放和诊断状态恢复。
实机播报不做真人听感验收。随后实现计时器的本地倒计时、持久化、重启恢复、停止和状态
同步；在这些行为完成前不打开 `TIMERS` 能力位。
