# Phicomm R1 Voice Satellite

将斐讯 R1 改造为 Home Assistant 中文语音卫星；当前范围为首台 r1-sample01。

## 当前状态

- 2026-09-08 用户将[原厂四麦与音频调校优先路线](docs/2026-09-08-r1-factory-audio-root-plan.md)提升为最高开发优先级：先为 `r1-sample01` 建立完整 eMMC 备份和受控回刷，再使用 Root、特权代理、受限 SELinux、定制系统及必要刷机实际复用 MicArray、DOA、AEC和DSP处理。标准 AudioRecord和自研处理只作对照及最终降级候选。
- R0 主机端清单、复读校验、门槛报告、现场模板和一键合成演练已实现；默认仍要求两份加密副本。工具也记录用户针对 `r1-sample01` 明确接受的“当前单主机、明文”高风险例外，只有完整回刷全部验证后才会得到 `pass_with_exception`，绝不伪装成普通 `pass`。完整 eMMC、低层恢复入口和受控回刷仍为“待验证”。操作边界见 [R0 恢复手册](docs/2026-09-08-r1-r0-recovery-runbook.md)。
- 2026-09-10 用户进一步决定跳过拆机和物理Maskrom，仅对 `r1-sample01` 接受无可靠恢复入口时修改boot可能永久变砖或丢失数据的风险。R0继续为`pending`；豁免只覆盖boot，不覆盖system、recovery、Loader、分区表、擦除或其他设备。首个v2镜像因构建器漏算Rockchip扩展boot SHA并缺少4字节ramdisk对齐，被U-Boot拒绝后进入recovery；原boot两次按读回哈希恢复。修复后的v13 boot `09c89752f388bf09797251c819f7629a39f5ac5a24e93df7a5995154e187a787`已在Enforcing下启动专用代理。v80 APK完成10秒原厂链采集：500帧、0缺口、0代理丢帧、500帧有效DOA且PCM非零。该结果证明卫星实际消费原厂四麦阵列输出，但四麦独立响应、运行时通道形状、AEC消除量和DSP质量仍待R3验证，详见[boot-only风险实验](docs/2026-09-10-r1-boot-only-risk-experiment.md)。
- 2026-09-11 用户将后续边界调整为[首台免拆分级授权](docs/2026-09-11-r1-no-disassembly-authorization.md)：始终不拆机，只绑定当前 `r1-sample01` 与3448基线；较低权限路线有可复现不足证据后，可使用必要的root、boot、system、recovery、特权服务及专用Enforcing策略完成既定功能。Loader、参数/分区表、物理首4 MiB、擦除、格式化和整盘覆盖仍须另行授权。电气硬断麦和所有引导组件同时损坏后的恢复改为非强制项；实体按键强制软件静音、远程不可解除及真实状态/灯效仍必须交付。R0继续为`pending`，文档授权不代表功能或恢复门槛已经通过。
- 2026-09-09 至 2026-09-10 已确认第三方 Type-C 口可进入 `2207:320b` RockUSB。Android盘点确认eMMC为15,269,888个512字节扇区、16个分区；已有Loader映射到物理4 MiB之后的7,813,988,352字节image空间，该空间已分117块从设备读取两遍，逐块及整体SHA-256一致。免拆软件路线可执行 Android→`2.01 Loader`→`2.00 Maskrom`，但它依赖Android，不能算独立恢复入口。固定 `v1.04.232`、官方一致组合 `v1.10.256` 及与设备2018-06 U-Boot年代匹配的 `v1.07.238` 三枚 RAM Loader 均各发送一次，下载命令成功后设备仍保持Maskrom；三次均未执行能力、FlashInfo、分区或LBA读取，同候选已由工具强制禁止重发。第三次后物理断电已恢复 Android USB `2207:0010`。离线反汇编确认同年代官方 `upgrade_tool` 与固定 `rkdeveloptool` 的471/472、1 ms等待、分块及CRC传输语义一致，没有证据支持换工具重发。2026-09-10 用户决定跳过当前物理Maskrom验证；该项保持未验证，不等于通过。双副本仍缺物理首4 MiB，R0保持 `pending`。详见[RockUSB入口记录](docs/2026-09-09-r1-maskrom-entry.md)。
- 跳过物理入口后已继续离线推进：从已复核的A/B Loader image副本分别提取 `kernel`、`boot`、`recovery`，三组尺寸、SHA-256及逐字节比较均一致；boot/recovery为16 KiB页Android boot image，共用原厂zImage和Rockchip RSCE/DTB。DTB确认RK3229及I2S0/1/2、ES7243、ES8323、AK7755等音频硬件节点。该基线只用于未来补丁输入与回退比对，不是完整eMMC或Root授权，详见[原厂boot/recovery离线基线](docs/2026-09-10-r1-boot-recovery-baseline.md)。
- 已从相同A/B Loader image双份提取805,306,368字节system分区，两份SHA-256一致；固定白名单复核原厂Unisound APK、四麦HAL、圆形/线性MicArray、软件AEC库、配置与AK7755 data2固件。更新后的离线审计用37个精确锚点自动复核原APK/JNI/HAL调用链，并纠正早期人工结论：默认包长为1,200样本、四麦分支默认申请2,400字节且可运行时配置，不是已证明的4,800字节。Java只在JNI读取返回正值时回调，而HAL透传底层 `pcm_read` 非负返回值，该返回语义矛盾保持待实机确认；实际有效通道布局、PCM、DOA和AEC仍须实机证明，详见[system与原厂音频离线审计](docs/2026-09-10-r1-system-audio-offline-audit.md)。
- v81（`f7723c945da5dc222b5d058f6265c3492db6e335`）原厂音频代理沿用真实 3448 动态后端、固定 v1 Protobuf IPC、UID/SELinux隔离及生产失败关闭门槛，并为显式限时验证请求增加双输出通道诊断旁路。生产流仍固定为PCM S16LE、16 kHz、单声道、20 ms；诊断另存双通道WAV并审计哈希、通道非零性、差异和单声道映射。`9ad9e6c873c876d1d44ce05122fde81d0aaa4e58`又增加四方向DOA矩阵审计，在未知设备零度下核对有效帧比例、集中度和相对方向；其`pass`只证明上报DOA的相对响应。v82源码（`519def937b28b095dbfd0e63ea17cb7e6ed30e9e`）允许在最长30秒验证窗口内延迟1秒并发播放受控本地参考，记录参考哈希、真实媒体音量档位及播放单调时钟边界；离线审计缺少或篡改任一旁证即拒绝。v81/v82仍未部署，不能把主机测试写成运行时通道形状、播放参考覆盖、AEC、四麦独立响应或DSP质量已通过。v80实机结果及原厂链历史见[主机开发记录](docs/2026-09-08-r1-factory-audio-agent-host.md)。
- 首台设备当前运行 v80 APK与v13 boot代理；当前开发源码为 v82 R3诊断候选。现场盘点见[硬件能力探测](docs/2026-09-07-r1-hardware-capability.md)。安卓与 iPhone 的 A2DP 配对、播放、断开和重连播放通过。中央键短按和长按已由系统消息桥实机捕获，长按可开启原厂热点；两台手机可同时连接并独立操作配网页面，输入及跨窗口缓存隔离通过。v78 单手机提交后因热点模式下提前写入 Wi-Fi 配置而回退，未通过完整配网。v79 改为使用 Android Keystore 加密一次性交接、恢复 station 后写入，R1 上合成数据往返自检通过；完整手机配网按用户决定留待之后复测。
- 保留 Android 5.1.1 / API 22、ARMv7、固件 3448 的原厂音频底层，独立包名 `dev.sewellzhong.r1probe`。原生链路使用固定 ESPHome 2026.8.0 协议及 Noise PSK。
- 唤醒词仅为英文 `Alexa`，使用现有 microWakeWord v2 模型；STT、对话、TTS 固定中文。停止 Camila 训练、模型选型及 KWS 专项声学测试。
- 阶段 0 和阶段 1 音频子门槛已通过；原包非 root 持久隔离与三次重启恢复有实机证据。阶段 2/3 正式量化验收未完成。
- v62 真实首次静默 5/5、首次回应后立即开口 3/3 通过；“是→4”、提问理解偏差、历史偶发误触发仍开放。“好”修复的真人复测暂缓。详见[短句失败](docs/2026-09-07-r1-short-reply-failures.md)和[交互回归](docs/2026-09-06-r1-v62-interaction-regression.md)。

