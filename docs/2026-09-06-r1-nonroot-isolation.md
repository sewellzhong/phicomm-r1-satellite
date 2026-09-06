> 历史记录：本文版本、命令及“下一步”反映记录当时状态；当前排期以[根 README](../README.md)为准。原始产物迁移见[归档说明](../test-results/README.md)，原验收结论不变。

# R1 sample01：非 root 持久隔离

## 结果

版本46采用 Android 用户级 `hide/unhide` 隔离 `com.phicomm.speaker.device` 和 `com.phicomm.speaker.player`。本机普通 shell 可执行该标准管理接口，不需要 root。两包 APK 和数据保留，启用状态仍分别为1和0，用户0隐藏状态为true；两包及其子进程均退出。

两包隐藏、解除隐藏恢复均已在R1验证。版本46连续三次普通重启后，两包仍隐藏且无进程，卫星自行恢复连接和真实收音，分别耗时31.14、36.63、40.75秒。这些时间从发出重启命令计到第二个增长的音频帧样本，并包含ADB观察间隔；不是语音响应延迟，也不代表量化稳定性总验收。

这解决了原包在重启后恢复的已知阻塞。完整真人中文问答、网络/IP变化、HA重启在当前配置下的恢复，以及72小时稳定性仍未在本轮验收。没有再次执行 root 探测、刷机或改写原包/音频底层。

## 路线选择与失败证据

- 从卫星UID停止导出主服务时，显式指定 `--user 0` 后两个调用均返回成功；WindowsService约2秒后重新启动，播放器 NetPlayer、DLNA、AirPlay 子服务仍在。不能用于持续隔离。
- 语音包可用 `run-as` 以自身UID停用，进程立即退出；但一次普通重启后启用状态恢复为1，语音进程也回来。失败后已用同一入口恢复原状态，未采用该路线。没有把该现象确定归因于厂商代码或写盘时序。
- 发现 shell 持有 `MANAGE_USERS` 后，先验证原值 `unhide` 接口，再验证隐藏、重启保持和解除隐藏恢复。它与 `disable-user` 的权限要求不同。[Android 5.1 包管理实现](https://raw.githubusercontent.com/aosp-mirror/platform_frameworks_base/android-5.1.1_r38/services/core/java/com/android/server/pm/PackageManagerService.java)

## 实现与回退

`FactoryAudioIsolation` 在API22读取系统定义的 `FLAG_HIDDEN`，同时要求应用仍安装并确认没有两包及其子进程。状态为 `packages_hidden` 才按此路线允许音频；读取失败仍阻断。字段按系统名称反射取得，未硬编码位值；其他API版本不自动接受这条隐藏路线。[API22 字段定义](https://raw.githubusercontent.com/aosp-mirror/platform_frameworks_base/android-5.1.1_r38/core/java/android/content/pm/ApplicationInfo.java)

`deploy-r1-native.py` 新增 `hide`，安装基线保存隐藏状态。隐藏前核对设备/固件、原APK备份与现装哈希、原状态和解除隐藏入口；操作后回读隐藏状态、确认进程退出并重新核对APK。部分失败会先停止卫星音频，再解除已完成的隐藏。恢复等待卫星录放资源释放后，才允许原包恢复，避免重现音频竞争。隐藏包的 `pm path` 可能为空，此时从已校验的包管理记录定位同一安装APK。

当前配置的查看和恢复：

```sh
python3 tools/native/manage-r1-native.py status 192.0.2.10:5555
python3 tools/native/deploy-r1-native.py restore 192.0.2.10:5555 --evidence test-results/2026-09-06-r1-sample01-nonroot-isolation
```

`restore` 会停止卫星、解除本次隐藏并恢复原包启用状态与服务，已实测。恢复后重新采用卫星配置：

```sh
python3 tools/native/deploy-r1-native.py hide 192.0.2.10:5555 --evidence test-results/2026-09-06-r1-sample01-nonroot-isolation
python3 tools/native/manage-r1-native.py start 192.0.2.10:5555 --listen
```

应使用本次基线目录，旧基线不记录隐藏状态。若两包已隐藏，不必再次执行 `hide`。版本45 APK 已另存为本次安装回退基线；本轮未重复执行APK降级测试。用户级隐藏恢复已验证，不等于完整固件回刷已验证。

## 验证与证据

证据目录：`test-results/2026-09-06-r1-sample01-nonroot-isolation/`。

- `service-stop.json`：首次命令的默认跨用户错误；`exported-service-stop/service-stop.json`：指定用户0后实际停止与恢复情况。AudioFlinger快照仅为资源元数据，没有保存录音。
- `voice-disable-restore.json`：自身UID停用、重启后恢复及回退，判定失败。
- `hide-probe.json`：隐藏、重启保持、解除隐藏恢复成功。
- `tool-restore.json`、`tool-hide.json`：新部署工具实测。
- `three-reboots.json`：三次重启时仅观察，不执行 `start` 或修复动作；检查原包状态/进程、设备身份以及连续音频帧增长。
- `hidden-audio-health.json`：当前隔离条件下的1秒真实采集及200毫秒播放头排空检查；不保存样本，不声称已经由人确认可闻性。
- `final-runtime.json`：最终实际收音与原包哈希；`summary.json`：结果汇总。

执行的自动检查：

```sh
JAVA_HOME=/home/developer/.sdkman/candidates/java/17.0.19-tem ANDROID_SDK_ROOT=/home/developer/.local/share/android-sdk android/r1-probe/gradlew -p android/r1-probe --no-daemon testDebugUnitTest lintDebug assembleDebug
python3 -m unittest discover -s tools/native/tests -v
python3 -m py_compile tools/native/deploy-r1-native.py tools/native/check-persistent-isolation.py
python3 tools/native/check-persistent-isolation.py 192.0.2.10:5555 --evidence test-results/2026-09-06-r1-sample01-nonroot-isolation --reboot
```

Android113项单元测试、lint和构建通过；部署工具15项测试通过，覆盖隐藏状态回读、非目标包拒绝、部分失败恢复、恢复前音频释放和已隐藏基线不得启动原服务。最终APK SHA-256：`04e2909f2403cacb7dc9972edb02a4b969cbaf088d5d97a716a2d00cf3e69b1d`。
