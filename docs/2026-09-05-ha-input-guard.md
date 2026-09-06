> 历史记录：本文版本、命令及“下一步”反映记录当时状态；当前排期以[根 README](../README.md)为准。原始产物迁移见[归档说明](../test-results/README.md)，原验收结论不变。

# HA 意图执行前输入过滤（2026-09-05）

新增独立自定义集成 `r1_input_guard`，在 HA 中创建可单独选择的 STT 包装实体。它调用现有识别实体，过滤成功返回的空白、纯标点/符号及整段非语音标记。通过结果保留原文，识别失败保持失败。没有修改 HA Core、Whisper 模型或已有管线。

## 拦截位置与依据

固定 HA Core 2026.8.2 的 `PipelineRun.speech_to_text()` 在处理成功结果后、发出 STT_END 之前，检查 `result.text`。为空则抛出 `stt-no-text-recognized`。`PipelineInput.execute()` 捕获该错误，发送 ERROR 并结束 RUN，不进入 `recognize_intent()` 或 TTS。因此过滤器返回 `SpeechResult("", SUCCESS)`，能在意图执行前终止。

这条路径不会生成“抱歉，无法理解”的对话回复；调试页面仍可显示“没有识别到文字”，不把它伪装成一次成功问答。故障仍使用原来的错误结果/异常。

依据：

- [HA 2026.8.2 管线执行顺序](https://github.com/home-assistant/core/blob/2026.8.2/homeassistant/components/assist_pipeline/pipeline.py)
- [HA 2026.8.2 STT 实体接口](https://github.com/home-assistant/core/blob/2026.8.2/homeassistant/components/stt/__init__.py)
- [ESPHome 的管线事件转发](https://github.com/home-assistant/core/blob/2026.8.2/homeassistant/components/esphome/assist_satellite.py)

## 规则与保守边界

- Unicode NFKC、格式/控制字符处理仅用于比较。没有字母或十进制数字的结果为空输入。
- 整段已知非语音标记组合可过滤，如 `[BLANK_AUDIO]`、`[no speech]`、`(silence)`、`【噪音】`、`<|nospeech|>`；`音乐`、`播放[音乐]`等正常文本保留。
- “现在什么时间？”、“好”、“不”、“5”、“嗯”、“算了”、仅 Alexa、真实重复句均保留。STT接口不提供追问状态、R1的VAD时长或实际提示语，不能臆造这些字段后套用依赖它们的规则。
- 该入口不能取代端侧的回应隔离、6秒无开口静默关闭，也不能保证拦截有完整文字的任意识别幻觉。
- 不保存音频、识别正文或凭据；并发请求各自处理，不使用共享的“上一条文字”。

## 集成与回退

源码：`integrations/home_assistant/custom_components/r1_input_guard/`。

- 配置流选择现有STT实体，按实体注册表UUID关联，支持实体改名后的重新解析。
- 重复添加同一来源、选择其他过滤实体形成嵌套均被拒绝；来源丢失、不可用或不支持格式时返回错误，不能绕过过滤直接运行意图。
- 语言、格式、采样率及音频处理需求透传来源，包装器不改变音频格式。
- 原生 Android 会话增加 `NO_INPUT` 与 `FAILED` 等结果区分；只识别明确的 `stt-no-text-recognized` 为无输入，其余错误、无结束事件的超时保持失败。结果不保存HA错误正文或识别文字。

安装命令（仅首次，拒绝覆盖已有目录）：

```bash
python3 tools/ha/install-input-guard.py --host home-assistant
```

实际目标为 HA 2026.8.2 的 `/config/custom_components/r1_input_guard`，逐文件SHA-256核验通过；`ha core check`通过。HA重启成功，loader日志确认发现新增集成，HA内部HTTP访问返回200。开发机访问公网域名时DNS解析超时，未据此判定HA服务故障，也未宣称已验证公网访问；详情见 `deployment.json`。

用户启用入口：

1. HA「设置 → 设备与服务 → 添加集成」，搜索 `R1 Input Guard`。
2. 选择来源 `faster-whisper`（`stt.faster_whisper`）。
3. 后续为R1创建/选择中文语音助手时，将“语音转文字”设为“R1 输入过滤”，继续使用原中文对话与Piper。

部署文件和重启并不等于已选择入口；必须完成配置并将目标助手的STT指向它后，过滤才影响那条管线。当前不自动更改原助手。

回退：将使用该入口的助手语音转文字改回 `faster-whisper`，再删除 `R1 Input Guard` 集成条目即可。若需移除代码，可将独立目录移出 `custom_components` 后重启；不涉及原STT配置或模型。

## 验证与证据

在与生产相同版本的官方容器中进行验证，镜像摘要：
`sha256:56690a89c79a0de98035e1719f8324a92d5859c1192ff45adb0230ea81cb42a5`。

```bash
docker run --rm --network none --entrypoint python -e PYTHONPATH=/work/integrations/home_assistant -v /path/to/phicomm-r1-satellite:/work:ro ghcr.io/home-assistant/home-assistant:2026.8.2 /work/tools/ha/tests/test_input_guard.py -v
docker run --rm --network none --entrypoint python -e PYTHONPATH=/work/integrations/home_assistant -v /path/to/phicomm-r1-satellite:/work:ro ghcr.io/home-assistant/home-assistant:2026.8.2 /work/tools/ha/tests/check_guard_setup.py
JAVA_HOME=/home/developer/.sdkman/candidates/java/17.0.19-tem ANDROID_SDK_ROOT=/home/developer/.local/share/android-sdk android/r1-probe/gradlew -p android/r1-probe --no-daemon testDebugUnitTest lintDebug assembleDebug
```

- 8组 Python 测试通过，覆盖多项规则用例、原文透传、并发隔离、来源失效、异常和取消。
- 管线边界测试执行原版HA的 `speech_to_text()` 和 `PipelineInput.execute()`，使用合成STT结果与意图/TTS计数替身，证明空结果不调用下游，正常文字调用下游。不是Whisper真实识别或生产全管线测试。
- 独立HA生命周期测试：真实配置流、实体加载、重复/嵌套拒绝及卸载通过。测试源为合成实体。初始测试夹具遗漏HA loader初始化及源实体注册，修正夹具后通过；未以失败结果宣称已加载。
- Android 91项单元测试、lint和构建通过；本轮未替换R1已安装APK，也未运行真人测试。
- 证据目录：`test-results/2026-09-05-r1-input-guard/`。

下一开发入口：连接原生语音上下行与实际回应/收音状态机，确保NO_INPUT不进入播放，真实故障可诊断。随后完成设备身份、Noise密钥初始化、原生配对和常驻；真实中文全链路、无命令静默及长期稳定性仍未验收。
