> 历史记录：本文版本、命令及“下一步”反映记录当时状态；当前排期以[根 README](../README.md)为准。原始产物迁移见[归档说明](../test-results/README.md)，原验收结论不变。

# Native API 命令音频上传底座（2026-09-05）

本轮在现有 Noise 协议基础上补充单连接语音会话状态和命令 PCM 上传。主机 JVM 与 r1-sample01/API 22 均通过官方客户端的合成数据互通。**这不是 HA 中文问答、录音/播放或独立常驻验收；阶段门槛没有因此通过。**

## 实现与约束

- `NativeVoiceSession`：订阅、空闲、等待 HA 接受、上传、等待处理、取消和关闭状态。消息编号均使用固定 `api.proto` 生成的 `MessageIds`。
- 只接受 API 音频订阅；每帧 PCM S16LE / 16 kHz / 单声道 / 20 ms，即 640 字节。拒绝 UDP 端口响应和错误帧长。
- HA 接受前不发送 PCM；正常结束发送 `VoiceAssistantAudio(end=true)`；取消发送 `VoiceAssistantRequest(start=false)`。零帧会话走取消。
- 启动响应最多等待 10 秒，上传最多 20 秒/1000 帧，处理最多等待 60 秒；取消后最多等待 5 秒 RUN_END，否则关闭连接。ERROR 后等待 RUN_END，避免旧结束事件提前结束新一轮。
- 本地回应与 VAD 调用者尚未接入。未来调用者必须在回应播完且确认人声之后调用 `startCommand()`；单纯订阅/等待不会发起请求。原有6秒开口窗口、1.2秒尾部静音与随机回应不由这个传输类修改。
- `NativeApiConnection.Handler` 在连接线程串行处理消息，每秒空闲轮询会话超时；半帧接收超时直接断开，避免解析错位。传输错误/断线释放会话。
- 默认接口继续不宣告语音/播放器能力。只有显式 `--synthetic-voice` 协议探针使用测试 handler，上传两帧确定性合成字节，既不开麦也不播放。探针绑定 loopback，限时两分钟，PSK 仅驻留内存。

## 发现并修正的版本差异

第一次官方客户端互通因未接受音频订阅而超时：固定 ESPHome schema 的 `VOICE_ASSISTANT_SUBSCRIBE_API_AUDIO` 为 `1`，而 aioesphomeapi 45.6.1 的 `VoiceAssistantSubscriptionFlag.API_AUDIO` 实际为 `1 << 2`（`4`）。实现接受这两种音频订阅位，并保留单独回归测试；这不是手写消息编号，也不修改上游 schema。

依据：

- [固定 api.proto](https://github.com/esphome/esphome/blob/6f8dbb6fbc1b9c108df53e5cf78d5b2316ea3af2/esphome/components/api/api.proto)
- [aioesphomeapi v45.6.1 类型定义](https://github.com/esphome/aioesphomeapi/blob/v45.6.1/aioesphomeapi/model.py)
- [官方客户端的语音订阅及正常结束/取消处理](https://github.com/esphome/aioesphomeapi/blob/v45.6.1/aioesphomeapi/client.py)

## 实际验证

```bash
JAVA_HOME=/home/developer/.sdkman/candidates/java/17.0.19-tem ANDROID_SDK_ROOT=/home/developer/.local/share/android-sdk android/r1-probe/gradlew -p android/r1-probe --no-daemon testDebugUnitTest lintDebug assembleDebug
local-deps/esphome-interop-venv/bin/python tools/esphome/check-native-api.py --synthetic-voice
local-deps/esphome-interop-venv/bin/python tools/esphome/check-native-api.py --adb 192.0.2.10:5555 --adb-apk android/r1-probe/app/build/outputs/apk/debug/app-debug.apk --synthetic-voice
```

- 87 项主机单元测试，0 失败，0 错误，0 跳过；其中新增会话测试14项。lint 与 APK 构建通过。
- JVM 和 R1 分别通过订阅→发起→接受→两帧逐字节校验→正常结束，且错误连接之后再次运行成功。
- 两侧均通过 DeviceInfo、实体查询、Ping、Disconnect、错误密钥拒绝、明文拒绝、篡改密文拒绝与重连。
- 超时、错误事件、取消等待、无帧取消、错误帧长、UDP 拒绝、断线等状态边界由主机单元测试验证；未冒称全部经过 R1 故障注入。
- R1 通过 `dalvikvm` 加载临时 APK，复用已安装探针的同版 Noise JNI；未安装/替换现有 APK或修改系统包。结束后确认无探针进程、无 ADB 转发、无临时探针 APK。
- 证据：`test-results/2026-09-05-r1-sample01-native-voice/` 中的构建日志、主机检查汇总、JUnit XML 和两侧互通 JSON。`audio_opened=false`，不含家庭录音或凭据。

## 未交付项与下一入口

当前是上传及会话控制组件，不包含下行 TTS、实际麦克风/KWS/VAD 连接、HA 原生实体配对、PSK 持久化、mDNS、前台常驻或脱离开发机运行。Native API 音频不经过现有 WebSocket 输入过滤器；特别是 STT 后意图处理在 HA 侧连续执行，不能假设卫星收到 STT_END 后再取消就能阻止设备操作。

接入真实命令前须明确 HA 侧的无有效输入拦截点，保证标点/幻觉文本在意图执行前被阻止；随后接入回应后收音、无命令静默关闭和 TTS 播放完成状态。继续保持不宣告尚未实现的能力，完成这些开发工作后再做原生配对和常驻集成。此次无需用户进行真人测试。
