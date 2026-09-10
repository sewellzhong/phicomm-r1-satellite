# R1 原厂音频代理无设备开发记录

## 已实现边界

v80 建立自有的原厂音频代理公共骨架。协议固定为版本 1，使用 4 字节网络序长度
加 Protobuf Lite `Envelope`，最大消息 1 MiB。生产 socket 名为
`/dev/socket/r1_factory_audio`；代理要求显式目标 UID，并使用 `SO_PEERCRED` 拒绝
其他进程。它不监听网络端口，一次只服务一个采集客户端。

协议支持版本协商、开始/停止、健康状态、640 字节 PCM 帧、DOA 字段、播放参考、
丢帧计数和结构化错误。除必须显式指定的 `--fake` 合成后端外，现已加入真实动态
后端：只从指定绝对路径加载设备已有的 3448 原厂库，调用已审计的
`init(1) → debug(0) → algorithm(0) → pcm_open(2) → start/read/DOA → stop/close/release`
序列。静态反汇编同时确认 `pcm_read` 转发 tinyalsa 状态码（`0` 成功、负数失败），
不把返回值误当字节数。输出通道数和选用通道必须显式提供，未证明时不能生成启动配置。

真实后端不会把原厂二进制打包进 APK、代理或仓库。ABI 审计只接受
`r1-sample01` 已观察到的两个 SHA-256 和所需 ARM ELF32 符号。健康协议新增板级
版本、原始麦克风数、AEC 参考数、阵列处理和 AEC 生效字段；APK 只有在后端名、
板级版本、四麦、双参考、阵列和 AEC 全部成立时才接受为生产原厂链。当前代码有意
上报 AEC 未证明并拒绝外加软件参考，所以仍不能进入生产采集。

启动模板先以 root 创建 socket，限定为卫星 UID 10010 可访问，然后清空附加组并降权
到 Android `audio` UID/GID 1041，才接受连接及初始化后端。专用 SELinux 域只声明
系统只读文件、`audio_device` 和本地 socket 权限，没有网络、块设备或 permissive
授权。它仍是待合入目标 boot sepolicy 的模板，不是已部署策略。

APK 客户端固定请求 PCM S16LE、16 kHz、单声道、20 ms/帧，并校验每帧恰好
640 字节。`factory_proxy` 是显式来源标识，尚未成为默认采集链；代理错误会直接上报，
不会静默转用标准 AudioRecord 后继续声称原厂处理生效。

客户端本地 IPC 读操作使用 2 秒有界超时。停止确认失败或对端异常消失时仍清理本地
采集状态、待处理帧和 socket，重复关闭保持安全；恢复由上层显式重新连接完成，不在
客户端内静默重试。代理检测到流式客户端断开后释放后端，下一目标 UID 客户端可重新
协商并从新的采集序列开始。

为解除“尚未证明AEC所以生产入口拒绝、生产入口拒绝所以无法取证”的闭环，APK新增
`factory_audio_validate` 限时诊断动作。它与生产 `startCapture()` 分离，只接受已识别的
3448原厂后端、四麦声明、阵列激活声明和非空板级版本；不要求也不伪造尚未证明的AEC
字段。诊断最长30秒，写入16 kHz单声道WAV及元数据，记录帧序号、代理丢帧、DOA有效数、
10度直方图和WAV哈希。接收器仍受系统 `DUMP` 权限保护，普通应用不能触发。

拉回本地后用 `tools/factory_audio/audit-validation-capture.py` 复核格式、哈希、帧连续性和
元数据边界。审计的 `pass` 仅表示传输及上报DOA字段自洽，报告固定保留四麦独立响应、
运行时通道形状、AEC消除量和DSP质量为未验证。诊断WAV可能包含家庭对话，默认只保留在
本地，不提交仓库。

## 主机验证

运行：

```bash
bash tools/factory_audio/check.sh
python3 tools/recovery/rehearse.py
```

主机检查构建 C++ 代理，并使用由固定 protoc 3.25.5 生成的 Python 类型验证版本
协商、固定格式、流式帧、播放参考、停止、版本错误、格式错误、UID 拒绝和无真实
后端时失败关闭。若主机配置了固定 Android NDK，脚本同时构建 API 22、
`armeabi-v7a` 代理。

当前增量测试覆盖真实后端必须显式选型、符号/调用顺序、DOA 编码、单/双通道选择、
调试关闭、释放路径、生产证明拒绝，以及启动/SELinux 模板和私有 overlay 门槛。
统一 `tools/dev/check.sh` 实际通过 Android 168 项单元测试、lint、hostcheck APK、
32 项工具测试、21 项 R0 测试与桌面演练、24 项代理/策略/ABI/受控窗口测试、API 22 ARMv7
交叉构建、HA 44 项测试和配置加载检查。hostcheck APK SHA-256 为
`a1c11ddb8d9a91acf73aaaa27e8ee22a772482450bde66c16dd964b2b1a63a37`；ARMv7
代理 SHA-256 为
`d89cf581f8069151e8a262a18934ab40de46013c4b64558fccca3e6999f372df`。

