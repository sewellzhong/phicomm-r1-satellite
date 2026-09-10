# r1-sample01 原厂链受控运行记录（2026-09-08）

## 范围与安全条件

本轮只在首台 `r1-sample01` 上临时解除
`com.phicomm.speaker.device/player` 隐藏状态，未 Root、未修改 SELinux、boot、system
或 eMMC 分区。执行前后均验证局域网网关可达，而公网 IPv4、IPv6、TCP 443 和 HTTP
被路由器拒绝。每轮先释放 v79 的录音所有权，结束后重新隐藏原包并恢复 v79；最终状态为
`listening`、`audio_opened=true`、`factory_isolation=packages_hidden`，外网阻断复检通过。

现场证据及可能包含家庭环境音的文件只保存在仓库外的本地私有目录
`/opt/_agents/private-r1-audio/`，不提交公开仓库。当前生效应用层是已确认经过第三方修改的
覆盖包，以下结论只把底层库、HAL、配置和 DSP 称为原厂 3448 组件，不把完整应用体验称为
纯原厂。

## 工具实现

新增 `tools/factory_audio/run-original-chain-smoke.py`，要求显式确认设备、WAN 阻断和录音，
且只允许将结果写到仓库外的新建私有目录。工具执行只读预检、覆盖 APK 哈希确认、调试文件
备份、卫星音频释放、限时原厂窗口、按 PID 收集日志和 WAV 元数据，然后无条件恢复隔离、
v79 与 WAN 检查。它拒绝未知调试路径和仓库内输出，不会把原厂 APK、库或音频复制进仓库。

工具曾在旧 Android ADB 上错误地把远端文件存在性判为不存在；修复后改为单一远端 shell
条件并增加回归测试。缺陷发生时删除了 3 个 44 字节空 WAV 头和 3 个 0 字节占位文件，
其中没有语音帧，设备上不可恢复。本轮没有删除有效家庭录音，但此偏差仍作为工具缺陷保留。

## 真机结果

最终真实唤醒窗口使用覆盖包内确认的“小讯小讯”只作为原厂 HAL 状态触发，不属于恢复 KWS
训练、选型或声学验收。相同原厂进程的限时日志满足工具全部严格运行证明项：

- `UNI_4MIC_HAL_ANDROID_V1.1`，`use_4mic=1`；
- `uni_hal_4mic_array_init sucess`，MicArray 版本 `v2.3.0`；
- `mic_num=4`、`echo_num=2`、`aec_on=1`；
- `AudioSourceImplopenIn uni4micHalJNI status = 0`；
- 真机产生“小讯小讯”唤醒事件，断网后按预期进入网络失败分支。

这证明 3448 原厂四麦 HAL/MicArray 配置并非只存在于文件系统：恢复的语音进程实际完成了
私有音频源初始化并能从真人输入到达唤醒事件。它仍不证明四路各自的波形响应、DOA 数值、
AEC 实际消除量、波束输出质量或 DSP 声学效果达到验收指标。

真实唤醒后生成了六个预期调试文件。`waked_file_4mic.wav` 是 16 kHz、16-bit、4 声道的
44 字节空 WAV 头，`waked_file_2aec.wav` 与 `waked_file_out.wav` 是 16 kHz、16-bit、2 声道
空 WAV 头；三个 `waking_*` 为 0 字节。所有文件帧数均为 0，因此自动结果正确保持
`no_valid_factory_audio_artifacts`，不能把成功码、日志配置或空头替代为实际处理音频证明。

## 当前判定与下一入口

原厂链“可在当前 3448 真机初始化并接收真人唤醒”从待验证更新为部分通过；实际 PCM、DOA、
AEC、波束和 DSP 效果仍为待验证。非 Root 原厂应用调试文件路线到此停止重复尝试，不将空文件
解释为路线失败或降级依据。

下一步严格进入 R0：完成完整 eMMC/实际区域备份、用户已接受的单主机明文例外记录、低层
恢复入口和一次受控完整回刷。只有 R0 得到 `pass_with_exception` 后，才渲染和部署已实现的
受限特权代理，由代理正常调用原厂 close/release 并取得实际帧、DOA及播放参考，再按 R3 做
同条件对照和声学验收。R0 前继续保持 v79、原包隐藏、SELinux Enforcing，不修改永久分区。
