> 历史记录：本文版本、命令及“下一步”反映记录当时状态；当前排期以[根 README](../README.md)为准。原始产物迁移见[归档说明](../test-results/README.md)，原验收结论不变。

# Camila spk01 confusables 采集

## Confusables 01（不计入有标签覆盖）

- 原始序列：`Camille`、`camellia`、`camera`、`Pamela`、`Carmela`、`Samira`、`vanilla`、`can Mila`、`call Mila`、`come here`。
- 用户确认本轮没有说 `Camila`/`Camilla`，且没有需要删除的私人内容。
- 录音完整 30 秒、无部分读取、无削波；SHA-256 `cb3862f0b227ea236ac2c8c90c8c02122c730d39a4a5a195a7d466acc9883fde`。
- 自动分割只得到 8 个完整事件及 1 个 140 ms 开头截断事件，无法将 10 个词按顺序可靠绑定。
- 本轮仅可作为“未标注近音负流”做整体误触发检查，不计入每词覆盖和 30 条有标签近音门槛。
- 后续采集改为录音期间终端每 2 秒显示一条当前词，避免开头截断和顺序遗漏。
- 证据：[`test-results/2026-09-05T005556-r1-sample01/stage1/camila-kws/capture-confusables/`](../test-results/README.md)。

## Confusables 02（作废）

- 脚本尝试在录音期间每 2 秒输出一条词，但用户界面没有实时显示工具输出，用户无法接收对应提示。
- 用户明确报告未看到提示，本轮不批准、不切片、不用于任何训练或测试。
- 本地私有 WAV 已删除；设备副本原本已在采集脚本退出前删除。
- 失败证据：[`test-results/2026-09-05T010113-r1-sample01/stage1/camila-kws/capture-confusables/`](../test-results/README.md)。

## Confusables 03（仅未标注负流）

- 用户确认按固定列表朗读且没有目标词或需删除的私人内容。
- 原始 WAV 完整 30 秒、无部分读取、无削波；SHA-256 `f4fbb77c7faab5bc63f1f14e2b0101b823b173c208397f22c8292c2e2a895bcb`。
- 自动分割得到 9 个完整事件，无法判断 10 项中缺少哪一项，因此拒绝顺序标签绑定。
- 本轮仅作为未标注近音负流，不计入每词覆盖。
- 证据：[`test-results/2026-09-05T010440-r1-sample01/stage1/camila-kws/capture-confusables/`](../test-results/README.md)。

后续改为 A/B 两个五词组，每个词连续说 3 次；每组只有在正好检测到 15 个完整事件时才绑定标签。

## Confusables A

- 用户确认依次将 A 组五个词各说 3 次，没有目标词或需删除的私人内容。
- 原始 WAV 完整 30 秒、无部分读取、无削波；SHA-256 `6bb0711b1328aad785d52716e3ef483f06135fdb7a6b7fb092d2ae1b6618607e`。
- 时间轴得到 14 个规则事件：`Camille`、`camellia`、`camera`、`Pamela` 各 3 次，`Carmela` 2 次；预期的最后一次 `Carmela` 位于 30 秒录音边界之后。
- 前 14 个事件按证据明确的顺序绑定；另录一个只含 3 次 `Carmela` 的补充会话，不重录整个 A 组。
- 证据：[`test-results/2026-09-05T010835-r1-sample01/stage1/camila-kws/capture-confusables-a/`](../test-results/README.md)。

## Carmela 补录

- 用户确认只说了 `Carmela` 3 次，没有目标词或需删除的私人内容。
- 原始 WAV 为 10 秒、160,000 帧、无部分读取、无削波；SHA-256 `c18436da977989d7277b862242ba57866fb2b64d9ac8d8598fa37d51e2c479ea`。
- 证据：[`test-results/2026-09-05T011249-r1-sample01/stage1/camila-kws/capture-confusables-carmela/`](../test-results/README.md)。
- 补录自动检测并绑定 3 条 `Carmela`。A 组当前共 17 条唯一有标签切片：前四词各 3 条，`Carmela` 5 条。

## Confusables B

- 用户最终确认按顺序说了 `Samira`、`vanilla`、`can Mila`、`call Mila` 各 3 次，`come here` 按实际检测到的 2 次计算；没有目标词或需删除的私人内容。
- 原始 WAV 为 30 秒、480,000 帧、无部分读取、无削波；SHA-256 `64aed77efee66b1d425ba8939f62345b2d7194ecc4f61dde570e993e4b9d0bae`。
- 证据：[`test-results/2026-09-05T011546-r1-sample01/stage1/camila-kws/capture-confusables-b/`](../test-results/README.md)。
- 自动检测得到 14 个规则事件：`Samira`、`vanilla`、`can Mila`、`call Mila` 各 3 条，`come here` 2 条。
- 用户明确确认 `come here` 按 2 条计算且不再补录。A/B 有标签近音总数仍为 31，满足至少 30 条总量；每词 3 条不是既定硬门槛，因此该偏差记录后接受。
