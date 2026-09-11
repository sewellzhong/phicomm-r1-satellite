# 文档与历史证据

当前状态与开发顺序见[根 README](../README.md)。历史报告保持原结论；旧下一步不作为执行指令。

本次整理结果见[仓库清理报告](2026-09-07-repository-cleanup.md)。

当前首台设备的按键、音量环、灯光权限、蓝牙与配网前置探测见[硬件能力记录](2026-09-07-r1-hardware-capability.md)。

## 当前需求

- [r1-sample01 免拆分级授权与验收边界](2026-09-11-r1-no-disassembly-authorization.md)：2026-09-11现行决策；只绑定当前首台和3448基线，分级允许必要的root、boot、system/recovery及特权服务，明确非强制的电气硬断麦/全引导灾难恢复和仍须另行授权的高风险范围。

- [原厂四麦与音频调校优先路线](2026-09-08-r1-factory-audio-root-plan.md)：2026-09-08 用户确认的最高优先级，包含完整回刷门槛、Root/SELinux/特权代理路线、公开发布边界、声学验收和降级条件。

- [r1-sample01 R0 完整备份与回刷操作手册](2026-09-08-r1-r0-recovery-runbook.md)：无设备阶段的主机清单与校验工具用法，以及设备到手后的只读盘点、双副本、低层恢复和受控回刷步骤。

- [原厂音频代理主机开发记录](2026-09-08-r1-factory-audio-agent-host.md)：真实库动态后端、最小权限边界、严格链路证明字段、只读预检和待完成实机门槛。

- [r1-sample01 原厂链受控运行记录](2026-09-08-r1-original-chain-smoke.md)：WAN 阻断下的原厂四麦/MicArray实际初始化、真人原厂唤醒、空调试文件边界及安全恢复结果。

- [r1-sample01 Type-C 与 RockUSB 入口识别](2026-09-09-r1-maskrom-entry.md)：有效数据线对照、静态Maskrom名称与实际 `bcdUSB=2.01` Loader判定、固定只读查询及外部RAM Loader发送前停止证据。

- [r1-sample01 原厂 boot/recovery 离线基线](2026-09-10-r1-boot-recovery-baseline.md)：从已复核Loader image双份副本提取原厂kernel、boot、recovery，记录Android boot image、ramdisk、RSCE/DTB及音频硬件约束；不改变R0门槛。

- [r1-sample01 system与原厂音频离线审计](2026-09-10-r1-system-audio-offline-audit.md)：从已复核Loader image双份提取system，固定白名单校验原厂音频材料并记录APK/JNI静态接口；实际通道、PCM、DOA和AEC仍待实机证明。

- [全链路优化分析与开发任务 O1～O8](2026-09-07-r1-chain-optimization.md)：现状证据、任务依赖、HA 外部交接及验证要求；已纳入后续开发，未视为实现或验收。

- [首台功能盘点、必要性与语音/HA 双入口管理](2026-09-07-r1-feature-requirements.md)：2026-09-07 用户确认的目标需求，未实现项及验收状态分别记录。

## 阶段与版本记录

- [2026-09-11-r1-factory-audio-v84-device](2026-09-11-r1-factory-audio-v84-device.md)
- [2026-09-11-r1-vendor-debug-probe](2026-09-11-r1-vendor-debug-probe.md)
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
