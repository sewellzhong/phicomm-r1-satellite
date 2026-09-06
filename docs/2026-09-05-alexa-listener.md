> 历史记录：本文版本、命令及“下一步”反映记录当时状态；当前排期以[根 README](../README.md)为准。原始产物迁移见[归档说明](../test-results/README.md)，原验收结论不变。

# Alexa 检测事件与前台监听（2026-09-05）

> 后续决策：用户已选择现有 Alexa 模型并停止追加 KWS 测试，当前推进 Assist 集成。下文测试计划保留为历史记录，不再继续执行；旧训练/候选产物已按用户要求清理。

## 已实现的范围

版本 32 新增 AlexaKwsEngine、AlexaDecision 和 AlexaListeningService。固定模型仍为
`9011a8155b04de858c48038529235cbc0e42e9fca05a55bf588cb80a653a723b`，
运行时 TFLite 2.10.0，API 22 / armeabi-v7a。

- KwsEngine 接收连续的 320 样本 PCM 帧，内部拆成两段 160 样本供原生 microfrontend 使用，每 3 个特征帧推理一次。固定校验输入/输出形状、类型和量化参数。
- 滑窗包含 5 次原始输出。上游清单阈值 0.9 按 int(0.9×255) 转为 229；输出之和严格大于 1145 才满足分数条件。事件分数则用 sum/(5×256) 解量化，两种换算用途不同。
- 启动和每次触发后清空分数窗口；最近分数低于 229 的每个 10 ms 特征帧才累计冷却，共需 100 帧。持续高分不会反复触发。触发后保留模型流式状态。
- 显式 reset 重建原生前端和解释器，拒绝帧大小错误、时间轴不连续和关闭后的输入。
- 服务显式启动，前台通知、有限期 CPU wake lock，5～3600 秒自动结束，支持提前停止；重复启动不创建第二个监听线程。录音阻塞有超时保护。
- 日志仅包含时间戳、检测事件、采样计数、分数、幅度统计及性能计数；不保存 PCM，不上传音频，不接入 HA。
- 未启用开机自启、进程被杀自动恢复和无限期监听，因此不能据此宣称生产常驻能力交付。

