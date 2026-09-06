> 历史记录：本文版本、命令及“下一步”反映记录当时状态；当前排期以[根 README](../README.md)为准。原始产物迁移见[归档说明](../test-results/README.md)，原验收结论不变。

# R1 sample01 3448 音频底层来源审计

- 日期：2026-09-02
- 设备：`r1-sample01` / `rk322x_echo` / Android 5.1.1 API 22 / 3448
- 结论：当前设备使用与公开 3448 OTA 目标一致的系统音频底层，应用层由 `/data/app` 第三方修改包覆盖。

## 来源基线

公开 OTA 镜像固定到 `pexcn/phicomm-r1-ota` 的 gh-pages 提交 `2ce76756bfd9495370a5e82e46474032779654dc`。`incremental-ota-3415-3448.zip` 的 SHA-256 为 `581c1bdcb6313b9b9acf2ea545731816872298c97326005ab7a409f5efa89b88`，包内 post-build 与实机 fingerprint 完全一致，OTA 证书主题为斐讯 R1。

实机审计将 Android OTA 脚本中的目标 SHA-1 与设备文件逐项比较，并另外记录 SHA-256。SHA-1 只作为 OTA 文件身份字段，不作为新证据的安全校验算法。

| 层级 | 文件 | 结果 |
| --- | --- | --- |
| 系统基础应用 | EchoService、Unisound | 均匹配 3448 OTA 目标 |
| Audio HAL | `audio.primary.rk30board.so` | 匹配 3448 OTA 目标 |
| 四麦接口 | `libuni4michal.so`、`libuni4michalchance.so` | 均匹配 3448 OTA 目标 |
| AK7755 DSP | data2 CRAM、PRAM、OFREG | 均匹配 3448 OTA 目标；实机 mixer 当前也报告加载 data2 |
| 内核 | Linux 3.10，`jenkins@phicomm`，2018-06-26 | 确认为斐讯构建血统；未读取 boot 分区，不能等同完整 boot 镜像校验 |
| 生效应用 | `com.phicomm.speaker.device/player` | 位于 `/data/app`，为第三方修改覆盖层 |

因此准确表述是“**官方 3448 音频底层文件已哈希确认，第三方应用层覆盖**”，而不是纯原厂整机，也不是通用 Android 驱动环境。

## 音频调用边界

标准 Android 应用通过 AudioRecord/AudioTrack、AudioFlinger 和 R1 Audio HAL 使用内核与 DSP 路由，所以独立卫星 APK仍在复用官方底层。播放实测已观察到 HAL 自动解除 AK7755 DAC 静音并打开 LineOut Amp。

但官方 Unisound 应用还包含 `Uni4micHalJNI`、`FourMicAudioManager`、`IAudioSourceAEC` 和四麦 ASR 事件。`libuni4michal.so` 导出 `uni_4mic_pcm_open/read/start/stop`、MicArray、DOA、AEC 参考输入和 I2C 接口，并直接打开 tinyalsa PCM。独立 AudioRecord 不会自动获得这些应用级四麦/AEC能力。

2026-09-02 路由快照进一步显示：

- 独立 VOICE_COMMUNICATION 录音创建 AudioFlinger 16 kHz、双声道输入线程，APK 最终取得单声道数据。
- 录音期间 AK7755 mixer 没有变化，说明本次标准采集不由 AK7755 控件切换驱动。
- 当前第三方语音包运行时没有对应 AudioFlinger 输入线程，却能独占录音设备，符合其通过私有四麦 JNI/tinyalsa 路径采集的特征。

这解释了当前现象：驱动和官方 DSP 文件仍在使用，但独立 APK 尚未复用原应用私有的阵列处理、AEC 和增益链。

versionCode 8 随后以完全相同的 `com.unisound.jni.Uni4micHalJNI` Java ABI 动态加载设备系统库，APK 内没有 `.so`。只读能力调用成功返回 `UNI_4MIC_HAL_ANDROID_V1.1`；进入原厂初始化顺序后，`openAudioIn(2)` 返回 0，内核在同一时刻记录 `u:r:untrusted_app:s0` 对标记为 `audio_device` 的 `/dev/snd` 目录被拒绝 `{ search }`。这证明库存在和 ABI 可调用不等于普通独立 APK拥有直连 tinyalsa 的 SELinux 权限。

## 生产决策

- 保留已经哈希确认的 3448 内核、Audio HAL、四麦库、AK7755 固件和板级配置。
- HA 卫星为生产主功能；当前第三方小讯、DLNA 和 AirPlay 不作为必须保留依赖。
- 当前阶段只临时停止第三方包做实验。永久切换先使用可恢复的 `disable-user`，不卸载包。
- 在卫星 APK具备开机自启、健康检查、录放音和恢复验证前，应用层管理工具必须拒绝执行禁用。
- 不通过平台签名、共享 UID、root 或修改 SELinux 绕过本次失败；私有四麦 JNI 不作为普通独立卫星 APK 的生产采集后端，标准 AudioRecord 继续作为当前主线。

## 证据与工具

- 来源审计：[`test-results/2026-09-02T012609-r1-sample01/stage0/provenance/`](../test-results/README.md)
- 应用层只读状态：[`test-results/2026-09-02T011936-r1-sample01/stage1/app-layer-status/`](../test-results/README.md)
- VOICE_COMMUNICATION 路由快照：[`test-results/2026-09-02T011943-r1-sample01/stage1/capture-route-voice_communication/`](../test-results/README.md)
- 四麦 JNI/原生接口审计：[`test-results/2026-09-02T012535-r1-sample01/stage1/four-mic-interface/`](../test-results/README.md)
- 四麦能力实机通过：[`test-results/2026-09-02T015542-r1-sample01/stage1/four-mic-capabilities/`](../test-results/README.md)
- 四麦录音 SELinux 失败与恢复：[`test-results/2026-09-02T015903-r1-sample01/stage1/four-mic-record/`](../test-results/README.md)
- 固定参考：[`docs/references/r1-3448-provenance.json`](./references/r1-3448-provenance.json)

来源审计使用 `tools/audit-r1-audio-provenance.sh`；采集路由使用 `tools/run-r1-capture-route-probe.sh`；`tools/manage-r1-app-layer.sh` 提供只读状态及带防护的禁用/恢复，但本轮只执行了 `status`。
