> 历史记录：本文版本、命令及“下一步”反映记录当时状态；当前排期以[根 README](../README.md)为准。原始产物迁移见[归档说明](../test-results/README.md)，原验收结论不变。

# R1 sample01：隔离诊断与开机保护

最新进展：版本46已通过非root隐藏方案与三次重启恢复，见 [最新报告](./2026-09-06-r1-nonroot-isolation.md)。本文保留版本45当时的失败与保护证据。

后续更新：用户允许一次标准临时 ADB root 探测后已实际执行，未取得root，重启后恢复shell。见 [探测报告](./2026-09-06-r1-standard-root-probe.md)。下文“尚未尝试”描述的是版本45交付时的历史状态。

## 交付边界

版本45增加原音频包状态检查和部署权限核验。它防止已知未隔离状态下开启音频，**没有实现持久隔离**。两包进程完全退出仍是第一优先级，音频独占是待验证的后备路线。Root 已纳入候选，但没有执行提权。

当前原生协议、HA 中文流水线和认证配置沿用版本44。临时隔离仍可收音；设备重启后原包恢复时，服务保留管理与 HA 连接，保存 `audio_blocked` 和 `factory_audio_not_isolated`，等待明确重试。

## 实现

- `FactoryAudioIsolation` 使用 API22 包状态与进程信息检查两个原包及其子进程。包禁用且无进程记为 `packages_disabled`；仅 force-stop 且无进程记为 `temporary_force_stop`，不把后者当作持久隔离。包可启动、进程存在或无法确定状态时拒绝音频。
- 服务启动、等待 HA、每次连接和监听期间均检查隔离；打开录音、TTS 播放和唤醒回应前再次检查。检查不会修改其他包，存在并发启动的观察窗口，因此仍不能替代系统层持久隔离或证明音频独占。
- 状态增加 `factory_isolation`；阻断原因区分原包未隔离与后端停止阻塞。原包退出不会自动清除阻断，管理员显式 `start --listen` 后重新核验。
- `deploy-r1-native.py diagnose` 只读核对固件、备份与现装包哈希、实际 ADB UID、调试属性、进程和 `run-as`。`ro.debuggable=1` 只记录为候选，不报告 root 成功。
- `commit` 不再用 shell 权限声明代替能力验证。先按原值执行包状态写入并核验明确成功结果与状态回读，再停用两包。DEFAULT 状态使用已有 API22 helper；未确认权限时停止。停用后进程未退出也进入恢复处理。该持久切换路径尚未在有权限的 R1 上通过。

## 验证与证据

证据目录：`test-results/2026-09-06-r1-sample01-isolation/`。

实际执行：

```sh
JAVA_HOME=/home/developer/.sdkman/candidates/java/17.0.19-tem ANDROID_SDK_ROOT=/home/developer/.local/share/android-sdk android/r1-probe/gradlew -p android/r1-probe --no-daemon testDebugUnitTest lintDebug assembleDebug
python3 -m unittest discover -s tools/native/tests -v
python3 -m py_compile tools/native/deploy-r1-native.py tools/native/check-isolation-boot.py
python3 tools/native/deploy-r1-native.py diagnose 192.0.2.10:5555 --evidence test-results/2026-09-06-r1-sample01-isolation
python3 tools/native/deploy-r1-native.py install 192.0.2.10:5555 --evidence test-results/2026-09-06-r1-sample01-isolation
python3 tools/native/check-isolation-boot.py 192.0.2.10:5555 --evidence test-results/2026-09-06-r1-sample01-isolation --reboot
```

- Android 构建、lint 和113项原有单元测试通过；部署工具新增7项回归检查通过，包括权限失败、空成功输出、状态回读不一致、隐藏系统包状态误判和恢复失败不得启动原服务。
- 版本44 APK 已保存为本轮回退基线；两个原包当前 APK 均与备份一致。阶段0清单中的13个备份文件校验通过。
- 初次重启测试发现阻断状态直到 HA 连接才出现，测试未通过，证据保留在 `boot-guard-initial.json`；修复将检查提前到服务启动阶段。
- 最终重启保护复测通过，结果见 `boot-guard.json`；临时隔离下帧增长见 `temporary-capture.json`。此测试只验证开机保护，不计入持久专用部署三次重启验收。
- 首次构建命令使用了不存在的 JAVA_HOME，未启动构建；修正为上面的 `17.0.19-tem` 后通过，最终构建日志见 `build.log`。

## 恢复与下一步

已验证的临时恢复命令为 `deploy-r1-native.py restore`，使用本轮 evidence 目录。该命令停止卫星监听、恢复原包启用状态并检查原服务进程；它不是整机回刷验证。`rollback` 还可使用本轮保存的版本44 APK，但本轮未再次执行 APK 降级验证。

临时开发可使用同目录的 `isolate`，确认两包退出后执行 `manage-r1-native.py start ... --listen`。上述操作不修改包启用状态，重启后仍会失效。

实际诊断：ADB UID2000，SELinux Enforcing，`ro.debuggable=1`；语音包 `run-as` UID10008，播放器不支持。尚未验证标准 `adb root` 是否可用；也没有证明语音包能通过自身 UID 修改并恢复启用状态。导出 EchoService 停止后能否释放所有子播放器和音频资源仍未验证，不能直接选为独占方案。

`AGENTS.md` 要求获取 root 前确认设备、固件并完成可验证的备份与回刷方案。现有阶段0记录明确未验证 Loader/Maskrom 和实际回刷，现有 OTA 来源为增量包；不能把 APK/音频备份当作完整固件恢复材料。因此本轮未执行 `adb root`、漏洞提权、原包覆盖或分区写入。后续需要补齐恢复路径，或由用户明确调整标准临时 ADB root 探测的准入条件。不能仅因用户同意考虑 root 就记为恢复前提已满足。

持久隔离确定后，再验证三次重启、真人中文交互、网络恢复和72小时稳定性；本轮没有启动72小时验收。

最终安装 APK SHA-256：`a4a8f539ed333eab6dbe9323dd0c0df03526aad14be171f1bfb0f7135ce99a6d`，已与实机文件核对。最终恢复为临时隔离、`listening`、实际帧增长，见 `final-runtime.json`；重启仍需隔离后明确重试。

若恢复前提得到满足，或用户明确豁免本次标准临时 root 探测的该前提，下一项具体操作限定为：核对设备后执行一次 `adb -s 192.0.2.10:5555 root`，重连读取实际 `id` 与 SELinux 状态，不以输出提示判定成功；随后普通重启并核验恢复 UID2000。不能假定此旧固件支持 `adb unroot`，网络连接若无法恢复需现场断电重启。本探测不包含修改包状态、安装 su、修改 SELinux、刷机或分区写入；这些操作不会由 root 成功自动触发。以上探测本轮尚未执行。
