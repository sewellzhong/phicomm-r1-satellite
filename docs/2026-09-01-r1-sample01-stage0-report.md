> 历史记录：本文版本、命令及“下一步”反映记录当时状态；当前排期以[根 README](../README.md)为准。原始产物迁移见[归档说明](../test-results/README.md)，原验收结论不变。

# R1 真机 r1-sample01 阶段 0 实机盘点报告

- 日期：2026-09-01
- 设备 ID：r1-sample01
- 盘点方式：免拆、局域网 ADB
- 结论：免拆独立 APK 准入通过，可以进入音频真机开发与验证；不需要为当前路线拆机或刷机。

## 能力表

| 项目 | 实机结果 | 判定 |
| --- | --- | --- |
| 主控/ABI | Rockchip RK3229，ARMv7，`armeabi-v7a` | 符合预期 |
| 内存 | 约 512 MB | 符合轻量 APK 路线 |
| 系统/API | Android 5.1.1，API 22 | 符合兼容基线 |
| 固件 | 增量版本 3448，release-keys | 已固定记录 |
| ADB | 局域网 TCP 5555 可连接 | 通过 |
| Android root | 普通 `shell`；无 `su`；SELinux Enforcing | 未取得，当前准入不依赖 root |
| Loader/Maskrom | 未测试 | 免拆路线已通过，不执行拆机测试 |
| APK 安装 | 标准 `adb install` 挂起；显式调用 `pm.jar` 安装成功 | 通过，但必须使用兼容入口 |
| APK 覆盖升级 | versionCode 1 升级到 versionCode 2 成功 | 通过 |
| APK 启动 | Activity 启动成功，Logcat nonce 验证通过 | 通过 |
| ADB 重连持久性 | 重连后包仍存在，versionCode 2 可再次启动 | 通过 |
| 音频枚举 | `RK_MA4` 四麦采集、`RK_AK7755` 播放/采集节点存在 | 仅枚举通过，未代表录放音/AEC 通过 |

## 备份与证据

- 首轮系统、原厂 APK、音频配置和 Audio HAL 备份：[`test-results/2026-09-01-r1-sample01/stage0/`](../test-results/README.md)
- 首次安装与启动：[`test-results/2026-09-01T223930-r1-sample01/stage0/apk-install/`](../test-results/README.md)
- versionCode 2 覆盖升级及重连验证：[`test-results/2026-09-01T224107-r1-sample01/stage0/apk-install/`](../test-results/README.md)
- 最终安装脚本复测：[`test-results/2026-09-01T224236-r1-sample01/stage0/apk-install/`](../test-results/README.md)
- 3448 音频底层与第三方覆盖层审计：[`test-results/2026-09-02T012609-r1-sample01/stage0/provenance/`](../test-results/README.md)

当前备份不是完整 eMMC 固件备份，也没有验证实际回刷。由于免拆、独立包名路线已通过，当前不执行拆机、root、停用原厂包或刷机。

## 当前 APK 来源复核

- 复核日期：2026-09-02
- 方法：只读查询 Package Manager 路径与版本、读取文件头和 ZIP 偏移、计算 SHA-256、使用 Android Build Tools `apksigner` 检查 v1 签名，并对前置 DEX 做字符串检查。
- 总结：当前真机不是纯原厂应用层，而是原厂系统基础 APK、第三方修改更新包和本项目真机调试 APK 的混合状态。

| 包名/基础文件 | 当前或系统路径 | SHA-256 | 结构与签名结果 | 判定 |
| --- | --- | --- | --- | --- |
| `com.phicomm.speaker.device` | `/data/app/com.phicomm.speaker.device-1/base.apk` | `d98ff6aeab80c562498f42b45ddf4bb58eae318d64e47cecca7355799cee6542` | 文件从 `dex\n035` 开始，首个 ZIP 头位于偏移 5,425,132；现代 `apksigner` 不通过 | **确认第三方修改** |
| `com.phicomm.speaker.player` | `/data/app/com.phicomm.speaker.player-1/base.apk` | `eee63585effda9697c6fb1da5ae82ddf0fc41566aa8462841e407f15aae6fdc8` | 文件从 `dex\n035` 开始，首个 ZIP 头位于偏移 5,707,780；后部 v1 APK 仍显示斐讯 R1 证书 | **高度确定第三方修改** |
| `dev.sewellzhong.r1probe` | `/data/app/dev.sewellzhong.r1probe-2/base.apk` | `784f676d0c3e873ae10fa0df35b3c4f49266cc8dc2c396400ca22a925772e947` | 标准 ZIP APK，Android Debug 证书 SHA-256 为 `0be7a3643442658354c185ec53cb50e73bc1516a56f2760ca46f2c932c1d2639` | 本项目真机调试 APK |
| `EchoService.apk` | `/system/app/EchoService/EchoService.apk` | `6245d3632ca4530c28b8ab64ed5885870434afc8fc1ede84a795e855745cbdf8` | SHA-1 `e496...c442` 与 3448 OTA 目标一致 | **确认 3448 系统基础文件** |
| `Unisound.apk` | `/system/app/Unisound/Unisound.apk` | `a0548242414666d27df9b099e85ab69697cc5c1599f019ce34dd2460f8841bd7` | SHA-1 `3958...53b3` 与 3448 OTA 目标一致 | **确认 3448 系统基础文件** |

`com.phicomm.speaker.device` 的前置 DEX 中直接出现 `com.phicomm.speaker.device.custom.*` 类，以及[恩山论坛 `thread-6445368-1-1.html`](https://www.right.com.cn/forum/thread-6445368-1-1.html) 链接；该页面标题明确描述基于 3448 版本修改小讯。因此该包不是未经修改的原厂执行代码。`com.phicomm.speaker.player` 同样是前置 DEX 加后置 APK 的双重结构，前置代码规模和类集合明显不同于系统 `EchoService.apk`，且包含较新的 ExoPlayer 类，故判为高度确定经过第三方修改。

设备安全补丁级别为 2016-04-01，而 [Android 官方 2017 年 12 月安全公告](https://source.android.com/docs/security/bulletin/2017-12-01)将 CVE-2017-13156 列为影响 Android 5.1.1 的签名处理漏洞。这类文件可以让后部 v1 签名继续显示原厂证书，同时由运行时读取前部 DEX；所以“版本号相同”或“v1 签名仍通过”不能证明实际执行代码仍为原厂代码。

后续使用带斐讯 R1 OTA 证书的公开 3415→3448 增量包固定来源，对系统基础 APK、Audio HAL、四麦库及 AK7755 data2 固件完成逐文件目标哈希核对，八项全部匹配。该结论确认关键音频底层文件属于 3448 目标，但普通 ADB 仍不能证明 boot/eMMC 所有字节从未被重打包。完整第三方 APK 不提交到仓库；这里只保留可复核的路径、哈希、结构和签名摘要。

## 已知偏差与下一步

- 固件 3448 的 `/system/bin/pm` 包装入口会关闭或扰动 ADB shell，标准 `adb install` 会持续等待设备。
- 可复现的兼容入口为 `CLASSPATH=/system/framework/pm.jar app_process /system/bin com.android.commands.pm.Pm ...`；安装脚本在标准入口 15 秒超时后自动使用该入口。
- 当前两个核心音频包由 `/data/app` 中的第三方修改版本覆盖系统基础 APK；后续不能将其行为直接归因于纯原厂应用层。
- 下一步将现有独立调试 APK 扩展为音频真机开发版本，先做 10 秒 PCM S16LE、16 kHz、单声道录音和 WAV 播放，再对照三种 `AudioSource`。所有音频结论必须在当前真实 R1 上验收。
