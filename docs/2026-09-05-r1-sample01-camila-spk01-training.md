> 历史记录：本文版本、命令及“下一步”反映记录当时状态；当前排期以[根 README](../README.md)为准。原始产物迁移见[归档说明](../test-results/README.md)，原验收结论不变。

# Camila spk01 training 采集

- 设备：`r1-sample01`，固件 3448，Android API 22。
- 说话人：`spk01`；分区：`training`。
- 目标声音：`Camila`，`/kaˈmila/`，不使用前缀。
- 采集流程：1 秒 1000 Hz 开始提示音完全结束后录音 30 秒，录音结束后播放 1 秒 600 Hz 结束提示音。两个提示音均不在录音内。
- 格式：PCM S16LE、16 kHz、单声道；480,000 帧，无部分读取，无削波。
- 原始 WAV SHA-256：`252166b3be355873c48c9f2432b25618183a6f413cd49f3381e5b5f21091ec7b`。
- 用户于 2026-09-05 确认录音中只说了目标词，且没有需删除的家庭对话或其他私人内容。
- 设备副本已删除，原厂语音和播放器服务已恢复。
- 修正相邻发音泄漏风险后，自动分割得到 16 个间隔规则的候选；每个只保留当前事件前后 200 ms，再用静音居中补到 3.2 秒。全部切片格式和时长检查通过。

证据位于 [`test-results/2026-09-05T003526-r1-sample01/stage1/camila-kws/capture-training/`](../test-results/README.md)。原始录音和候选切片位于已忽略提交的 `local-models/camila/` 中。

## Training 02

- 采集方式：轻声→正常→稍响循环，其他边界与第 1 轮相同。
- 原始 WAV：30 秒、480,000 帧、无部分读取、无削波；SHA-256 `f2c005021df778a737ed43510441b9187f944f74e67ec81c91ef77312150b682`。
- 用户于 2026-09-05 确认只按指定音量循环说了 `Camila`，且没有需删除的家庭对话或其他私人内容。
- 证据：[`test-results/2026-09-05T004015-r1-sample01/stage1/camila-kws/capture-training/`](../test-results/README.md)。

## Training 03

- 采集方式：朝左→正前方→朝右循环，保持约 1 米和正常交谈音量。
- 原始 WAV：30 秒、480,000 帧、无部分读取、无削波；SHA-256 `89465508da3d91c7d34d8466177b58989a55531d84f34a361d19fe6f4a882ff3`。
- 用户于 2026-09-05 确认只按指定方向循环说了 `Camila`，且没有需删除的家庭对话或其他私人内容。
- 证据：[`test-results/2026-09-05T004248-r1-sample01/stage1/camila-kws/capture-training/`](../test-results/README.md)。
- 分割得到 17 个候选。三轮累计 49 个切片，逐文件 SHA-256 无重复，training 数量与会话多样性入口通过。
