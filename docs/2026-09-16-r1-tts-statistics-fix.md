# R1 TTS 统计修正

日期：2026-09-16

## 问题

V174 真人命令实际听到正确时间回答，但设备状态中的 `tts_streams=0`。原因是该字段此前只在 `VOICE_ASSISTANT_TTS_STREAM_START` 或 `tts_start_streaming=1` 时递增；非流式 URL TTS 通过 `TTS_START/TTS_END` 启动播放，不会计入该字段。

## 修正

保留 `tts_streams` 的原有语义，并新增：

- `tts_responses`：本次 Assist 运行收到的有效 TTS 回答数；
- `tts_playback_completed`：TTS 播放完成数；
- `tts_playback_failed`：TTS 播放失败数。

每个 Assist 运行最多计一次回答和一次流式启动；取消运行不计为播放完成。本地结束提示音不计入 Assist TTS 回答。

## 验证

- 流式、非流式 URL、本地提示、播放失败、跨运行隔离均有单元测试。
- Android `testDebugUnitTest`、`lintDebug`、`assembleDebug` 通过。
- 统一 `tools/dev/check.sh` 通过。

V175 仍需在 R1 上安装后复测非流式真人回答，确认 `tts_responses=1`、`tts_playback_completed=1` 与现场听感一致。
