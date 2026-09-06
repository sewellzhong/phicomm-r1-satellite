> 历史记录：本文版本、命令及“下一步”反映记录当时状态；当前排期以[根 README](../README.md)为准。原始产物迁移见[归档说明](../test-results/README.md)，原验收结论不变。

# Camila 免费离线 KWS 候选准入

## 固定需求

- 唤醒声音：`Camila`，`ka-MEE-la /kaˈmila/`；同音拼写 `Camilla` 同样属于正类。
- 禁止 `Hi`、`Okay`、`Hello` 等前缀。
- R1 输入：PCM S16LE、16 kHz、单声道、20 ms/帧。
- 唤醒后进入 Home Assistant 中文 STT、中文对话和中文 TTS。
- 当前是一位说话人的单用户选型；跨说话人泛化未验证。

## 2026-09-04 上游核验

| 候选 | 固定来源 | 许可初审 | 当前准入状态 |
|---|---|---|---|
| sherpa-onnx English GigaSpeech INT8 | sherpa-onnx `v1.13.7` / `917bed95c8e5c7c18aa4d69fea42e9ef8ef0a60e` | 框架 Apache-2.0；模型归档 README 标注 Apache-2.0，公开分发前仍保留权重来源审计 | 新归档哈希通过；Camila BPE 为 `▁CA M IL A`；主机加载/静音流通过，待真人/R1 |
| microWakeWord | `4665173cd35f1cff9a61e06fc427f124766c488e` | Apache-2.0；训练数据逐项另审 | v2 checkpoint 3500 已通过单人 validation 主门槛并在 R1/API 22 回放一致，冻结进入盲测 |
| openWakeWord | `368c03716d1e92591906a84949bc477f3a834455` | Apache-2.0；预训练特征和训练数据逐项另审 | 主机 ONNX 链通过；官方动态输入 mel TFLite 在 R1/TFLite 2.10 构造期溢出，需固定 `[1,1280]` 形状重新导出后复测 |
| PocketSphinx | `f20ff1b7a5db64c5e892a798479e20df86e79a35`（README 5.1.1） | BSD 风格许可；声学模型另审 | 主机词典/静音流通过；ELF32 ARM/API 22 双哈希库已构建并在 R1 加载通过，待模型和真人效果 |

官方依据：

