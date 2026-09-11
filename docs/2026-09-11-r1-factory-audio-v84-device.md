# R1 v84 特权原厂调试窗口实机记录（2026-09-11）

## 结论

`r1-sample01` 已按免拆分级授权部署 v15 boot 与 v84 APK。boot 现场双读、单次写入、
复位前完整读回、Android 启动、Wi-Fi、ADB 与 SELinux Enforcing 均通过；APK 原签名覆盖安装
及设备端回读哈希也通过。v84 的协议与 boot 双开关实际生效，5 秒验证采集返回 250 帧、
0 序列缺口、0 代理丢帧和 250 帧有效 DOA。

原厂 `waking/waked` 的 `4mic/2aec/out` 固定文件仍未生成。采集元数据明确记录
`vendor_debug_files_requested=true`、`vendor_debug_files_active=true`，因此本次不是开关未启用。
同一窗口的内核 AVC 给出可复现边界：`mediaserver` 对
`vfat:/sdcard/unidata` 的目录写入被 Enforcing 拒绝；代理调用原厂辅助逻辑时对
`shell_exec` 的执行也被拒绝。当前结论是“特权调用与采集通过、原厂落盘失败”，不能计算
AEC 消除量，R3 与 R0 状态均不改变。

## boot 与 APK 门禁

- 写前当前 boot 两份 SHA-256：
  `53911d71787d3e8f4dc9b31b73b0b4dafde569d30795023a2712a43bcb5e7110`
- v15 候选及写后读回 SHA-256：
  `29dcdb3bdcf85a15a875c6f87a100b9799a57323b111f8223449f9387a12b77e`
- v84 ARMv7 代理 SHA-256：
  `9be23acfd2c78d90549a9f801610f46ab2f93f2c50155e75a38a955ff37a87ce`
- v84 APK 候选及设备回读 SHA-256：
  `f62e058d308495f5165f9e402b023ecfcf8e5b10104197155a0c5c43e789216c`
- APK versionCode 84、API 22、v1/v2 签名通过；证书 SHA-256 与 v82 一致：
  `0be7a3643442658354c185ec53cb50e73bc1516a56f2760ca46f2c932c1d2639`

本轮还修复了增量 boot 构建器的链式清单契约：旧增量清单只记录输入 overlay，导致下一轮
无法证明嵌入代理的来源。新逻辑要求旧代理、前一候选代理和当前 boot 三者形成完整哈希链，
并为新候选写出明确的有效 overlay 哈希；不会放宽 ramdisk 内容检查。

## 5 秒窗口与数据处置

设备端原厂固定目录在录音前为空，关闭后两次快照仍为空。应用侧验证输出已拉到仓库外，
三份文件 SHA-256 与元数据自报一致，随后从设备精确删除；没有把家庭录音、原厂二进制、
私有 boot 或 APK 提交到仓库。工具最终恢复卫星为 `listening`、`audio_opened=true`、连接数 1、
失败数 0；原厂 device/player 包继续保持隐藏。

新增的 v84 专用探测器使用受 `android.permission.DUMP` 保护的显式广播，只接受当前
versionCode 与 APK 哈希。它继续执行固定文件名、空目录前置、关闭后稳定、拉取哈希、精确
删除和完整监听恢复门禁，并补充应用侧三份输出的自动拉取与删除。

## 已运行检查与下一入口

```bash
ANDROID_SDK_ROOT=/home/sewellzhong/.local/share/android-sdk \
  R1_GRADLE_OFFLINE=1 bash tools/factory_audio/check.sh
ANDROID_SDK_ROOT=/home/sewellzhong/.local/share/android-sdk \
  R1_GRADLE_OFFLINE=1 android/r1-probe/gradlew -p android/r1-probe \
  --no-daemon testDebugUnitTest lintDebug assembleDebug
python3 -m unittest \
  tools.factory_audio.tests.test_boot_agent_update \
  tools.factory_audio.tests.test_privileged_vendor_debug_probe
```

统一检查通过 Android 单元测试/lint/hostcheck、native 32 项、R0 73 项与演练、原厂音频
85 项、HA 44 项及 HA 2026.8.2 配置加载；新增定向 18 项也通过。实机写入与录音证据仅
保存在仓库外。

下一步不重复当前录音。先依据本次 AVC 为临时诊断 boot 增加最小专用 Enforcing 规则，优先
验证 Android 5.1 策略是否能用固定文件名 transition 限制 `mediaserver` 的创建范围；不能时
必须明确记录扩大到 `vfat` 类型的临时权限风险。策略仍只服务显式短时请求，取得证据后应
恢复不含该诊断权限的生产 boot。完成策略主机编译、boot 双读和写后读回门禁后，再运行一次
短时同窗口采集；在得到非空且格式可校准的 `4mic/2aec/out` 前不计算或宣称 AEC 通过。
