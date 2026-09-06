> 历史记录：本文版本、命令及“下一步”反映记录当时状态；当前排期以[根 README](../README.md)为准。原始产物迁移见[归档说明](../test-results/README.md)，原验收结论不变。

# R1 真机 r1-sample01 阶段 1 音频受控验收与独占矩阵

- 日期：2026-09-02
- 设备 ID：r1-sample01
- 固件：3448 / Android 5.1.1 / API 22
- 真机调试 APK：`dev.sewellzhong.r1probe` versionCode 8（早期音频证据由 versionCode 7 采集）
- 结论：自动录放音链路再次完成，但本轮人声时长不足，音频子门槛未通过；后续 5 秒路由诊断音已由用户确认实际可闻。当前第三方修改的 `device` 更新包单独运行已足以阻塞独立 APK 的输入和输出。

## 受控录音结果

在临时停止 `com.phicomm.speaker.device` 和 `com.phicomm.speaker.player` 后，三种输入源各完成 5 秒静音基线和 10 秒人声窗口，均为 PCM S16LE、16 kHz、单声道，无部分读取或削波。用户在预期提示音后说了一段时间，但没有持续 35 秒；因此后两路窗口不能作为同等人声样本比较。

| 输入源 | 静音 RMS | 人声窗口 RMS | 电平差 | 判定 |
| --- | ---: | ---: | ---: | --- |
| VOICE_COMMUNICATION | -64.95 dBFS | -55.23 dBFS | 9.72 dB | 接近 10 dB，但未达门槛 |
| VOICE_RECOGNITION | -64.46 dBFS | -59.04 dBFS | 5.42 dB | 人声时长不足，不作声学结论 |
| MIC | -64.83 dBFS | -65.01 dBFS | -0.18 dB | 未包含有效人声，不作声学结论 |

用户确认没有听到本轮 2 秒提示音，也尚未人工回听三份 WAV，因此本轮不可懂度未通过。设备端 WAV 在拉回后删除，本机 WAV 继续由 `.gitignore` 排除。

随后将流程改为每个输入源前播放 5 秒 1 kHz 提示音、每路单独说 10 秒、最后播放 5 秒 500 Hz 结束音。三路再次完整采集且无部分读取或削波，结果如下：

| 输入源 | 静音 RMS | 人声 RMS | 整段电平差 | 20 ms 窗口观察 |
| --- | ---: | ---: | ---: | --- |
| VOICE_COMMUNICATION | -64.05 dBFS | -59.13 dBFS | 4.92 dB | 人声 P95 -53.87 dBFS，静音 P95 -61.11 dBFS |
| VOICE_RECOGNITION | -61.95 dBFS | -59.28 dBFS | 2.67 dB | 人声 P95 -54.18 dBFS，静音 P95 -58.71 dBFS |
| MIC | -61.57 dBFS | -60.15 dBFS | 1.41 dB | 人声 P95 -55.59 dBFS，静音 P95 -57.38 dBFS |

三路都包含与说话时段一致的能量变化，但整体增益明显过低，均未达到 10 dB 门槛。为便于人工回听，工具使用固定 +24 dB 生成标准 44 字节 WAV；放大后的 VOICE_COMMUNICATION 峰值为 -8.64 dBFS、无削波，并已在 R1 上完成 10 秒回放。用户确认能听到录音但音量较小，并说明采集时可能说得较轻；尚未明确确认每个字都可懂。该放大只用于诊断，不改变原始证据，也不能作为生产增益方案。

最后按 1 米正常交谈音量再次完成三路受控采集。VOICE_COMMUNICATION 提升到整段 8.95 dB，VOICE_RECOGNITION 为 4.16 dB，MIC 为 3.64 dB，仍均低于保守的整段 10 dB 门槛；VOICE_COMMUNICATION 的 100 ms 活跃窗口 P95 相对静音 P95 为 10.94 dB。该最佳样本固定放大 +22 dB 后峰值约 -8.81 dBFS、无削波，用户确认固定中文短语可以清楚听懂但整体仍较小。结论为语音内容保留、可懂度通过，原始采集增益门槛未通过；不把诊断放大视为生产修复。

## 当前第三方更新包独占矩阵

- 只停止 `com.phicomm.speaker.device` 时，该包被自动重新拉起，无法稳定保持“仅 player 运行”的状态；脚本停止该场景，没有循环强停或禁用包。
- 只停止 `com.phicomm.speaker.player` 时状态可保持，但三个 AudioSource 全部阻塞，AudioTrack 也阻塞并由看门狗回收。
- 结合两个包同时停止后录放音可以推进的既有结果，可确认 `com.phicomm.speaker.device` 单独运行已足以占用第三方输入和输出；尚不能证明 player 包单独运行是否也会占用。

## 输出路由诊断

