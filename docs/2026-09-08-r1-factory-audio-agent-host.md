# R1 原厂音频代理无设备开发记录

## 已实现边界

v80 建立自有的原厂音频代理公共骨架。协议固定为版本 1，使用 4 字节网络序长度
加 Protobuf Lite `Envelope`，最大消息 1 MiB。生产 socket 名为
`/dev/socket/r1_factory_audio`；代理要求显式目标 UID，并使用 `SO_PEERCRED` 拒绝
其他进程。它不监听网络端口，一次只服务一个采集客户端。

协议支持版本协商、开始/停止、健康状态、640 字节 PCM 帧、DOA 字段、播放参考、
丢帧计数和结构化错误。唯一可运行后端是必须显式指定的 `--fake` 合成静音后端；
未指定时以 `factory_backend_unimplemented` 退出。公开源码不包含原厂库、设备节点、
校准、固件、Root 工具、SELinux 策略或刷写命令。

APK 客户端固定请求 PCM S16LE、16 kHz、单声道、20 ms/帧，并校验每帧恰好
640 字节。`factory_proxy` 是显式来源标识，尚未成为默认采集链；代理错误会直接上报，
不会静默转用标准 AudioRecord 后继续声称原厂处理生效。

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

本次统一主机检查实际通过 Android 162 项单元测试、lint、hostcheck APK、32 项工具
测试、18 项 R0 测试与桌面演练、6 项代理 socket 契约测试（含 1,000/90,000 帧的
20 秒及 30 分钟音频预算加速演练）、API 22 ARMv7 代理
交叉构建、HA 44 项测试和配置加载检查。hostcheck APK SHA-256 为
`30f5558e5de258bfd02428f683791abd291ecc9e87786cd2e729d45be530192f`；ARMv7
合成代理 SHA-256 为
`9124d100f40372b29539ba57842149963e96fc6887b026b4cbd5206dafe4a4ff`。

这些结果只证明公共协议和合成状态机，不证明 R1 原厂四麦、MicArray、DOA、AEC
或 DSP 可用；hostcheck APK 和合成代理都不得部署为设备候选。

## 实机续接入口

先按 R0 手册完成完整 eMMC 双副本、低层入口和受控回刷，使门槛报告为 `pass`。
随后只读确认真实 UID、socket 所有权、原厂符号、设备节点、初始化顺序、播放参考
来源和 AVC 拒绝，再实现动态原厂后端及最小 SELinux 域。任何字段或调用假设与
实机冲突时，以实机证据修改协议适配层，不把假后端结果继承为实机通过。
