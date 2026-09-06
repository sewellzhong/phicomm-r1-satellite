> 历史记录：本文版本、命令及“下一步”反映记录当时状态；当前排期以[根 README](../README.md)为准。原始产物迁移见[归档说明](../test-results/README.md)，原验收结论不变。

# Assist 停顿与唤醒词误转写修正（版本 39）

## 用户报告与原因

用户报告：说 Alexa 后停顿数秒再说命令，HA 收到“奥ex斯。”并返回无法理解；
连说时收到“欧ex萨现在几点？”并把“欧ex萨现在”作为设备名。
版本 38 只删除英文 Alexa，未覆盖这些用户确认的误转写。唤醒前两秒音频上传包含完整唤醒词，
HA 默认 VAD 可在唤醒后停顿时结束输入，过早把唤醒词交给 Whisper。

## 版本 39 行为

- 本地 KWS 模型、阈值与 PCM S16LE/16k/单声道/20ms 格式保持不变。
- 上传最近 10 帧（200ms）预缓冲，替代两秒全量预缓冲；减少完整唤醒词进入 STT。
  保留短缓冲帮助接续命令，不能保证所有连说场景不丢首字或唤醒词尾音。
- STT 请求设置 `input.no_vad=true`，由 R1 发送音频结束帧。
  HA Core 2026.8.2 的 WebSocket 实现将它传给 `AudioSettings.is_vad_enabled`。
- `CommandWindow` 至少接收 400 帧（8 秒音频），其后累计安静 75 帧（1.5秒）结束，
  最多 1000 帧（20秒）。固定 RMS 120 仅是开发端点能量启发式，不是真正语音分类器。
  因此短命令也至少等到 8 秒窗口结束；连续噪声可能延长至20秒，低声命令可能被视作安静。
  新端点和预缓冲长度尚未实机声学验收，不承诺解决全部房间噪声或连说情况。
- `WakeWordPrefix` 额外只处理用户报告的句首“奥ex斯”“欧ex萨”；不做模糊删除，
  不修改句中同名内容。仅有这些唤醒词及标点时不提交意图。
- 两段式 STT→STT / intent→tts、令牌仅内存、最长运行一小时不变。

## 验证与证据

`testDebugUnitTest lintDebug assembleDebug` 成功，52 项单元测试全部通过；
覆盖唤醒尾音+5秒停顿+命令、接近8秒开始说话、静音8秒结束、连续噪声20秒上限、
200ms 环形缓冲及已报告误转写。`python3 -m py_compile tools/assist/run-r1-assist.py` 通过。
这些是合成帧和协议单元测试，不是 R1 真人效果结论。本轮不开展新 KWS 测试或采集音频。

依据：[HA Core 2026.8.2 WebSocket 实现](https://github.com/home-assistant/core/blob/2026.8.2/homeassistant/components/assist_pipeline/websocket_api.py)。
证据目录：`test-results/2026-09-05-r1-sample01-assist-command-window/`。
