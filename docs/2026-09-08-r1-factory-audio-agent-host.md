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

启动模板由Android init创建socket，限定为卫星 UID 10010 可访问，代理继承后清空附加组并降权
到 Android `audio` UID/GID 1041，才接受连接及初始化后端。专用 SELinux 域只声明
Android 5启动/动态链接、本地日志、系统只读文件、`audio_device` 和本地 socket 权限，
没有网络、块设备或 permissive授权；实机上继续拒绝原厂库执行`/system/bin/sh`。

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

v81代码提交`f7723c945da5dc222b5d058f6265c3492db6e335`在同一v1协议中增加向后兼容字段，只有`startUnattestedValidationCapture()`显式请求时，
代理才附带原厂读取缓冲中的全部交错输出通道；生产`startCapture()`不会发送该旁路。
验证动作在原单声道WAV之外保存`-diagnostic-stereo.wav`，元数据绑定文件名、通道数、长度和
SHA-256。离线审计逐通道统计非零样本、峰值、RMS、两通道相同样本数，并核对生产单声道
实际映射到哪一路。该证据只能回答原厂接口本次实际返回的输出形状，不能把两路输出解释为
四个独立麦克风，也不能证明AEC消除量或DSP质量。v81主机代码尚未部署到R1。

v81统一主机检查通过：Android 171项、lint、native工具32项、R0恢复73项与桌面演练、
原厂代理/策略/ABI/离线审计50项、HA 44项、配置加载、公开审计和API 22 ARMv7交叉构建。
hostcheck APK SHA-256为
`517b3fa7dc46d5cba801a7e51099bd93cb9e5f6f1e0aa12a7ac5b32b443676a7`，ARMv7代理
SHA-256为`d06325edb1b048bec990c822a015986b762a27263cc8d5ffd0e9a7ad337e5843`。
两者均为主机产物，未签名为设备候选，也未连接ADB或HA。

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

默认仍按 R0 手册完成完整 eMMC、低层入口和受控回刷。用户针对首台boot风险豁免时，只有
外部风险记录、原厂boot基线、ABI和预检全部匹配，私有overlay渲染器才生成暂存目录；它
本身永不刷机。2026-09-10新增的boot基线门禁会复读
私有kernel/boot/recovery双份文件及其来源证据，并把固定公开参考和私有清单哈希写入overlay
清单，详见[原厂boot/recovery离线基线](2026-09-10-r1-boot-recovery-baseline.md)。

后续决策：用户于2026-09-10接受仅`r1-sample01`、仅boot范围的不可恢复变砖风险。R0仍为
`pending`；渲染器只在外部风险记录精确绑定设备、原boot哈希和范围时接受该状态。代理现支持
init继承socket；固定策略工具只改写未加载的policy v26副本，boot构建器保持kernel、DTB、
second、地址和页大小不变。详见[boot-only风险实验](2026-09-10-r1-boot-only-risk-experiment.md)。

2026-09-11后续开发改按[免拆分级授权](2026-09-11-r1-no-disassembly-authorization.md)：当前
首台和3448基线在较低权限路线有可复现实机不足证据后，可按目标分区双读、候选固定、单次
写入和复位前读回门禁使用必要的boot/system/recovery修改。现有overlay渲染器和boot写入器
并未因此自动获得system/recovery能力；真正需要时必须先实现同等级失败关闭工具并完成主机
测试。Loader、分区表、物理首4 MiB、擦除、格式化和整盘覆盖仍须另行授权，R0保持`pending`。

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
  --device r1-sample01 --wav <local-wav> \
  --diagnostic-wav <local-diagnostic-stereo-wav> --metadata <local-meta> \
  --output <new-local-report.json>
```

旧v80采集没有诊断旁路，继续省略`--diagnostic-wav`即可复核；其报告会继续将运行时通道形状
列为未验证。v81必须同时拉回三个文件，缺少或篡改双通道旁路时审计拒绝。

v82可选地在同一个有界窗口内播放受控本地参考。参考文件必须已经位于应用自己的
`diagnostics`目录，格式为16 kHz、单声道、S16LE WAV；窗口必须比参考至少长2秒。触发前
先把`STREAM_MUSIC`设为受测档位，命令增加：

```bash
--es playback_reference_path <diagnostics内参考文件名>
```

采集固定保留1秒前导和至少1秒尾段，并记录设备实际媒体音量index/max，而不相信命令行
声称的百分比。拉回原参考文件后，离线审计增加：

```bash
--playback-reference-wav <local-reference-wav>
```

审计会核对参考SHA-256、长度、格式、音量换算及播放单调时钟完全位于采集窗口内。该pass
仅证明同次采集确实包含受控本机播放，不能单独证明硬件参考覆盖或AEC消除效果。

完成四个等距离、相同声源和音量的方向采集后，先分别运行上述单次审计。再复制
`tools/factory_audio/templates/doa-direction-matrix.example.json` 到仓库外，填写四份审计
报告的相对路径，并执行：

```bash
python3 tools/factory_audio/audit-doa-direction-matrix.py \
  --manifest <local-direction-manifest.json> \
  --output <new-local-direction-report.json>
