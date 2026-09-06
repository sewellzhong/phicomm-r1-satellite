> 历史记录：本文版本、命令及“下一步”反映记录当时状态；当前排期以[根 README](../README.md)为准。原始产物迁移见[归档说明](../test-results/README.md)，原验收结论不变。

# v60 诊断队列与预算门槛

> **2026-09-07 排期更新：** 用户已暂停意图/语音链路调试、断网/IP 变化恢复检查及 72 小时稳定性验收，优先补齐单台功能实现，再对最终候选版本统一验证。开发期间保留必要构建、单元测试和最小实机检查。本报告的测试结果、失败与未验证项保留，旧“下一步”和测试命令仅作历史/恢复说明，不代表当前待执行任务。当前入口见 [README](../README.md#下一步)。

## 依据

v59 的六轮用户确认静默检查均未误上传，但第二轮记录 `max_offer_us=41624`。该计时包括调度暂停，不能据此确定是哪条线程被阻塞或认定实际丢帧；整组诊断性能不通过。完整失败证据保存在 `test-results/2026-09-06-r1-sample01-diagnostic-v59/silence-02/`。

## 改动

- 诊断生产者改用 `ConcurrentLinkedQueue` 加原子计数预留，最多 64 个待写记录，避免生产者等待消费者持有的队列锁。写线程只在无数据时休眠 5 ms，不让音频线程等待磁盘。
- 跟踪执行中的生产者，正常停止时等待已接纳记录排空；拒绝采集开始前的旧时间戳。保留 30 秒、单份私有文件、8 MiB 及哈希导出边界。
- 保留 `max_offer_us`，增加复制/入队耗时 `max_producer_us`、录音线程 `max_capture_producer_us`、提示播放线程 `max_playback_producer_us` 及 `producer_over_budget`。这些是墙钟耗时，包含被系统抢占的时间；不等于 CPU 时间，也不覆盖调用方全部字符串构造和整帧 DSP 开销。
- 复制/入队超过 20 ms 时终止诊断，原因 `producer_over_budget`，保留文件用于分析。调度抢占仍可能导致超预算，不能因改用非阻塞队列就宣称实机开销通过。
- 新增静默采集及数字分析工具；分析报告分别列出静默行为和诊断预算，任何一个失败都不能通过本轮回归。诊断在基线阶段已停止时，不再触发设备提示。

不改变提示参考减除、VAD、开口条件、HA 协议或当前音量/等待参数，不代表 v58 静默误触发已修复。

## 验证

```sh
JAVA_HOME=/home/developer/.sdkman/candidates/java/17.0.19-tem ANDROID_SDK_ROOT=/home/developer/.local/share/android-sdk android/r1-probe/gradlew -p android/r1-probe --no-daemon testDebugUnitTest lintDebug assembleDebug
python3 -m unittest discover -s tools/native/tests -v
```

150 项 Android 测试、lint/构建通过；24 项 Python 测试通过。新增测试覆盖并发生产者排空、过期帧拒绝、超预算自动停止、预算失败不掩盖静默行为及基线提前结束不触发提示。

证据目录为 `test-results/2026-09-06-r1-sample01-diagnostic-v60/`；构建与工具日志分别为 `build.log`、`python-tests.log`。用户已同意部署后追加一轮静默采集；实机结果完成后追加，不以主机测试代替。


## v60 单轮实机结果

v60 已安装，哈希 `ff6c6f34231e4064833b680d2f7440fe1926caaf557e29b398db9f763a942d95` 与设备一致。用户确认后追加的一轮使用 ack:4：无上传/STT/TTS，完整等待后一次结束语。诊断入队最大 100 μs、复制/入队最大 1113 μs（录音线程 1113 μs，提示播放线程 94 μs）；参考处理观测最大 12266 μs，无预算超限。单轮通过，不代替长时性能或真实 Alexa 验收。

原始文件校验后已清理设备副本，本地证据在 `silence-01/`，汇总为 `summary.json`。回查 v58 失败证据确认当时开始提示为 ack:1；本轮及 v59 六轮尚未覆盖该编号。当时的下一入口是固定 ack:1 的定向复现，不改变正常随机回应；后续结果见下文，当前排期以文首更新为准。


## v61 固定提示诊断入口

新增 `diagnostic-window --prompt-index 1`，仅供 shell 授权的本地首次窗口诊断使用；默认仍随机，真实 Alexa 路径不使用覆盖值。索引范围从现有提示选择器取得（当前 0～9），续听窗口拒绝指定开始提示。请求取出时标记 `diagnostic_requested`，避免取出与播放之间再次接受请求。

一轮明确静默采集的入口：

```sh
python3 tools/native/capture-silence-diagnostic.py DEVICE_SERIAL --prompt-index 1 --output test-results/DATE-r1-sample01-diagnostic-v61/prompt-1-round-01
python3 tools/native/analyze-silence-diagnostic.py test-results/DATE-r1-sample01-diagnostic-v61/prompt-1-round-01
```

执行前须确认无人说话窗口；不要未经确认运行以上命令。该工具先录制 5 秒无提示基线，再触发固定提示。152 项 Android 测试、lint/构建和 26 项 Python 测试通过，覆盖固定索引不消耗随机序列、非法索引/续听覆盖拒绝及 CLI 参数传递。v61 的实机定向复现尚未执行。

v61 证据目录：`test-results/2026-09-06-r1-sample01-diagnostic-v61/`。停止后再次开始采集仍须显式操作；诊断开关不持久化。


v61 已安装，SHA-256 `7154151fdaac32068ea8dfade79eb69dd7294c14e41ccb69e886da73d4e36d89` 与设备一致。R1 为 listening、last_error=null，原配置/设备身份/原包隐藏状态均保留；-2/10 非法编号与续听指定编号三项实机请求均被拒绝。诊断关闭、0 字节，未执行固定编号 1 的录音。v60 回退 APK 与部署基线保存在 v61 证据目录，结果见 `summary.json`。


## v61 固定 ack:1 首轮实机结果

用户确认后执行：

```sh
python3 tools/native/capture-silence-diagnostic.py 192.0.2.10:5555 --prompt-index 1 --output test-results/2026-09-06-r1-sample01-diagnostic-v61/prompt-1-round-01
python3 tools/native/analyze-silence-diagnostic.py test-results/2026-09-06-r1-sample01-diagnostic-v61/prompt-1-round-01
```

已确认实际提示为 ack:1。首次等待墙钟 9963.476 ms（端侧按 20 ms 帧计时），无命令上传、STT 或 TTS，超时一次、结束语一次，回到 listening。诊断复制/入队最大 2244 μs（录音线程 2244 μs、播放线程 136 μs），入队最大 327 μs；参考处理观测最大 15675 μs，未观测到超预算。本轮行为与诊断预算通过，仍绕过 Alexa。

窗口开始后前约 61 ms 有四帧被判为语音，之后降为安静。窗口后 1.6～2.2 秒的 29 帧，AC RMS 最大约 28.93，VAD 和合格语音帧均为零；历史 v58 的 1900 ms 桶为峰值 74、5 帧 VAD/合格/强语音。历史为帧计时、当前为读取完成墙钟，时间基准不能视为精确硬件采样时间。定向检查仍未复现历史迟发输入，具体声源与修复保持未确认。

证据在 `test-results/2026-09-06-r1-sample01-diagnostic-v61/prompt-1-round-01/`，含 `analysis.json`、`late-window-comparison.json`、采集文件及校验元数据。原始录音只留本地，设备副本已清理；检查结束诊断关闭、0 字节，服务 listening、last_error=null。

本轮没有修改 APK 或处理阈值，因此未重复构建。当时下一项有区分价值的检查为用户配合的真实 Alexa 唤醒后静默交互采集（当前已暂停）；不继续无差别增加本地接口随机轮次。真实 Alexa 回归、网络恢复与 72 小时稳定性均未通过本轮交付。