2026-09-10新增原厂boot基线门禁后，增量检查通过73项恢复测试与桌面演练、26项
代理/策略/ABI/受控窗口测试、主机及API 22 ARMv7代理构建、公开文件审计和凭据扫描。
`tools/factory_audio/check.sh` 改为使用统一准备流程生成的固定Python环境，避免系统Python
缺少protobuf时在测试收集阶段产生环境假失败。

这些结果证明公共协议、代理状态机和对已审计 ABI 的主机替身调用；后续受控原厂窗口
已补充证明 R1 上的 HAL/MicArray 初始化和真人原厂唤醒，但仍未证明实际 PCM、DOA、
AEC消除量或 DSP 输出质量。hostcheck APK、mock 库和未过门槛的代理都不得部署为设备候选。

2026-09-10在不连接设备的前提下，从已双读复核的Loader image A/B副本提取system分区，
两份805,306,368字节镜像的SHA-256一致。固定白名单内的原厂APK、JNI、四麦HAL、
圆形/线性MicArray、软件AEC库、配置及AK7755 data2固件完成来源复核和私有反汇编。
原APK调用证据确认 `openAudioIn(2)`；机器复核纠正默认读取缓冲为2,400字节（1,200样本乘
2字节），且包长可运行时配置，因此该长度不能证明有效输出通道。Java只在JNI读取返回正值
时回调，而HAL透传底层读取的非负返回值，该返回语义矛盾仍待实机确认。当前代理的显式通道
参数和AEC失败关闭策略保持不变。详见
[system与原厂音频离线审计](2026-09-10-r1-system-audio-offline-audit.md)。

离线审计增量的统一检查通过Android 168项、lint、native 32项、恢复73项与桌面演练、
原厂代理/策略/ABI/离线审计39项、HA 44项、API 22 ARMv7交叉构建、公开审计及凭据扫描。
hostcheck APK和ARMv7代理哈希与上述已记录基线一致；本步没有构建设备签名APK。

验证采集增量的统一检查通过Android 170项、lint、native 32项、恢复73项与桌面演练、
原厂代理/策略/ABI/离线审计42项、HA 44项、配置加载、API 22 ARMv7交叉构建、公开审计
及凭据扫描。hostcheck APK SHA-256为
`661ccc32b74b62b26cb2263fd9f93687e3a365ddaf0c3f941022979d8ecb1348`；ARMv7代理未变，
SHA-256仍为`d89cf581f8069151e8a262a18934ab40de46013c4b64558fccca3e6999f372df`。
本步没有连接ADB/HA，也没有构建设备签名APK或采集真实录音。

## 实机续接入口

2026-09-08 的只读预检已确认 `r1-sample01` 为 3448/API 22、SELinux Enforcing、
卫星 UID 10010、原厂包保持隐藏、四个原厂音频库哈希匹配，配置声明四麦圆阵、双
AEC 参考、AEC 开启及调试路径。该结果只说明测试前状态正确，不说明算法已运行。

WAN 阻断下的原厂窗口已经完成：同一进程报告四麦、双参考、AEC 开启、MicArray
v2.3.0 和私有音频源打开，真人“小讯小讯”到达唤醒事件；生成的 4 麦/2 AEC/输出
调试 WAV 均为 0 帧，不能确定代理输出通道或量化 AEC。详见
[受控运行记录](2026-09-08-r1-original-chain-smoke.md)。

下一步按 R0 手册完成完整 eMMC、低层入口和受控回刷。只有门槛为 `pass` 或用户
明确接受的 `pass_with_exception`，且原厂boot基线、ABI、预检和通道证明都匹配，私有
overlay渲染器才生成暂存目录；它本身永不刷机。2026-09-10新增的boot基线门禁会复读
私有kernel/boot/recovery双份文件及其来源证据，并把固定公开参考和私有清单哈希写入overlay
清单，详见[原厂boot/recovery离线基线](2026-09-10-r1-boot-recovery-baseline.md)。

后续决策：用户于2026-09-10接受仅`r1-sample01`、仅boot范围的不可恢复变砖风险。R0仍为
`pending`；渲染器只在外部风险记录精确绑定设备、原boot哈希和范围时接受该状态。代理现支持
init继承socket；固定策略工具只改写未加载的policy v26副本，boot构建器保持kernel、DTB、
second、地址和页大小不变。详见[boot-only风险实验](2026-09-10-r1-boot-only-risk-experiment.md)。

代理实际运行且用户明确同意采集诊断音频后，可由受 `DUMP` 权限保护的ADB shell显式触发：

```bash
adb -s <adb-serial> shell am broadcast \
  -n dev.sewellzhong.r1probe/.ProbeCommandReceiver \
  -a dev.sewellzhong.r1probe.COMMAND \
  --es probe_action factory_audio_validate --ei duration_seconds 10 \
  --es sample_id <non-personal-sample-id> --es probe_nonce <unique-nonce>
```

完成日志会给出WAV和元数据路径。将两者拉到仓库外的本地目录后执行：

```bash
python3 tools/factory_audio/audit-validation-capture.py \
  --device r1-sample01 --wav <local-wav> --metadata <local-meta> \
  --output <new-local-report.json>
```
