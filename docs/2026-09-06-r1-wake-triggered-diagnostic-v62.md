> 历史记录：本文版本、命令及“下一步”反映记录当时状态；当前排期以[根 README](../README.md)为准。原始产物迁移见[归档说明](../test-results/README.md)，原验收结论不变。

# v62 按真实唤醒触发诊断

> **2026-09-07 排期更新：** 用户已暂停意图/语音链路调试、断网/IP 变化恢复检查及 72 小时稳定性验收，优先补齐单台功能实现，再对最终候选版本统一验证。开发期间保留必要构建、单元测试和最小实机检查。本报告的测试结果、失败与未验证项保留，旧“下一步”和测试命令仅作历史/恢复说明，不代表当前待执行任务。当前入口见 [README](../README.md#下一步)。

## 发现与修正

v61 首轮真实 Alexa 静默交互通过：一次实际唤醒，ack:5，首次窗口约 9.964 秒，无上传/STT/TTS，一次结束语；诊断复制/入队最大 147 μs。第二轮 30 秒录音未观测到新的唤醒，但用户确认说了 Alexa 且设备回应。后续同一 HA 连接的计数确认新增一次唤醒、一次无输入结束和一次结束语，没有命令上传；结束语时间在录音最后一帧后约 17.848 秒。

结论是第二轮采集没有覆盖这次交互，不能判为设备未响应，也不能把这份录音计入完整静默验收。证据：`test-results/2026-09-06-r1-sample01-diagnostic-v61/real-alexa-summary.json`、`alexa-silence-02/after-user-report.json`。

## v62 行为

- `diagnostic-arm` 显式准备一次采集，最多等 90 秒。准备期间只有文件格式头，不写音频或事件；正常唤醒监听仍沿用原运行路径。
- 只有真实 Alexa 检测分支能激活采集，且在开始播放本地提示之前激活；本地 `diagnostic-window` 不激活。激活时无磁盘打开或创建操作，相关操作已在管理线程准备完成。
- 激活后最长录音 30 秒，从激活时重新计时；只触发一次，不自动重新准备。不保存触发前的关键词录音或等待阶段声音，适用于唤醒后误触发诊断。
- 超过准备时限记录 `arm_timeout`；停止、断线、服务退出及诊断超预算均结束准备/录音。设备重启不恢复准备状态。设备副本仍经大小及 SHA-256 校验后清理。
- 状态增加 `armed`；原有 `active` 区分是否正在录音。主机真实 Alexa 模式使用准备接口，等待期间继续观察状态，不注入本地窗口。分析器要求真实唤醒计数增加一次、窗口来源为 Alexa、窗口数增加一次，才可能通过。

```sh
python3 tools/native/capture-silence-diagnostic.py DEVICE_SERIAL --trigger alexa --output test-results/DATE-r1-sample01-diagnostic-v62/alexa-silence-01
python3 tools/native/analyze-silence-diagnostic.py test-results/DATE-r1-sample01-diagnostic-v62/alexa-silence-01
```

打印 `ARMED_FOR_ONE_REAL_ALEXA` 后通知用户说一次 Alexa，随后保持安静至结束语。每轮仍需明确的测试窗口。该能力不改变 KWS 模型/阈值、提示语、开口判定或 HA 对话逻辑。

## 验证

154 项 Android 单元测试、lint/构建通过；28 项 Python 工具测试通过。新增覆盖准备期间不写音频、仅一次激活、激活后重新计时、准备超时、取消后不再激活，以及主机在 armed/active 两阶段均正确等待且不注入窗口。命令：

```sh
JAVA_HOME=/home/developer/.sdkman/candidates/java/17.0.19-tem ANDROID_SDK_ROOT=/home/developer/.local/share/android-sdk android/r1-probe/gradlew -p android/r1-probe --no-daemon testDebugUnitTest lintDebug assembleDebug
python3 -m unittest discover -s tools/native/tests -v
```

本轮修正的是诊断采集时序，不能宣称 v58 的迟发误触发已修复。实机结果及下一入口在本报告后续追加；生产网络恢复、长期稳定性等仍未验收。


## 部署与首次准备超时

v62 已安装，SHA-256 `ee0250323981e03c5837cd5f37776dc5e37ebcadb771d912ca002b3bdd5353e7` 与设备一致，服务恢复 listening、无错误。首个 90 秒准备窗口未检测到唤醒，期间观测到 armed=true、active=false、records=0；到期后自动停止，导出文件只有 4 字节格式头，原因为 arm_timeout，校验后清理设备副本。

此轮验证了实机准备超时和未触发不保存音频，不是一次有效静默交互，也不能据此判为模型漏检。证据在 `test-results/2026-09-06-r1-sample01-diagnostic-v62/alexa-silence-01/`。后续改为准备后立即结束助手消息，让用户说词并回复“说了”，再核查由设备触发的采集结果。


## v62 首个有效真实唤醒采集

`alexa-silence-02/` 在准备后捕获一次真实 Alexa，首条记录包含 `capture_trigger=alexa`，确认由设备检测启动录音。实际提示 ack:5，等待 9978.736 ms，无上传/STT/TTS，一次无输入结束及结束语；诊断复制/入队最大 2853 μs，参考处理观测最大 12312 μs，无超预算。音频校验导出后清理设备副本。

这是 v62 当前版本 1/5 个有效静默检查样本。之前的准备超时及未覆盖交互的录音不计入通过轮次。未确认历史误触发已修复，继续同版本检查。


第二个有效样本 `alexa-silence-03/`：实际提示 ack:0，窗口 9958.484 ms，无上传/STT/TTS，一次结束语；诊断复制/入队最大 507 μs、参考处理观测最大 12754 μs，未超预算。导出已校验且设备副本清理，当前 v62 为 2/5 轮有效检查通过。


第三个有效样本 `alexa-silence-04/`：实际提示 ack:2，窗口 9968.621 ms，无上传/STT/TTS，一次结束语；诊断复制/入队最大 133 μs、参考处理观测最大 15005 μs，未超预算。导出已校验且设备副本清理，当前 v62 为 3/5 轮有效检查通过。


第四个有效样本 `alexa-silence-05/`：实际提示 ack:7，窗口 9972.071 ms，无上传/STT/TTS，一次结束语；诊断复制/入队最大 184 μs、参考处理观测最大 15005 μs，未超预算。导出已校验且设备副本清理，当前 v62 为 4/5 轮有效检查通过。


## v62 五轮真实 Alexa 静默检查汇总

五个有效样本为 `alexa-silence-02/` 至 `alexa-silence-06/`，每轮均由真实 Alexa 检测在设备上启动采集，用户说词后保持安静；不是本地管理接口注入。第一次准备超时不计入有效轮次。

| 有效轮次 | 提示 | 等待墙钟 ms | 诊断复制/入队最大 μs | 参考处理观测最大 μs | 结果 |
|---|---|---:|---:|---:|---|
| 1 | ack:5 | 9978.736 | 2853 | 12312 | 通过 |
| 2 | ack:0 | 9958.484 | 507 | 12754 | 通过 |
| 3 | ack:2 | 9968.621 | 133 | 15005 | 通过 |
| 4 | ack:7 | 9972.071 | 184 | 15005 | 通过 |
| 5 | ack:1 | 9961.979 | 4122 | 12200 | 通过 |

**本组 5/5 通过。** 每轮新增一次真实唤醒、一个窗口、一次无输入超时和一次结束语；上传命令、STT 和 TTS 增量均为零。覆盖五种提示，含历史 v58 失败使用的 ack:1。诊断复制/入队最大 4.122 ms，参考处理观测上限 15.005 ms，未观测到超预算。

所有本地录音重新校验 SHA-256，与导出元数据一致；设备副本已清理。最终服务 listening、last_error=null，诊断 active=false、armed=false、ready=false、bytes=0。汇总证据为 `real-alexa-five-round-summary.json`，最终状态为 `after-five-rounds.json`。

实际执行各轮 `capture-silence-diagnostic.py --trigger alexa` 和 `analyze-silence-diagnostic.py`，并检查 SHA-256、设备状态和诊断关闭。本阶段仅采集、分析及更新文档，没有改 APK，因此没有重复构建。

边界：这是同一台 R1、当前配置且诊断开启时的五轮首次静默检查。历史迟发误触发未复现，声源与针对性修复仍未确认；不能宣称彻底修复或生产验收通过。当时计划继续进行立即说指令、立即接话和短句等检查；该排期现已由 2026-09-07 用户决策替代，调试与网络/IP 恢复、72 小时验收暂缓，待单台功能实现齐备后统一验证。后续发生误触发时保留失败证据，不用本组通过覆盖它。