## 当前开发顺序

2026-09-07 已将[全链路优化 O1～O8](docs/2026-09-07-r1-chain-optimization.md)纳入开发。v64 完成 O1/O2 的首个无设备增量；v65/v66 增加硬件及限时蓝牙、BLE、热点能力探针。手机蓝牙音箱已通过两类手机实测。中央键和音量环的普通 APK 输入路径、LED 写入受权限或框架拦截；自建热点实测失败。v67 接入保留的原厂配网服务，v68～v77 补齐移动端页面、扫描快照及恢复状态机。v78 允许最多 16 个独立浏览器会话同时浏览和填写，只在最终提交时仲裁，并强制页面与接口不缓存。v79 的一次性交接密文由设备 Keystore 保护，成功或失败后删除；应用和日志不保存明文密码。

当前boot-only权限环境、专用代理、原厂四麦阵列PCM及DOA传输门槛已实机通过；v81通道形状采集、四方向DOA离线矩阵审计及v82受控播放同步采集已具备，等待同一候选的受控实机输入。下一步先核对v81代理不变的构建哈希并为v82生成签名设备APK，再按相同参考和实际媒体音量档位取得安静、60%和90%播放样本；这些采集只建立AEC定量输入，不直接证明AEC。随后继续完成四麦独立响应、AEC消除量和DSP质量的R3声学准入。R0恢复门槛并未取消，只是不再作为首台boot实验的前置。之后补齐单台核心功能：播放中打断、流式回答、主动播报与计时器、本地闹钟、免打扰、媒体播放、手机蓝牙音箱、安卓/iPhone 自助配网、按键/物理静音/灯效、设备名称/区域与系统管理、签名更新与回滚。以上为待完成交付的功能组，不表示全部尚无代码。

