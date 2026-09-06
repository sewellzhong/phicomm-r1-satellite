> 历史记录：本文版本、命令及“下一步”反映记录当时状态；当前排期以[根 README](../README.md)为准。原始产物迁移见[归档说明](../test-results/README.md)，原验收结论不变。

# R1 原生收音结束控制与持续对话（2026-09-06）

本轮实现独立的原生STT模式、会话适配以及R1回复后续听。新增HA代码已部署，未修改现有两个助手、默认助手、模型选择、提示词或设备权限；未替换正在运行的R1 APK。真实录音/播放、原生配对、持续对话声学体验与独立常驻仍未交付。

## 实施前核对与保留项

- HA Core 2026.8.2；Whisper 3.5.1与Piper 2.3.3运行。
- 默认助手现在名为“中文语音助手（本地＋AI）”，ID仍为 `521e6fbe73fe8a496b1a84e559`；另一个为“中文语音助手（纯本地）”。
- 两者仍使用 `stt.faster_whisper`，中文；Piper音色 `zh_CN-huayan-medium`。Whisper的model/stt_library为auto，vad_clip=false。
- AI助手使用 `conversation.jia_ting_ai_lu_you`（家庭助手〔自动分流〕），转交 `conversation.dui_hua`（AI对话〔模型中心〕）。模型自动选择、工具开启、设备控制关闭；相关配置均保留。
- 现有 `stt.r1_shu_ru_guo_lu` 名为“语音识别（Whisper＋无效输入过滤）”，没有被两个助手选用。其行为、实体ID和你改过的名称不变。
- 现场集成与仓库版本逐文件SHA256一致后才编辑；部署时再次比较文件列表和旧摘要，发现外部改动即拒绝覆盖。旧组件在HA本机保留完整回退副本。

## 新的HA入口

输入过滤集成版本升为0.2.0，添加配置时可选：

| 模式 | 实体与行为 |
|---|---|
| 通用无效输入过滤 | 原行为；透传识别来源的外部VAD要求；旧条目默认属于此模式，无迁移/改名 |
| R1原生 | 单独创建“R1原生语音识别”和“R1原生会话”；不改变旧条目 |

原生STT继续调用同一Whisper，声明 `requires_external_vad=false`，由有保护的输入流与端侧结束标志负责结束。不更改HA Core，也不启用/关闭Whisper内部其他模型设置；增益、降噪偏好仍透传。

固定格式WAV元数据承载PCM S16LE、16kHz、单声道，最多640000字节（20秒）。5秒没有收到下一块、输入墙钟超过30秒、总识别超过60秒、格式错误、数据超量均按错误结束。成功识别必须已观察到正常输入EOF；来源提前返回文字但没有消费到EOF时拒绝提交意图。取消异常原样传播。零字节正常EOF、空白/标点与整段非语音标记走无文字结果，其他短回答原样传递。

新会话实体按用户/设备/卫星/外层会话ID隔离内部会话，最多256组，仅保留ID及时间信息。每次仍调用现有家庭助手路由，保留认证Context、设备/卫星身份、语言和原响应。

- 明确“结束对话”“取消本次对话”“取消这次对话”“不用回答了”清除该组内部会话，返回空回复且不续听。
- “取消”“停止”“好”“是”“嗯”“客厅”等仍委托现有路由，不把它们统一当作结束聊天。
- 120秒内继续输入沿用内部会话；到期后新建。**有效期按最近一次请求计时，与现场模型中心Hub保持一致**；长时间模型处理同样占用这段时间，不能把适配层ID保留误当作底层事实永不过期。
- 同一会话的并发请求拒绝重入，异常/取消清除映射，卸载清空。清除会话不撤销已执行的动作或擅自确认/撤销UI待确认请求。

固定HA原生卫星由服务端维护会话，不直接使用请求中的conversation_id决定重置；因此采用独立会话适配，而非假设R1发送空ID就能清除服务器历史。

## R1续听

- 首次Alexa唤醒仍播放已选随机回应；后续轮次不重复播放唤醒回应。
- 普通回复实际播完后自动续听；HA明确追问也允许续听。RUN_END和播放排空仍分别等待。
- 每轮6秒等待开口、80ms连续VAD确认起音、1.2秒连续尾部静音、最长20秒保持。
- 续听6秒无开口：关闭命令窗口，返回Alexa监听，不发起新的HA请求，不清除短期对话。120秒有效期内再次唤醒可承接；实际服务器上下文以适配层及模型中心有效期为准。
- 无输入、静默结束和失败不循环续听。原生会话解析INTENT_END的会话ID与continue_conversation信息，ID仅作为协议信息保留/透传，不以此冒充服务端重置控制。
- 播放中插话、硬件共存、前台服务与开机启动未在本轮新增。

