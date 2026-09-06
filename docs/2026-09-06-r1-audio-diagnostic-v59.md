> 历史记录：本文版本、命令及“下一步”反映记录当时状态；当前排期以[根 README](../README.md)为准。原始产物迁移见[归档说明](../test-results/README.md)，原验收结论不变。

# v59 有界音频诊断

## 目的与边界

排查 v58 提示结束约 1.92 秒后的静默误触发。当前尚未确定声源；v59 仅补充同步证据，不改变参考减除模型、VAD 门槛、禁听时间或 HA 处理。不是误触发修复交付。

用户选择静默优先：只有在明确的无人说话窗口开启采集；真人短句另行安排。不开启持续录音，不将家庭对话或原始音频提交仓库。Alexa 训练、选型及专项声学测试不在本轮范围。

## 诊断实现

- 管理入口沿用 ADB 本地抽象 socket，仍验证调用者 UID 为 root/shell。没有新增网络端口或凭据。
- `diagnostic-start --seconds N` 默认 30 秒，允许 1～30 秒；要求原生服务处于 listening。默认不采集，自动超时不依赖客户端在线。连接关闭、服务销毁也结束采集。
- 单一私有文件 `audio-diagnostic.r1diag`；未导出/清理前拒绝下一轮。进程中断后保留文件，状态为 `interrupted_previous_process`，不得作为完整采集。
- 64 条有界队列，单条 PCM 不超过 2048 字节，文件上限 8 MiB。音频线程只复制并非阻塞入队；独立线程写盘。队列满、容量超限或写入失败结束诊断并保留失败原因，不阻塞音频以等待磁盘。
- 同步记录麦克风原始片段、处理后帧、实际写入的本地提示 PCM；保存单调时间、录音读取开始时间、帧计数、提示编号、播放音量/播放头、VAD/能量/相关性及窗口事件。播放头诊断最多每 20 ms 一条。原始输入在播放丢弃阶段仍记录，重放的交接帧不重复记为麦克风读取。
- 处理后 PCM 只在原运行路径实际处理时记录。播放丢弃阶段不虚构 VAD 结果；HA TTS PCM 不在本地提示参考流内。HA 事件只记类型，不记识别文本或回答。

## 文件格式与使用

R1D1 文件头为四字节 ASCII `R1D1`。每条记录依次是大端 int64 序号、int64 单调纳秒、Java writeUTF 类型、writeUTF ASCII 元数据、int32 PCM 字节数和 PCM。PCM 本体为 S16LE、16 kHz、单声道。记录类型为 raw / processed / playback / event；两线程提交顺序可能与事件时间不同，分析时使用时间戳，不能只按记录序号推断因果。

```sh
python3 tools/native/manage-r1-native.py diagnostic-status DEVICE_SERIAL
python3 tools/native/manage-r1-native.py diagnostic-start DEVICE_SERIAL --seconds 30
# 先观测无提示监听基线，再在同一个明确的静默窗口触发：
python3 tools/native/manage-r1-native.py diagnostic-window DEVICE_SERIAL
python3 tools/native/manage-r1-native.py diagnostic-stop DEVICE_SERIAL
python3 tools/native/manage-r1-native.py diagnostic-export DEVICE_SERIAL --output test-results/DATE-r1-sample01-diagnostic/capture.r1diag
python3 tools/native/decode-audio-diagnostic.py test-results/DATE-r1-sample01-diagnostic/capture.r1diag test-results/DATE-r1-sample01-diagnostic/decoded
```

导出必须等待 `ready=true`，沿原 socket 每次读取最多 2048 字节，校验大小和 SHA-256 后写入来源/用途/UTC 元数据，随后凭同一 SHA-256 清理设备副本。任何传输/校验失败都保留设备文件，不覆盖主机已有文件；失败的主机部分文件也保留，重试换新文件名。必要时使用 `diagnostic-clear --sha256 HASH` 显式删除。

解码生成 `records.jsonl` 和三个 WAV；WAV 按各流记录拼接，**不代表无间隙的共同时间轴**。须结合原始读取时间、recorder_started/released、播放头及窗口事件定位。原始文件和 WAV 已加入忽略规则；只归档不含对话的统计及测试报告。

