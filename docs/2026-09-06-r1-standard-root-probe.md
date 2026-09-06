> 历史记录：本文版本、命令及“下一步”反映记录当时状态；当前排期以[根 README](../README.md)为准。原始产物迁移见[归档说明](../test-results/README.md)，原验收结论不变。

# R1 sample01 标准 ADB root 探测

后续进展：版本46通过非root `hide/unhide` 持久隔离及三次重启恢复。最新状态见 [非root隔离报告](./2026-09-06-r1-nonroot-isolation.md)；本文保留当时的实机结果。

2026-09-06，用户明确允许在整机恢复路径尚未验证的条件下，执行一次标准 `adb root`、核验身份，再普通重启核验恢复。本次豁免仅覆盖该探测，不代表完整固件恢复前提已满足。

## 实机结果

目标 `192.0.2.10:5555`，`rk322x_echo`，API22，固件3448。探测前核对两个原音频包当前 APK 与已有备份一致。

| 时点 | 实际 UID | SELinux | service.adb.root |
| --- | --- | --- | --- |
| 探测前 | 2000 / shell | Enforcing | 空 |
| 一次 adb root 并重连后 | 2000 / shell | Enforcing | 1 |
| 普通重启后 | 2000 / shell | Enforcing | 空 |

命令输出为 `restarting adbd as root`，但真实身份仍为 shell。**本次标准 ADB root 未取得 root 权限。** 不据此声称所有提权方式均不可行，也不确定归因为某个编译选项或厂商实现。

实际执行的核心命令：

```sh
adb -s 192.0.2.10:5555 root
adb connect 192.0.2.10:5555
adb -s 192.0.2.10:5555 shell id
adb -s 192.0.2.10:5555 shell getenforce
adb -s 192.0.2.10:5555 shell getprop service.adb.root
adb -s 192.0.2.10:5555 reboot
```

重启后重连并复查设备、固件、`sys.boot_completed`、UID、SELinux 和调试属性。未重复尝试 root，未安装 su、使用漏洞、改变 SELinux、修改原包启用状态、覆盖原包或写分区。

## 恢复与后续

重启后原包恢复，卫星开机保护进入 `audio_blocked`，未打开麦克风。随后使用既有已验证的临时 `isolate` 和 `start --listen` 恢复开发运行；这仍不构成持久隔离。

原包完全退出仍优先，但目前没有经过实机验证的双包管理权限。下一步可调查非 root 服务停止路径：语音包自身 `run-as` 能力，以及导出 EchoService 停止后的子进程、音频资源和重启行为。不得将停止服务成功直接当作音频独占。其他 root 路线需要独立评估，不属于本次豁免。

证据：`test-results/2026-09-06-r1-sample01-root-probe/root-probe.json`、`after-reboot-runtime.json`、`final-runtime.json`。本轮没有修改 APK 或实现代码，未重复构建；验证是实际设备身份、重启恢复和真实收音帧增长。