## 验证与证据

证据目录：`test-results/2026-09-06-r1-native-dialogue/`。

- 19组HA容器测试通过，包含20秒输入、两段短语间停顿、HA分段器不得启用、超量拒绝、提前返回、停滞、墙钟/识别超时、取消、零输入、普通短答、明确结束、120秒上下文和用户/卫星隔离。
- 原版HA PipelineRun/STT流处理与PipelineInput执行方法用于管线检查；识别、AI和设备调用为合成替身，不是Whisper实录或真实AI问答。
- 另以现场路由源码和Hub会话方法执行兼容测试：同源会话一致；设备控制拒绝不执行动作、不转模型重试。源文件摘要记录于 `router-reference-hashes.json`，未调用真实云模型或设备。
- 真实HA配置流/平台生命周期容器检查通过：新旧STT共存、原生conversation实体加载、重复/嵌套拒绝及卸载。
- Android 110项单元测试、lint、构建通过。新增普通回复后续听、追问、无开口保留上下文、到期和静默/错误不续听检查。
- 主机JVM与R1/API22通过官方aioesphomeapi的连续两轮合成协议检查：第一轮接收回复并等待模拟排空后，第二轮携带相同会话ID发起；第二轮静默结束。仍检查加密拒绝与重连。探针不开麦、不播放，也未运行真实AudioTrack。

主要命令：

```bash
docker run --rm --network none --entrypoint python -e PYTHONPATH=/work/integrations/home_assistant -v /path/to/phicomm-r1-satellite:/work:ro ghcr.io/home-assistant/home-assistant:2026.8.2 -m unittest discover -s /work/tools/ha/tests -p 'test_*.py' -v
docker run --rm --network none --entrypoint python -e PYTHONPATH=/work/integrations/home_assistant -v /path/to/phicomm-r1-satellite:/work:ro ghcr.io/home-assistant/home-assistant:2026.8.2 /work/tools/ha/tests/check_guard_setup.py
JAVA_HOME=/home/developer/.sdkman/candidates/java/17.0.19-tem ANDROID_SDK_ROOT=/home/developer/.local/share/android-sdk android/r1-probe/gradlew -p android/r1-probe --no-daemon testDebugUnitTest lintDebug assembleDebug
local-deps/esphome-interop-venv/bin/python tools/esphome/check-native-api.py --synthetic-dialogue
local-deps/esphome-interop-venv/bin/python tools/esphome/check-native-api.py --adb 192.0.2.10:5555 --adb-apk android/r1-probe/app/build/outputs/apk/debug/app-debug.apk --synthetic-dialogue
python3 tools/ha/update-input-guard.py --expected-hashes test-results/2026-09-06-r1-native-dialogue/baseline-hashes.json
```

## 部署、回退与下一步

更新器保留现场旧代码于 `/config/r1_component_backups/20260905T183935Z-97578593/r1_input_guard`，文件校验与 `ha core check`通过后加载。重启及配置摘要核对结果见证据文件。仓库未保存HA令牌、模型凭据或PSK。

回退时先卸载新增原生配置条目（若以后添加），将当前组件移入另一个备份目录，再恢复上述旧代码到 `/config/custom_components/r1_input_guard`，执行配置检查并重启。现有通用实例无需删除。

本轮只部署新增入口的代码，不创建/选择新的原生助手，不改变当前R1启动命令。原生配对阶段再添加“R1原生”模式，来源选择“语音识别（本地Whisper）”，对话代理选择“家庭助手（自动分流）”；新建“R1原生中文助手”选择这两个新实体与原Piper，保留原默认助手。

接下来仍需设备身份/密钥初始化、明确的原生配对和前台服务。当前设备控制关闭，以及Native API会话认证Context与现有Hub用户权限的适配边界，都不能通过伪造用户身份来绕过；正式接入时须单独核验。持续对话的物理声音效果及既有路由对所有追问的语义处理仍待实际验收，不能用本轮传递正确的测试代替。
