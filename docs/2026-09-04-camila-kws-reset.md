> 历史记录：本文版本、命令及“下一步”反映记录当时状态；当前排期以[根 README](../README.md)为准。原始产物迁移见[归档说明](../test-results/README.md)，原验收结论不变。

# Camila KWS 重置记录

## 决策

- 执行日期：2026-09-04（Asia/Hong_Kong）
- 新唤醒词：`Camila`，目标发音 `ka-MEE-la /kaˈmila/`，中文提示“卡-米-拉”
- 唤醒词是单个英文词，不添加 `Hi`、`Okay`、`Hello` 等前缀。
- 唤醒后使用中文 STT、中文对话和中文 TTS。
- 用户明确要求永久删除旧 Amity/KWS 训练、录音、模型和测试结果，从 KWS 选型重新开始。
- 当前只有一位说话人，本轮允许单用户最终选型；跨说话人指标保持未验证。

## 删除前核验

目标 R1 在清理前通过 ADB 核验为固件 `3448`、API `22`、ABI `armeabi-v7a`。待卸载包仅为独立调试包 `dev.sewellzhong.r1probe`，不属于原厂系统包。

删除前本地资产统计：

- `local-models/amity-training`：53,390,220,161 字节，307,651 个文件。
- 旧 microWakeWord/sherpa KWS 模型和归档：9 个路径，合计约 121 MB。
- `local-deps/amity-mww-training-venv`：7,093,220,710 字节，43,285 个文件。
- `local-deps/amity-training-venv`：174,860,057 字节，3,435 个文件。
- `test-results` 旧 KWS/Amity 证据：37 个精确叶目录，约 17 MB。
- 旧 Amity/KWS 专用文档：15 个文件；旧模型专用工具、配置和测试：56 个文件。

## 永久删除范围

模型和专用环境：

```text
local-models/amity-training
local-models/r1-microwakeword
local-models/r1-wenetspeech-int8
local-models/r1-zh-en-chunk16-int8
local-models/r1-zh-en-chunk8-int8
local-models/sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01-mobile
local-models/sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01-mobile.tar.bz2
local-models/sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20
local-models/sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20.tar.bz2
local-deps/amity-mww-training-venv
local-deps/amity-training-venv
```

测试证据叶目录：

```text
test-results/2026-09-03T050750-r1-sample01/stage1/kws-capability
test-results/2026-09-03T051906-r1-sample01/stage1/kws-capability
test-results/2026-09-03T052343-r1-sample01/stage1/kws-live-smoke
test-results/2026-09-03T052443-r1-sample01/stage1/kws-live-smoke
test-results/2026-09-03T052945-r1-sample01/stage1/kws-live-smoke
test-results/2026-09-03T053108-r1-sample01/stage1/kws-live-smoke
test-results/2026-09-03T053441-r1-sample01/stage1/kws-live-smoke
test-results/2026-09-03T053500-host/stage1/kws-model-validation
test-results/2026-09-03T054315-r1-sample01/stage1/kws-capability
test-results/2026-09-03T054333-r1-sample01/stage1/kws-live-smoke
test-results/2026-09-03T054415-r1-sample01/stage1/kws-live-smoke
test-results/2026-09-03T055356-r1-sample01/stage1/kws-capability
test-results/2026-09-03T055412-r1-sample01/stage1/kws-live-smoke
test-results/2026-09-03T055458-r1-sample01/stage1/kws-live-smoke
test-results/2026-09-03T060452-r1-sample01/stage1/mww-capability
test-results/2026-09-03T060725-r1-sample01/stage1/mww-capability
test-results/2026-09-03T061247-r1-sample01/stage1/mww-capability
test-results/2026-09-03T062000-host/stage1/amity-training-preview
test-results/2026-09-03T070150-host/stage1/amity-training-data
test-results/2026-09-03T212308-host/stage1/amity-rir-v1
test-results/2026-09-03T214841-host/stage1/amity-v2-hard-negatives
test-results/2026-09-03T220843-r1-sample01/stage1/amity-positive-capture
test-results/2026-09-03T223854-host/stage1/amity-rir-v2
test-results/2026-09-04T000806-host/stage1/amity-seeded-hn-ablation
test-results/2026-09-04T002810-host/stage1/amity-seeded-hn1
test-results/2026-09-04T004424-host/stage1/amity-v1-finetune
test-results/2026-09-04T004914-host/stage1/amity-speaker-coverage
test-results/2026-09-04T005228-r1-sample01/stage1/amity-positive-capture-spk02
test-results/2026-09-04T011218-host/stage1/amity-speaker-coverage
test-results/2026-09-04T011701-host/stage1/amity-speaker-coverage-corrected
test-results/2026-09-04T012152-r1-sample01/stage1/amity-positive-capture-spk02
test-results/2026-09-04T012609-host/stage1/amity-speaker-coverage
test-results/2026-09-04T012900-r1-sample01/stage1/amity-positive-capture-spk03
test-results/2026-09-04T013312-host/stage1/amity-speaker-coverage
test-results/2026-09-04T014327-host/stage1/amity-multispeaker-feature-prep
test-results/2026-09-04T020259-host/stage1/amity-v5-multispeaker-training
test-results/2026-09-04T025149-host/stage1/amity-v6-vctk-confusables
```

所有删除目标在执行前必须解析为 `/path/to/phicomm-r1-satellite/` 的子路径。项目没有 Git 历史；删除的录音、模型和结果不可通过本仓库恢复。阶段 0 和阶段 1 音频证据不在删除范围内。

## 保留的通用基础

- Android 5.1/API 22、`armeabi-v7a` 构建配置。
- `VOICE_COMMUNICATION` AudioRecord、PCM S16LE/16 kHz/单声道/20 ms 音频链路。
- 原厂 Android 内核、Audio HAL、DSP 固件和校准数据。
- sherpa-onnx API 22 静态链接构建、TFLite 2.10 和 microfrontend 通用兼容实现。
- 阶段 0、录放音、流式处理和音频验收文档与证据。

## 后续入口

新数据统一放入忽略提交的 `local-models/camila/`，新证据按日期和设备 ID 放入 `test-results/.../stage1/camila-kws/`。任何录音开始前必须显示用途并等待用户就绪确认。

## 执行结果

- 上述 11 个模型/专用环境路径和 37 个测试证据叶目录均已逐项通过 `realpath` 范围检查并永久删除；删除后复核未发现残留旧 KWS/Amity 目录。
- 15 个旧专项文档和 56 个模型专用工具、配置及测试文件已删除。
- 旧 versionCode 22 独立调试包已通过固件兼容的 `pm.jar` 入口卸载；标准 `adb uninstall` 会使该固件的网络 ADB 断开并无限等待，因此中止后重连、核验包仍存在，再使用兼容入口完成卸载。
- versionCode 27 通用采集 APK 不携带旧模型，已经重新构建并安装。versionCode 24/26 只用于 PocketSphinx/openWakeWord 准入，验证后已恢复无候选资产的 27。原厂包、分区、Audio HAL、DSP 和校准数据未修改。