媒体流未处于 mute，当前默认媒体音量为 6/15。静止时 AK7755 为 `DAC Mute=On`、LineOut Amp1/2=Off；独立 APK 播放 5 秒测试音期间，HAL 自动切换为 `DAC Mute=Off`、LineOut Amp1/2=On，AudioFlinger 48 kHz 输出线程进入非待机，恢复当前第三方音频服务后重新关闭。用户听到与 1 kHz 纯音相符的持续嗡声，因此测试音实际可闻门槛通过；该文件本来不包含语音内容。

## 证据

- 受控录音、用户观察和校验清单：[`test-results/2026-09-02T001602-r1-sample01/stage1/audio-acceptance/`](../test-results/README.md)
- 单包隔离矩阵：[`test-results/2026-09-02T001758-r1-sample01/stage1/isolation-matrix/`](../test-results/README.md)
- player 停止、device 运行时的失败日志：[`test-results/2026-09-02T001815-r1-sample01/stage1/audio-probe/`](../test-results/README.md)
- 播放期间 mixer 与 AudioFlinger 快照：[`test-results/2026-09-02T002425-r1-sample01/stage1/playback-route/`](../test-results/README.md)
- 带逐路提示音的第二次受控录音：[`test-results/2026-09-02T002737-r1-sample01/stage1/audio-acceptance/`](../test-results/README.md)
- +24 dB 人工可懂度回放：[`test-results/2026-09-02T003234-r1-sample01/stage1/manual-intelligibility/`](../test-results/README.md)
- 正常交谈音量复测：[`test-results/2026-09-02T003444-r1-sample01/stage1/audio-acceptance/`](../test-results/README.md)
- 最佳样本 +22 dB 清晰度确认：[`test-results/2026-09-02T003703-r1-sample01/stage1/manual-intelligibility/`](../test-results/README.md)

## 下一步门槛

后续来源和路由审计已确认官方 3448 HAL/DSP 文件仍在，标准 VOICE_COMMUNICATION 使用 AudioFlinger 16 kHz 双声道输入线程，但没有触发 AK7755 mixer 变化；当前第三方语音包运行时没有对应 AudioFlinger 输入线程。系统四麦库则明确导出 tinyalsa PCM、MicArray、DOA 和 AEC 参考接口，详细证据见 [`2026-09-02-r1-sample01-audio-provenance.md`](./2026-09-02-r1-sample01-audio-provenance.md)。

2026-09-02 已完成内部 PoC：APK 未打包专有库，系统 JNI 能加载并返回板卡版本 `UNI_4MIC_HAL_ANDROID_V1.1`。但录音初始化的 `openAudioIn(2)` 返回 0，内核同步记录 `untrusted_app` 对 `/dev/snd` 的 SELinux `{ search }` 拒绝；普通 ADB shell 对两个音频覆盖包执行 `disable-user` 也被 Package Manager 拒绝。实验在首个静音样本前停止，原服务已恢复，没有生成家庭对话录音。

1. 私有四麦 JNI 在普通独立 APK 路线判定为实机不可用；不以平台签名、共享 UID、root 或降低 SELinux 安全性绕过。
2. 继续以标准 VOICE_COMMUNICATION 为基线验证安全的输入增益或应用层处理，并保持 PCM S16LE、16 kHz、单声道、20 ms/帧。
3. 至少一个输入源达到整段 10 dB 电平差且原始固定短语可懂，才进入 KWS 对照；数字放大仍只作为诊断。

## 标准 AudioRecord 双声道诊断

versionCode 9 请求 VOICE_COMMUNICATION、16 kHz、PCM S16LE 双声道，并从同一批帧派生左、右、平均和差分单声道。设备端提示音在 AudioRecord 初始化完成后播放，结束即开始 10 秒采集，避免人工提示与约 5 秒初始化延迟错位。

对齐后的实机结果：左、右、平均通道人声相对各自静音基线分别为 4.11、4.63、4.71 dB，100 ms 活跃窗口 P95 差为 7.30、8.24、8.26 dB，均无削波。语音期间左右相关系数为 0.875；右路比左路高约 4.0 dB，但静音也高约 3.5 dB，差分通道语音 RMS 仅 -69.27 dBFS。由此排除明显反相下混和单侧弱麦导致的主增益问题：选择右声道可提高绝对电平约 2 dB，但不能提高语音/静音分离，不作为生产修复。

证据：[`test-results/2026-09-02T023041-r1-sample01/stage1/stereo-channel-controlled/`](../test-results/README.md)。双声道只用于诊断，生产链路仍输出 PCM S16LE、16 kHz、单声道、20 ms/帧。

## 离线频谱降噪 A/B

以对齐后的平均单声道为输入，使用同一份 5 秒静音建立噪声谱，对 gentle、balanced、strong 三组固定参数执行高通、512 点 STFT 频谱减法和固定 +18 dB 输出增益。算法只依赖 Python 标准库，三档均未削波；固定增益不参与信噪比分离判定。

| 档位 | 整段语音/静音差 | 活跃窗口 P95 差 | 与原语音波形相关性 | 语音峰值 |
| --- | ---: | ---: | ---: | ---: |
| gentle | 6.90 dB | 10.24 dB | 0.975 | -13.33 dBFS |
| balanced | 8.20 dB | 11.47 dB | 0.957 | -13.46 dBFS |
| strong | 9.996 dB | 12.83 dB | 0.927 | -13.63 dBFS |

