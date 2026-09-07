# R1 原生语音卫星 APK

当前开发源码 v66，独立包名 `dev.sewellzhong.r1probe`；Android 5.1 / API 22、ARMv7、固件 3448。`NativeSatelliteService` 提供原生运行、持久配置、开机恢复、按键/音量环探针及限时硬件能力窗口。v65 实机确认普通应用被 SELinux 拒绝直接打开 evdev；v66 由前台 Activity 接收 Android 分发事件并转给常驻服务，待实机复验。

## 构建

从新 Linux 电脑构建请按 [开发指南](../../docs/development.md)。

```bash
python3 tools/dev/prepare.py
bash tools/dev/check.sh
```

主机包使用 `-PhostCheck=true`、独立包名 `dev.sewellzhong.r1probe.hostcheck` 与合成测试音，不用于部署。设备部署构建省略此参数，必须有原签名和 `local-deps/private-prompts/assets/`。JDK 17 与 Android SDK 通过环境变量配置。

固定 AAR/JAR 依赖由准备脚本按 SHA-256 校验，三套 ARMv7 原生库按当前 NDK 重新配置并构建，Gradle 自动生成 ESPHome 协议 Java 代码。

PCM 固定 S16LE、16 kHz、单声道、20 ms/帧。`tools/assist/prepare-acknowledgements.py` 生成 `ack/` 源素材，`prepare-interaction-prompts.py` 使用它生成各语速提示；两者仍为当前工具，不应随旧链路删除。

## 运行与验证边界

使用根目录 `tools/native/manage-r1-native.py` 和 `deploy-r1-native.py`。原生 Noise 密钥留在设备私有配置中，不写入仓库或日志。升级前确认目标、固件、签名与回退 APK；恢复原包功能的基线见[根说明](../../README.md)。

`capability-status` 和 `hardware-reset` 查询/清除硬件探针计数；`bluetooth-discoverable`、`ble-window`、`hotspot-window` 只开启限时能力窗口，并分别用对应的 `*-close` 提前关闭。热点启动会短暂断开 Wi-Fi/ADB，必须现场执行并等待自动恢复；临时测试密码不得保存到日志或证据。

既有音频探针与 Alexa 有界诊断入口保留，不能和卫星音频并发运行，也不表示授权恢复 KWS 专项测试。涉及真实录放音的结论必须有实机证据。当前验收排期与已知失败见根说明。

旧探针命令与 v34～v42 说明见[历史快照](../../docs/history/android-probe-before-cleanup.md)，其中旧 WebSocket 命令已失效。