```

矩阵审计要求四次采集的DOA有效帧比例至少80%、圆形集中度至少0.5，并在拟合设备未知
零度偏移后把各方向残差限制在45度以内。阈值只用于拒绝无变化、发散或方向错误的DOA
证据，不替代技术方案第14章指标。输出的`pass`边界固定为“四方向上报DOA相对响应”；
它不证明四支麦克风各自响应，也不证明AEC消除量或DSP质量。原始录音、单次报告、矩阵
清单和矩阵报告均保留在仓库外。

## 2026-09-11实机结果

首个v2候选使用标准Android boot ID且ramdisk未按4字节对齐，被原厂U-Boot SHA检查拒绝并
进入recovery；两次均从Loader读回确认候选后写回原boot并复核哈希。构建器随后按同代
Rockchip `SecureNSModeBootImageShaCheck` 算法把tags/page/unused/name/cmdline纳入SHA-1，
并强制ramdisk四字节对齐。修复后的候选正常进入Android且保持Enforcing。

根据实机AVC逐项建立专用域启动、rootfs入口、Android 5 linker、logd、socket和audio设备
权限；没有开放网络、块设备、Permissive或shell执行。最终v13 boot SHA-256为
`09c89752f388bf09797251c819f7629a39f5ac5a24e93df7a5995154e187a787`，ARMv7代理SHA-256为
`4a2e7e8d4be302cd4e87bac88a838bccdc2f1058cccaa20762e0202133e13be0`。

v80设备APK SHA-256为`5883f28d2eb11aed9b6b14581b848b2b1fd628a876e4628f813f8a3bc6876b35`，
与v79证书SHA-256 `0be7a3643442658354c185ec53cb50e73bc1516a56f2760ca46f2c932c1d2639`
一致。最终10秒采集500帧、0序列缺口、0代理丢帧、500帧有效DOA；PCM共320,000字节且非零。
离线审计结果为pass，私有报告SHA-256为
`961f6b2f80b41584e0861105433b8bf624c442f343b16af919524f37298d57be`。该pass仍固定保留四麦
独立响应、运行时通道形状、AEC消除量和DSP质量为未验证，不放行生产采集。

## 2026-09-11 v82主机增量

提交`519def937b28b095dbfd0e63ea17cb7e6ed30e9e`实现上述受控播放同步采集。正式
`tools/factory_audio/check.sh`通过56项；新增Java纯逻辑JUnit 4项使用缓存API类库完成
Java 8定向编译和运行。首次运行时未发现Android SDK路径，故当时完整Gradle入口在解析SDK
位置停止。

同日后续在提交`76a2b4fba029a50d6bc090cae93e8cd691ff9b36`发现并固定本机SDK/NDK路径后，重新执行
`python3 tools/dev/prepare.py`及离线`bash tools/dev/check.sh`。统一检查通过Android 171项、
lint与hostcheck构建、native 32项、R0恢复73项及桌面演练、原厂音频56项、HA 44项和
HA 2026.8.2容器配置加载；公开扫描361项0发现，凭据扫描无泄漏。随后省略`hostCheck`
再次执行`testDebugUnitTest lintDebug assembleDebug`，生成包名`dev.sewellzhong.r1probe`、
versionCode 82、min/target SDK 22的设备APK。v1/v2签名验证通过，证书SHA-256与v79一致为
`0be7a3643442658354c185ec53cb50e73bc1516a56f2760ca46f2c932c1d2639`，APK SHA-256为
`b115b5077da502a7fbe9efd8a21e2cee6c2e5ae084e8c176d8ace79d52db1c73`。候选仅保留在被忽略的
本地`test-results/2026-09-11-r1-sample01-v82-candidate/`，不提交含私有提示音的APK。

本次重建的ARMv7代理SHA-256仍为
`d06325edb1b048bec990c822a015986b762a27263cc8d5ffd0e9a7ad337e5843`，与v81主机基线一致；但设备
当前v13 boot内仍是v80代理
`4a2e7e8d4be302cd4e87bac88a838bccdc2f1058cccaa20762e0202133e13be0`。双通道诊断旁路由代理提供，
所以实机采集前仍须以双份一致的当前boot为输入生成固定候选，并执行身份/范围核对、boot双读、
单次写入和复位前完整读回门禁。没有连接ADB、没有修改boot、没有安装APK或采集录音；v82运行时
通道形状、播放参考覆盖、AEC消除量、四麦独立响应及DSP质量仍待实机验证。
