> 历史记录：本文版本、命令及“下一步”反映记录当时状态；当前排期以[根 README](../README.md)为准。原始产物迁移见[归档说明](../test-results/README.md)，原验收结论不变。

# 原生音频收发与播放控制（2026-09-06）

本轮完成独立原生音频协调器、PCM播放适配器及会话状态扩展，保留现有“本地中文 AI”/WebSocket链路。开发验证采用合成字节和不出声的播放替身；没有替换R1已安装APK，没有修改HA助手、家庭AI路由或R1 Input Guard配置。

## 实现

- `NativeAudioRuntime` 是独立、显式构造的一次性连接 handler，复用Alexa KWS、已选6+4句随机回应、WebRTC VAD、CommandWindow及预缓冲组件；没有注册Service、开机广播或自动启用入口。后续前台服务须负责认证、唤醒锁和连接生命周期。
- 本地流程：唤醒→释放麦克风→播放随机回应→等待200ms→新建收音→最多6秒等开口；80ms连续VAD人声后才提交命令，尾部静音1.2秒、最长20秒。无开口不发起HA请求。每连接开发运行上限1小时，读音频超时10秒。
- `NativeAudioCoordinator` 把录音生产者与协议线程分开，最多160000字节/250帧上传队列；握手接受前保留命令起音及结束标志。队列满即终止，不覆盖旧帧后继续执行。原生会话和Noise发送由同一连接线程拥有，不从录音/播放线程调用。
- 原生连接在帧边界每20ms调度一次，进入帧体后读超时1秒；写阻塞超过5秒由独立看门狗关闭socket。保持已有Noise认证、生成消息编号及设备能力不宣告策略。
- `NativePcmPlayback` 是独立播放线程，接收32 KiB有界环形缓冲。HA网络音频块可变长，但须包含完整16位采样；重组为640字节块，最后不足一帧的完整采样不补零、不丢弃。固定16kHz/单声道/S16LE。
- `NativeAudioTrackSink` 使用API22兼容的AudioTrack接口；处理部分写入，按播放头累计帧数判断尾音是否播放完。停止时pause/flush以解除阻塞，再释放设备。
- 播放线程先请求关闭麦克风，待AudioRecord真正释放后才创建输出。TTS_STREAM_END、写入返回或RUN_END都不能单独代表播放完成；待流结束且硬件播放进度达到全部已写入采样，才发送一次 `VoiceAssistantAnnounceFinished(success=true)`。RUN_END和播放完成都满足后才能开始下一命令。
- 回复阶段从首次TTS事件起最多120秒，重复事件不延长。超时、播放故障、断线、缓冲溢出及非法音频顺序均停止并清空；无有效输入保持NO_INPUT，真正异常保持FAILED。不会自动重放设备命令。

## 验证

```bash
JAVA_HOME=/home/developer/.sdkman/candidates/java/17.0.19-tem ANDROID_SDK_ROOT=/home/developer/.local/share/android-sdk android/r1-probe/gradlew -p android/r1-probe --no-daemon testDebugUnitTest lintDebug assembleDebug
local-deps/esphome-interop-venv/bin/python tools/esphome/check-native-api.py --synthetic-duplex
local-deps/esphome-interop-venv/bin/python tools/esphome/check-native-api.py --adb 192.0.2.10:5555 --adb-apk android/r1-probe/app/build/outputs/apk/debug/app-debug.apk --synthetic-duplex
```

- Android单元测试、lint及构建结果见证据汇总。新增覆盖：无开口、接受前缓存与EOF、队列溢出、断线不重放、RUN_END早于播放、播放早于RUN_END、重复流结束、非法音频顺序、120秒绝对期限、麦克风释放屏障、部分写入、缓冲边界和停止解除阻塞。
- 官方aioesphomeapi 45.6.1与主机JVM、R1/API22互通：两帧命令音频上行、1886字节不等长块下行逐字节校验。探针模拟400ms播放进度延迟，确认不在流结束前或播放替身排空前回报成功。
- 同时检查DeviceInfo/实体/Ping/Disconnect、错误PSK、明文、篡改密文拒绝与重连。
- R1通过临时APK运行协议探针，复用同版Noise JNI。探针未调用NativeAudioRuntime/AudioRecord/AudioTrack，`audio_opened=false`，密钥只在内存。本轮没有家庭录音或真实发声。
- 清理本次临时APK和原生API端口转发；设备原有 `r1-assist-control` 转发属于当前链路，保留。未发现残留NativeApiProbe进程。

证据目录：`test-results/2026-09-06-r1-sample01-native-audio/`，包括构建日志、JUnit XML、APK摘要和两侧互通结果。

## 实机与协议限制

**代码已支持及合成协议互通不等于真实R1录音、播放、AEC或常驻验收。** 原生协调器尚未由生产Service启动，AudioTrack的真实排空行为、麦克风释放时序和原厂音频包共存仍待实机验证。不安排新的真人KWS测试。

检查固定HA 2026.8.2源码发现：`AudioSettings` 默认开启VAD、尾部静音0.7秒；Wyoming STT默认要求external VAD，ESPHome卫星的启动路径也没有把本项目的1.2秒参数传给HA。因此本轮只保证端侧CommandWindow仍是1.2秒，不能保证真实原生全链路不会被HA更早结束。正式接入前必须在独立原生助手路径解决端点控制；不能为此修改现有“本地中文 AI”或静默改变已安装Guard的通用行为。

同版HA `_stream_tts_audio` 在发送完数据后自行更新部分服务端状态；R1仍独立等待实际播放排空。发送播放完成回报并不证明HA所有UI状态都会等待R1扬声器，后续实体接入时须单独核验。

依据：固定仓库schema，以及 [HA 2026.8.2 ESPHome语音实现](https://github.com/home-assistant/core/blob/2026.8.2/homeassistant/components/esphome/assist_satellite.py)、[管线默认音频设置](https://github.com/home-assistant/core/blob/2026.8.2/homeassistant/components/assist_pipeline/pipeline.py)。

下一入口：独立原生助手的端点控制、设备身份/Noise密钥初始化和显式配对；之后才连接真实HA中文问答、启动前台服务和进行实际音频验收。生产原生能力位、mDNS、自动恢复和72小时稳定性保持未交付。
