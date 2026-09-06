> 历史记录：本文版本、命令及“下一步”反映记录当时状态；当前排期以[根 README](../README.md)为准。原始产物迁移见[归档说明](../test-results/README.md)，原验收结论不变。

# 阶段 2：Assist WebSocket 接入基础（2026-09-05）

> 本文记录版本 35 的基础阶段；版本 36 的后续 HTTPS 修复、运行服务及未完成项见 [运行记录](./2026-09-05-assist-runtime.md)。

## 用户决策与状态

用户决定直接采用 ESPHome Alexa microWakeWord v2，停止额外 KWS 训练和声学测试，
推进下一阶段集成。1 米 4 次说词/4 次事件是已有功能证据；未完成的正式召回、
FAPH、远场和稳定性验收继续标记未验证，不能将开发推进决定写成阶段 1 总验收通过。

本次完成协议基础及只读 HA 盘点，**尚未接通 R1 麦克风到 HA 再到 TTS 播放的完整闭环**。
本轮没有启动 R1 录音或唤醒测试，没有修改 HA 配置或部署新 APK。

## SSH 只读盘点

- 主机：home-assistant / 192.0.2.10；HA Core 2026.8.2，HTTP 80，Core SSL 关闭。
- 默认管线“本地中文”：ID `01m04j14wzw45d4094qn1s6x68`，管线/对话语言 zh-CN，
  stt.faster_whisper（zh）、conversation.home_assistant、tts.piper（zh_CN），
  声音 zh_CN-huayan-medium。
- 另有“本地中文 AI”管线，使用 conversation.jia_ting_ai_lu_you；
  未改变默认选择。
- Piper 2.3.3、Whisper 3.5.1 应用均为 started；这证明应用运行状态，
  不等于已经完成 STT/TTS 请求。
- 内网 REST 无认证访问返回 401。WebSocket 无认证握手返回 HTTP 101 和
  auth_required，服务器版本与盘点一致；没有发送凭据或运行语音管线。
- 配置的外部地址为 https://home-assistant.sewellzhong.com，
  开发机解析超时；SSH 会话尝试经 Supervisor 访问 Core API 返回 401。
  未读取既有用户令牌、未生成新凭据。

[盘点与握手证据](../test-results/README.md)仅保留白名单配置字段，
不包含令牌、HA 用户数据或家庭对话。

## 已实现的代码

`android/r1-probe/app/src/main/java/dev/sewellzhong/r1probe/assist/`：

- PcmPrebuffer：固定 2 秒、64000 字节 S16LE/16 kHz/单声道环形内存；
  输入为 20 ms 帧，快照按时序返回，支持清零。
- HaAssistSession：认证后列举并校验选定管线的 STT、对话及 TTS 中文配置；
  从 stt 到 tts 发起请求。收到 stt-start 后才上传带 handler 字节前缀的 PCM，
  等待期间缓存最多 160000 字节，满时中止，空闲期不发送音频。
- 支持音频结束标记、HA VAD 结束、中文 STT 和 TTS URL 回调、
  conversation_id 保留、超时、拒绝认证、错误事件及断连清理。
  断连不自动重放指令，调用方必须显式重建连接。
- HaAssistConnection：固定 OkHttp 4.12.0（上游声明 API 21+），
  保持默认 TLS 证书校验，仅接受 HTTPS origin；不自动跟随重定向，
  TTS URL 只允许同源 HTTPS。令牌只用于内存中的认证消息，不写入文件或日志。
- 客户端入口需要调用方传入地址、管线 ID 和临时认证；未硬编码用户配置。
  API 22 编译检查通过，新增网络依赖尚未在 R1 上运行验证。

协议依据为
[HA Assist 官方文档](https://developers.home-assistant.io/docs/voice/pipelines/)、
[HA WebSocket 官方文档](https://developers.home-assistant.io/docs/api/websocket/)及
[HA Core 2026.8.2 管线源码](https://github.com/home-assistant/core/blob/2026.8.2/homeassistant/components/assist_pipeline/pipeline.py)。
运行依赖依据为
[OkHttp 4.12.0 要求与许可](https://github.com/square/okhttp/blob/parent-4.12.0/README.md)。

## 验证及未完成项

执行：

```bash
JAVA_HOME=/home/developer/.sdkman/candidates/java/17.0.19-tem ANDROID_SDK_ROOT=/home/developer/.local/share/android-sdk android/r1-probe/gradlew -p android/r1-probe --no-daemon clean testDebugUnitTest lintDebug assembleDebug
```

36 项主机单元测试、lint 和干净 APK 构建通过。新增 10 项检查覆盖预缓冲回绕、
字节顺序、空闲不上传、认证/中文管线门控、音频结束顺序、缓存溢出、
旧会话事件隔离、发送失败及 conversation_id。它们不代替真实 HA 认证后的通信结论。

仍需：确定 R1 可用的安全直连地址和临时 API 认证交付方式，
将认证连接、Alexa 触发、AudioRecord 循环、上传结束与 TTS 播放串联，
实现连接恢复和播放状态管理，并解决当前音频修改包的独占。
内网 HTTP 可达并不意味着客户端默认可在明文通道传输令牌。
本阶段不产生 ESPHome 原生卫星实体；Noise PSK 属于后续原生协议阶段。