- sherpa-onnx：[KWS 预训练模型](https://k2-fsa.github.io/sherpa/onnx/kws/pretrained_models/index.html)、[Android KWS APK](https://k2-fsa.github.io/sherpa/onnx/kws/apk.html)
- microWakeWord：[项目说明](https://github.com/kahrendt/microWakeWord)、[模型集合](https://github.com/esphome/micro-wake-word-models)
- openWakeWord：[项目说明](https://github.com/dscripka/openWakeWord)、[自定义模型配置](https://github.com/dscripka/openWakeWord/blob/main/examples/custom_model.yml)
- PocketSphinx：[项目](https://github.com/cmusphinx/pocketsphinx)、[Android 教程](https://cmusphinx.github.io/wiki/tutorialandroid/)

## 排除项

- Porcupine：需要 AccessKey，许可/服务条件不满足本轮“免费、完全离线”的固定范围。
- Vosk：完整 ASR 的运行开销不是本轮 KWS 的默认解法；仅在四个候选均无法运行时重新立项。
- 现成的其他唤醒词权重：目标声音不等于 Camila，不能用运行成功代替 Camila 效果。

## 统一测试协议

1. 先完成许可和主机加载；openWakeWord/PocketSphinx 还必须先通过 API 22、`armeabi-v7a` 构建准入。
2. 真人训练、验证和盲测按完整会话隔离。阈值只使用验证集确定，冻结后不得再看盲测标签调参。
3. 所有候选以同一份原始 PCM 做盲测和近音测试，并使用同一公共环境流计算 FAPH。
4. 主机报告召回率、FAPH、近音误触发和检测延迟；R1 逐个测初始化、PSS、CPU、RTF、最大帧耗时和 30 分钟稳定性。
5. 技术方案门槛只显示通过/失败，不自动淘汰或指定赢家；最终模型由用户选定。

## 当前结论

全新 sherpa 归档 SHA-256 为 `f170013b4716e41b62b9bfd809687c207cef798ef9bc6534d524e17af9b6561a`。三条可直接运行的主机基础链已完成加载和一秒静音流烟雾测试；结果见 [`test-results/2026-09-05T000422-host/stage1/camila-kws/runtime-smoke/`](../test-results/README.md)。这些结果不包含 Camila 真人音频，不能解释为准确率通过。

不携带旧模型的通用 APK 已通过单元测试、lint 和 assemble，并在 `r1-sample01` 完成全新卸载/安装/启动验证；首次安装证据见 [`test-results/2026-09-05T000130-r1-sample01/stage0/apk-install/`](../test-results/README.md)。PocketSphinx versionCode 24 原生库加载证据位于 [`test-results/2026-09-05T001016-r1-sample01/stage1/camila-kws/pocketsphinx-load/`](../test-results/README.md)。openWakeWord versionCode 26 动态形状失败证据位于 [`test-results/2026-09-05T001800-r1-sample01/stage1/camila-kws/openwakeword-load/`](../test-results/README.md)。随后曾恢复为不携带候选资产的 versionCode 27，证据见 [`test-results/2026-09-05T001857-r1-sample01/stage0/apk-install/`](../test-results/README.md)；当前 R1 已安装携带冻结候选的 versionCode 29，等待全新盲测采集。

## 单人 validation 初筛

新数据集包含 49 条 training、34 条独立 validation 和 31 条有标签近音负样本，逐文件哈希无跨分区重复。另有两段因顺序事件不足而不能绑定具体词的负流，不参与本表的 31 条统计。

- sherpa GigaSpeech 在原始输入和统一 +18 dB 输入、score 3.0、threshold 0.01～0.25 全部为 0/34，近音误触发也为 0。降低阈值和增加固定增益均未恢复 Camila 召回，当前不能进入盲测。
- PocketSphinx 原始输入的零近音误报最佳点为 10/34（threshold 1e-30）；放宽到 1e-40 为 17/34，并误触发 3 条 Carmela 和 1 条 Pamela。
- PocketSphinx +18 dB 在 1e-30 达到 33/34，但近音误触发 13/31；继续放宽可达 34/34，误触发上升至 19/31 及以上。它证明输入电平显著影响召回，但当前没有可接受的召回/近音平衡点。

完整阈值表见 [`test-results/2026-09-05T012454-host/stage1/camila-kws/mature-validation/results.json`](../test-results/README.md)。这是 validation 初筛，不是冻结后的盲测，不能作为最终准确率。

## microWakeWord 冻结候选

microWakeWord v2 第 3500 步的 INT8 流式模型在阈值 `255/255` 时，主机验证为 34/34、真人近音 1/31（Samira）、公共环境音 1 次/9.670475 小时。Android 实际 microfrontend 量化路径在 R1 回放得到相同的 34/34 和 1/31；两条 `come here` 按用户决定只计算 2 次，分数为 77/255 和 199/255，均未触发。

该点达到技术方案第 14 章的正常环境唤醒成功率和误唤醒门槛，但未达到额外的近音零误触发目标。模型 SHA-256 `85bb71fe4c6f8475f5ee6f6475221d4b75456240b4073301ac36a768c1975e3e` 与阈值现已冻结，下一步只允许采集全新 blind testing 数据，不再用 validation 调整。详见 [`docs/2026-09-05-camila-microwakeword-validation.md`](./2026-09-05-camila-microwakeword-validation.md)。

冻结后的三轮 testing 共 45 条，首次揭盲为 35/45（77.78%），低于 95% 门槛；R1 逐条复核结果相同且与主机分数零差异。因此 v2 已明确失败，不作为最终模型。完整结果见 [`docs/2026-09-05-camila-microwakeword-blind-testing.md`](./2026-09-05-camila-microwakeword-blind-testing.md)。
