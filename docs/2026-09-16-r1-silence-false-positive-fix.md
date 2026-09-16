# R1 静默误判修复

日期：2026-09-16

## 现象

V173 在 `r1-sample01` 的自动静默窗口中连续出现 `end_reason=speech`，但没有 STT/TTS 运行。干净轮次的输入窗口约 220 ms，采样 RMS 快照约为 11、15、22、38，噪声底约为 11。该证据表明 VAD 对低能量环境声给出了阳性，原有能量门控仍允许其进入 `CommandWindow`。

## 修复

`SpeechEvidence` 的原始 PCM RMS 最低门槛由 24 提高到 48，并继续保留 `floor * 2` 的环境能量上升条件。48 低于现有正确姿态真人低音量样本约 54 RMS，且高于本次误判轮次的最高约 38 RMS。该数值是项目实现防护，不命名为原厂标准。

本次不改变上传 PCM、WebRTC VAD 模式、原厂 AEC、KWS 模型或噪声数据保存策略。

## 主机验证

- `SpeechEvidenceTest.lowLevelVadNoiseDoesNotStartWindow`：新增，覆盖约 35 RMS、连续 220 ms 的 VAD 阳性低能量噪声。
- Android `testDebugUnitTest`、`lintDebug`、`assembleDebug`：通过。

## 实机边界

修复尚未在 R1 安装验收。需要生成新版本（V174）并在麦克风朝上的正确姿态下复测：至少 3 轮静默负向窗口、真人短命令、回答后静默，以及已有 V173 的播放中 Alexa 打断回归。V173 的直接免 Alexa 插话仍为关闭状态，不因本修复改变。
