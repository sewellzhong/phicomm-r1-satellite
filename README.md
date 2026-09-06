# Phicomm R1 Voice Satellite

将斐讯 R1 改造为 Home Assistant 中文语音卫星；当前范围为首台 r1-sample01。

## 当前状态

- Git 整理基于 v63 源码，首台设备仍为原 v63（原生链路清理版），移除旧 Assist WebSocket 运行入口；部署与验证结果见[清理报告](docs/2026-09-07-repository-cleanup.md)。v63 构建及最小实机录放音检查通过，原生监听已恢复；v62 的历史通过项不自动视为 v63 正式验收通过。
- 保留 Android 5.1.1 / API 22、ARMv7、固件 3448 的原厂音频底层，独立包名 `dev.sewellzhong.r1probe`。原生链路使用固定 ESPHome 2026.8.0 协议及 Noise PSK。
- 唤醒词仅为英文 `Alexa`，使用现有 microWakeWord v2 模型；STT、对话、TTS 固定中文。停止 Camila 训练、模型选型及 KWS 专项声学测试。
- 阶段 0 和阶段 1 音频子门槛已通过；原包非 root 持久隔离与三次重启恢复有实机证据。阶段 2/3 正式量化验收未完成。
- v62 真实首次静默 5/5、首次回应后立即开口 3/3 通过；“是→4”、提问理解偏差、历史偶发误触发仍开放。“好”修复的真人复测暂缓。详见[短句失败](docs/2026-09-07-r1-short-reply-failures.md)和[交互回归](docs/2026-09-06-r1-v62-interaction-regression.md)。

## 当前开发顺序

2026-09-07 已将[全链路优化 O1～O8](docs/2026-09-07-r1-chain-optimization.md)纳入后续开发：分段诊断、统一音频控制与取消、真流式回答、配置确认、会话协调、HA 兼容适配及有测量依据的端点/TTS 优化。本次完成分析与文档整合，功能尚未因此实现或验收；任务随下述功能组推进，不替代当前硬件与配网/蓝牙入口。

先补齐单台核心功能：播放中打断、流式回答、主动播报与计时器、本地闹钟、免打扰、媒体播放、手机蓝牙音箱、安卓/iPhone 自助配网、按键/物理静音/灯效、设备名称/区域与系统管理、签名更新与回滚。以上为待完成交付的功能组，不表示全部尚无代码。

必要配置和状态统一支持语音与 HA 管理：可写配置查询/修改，只读状态查询/展示，共用确认结果并明确失败、离线和待同步状态。闹钟通过语音或 HA 创建/设置，全部已有闹钟在 HA 显示，R1 本地保存并执行；语音管理仍依赖 HA 中文链路。

2026-09-07 已完成[功能盘点与需求合并](docs/2026-09-07-r1-feature-requirements.md)文档，功能实现和新增验收尚未开展。下一开发入口为硬件及配网/蓝牙可行性验证，随后完善播放和双入口管理。热点网页配网优先验证，不能满足条件时验证蓝牙配网；蓝牙网关不纳入。HA 负责内容平台接入及视频检索/电视播放，该接入后续在 HA 实施，不阻塞 R1 基础功能交付。

意图与语音链路调试、断网/IP 恢复检查、72 小时稳定性验收暂停。功能齐备后按“最终候选版本语音回归 → 网络/IP 恢复 → 72 小时稳定性”统一验收；开发中保留构建、单元测试及最小实机检查。技术方案第 14 章指标不变，不扩大到多台、同步音乐或左右声道实验。

## Git 与开发流程

公开仓库：[sewellzhong/phicomm-r1-satellite](https://github.com/sewellzhong/phicomm-r1-satellite)，自有代码采用 [Apache-2.0](LICENSE)，第三方边界见 [声明](THIRD_PARTY_NOTICES.md)。

Linux 环境按 [开发指南](docs/development.md) 准备依赖，运行 `bash tools/dev/check.sh`；GitHub Actions 执行相同无设备检查。功能实现完成后执行主机检查，再对指定提交构建、签名并进行实机验证。`main` 不代表已验收版本；状态见 [实机待验证清单](docs/device-validation.md)。

公开仓库不包含本地备份、密钥和原中文提示音，hostcheck 构建采用独立包名与测试音。本次整理未部署 R1，当前源码的实机验证待完成。整理过程和主机结果见 [Git 整理报告](docs/2026-09-07-git-publication.md)。

## 开发与日常入口

- [Android 构建与运行说明](android/r1-probe/README.md)
- `tools/native/`：原生管理、部署、配对和有界诊断。
- `tools/assist/`：固定提示音素材生成；已无旧 WebSocket 启动工具。
- `tools/kws/`：当前 Alexa 模型准备和既有诊断工具，保留工具不表示恢复专项测试。
- `integrations/home_assistant/`：R1 原生 HA 集成；`protocol/`：固定版本协议与许可证。

```bash
python3 tools/native/manage-r1-native.py status <adb-serial>
```

恢复原厂应用功能使用 `tools/native/deploy-r1-native.py restore <adb-serial> --evidence test-results/2026-09-06-r1-sample01-nonroot-isolation`，先停止卫星音频再解除隐藏。该基线保留原位。恢复原包功能与回退卫星 APK 是不同操作，APK 回退须使用对应部署基线。

## 文档与证据

- [技术方案与验收指标](斐讯R1语音卫星技术方案-2026-08-27.md)
- [文档历史索引](docs/README.md)：阶段报告、版本记录和历史失败。
- [清理报告](docs/2026-09-07-repository-cleanup.md)与[归档恢复说明](test-results/README.md)。历史报告中的旧“下一步”不代表当前排期。
- [Alexa 来源与许可边界](docs/2026-09-05-alexa-pretrained.md)、[原包隔离证据](docs/2026-09-06-r1-nonroot-isolation.md)。

不保存凭据或新增家庭对话录音，不覆盖原厂 APK、分区、Audio HAL、DSP 固件和校准数据。代码支持、主机测试通过和实机验收通过分别记录。