判定行为核对来源：
[ESPHome 2026.8.0 streaming_model.cpp](https://github.com/esphome/esphome/blob/2026.8.0/esphome/components/micro_wake_word/streaming_model.cpp)、
[streaming_model.h](https://github.com/esphome/esphome/blob/2026.8.0/esphome/components/micro_wake_word/streaming_model.h)、
[配置阈值转换](https://github.com/esphome/esphome/blob/2026.8.0/esphome/components/micro_wake_word/__init__.py)。

## 音频路径与验收边界

本轮选择原生 VOICE_COMMUNICATION 输出直接送 microfrontend，未叠加自研
StreamingVoiceProcessor 降噪/增益。原因是先建立预训练 Alexa 的独立输入基线；
microfrontend 自身仍有上游噪声抑制与 PCAN。此选择不改变 PCM 格式，但不能复用
此前处理后 Camila 音频的识别结论。若真人效果不达标，应独立比较两条路径，
再冻结用于盲测的路径，不依据测试集调参。

首轮保持当前音频修改包运行，录音阻塞。随后核对设备/固件及既有两份 APK 备份哈希，临时 force-stop 语音/播放器修改包后测试；结束时恢复 EchoService、WindowsService 与语音 Activity，并复核两个前台服务。未卸载、覆盖或持久禁用任何包，未修改 Audio HAL、DSP 或分区。
检测时间戳是已经消费的 PCM 末端，不是语音词尾标注；词尾延迟仍需带标注的测试。

## 验证命令

```bash
JAVA_HOME=/home/developer/.sdkman/candidates/java/17.0.19-tem ANDROID_SDK_ROOT=/home/developer/.local/share/android-sdk android/r1-probe/gradlew -p android/r1-probe --no-daemon testDebugUnitTest lintDebug assembleDebug
python3 -m py_compile tools/kws/run-r1-alexa-listen.py
bash tools/install-r1-probe.sh <adb-serial> android/r1-probe/app/build/outputs/apk/debug/app-debug.apk
adb -s <adb-serial> shell am start -W -f 0x20000000 -n dev.sewellzhong.r1probe/.MainActivity --es probe_action alexa_engine_check --es probe_nonce <unique-nonce>
python3 tools/kws/run-r1-alexa-listen.py <adb-serial> --confirm-device r1-sample01 --seconds 20
```

主机构建、26 项单元测试、lint 通过。新增 4 个判定测试覆盖峰值抑制、严格阈值、
冷却单位、重置与高分平台不重复触发。实机引擎检查使用生成静音跑两次 3 秒，
每次 48000 样本/99 次推理，检查重置可复现、偏移输入、错误帧、
时间轴不连续以及关闭后的拒绝行为；它不构成唤醒效果测试。

## 实机结果与证据

- [共存失败](../test-results/README.md)：0 样本，capture_watchdog 触发；保留失败，不能将该路径标为支持。固件可能残留原生录音轨道，主机工具失败退出时补充 force-stop 独立探针回收。
- [隔离后 20 秒](../test-results/README.md)：320000 样本、666 次推理、部分读取 0、超过 20 ms 帧处理次数 0。最大帧 6.973 ms，引擎累计 CPU 0.592 秒，RTF 0.03053；单次 PSS 12016 kB。观测峰值 814、RMS 66.55（S16 计数），证明非零输入，不能证明语音可懂度。
- 此窗口没有人工内容标注，检测次数为 0，不计算 FAPH 或声学召回率。
- [隔离与生命周期](../test-results/README.md)：完成后再次启动服务，重复启动被拒绝；显式 stop 在 67520 样本后结束。服务退出，两个音频修改包前台服务恢复。目录同时包含备份检查、主机构建/测试、实机引擎检查和产物哈希。
- [安装记录](../test-results/README.md)：APK SHA-256 为 `2641cf0e46ea44c9d7b10588bfe1557327a15797a568305e72a8a5195673fc08`。

复现实机隔离短测（会临时停止音频修改包，退出后恢复）：

```bash
bash tools/kws/run-r1-alexa-isolated.sh <adb-serial> --confirm-device r1-sample01
```

这些结果只通过短时运行和生命周期检查。尚未完成真人正样本触发验证、冻结盲测、长时间后台存活及音频修改包共存问题的生产解决方案。

## 下一步

用户在设备旁准备好后开启明确的真人测试窗口，先做 Alexa 近距离功能检查，
再采集至少 20 条验证、冻结后至少 30 条独立盲测和至少 30 条近音/非唤醒语句。
不将未标注环境流中的检测次数直接称为 FAPH。远场、播放中唤醒、跨说话人、
长时间稳定性和 HA 中文对话尚未验收；阶段 1 总门槛仍未通过。

## 版本 33：真人测试提示音

用户开始真人测试后要求增加开始/结束提示音，原版本 32 窗口已主动停止并排除声学统计，
见 [中断记录](../test-results/README.md)。
版本 33 在采集前播放一声 1000 Hz/200 ms 短音，采集停止释放后播放两声
700 Hz/200 ms 短音，间隔 150 ms。幅度峰值 6000，边沿渐变 10 ms；
沿用系统当前音乐音量，不修改全局音量。开始声后等待约 2 秒再说唤醒词，
避开模型启动冷却。正常结束或显式 stop 都播放结束提示，播放失败则报告失败。

只在内部缓存临时生成提示 WAV，播放后删除；不保存麦克风音频。
提示音复用已有 AudioPlayback 的写入/排空及超时保护，播放完成后才发出
窗口就绪/结束标记，避免主机过早恢复音频修改包。提示音实际可闻性需现场确认。

构建、26 项单元测试、lint 和脚本语法检查通过。
新增 `--human-test` 模式运行 90 秒并跳过生命周期附加测试；
本轮计划约 1 米、正常音量、5 次 Alexa、间隔约 8 秒，实际次数和可闻性由用户确认。

版本 33 首轮 90 秒测试已运行完毕：
[监听证据](../test-results/README.md)、
[隔离恢复证据](../test-results/README.md)。
1440000 样本、2999 次推理、0 次检测，最大原始分数 5；最大帧耗时 9.947 ms，
部分读取与处理超时均为 0。开始提示的排空回调在运行中已观察到，最终缓冲仅保留结束
提示回调和完成统计。用户随后确认没有说话，并反馈提示音偏短。实际说词次数为 0，
该轮只记录无说话窗口内 0 次触发，不计入唤醒成功率或正式 FAPH 验收。

本次发现系统 Logcat 小缓冲会在 90 秒内淘汰早期记录，主机工具已补充逐次累积
本会话事件文件，后续运行不再仅依赖最终缓冲快照。此主机改动通过 Python 语法检查，
尚未在下一轮实机会话验证。采集未留存音频；两份音频修改包进程已恢复。

## 版本 34：延长提示音

按用户确认，开始音改为一声 0.8 秒；结束音改为两声各 0.5 秒，中间间隔 0.3 秒
（总长 1.3 秒）。频率、幅度、渐变及录音窗口之外播放的顺序保持原有配置。
新增 `--cue-check` 模式，仅运行 5 秒采集窗口，跳过附加生命周期检查；
无需用户说话，退出时恢复音频修改包。此模式只验证提示音播放和短时运行，不评估唤醒率。

版本 34 构建、26 项测试、lint、shell/Python 语法检查通过并已安装至 r1-sample01。
[提示音实机检查](../test-results/README.md)：
开始提示写入并排空 25600 PCM 字节（0.8 秒），结束提示 41600 字节（含间隔共 1.3 秒）；
两次提示完成标记均保留。5 秒窗口完整处理 80000 样本、166 次推理，无处理超时。
会话事件累积文件本轮验证通过。主机仅确认播放写入/排空，用户对新时长的主观满意度尚未反馈。
[隔离恢复记录](../test-results/README.md)确认音频服务进程恢复。

## 版本 34：第二轮 90 秒真人功能测试

用户要求继续后，按计划约 1 米、正常音量、5 次 Alexa、间隔约 8 秒开启测试。
[监听证据](../test-results/README.md)、
[隔离恢复证据](../test-results/README.md)。

实际捕获 1440000 样本、2999 次推理，记录 4 次检测事件。事件位于输入 PCM 时间轴
5.240、23.570、31.130、40.520 秒，分数分别为 0.965625、0.93046874、
0.8960937、0.9164063；这些是已消费 PCM 末端时间，不是词尾延迟标注。
最大帧耗时 6.898 ms，部分读取与处理超时均为 0。开始/结束提示完成日志和
4 条事件均在累计会话文件中保留，测试退出后音频服务进程恢复。模型与阈值未调整。

用户随后确认实际说了 4 次，距离约 1 米，开始和结束提示音均听到。记录为
4 次自报说词 / 4 次设备检测，近距离功能试测通过，提示音实机可闻性通过。
本轮没有逐词录音标注，样本量仅 4 次，不将计数相符等同于正式召回率验收，
也不将这一功能试测计为独立盲测通过。没有保存麦克风录音。

下一步使用独立、逐次标注的 Alexa 验证和近音/非唤醒语句，冻结输入路径、模型
及阈值后再做盲测。误唤醒、远场、播放中唤醒及长期稳定性仍未验收，阶段 1 总门槛未通过。
