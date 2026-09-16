# R1 提示音尾部误判修复

日期：2026-09-16

## 现象

V175 六轮静默负向在首轮约 120 ms 处判定 `speech`，峰值 RMS 约 694、VAD/strong 均为阳性，但没有 STT/TTS。输入发生在本地确认音结束后的第一帧，不能通过继续提高全局 RMS 门槛解决，否则会伤害低音量真人语音。

## 修复

所有本地提示音完成后统一进入 500 ms `PromptSettleGate`：

- 丢弃提示音尾部和 `promptHandoff` 帧；
- 不运行命令 VAD、起音判断或 Assist 上传；
- 保护期结束后重置 history、VAD、KWS 和提示音引用，再打开命令窗口。

覆盖本地诊断初始窗口、Alexa 确认音、回答打断确认音和自动 follow-up；原有 follow-up settle 字段保持兼容，并新增提示音 settle 诊断字段。

## 验证

- `PromptSettleGateTest` 覆盖保护期内丢弃、到期开放和重复 arm。
- Android `testDebugUnitTest`、`lintDebug`、`assembleDebug` 通过。
- V175 失败证据原样保留；V176 需重新安装后执行六轮静默和真人回归。
- V177 真人回归显示原 1.2 秒保护期会吞掉确认音后的短命令；当前缩短为 500 ms，仍覆盖已观测的 300 ms 内提示音尾部。