## 验证与后续

证据目录：`test-results/2026-09-06-r1-sample01-diagnostic-v59/`。

```sh
JAVA_HOME=/home/developer/.sdkman/candidates/java/17.0.19-tem ANDROID_SDK_ROOT=/home/developer/.local/share/android-sdk android/r1-probe/gradlew -p android/r1-probe --no-daemon testDebugUnitTest lintDebug assembleDebug
python3 -m unittest discover -s tools/native/tests -v
```

主机测试覆盖默认关闭、PCM 原值快照、自动超时、重复开始拒绝、磁盘阻塞导致有界溢出、中断文件保留、导出偏移检查、校验失败不清理、主机文件不覆盖、截断解码拒绝。主机通过不能替代 R1 诊断开销、真实录音连续性或误触发修复验证。

取得可靠静默证据后再决定最小修复；证据不完整或原因不明确则继续定向诊断。修复后执行 Alexa 静默至少五轮、立即说话/接话各至少三轮及持续静默；通过后进入网络恢复（30 秒）和 72 小时稳定性。未完成的第 14 章正式指标继续保留“未验证”。

## 本轮实际结果

- v59 已安装，APK SHA-256 为 `4759ab16b1e2028302f7e09bd734dbf56015d5c10d08ecfab243fc393853cae6`，与设备安装文件一致。
- 148 项 Android 单元测试、lint/构建通过；19 项 Python 工具测试通过。日志为证据目录的 `build.log` 和 `python-tests.log`。
- R1 恢复 `listening`、`last_error=null`，两次观察录音帧从 758 增至 2624；原包仍为隐藏状态。0/31 秒非法采集、无文件导出、错误哈希清理共四项请求均拒绝。诊断关闭、0 条记录、0 字节。
- v58 回退包保存为证据目录 `previous-satellite.apk`；其哈希与原 v58 报告相同，配置与原包状态基线保存在 `deployment-baseline.json`，配置快照在 `before.json`。必要时先停止原生服务，通过已验证的安装工具安装该 APK（`-r -d`），再 `start --listen`；无需解除原包隐藏。不要使用会同时恢复原音频包的整套隔离回退替代单独 APK 回退。
- 汇总见 `summary.json`。用户尚未确认本轮静默窗口，未开启采集；诊断实际开销、录音完整性、声源归因及修复后真人/网络/72 小时验收均未完成。


## 用户确认静默窗口后的六轮实测

用户分别确认首轮及追加五轮的无人说话窗口。六轮均通过本地管理接口触发，**绕过 Alexa，不能替代真实 Alexa 回归**；开始提示覆盖 ack:0/2/3/7。每轮完整等待约 10 秒、无命令上传/STT/TTS，各播放一次结束语。汇总见同证据目录 `silence-summary.json`，每轮保留 `capture.r1diag`、导出元数据、状态快照及 `analysis.json`；设备副本全部在校验后清理。

第一轮窗口开始后约 0～78 ms 有五帧被判为语音，首帧 AC RMS 625、与本地提示参考的相关性 0.918；第二轮首帧相关性 0.933。这支持提示残留仍进入开口检测，但没有复现 v58 约 1.92 秒后的误上传，不据此宣称该故障原因已确定或修复。

六轮观测到的参考处理最大耗时为 14.044 ms，未观测到参考处理超预算；但第二轮诊断队列 `max_offer_us=41624`，超过 20 ms，**本组诊断性能失败**。该统计为墙钟耗时，v59 无法区分录音/播放线程、锁等待和调度暂停；不能把它直接判为磁盘慢或确认丢帧。原始读取完成时间存在批量返回，也不能当硬件采样时间使用。其它五轮数据仍保留，失败轮不覆盖。

v60 随后对诊断生产者的队列锁等待进行改进并补充分线程耗时、自动超预算终止和分析器预算门槛，详见 `docs/2026-09-06-r1-diagnostic-queue-v60.md`。
