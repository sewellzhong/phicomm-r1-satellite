# 文档与历史证据

当前状态与开发顺序见[根 README](../README.md)。历史报告保持原结论；旧下一步不作为执行指令。

本次整理结果见[仓库清理报告](2026-09-07-repository-cleanup.md)。

## 当前需求

- [全链路优化分析与开发任务 O1～O8](2026-09-07-r1-chain-optimization.md)：现状证据、任务依赖、HA 外部交接及验证要求；已纳入后续开发，未视为实现或验收。

- [首台功能盘点、必要性与语音/HA 双入口管理](2026-09-07-r1-feature-requirements.md)：2026-09-07 用户确认的目标需求，未实现项及验收状态分别记录。

## 阶段与版本记录

- [2026-09-01-r1-sample01-stage0-report](2026-09-01-r1-sample01-stage0-report.md)
- [2026-09-01-r1-sample01-stage1-audio-report](2026-09-01-r1-sample01-stage1-audio-report.md)
- [2026-09-02-r1-sample01-audio-provenance](2026-09-02-r1-sample01-audio-provenance.md)
- [2026-09-02-r1-sample01-stage1-audio-followup](2026-09-02-r1-sample01-stage1-audio-followup.md)
- [2026-09-03-r1-sample01-stage1-processed-speech](2026-09-03-r1-sample01-stage1-processed-speech.md)
- [2026-09-03-r1-sample01-stage1-streaming-soak](2026-09-03-r1-sample01-stage1-streaming-soak.md)
- [2026-09-04-camila-kws-candidate-audit](2026-09-04-camila-kws-candidate-audit.md)
- [2026-09-04-camila-kws-reset](2026-09-04-camila-kws-reset.md)
- [2026-09-05-alexa-listener](2026-09-05-alexa-listener.md)
- [2026-09-05-alexa-pretrained](2026-09-05-alexa-pretrained.md)
- [2026-09-05-assist-acknowledgements](2026-09-05-assist-acknowledgements.md)
- [2026-09-05-assist-background](2026-09-05-assist-background.md)
- [2026-09-05-assist-command-window](2026-09-05-assist-command-window.md)
- [2026-09-05-assist-empty-command](2026-09-05-assist-empty-command.md)
- [2026-09-05-assist-input-policy](2026-09-05-assist-input-policy.md)
- [2026-09-05-assist-runtime](2026-09-05-assist-runtime.md)
- [2026-09-05-assist-websocket-foundation](2026-09-05-assist-websocket-foundation.md)
- [2026-09-05-camila-microwakeword-blind-testing](2026-09-05-camila-microwakeword-blind-testing.md)
- [2026-09-05-camila-microwakeword-validation](2026-09-05-camila-microwakeword-validation.md)
- [2026-09-05-ha-input-guard](2026-09-05-ha-input-guard.md)
- [2026-09-05-ha-time-sentences](2026-09-05-ha-time-sentences.md)
- [2026-09-05-model-cleanup](2026-09-05-model-cleanup.md)
- [2026-09-05-native-api-foundation](2026-09-05-native-api-foundation.md)
- [2026-09-05-native-voice-session](2026-09-05-native-voice-session.md)
- [2026-09-05-r1-sample01-camila-spk01-confusables](2026-09-05-r1-sample01-camila-spk01-confusables.md)
- [2026-09-05-r1-sample01-camila-spk01-training](2026-09-05-r1-sample01-camila-spk01-training.md)
- [2026-09-05-r1-sample01-camila-spk01-validation](2026-09-05-r1-sample01-camila-spk01-validation.md)
- [2026-09-06-native-audio-runtime](2026-09-06-native-audio-runtime.md)
- [2026-09-06-native-endpoint-dialogue](2026-09-06-native-endpoint-dialogue.md)
- [2026-09-06-native-satellite-runtime](2026-09-06-native-satellite-runtime.md)
- [2026-09-06-r1-audio-diagnostic-v59](2026-09-06-r1-audio-diagnostic-v59.md)
- [2026-09-06-r1-continuous-listening-v54](2026-09-06-r1-continuous-listening-v54.md)
- [2026-09-06-r1-diagnostic-queue-v60](2026-09-06-r1-diagnostic-queue-v60.md)
- [2026-09-06-r1-interaction-fixes](2026-09-06-r1-interaction-fixes.md)
- [2026-09-06-r1-interaction-settings](2026-09-06-r1-interaction-settings.md)
- [2026-09-06-r1-isolation-guard](2026-09-06-r1-isolation-guard.md)
- [2026-09-06-r1-nonroot-isolation](2026-09-06-r1-nonroot-isolation.md)
- [2026-09-06-r1-prompt-v55](2026-09-06-r1-prompt-v55.md)
- [2026-09-06-r1-reference-v56](2026-09-06-r1-reference-v56.md)
- [2026-09-06-r1-standard-root-probe](2026-09-06-r1-standard-root-probe.md)
- [2026-09-06-r1-v62-interaction-regression](2026-09-06-r1-v62-interaction-regression.md)
- [2026-09-06-r1-wake-triggered-diagnostic-v62](2026-09-06-r1-wake-triggered-diagnostic-v62.md)
- [2026-09-07-r1-short-reply-failures](2026-09-07-r1-short-reply-failures.md)

## 清理前入口快照

- [根 README 历史状态](history/repository-status-before-cleanup.md)
- [Android 探针历史说明](history/android-probe-before-cleanup.md)

原始音频、旧 APK 和源码副本的校验索引及恢复方法见[归档说明](../test-results/README.md)。

## 开发与验证

- [Linux 开发与自动检查](development.md)
- [实机待验证清单](device-validation.md)
- [公开证据说明](../test-results/README.md)
- [Git 整理与验证报告](2026-09-07-git-publication.md)