必要配置和状态统一支持语音与 HA 管理：可写配置查询/修改，只读状态查询/展示，共用确认结果并明确失败、离线和待同步状态。闹钟通过语音或 HA 创建/设置，全部已有闹钟在 HA 显示，R1 本地保存并执行；语音管理仍依赖 HA 中文链路。

2026-09-07 已完成[功能盘点与需求合并](docs/2026-09-07-r1-feature-requirements.md)文档。WAN 阻断下的可回退原厂链窗口已经完成；Android布局盘点及Loader可见7.814 GB image空间的双读、逐块和整体校验均已完成。免拆软件Maskrom可达，但三枚不同官方RAM Loader候选均未进入Loader，且已禁止重发；设备已恢复Android。共同失败离线审计排除主机工具核心传输算法差异。只有以后取得缺失首4 MiB、合成完整eMMC副本并复读，且验证不依赖Android的恢复入口后，才能把R0写成通过并进行受控完整回刷。后续开发按2026-09-11免拆分级授权，可在R0 pending时依据最小必要证据推进精确命名的boot/system/recovery操作；这不改变R0状态，也不授权Loader、分区表、首4 MiB、擦除或格式化。热点网页配网保留 v79 待复测状态，不因权限放宽自动绕过配网安全门槛。

意图与语音链路调试、断网/IP 恢复检查、72 小时稳定性验收暂停。功能齐备后按“最终候选版本语音回归 → 网络/IP 恢复 → 72 小时稳定性”统一验收；开发中保留构建、单元测试及最小实机检查。技术方案第 14 章指标不变，不扩大到多台、同步音乐或左右声道实验。

## Git 与开发流程

公开仓库：[sewellzhong/phicomm-r1-satellite](https://github.com/sewellzhong/phicomm-r1-satellite)，自有代码采用 [Apache-2.0](LICENSE)，第三方边界见 [声明](THIRD_PARTY_NOTICES.md)。

Linux 环境按 [开发指南](docs/development.md) 准备依赖，运行 `bash tools/dev/check.sh`；GitHub Actions 执行相同无设备检查。功能实现完成后执行主机检查，再对指定提交构建、签名并进行实机验证。`main` 不代表已验收版本；状态见 [实机待验证清单](docs/device-validation.md)。

公开仓库不包含本地备份、密钥和原中文提示音，hostcheck 构建采用独立包名与测试音。本次整理未部署 R1，当前源码的实机验证待完成。整理过程和主机结果见 [Git 整理报告](docs/2026-09-07-git-publication.md)。

## 开发与日常入口

- [Android 构建与运行说明](android/r1-probe/README.md)
- `tools/native/`：原生管理、部署、配对和有界诊断。
- `tools/recovery/`：R0 镜像清单、副本校验、恢复门槛报告、原厂boot双份与来源复读、固定只读RockUSB盘点器，以及只能离线准备和单次RAM加载的受限工具；默认双加密副本，单主机明文例外必须显式、限定设备并保留风险状态。所有设备工具均不提供复位、写入或擦除入口。
- `tools/factory_audio/`：原厂库 ABI 审计、双份system离线提取、私有材料静态审计、只读实机预检、可回退原厂链窗口和门槛化私有 overlay 暂存；不包含原厂二进制或刷写命令。
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
- [Alexa 来源与许可边界](docs/2026-09-05-alexa-pretrained.md)、[原包隔离证据](docs/2026-09-06-r1-nonroot-isolation.md)、[原厂音频 Root 路线](docs/2026-09-08-r1-factory-audio-root-plan.md)、[免拆分级授权](docs/2026-09-11-r1-no-disassembly-authorization.md)。

不保存凭据或新增家庭对话录音。原厂库、APK、DSP固件、校准、备份和修改镜像不进入公开仓库；任何分区修改都必须使用与目标范围相称的设备双读备份和写后读回门禁，完整恢复能力仍按R0单独记录。代码支持、主机测试通过和实机验收通过分别记录。