strong 最接近整段门槛，但波形变化最大，不能仅凭数值入选；当前优先人工比较原始 +18 dB 与 balanced +18 dB。balanced 已完成 R1 回放，用户听感仍待确认。证据位于 [`test-results/2026-09-02T023918-r1-sample01/stage1/offline-processing-ab/`](../test-results/README.md) 和 [`test-results/2026-09-02T024205-r1-sample01/stage1/manual-intelligibility/`](../test-results/README.md)。在主观确认、实时移植和 CPU/PSS 实测前，生产集成状态仍为未集成，阶段 1 仍未通过。

用户回听 A/B 后报告：原始 +18 dB 的 A 没有听到声音；balanced 的 B 第一段可以听清但仍偏小，之后越来越小，第三段不可懂或无声。逐秒对照显示 balanced 相对原始的处理增益没有持续衰减；原始录音第一个有效短语约 -53.6 dBFS，后续下降到约 -60～-63.5 dBFS，因此固定增益无法维持多段语音响度。

在 balanced 后新增 20 ms 活动门控、峰值受限的自适应增益候选 C。它只在超过同源降噪静音 RMS 1.5 倍的帧上追踪 -28 dBFS 目标，附加增益上限 18 dB、峰值限制 -1 dBFS。C 的整段差为 10.43 dB、活跃窗口 P95 差为 11.69 dB，最大实际附加增益 15.7 dB且零削波；后续多数秒提升到 -33～-35 dBFS，最弱一秒约 -40.9 dBFS。C 已在 R1 完成回放，用户主观评价待确认。证据位于 [`test-results/2026-09-02T024909-r1-sample01/stage1/offline-adaptive-gain/`](../test-results/README.md) 和 [`test-results/2026-09-02T024924-r1-sample01/stage1/manual-intelligibility/`](../test-results/README.md)。

用户随后确认后续短语变小是本人说话音量过小造成，要求跳过该轮主观调参；该样本不再用于判断 R1 是否自动衰减，也不据此降低或宣称通过声学门槛。

versionCode 10 将 balanced 频谱减法和自适应增益逐公式移植为 API 22 Java，并通过受 `android.permission.DUMP` 保护的离线诊断动作在 R1 处理同一 10 秒 WAV。真机输出与 Python 候选 C 的 160000 个样本完全一致，最大绝对差 0、RMSE 0、相关性 1.0；墙钟耗时 2.043 秒、线程 CPU 1.915 秒，对 10 秒音频的实时率为 0.204，折算连续处理约占单核 19%，处理期间 PSS 约 8.7 MB，零削波。证据位于 [`test-results/2026-09-02T025911-r1-sample01/stage1/processing-benchmark/`](../test-results/README.md)。当前实现一次性加载整段 WAV并分配随时长增长的数组，仅证明算法一致性和算力余量；未改为有界流式状态、未接入 AudioRecord，不能标记为实时处理完成。

随后将处理核心改为固定大小的增量状态：512 样本 STFT 输入环/overlap-add、320 样本增益帧，2 秒噪声校准缓冲固定为 32000 样本；JVM 使用不规则输入块验证流式输出与批处理逐样本一致。真实 R1 接入 VOICE_COMMUNICATION 后完成 2 秒校准和 20 秒连续处理，输入/输出均为 320000 样本，部分读取、处理超时和削波均为 0；最长单次处理 35.034 ms，总处理墙钟 3.154 秒、线程 CPU 3.034 秒，折算连续处理约占单核 15.2%。宿主 `am broadcast` 会等待异步 Receiver 完成，因此所谓 `during-1` 实为结束后的首个 PSS 快照 15.4 MB，随后快照 12.2 MB，不能冒充精确运行中峰值。证据位于 [`test-results/2026-09-02T030819-r1-sample01/stage1/streaming-processing/`](../test-results/README.md)。当前仍存在每个 STFT 帧分配临时数组的 GC 压力，需先复用工作区并完成长时 soak，才可标记实时处理稳定。

versionCode 11 已在代码层移除实时稳态路径的逐帧 FFT 数组、逐次解码数组、处理结果收集数组和写出字节数组分配，并新增独立 soak Service，避免用长生命周期 BroadcastReceiver 承载 30 分钟任务。soak 固定丢弃处理后 PCM，只保存元数据、逐分钟 PSS/PID/AudioFlinger 和应用 GC 证据；主机工具要求显式确认目标设备与临时隔离，并在所有退出路径恢复原音频服务。新增复用缓冲边界测试后共 14 个 JVM 测试通过，lint 与 debug APK 构建通过。2026-09-03 已完成覆盖安装、20 秒回归和第二轮正式 30 分钟 soak；完整结果、首次证据密度失败及工具修正见 [`2026-09-03-r1-sample01-stage1-streaming-soak.md`](./2026-09-03-r1-sample01-stage1-streaming-soak.md)。
