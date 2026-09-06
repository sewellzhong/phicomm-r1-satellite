> 历史记录：本文版本、命令及“下一步”反映记录当时状态；当前排期以[根 README](../README.md)为准。原始产物迁移见[归档说明](../test-results/README.md)，原验收结论不变。

# Camila spk01 validation 采集

## Validation 01

- 设备：`r1-sample01`，固件 3448，Android API 22；说话人 `spk01`。
- 采集方式：正前方约 1 米，自然正常音量说 `Camila /kaˈmila/`，不使用前缀。
- 原始 WAV：30 秒、480,000 帧、PCM S16LE/16 kHz/单声道、无部分读取、无削波。
- SHA-256：`5414481a96e95db74e88988c0566af39ec192ee18c38f9a2e5966d762823233f`。
- 开始/结束提示音均成功且不在录音内；设备副本已删除，原厂服务已恢复。
- 用户于 2026-09-05 确认只以自然正常音量说了目标词，且没有需删除的家庭对话或其他私人内容。
- 证据：[`test-results/2026-09-05T004613-r1-sample01/stage1/camila-kws/capture-validation/`](../test-results/README.md)。

Validation 仅用于阈值和训练选择，不作为最终盲测，不得并入 training。

## Validation 02

- 采集方式：保持正前方约 1 米和正常音量，自然改变语速和重音。
- 原始 WAV：30 秒、480,000 帧、无部分读取、无削波；SHA-256 `35a5ff3c45eb4d11279d84d6fa45e4405385d440e059526b37b87b4e11cc4e3c`。
- 用户于 2026-09-05 确认只按指定方式说了 `Camila`，且没有需删除的家庭对话或其他私人内容。
- 证据：[`test-results/2026-09-05T004848-r1-sample01/stage1/camila-kws/capture-validation/`](../test-results/README.md)。
- 本轮分割得到 17 个候选。两轮 validation 累计 34 个，与 49 个 training 切片的 SHA-256 交集为空，validation 入口通过。
