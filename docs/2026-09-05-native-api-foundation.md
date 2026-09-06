> 历史记录：本文版本、命令及“下一步”反映记录当时状态；当前排期以[根 README](../README.md)为准。原始产物迁移见[归档说明](../test-results/README.md)，原验收结论不变。

# ESPHome Native API 验收底座（2026-09-05）

本日完成了 R1 与 ESPHome Native API 的基础互通实现与实机验证，目标是为后续“原生常驻语音卫星”打底层协议通道。当前只验证握手与控制通道，不涉及 Android 长驻服务、麦克风采集与 HA 实际语音问答完整闭环。

## 已完成

- 固定 ESPHome API 版本：
  - `esphome/components/api/api.proto`、`api_options.proto`、`descriptor.proto` 来源于 `2026.8.0`，提交：
    `6f8dbb6fbc1b9c108df53e5cf78d5b2316ea3af2`
  - Python/Java 客户端版本与 HA 侧一致：`aioesphomeapi 45.6.1`
  - Noise C 版本固定：`esphome/noise-c` 提交 `b3da54dc1020150237054004c5fdbffc63a23538`
  - Protobuf 编译器固定：`protoc 3.25.5`
- 协议层实现使用 protobuf lite 与 Noise NNpsk0_25519_ChaChaPoly_SHA256，禁止明文通道，支持：
  - 客户端握手（Hello、设备身份、重放保护）
  - DeviceInfo、Ping/Pong、ListEntities、Disconnect
  - 严格长度、类型和边界检查，异常后关闭连接
- 已添加 `R1` 端可执行 probe（`native` 探针）与主机脚本互测工具
- `tools/esphome/check-native-api.py` 在主机+实机两侧都可运行
- `R1` 实机互通结果：
  - 文件：`test-results/2026-09-05-r1-sample01-native-api/device-interop.json`
  - 关键项全部通过：`valid_key_device_info_entities_ping_disconnect=passed`、`wrong_key=rejected`、`plaintext=rejected`、`tampered_ciphertext=rejected`

## 互测结果（实机）

```json
{
  "surface": "R1_API22",
  "client": "aioesphomeapi 45.6.1",
  "valid_key_device_info_entities_ping_disconnect": "passed",
  "wrong_key": "rejected",
  "wrong_key_error_type": "SocketClosedAPIError",
  "plaintext": "rejected",
  "tampered_ciphertext": "rejected",
  "reconnect_after_rejections": "passed",
  "audio_opened": false,
  "psk_saved": false
}
```

## 边界与下一步

- `audio_opened=false`，本次只做协议与加密握手，不含音频上报/播放通道。
- 未提交生产化持久身份（PSK 持久化、稳定 MAC/设备 ID）和原生唤醒/录音/播放常驻服务。
- 本次实现不影响你现有 WS Assist 的功能，但不能替代“真实可退换 R1 常驻使用体验”验收。

下一阶段计划：
1. 设计 R1 端原生常驻服务（前台/后台策略）
2. 解决 PSK 生命周期与配对初始化（可恢复、可替换、可清理）
3. 接入 HA 端语音上下行链路（音频、intent 过滤、超时与无效请求处理）
4. 去掉开发机进程依赖，完成长期稳定运行验收
