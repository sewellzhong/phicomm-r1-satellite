> 历史记录：本文版本、命令及“下一步”反映记录当时状态；当前排期以[根 README](../README.md)为准。原始产物迁移见[归档说明](../test-results/README.md)，原验收结论不变。

# R1 Assist 运行服务与 HTTPS 接入（2026-09-05）

## 当前结论

版本42将无有效输入判断扩展为分层策略，见 [完整规则](./2026-09-05-assist-input-policy.md)。版本41的单项纯标点修正见 [无命令修正](./2026-09-05-assist-empty-command.md)。原随机回应与分段收音详见 [随机回应与分段命令收音](./2026-09-05-assist-acknowledgements.md)。
先回应、后等待命令；无检测到人声则6秒静默退出。50项主机测试、lint、构建及R1新VAD库
合成静音检查通过；新版完整录放音交互未验收。以下版本36～39内容保留为历史开发证据，
其两秒上传缓冲、固定8秒窗口、唤醒词前缀删除策略以版本40说明为准。

## HTTPS 访问差异和 API 22 适配

用户浏览器可访问 `https://home-assistant.sewellzhong.com/home-control/overview`。
R1 和 HA 主机将此域名解析到 192.0.2.10；HA 主机 HTTPS 返回 200。
开发机默认 DNS 超时，但用 `curl --resolve` 指定同一地址后返回 200 且证书校验为 0（成功）。
不能将开发机的 DNS 故障当作该 HTTPS 服务不可用。应用使用 HTTPS origin，
不使用浏览器页面路径，也不降级到 HTTP。

R1 初次 HTTPS 连接报告 tls_failed。该设备系统信任库没有 ISRG Root X1 的
`6187b673.0` 文件。实际服务器链为叶证书 → YE1 → Root YE → ISRG Root X2 →
ISRG Root X1。应用新增 AssistHttpClient，在系统受信根基础上补充官方 X1，
继续使用正常证书链、日期和域名校验；TTS 下载共用同一配置。

- 公开根证书：[Let's Encrypt 官方 PEM](https://letsencrypt.org/certs/isrgrootx1.pem)
- 链说明：[Let's Encrypt 官方证书链](https://letsencrypt.org/certificates/)
- 根证书 DER SHA-256：
  `96bcec06264976f37460779acf28c5a7cfe8a3c0aae11a8ffcee05c0bddf08c6`
- 本地资源：`android/r1-probe/app/src/main/resources/assist/isrgrootx1.pem`
- 此资源是公开信任根，不含私钥、HA 令牌或其他用户凭据。

补充信任根后，以无效占位字符串进行的 R1 连接到达 HA 并返回 authentication_failed，
说明 TLS 已通过、认证拒绝生效。改用证书不匹配的 IP 地址连接时仍返回 tls_failed。
本轮没有使用真实账户认证，不能将预期的认证拒绝写成认证成功。

## 服务行为

- AssistRuntimeService 默认只等待配置；配置中 listen 默认 false。
- 认证成功且选定中文管线通过校验后，listen=true 才打开 AudioRecord。
- 空闲保持本地 Alexa 和 2 秒 PCM 环形内存；版本 39 仅上传最近 200ms，当前触发帧不重复上传。
  后续音频按 20ms 发送，关闭 HA VAD 自动结束，由客户端采用至少 8 秒窗口、1.5 秒安静尾部、
  最长 20 秒输入上限，管线超时仍为 60 秒。新端点实机效果尚未验证。
- TTS 到达后释放录音，再下载/播放同源 HTTPS 回复，完成后重置缓冲及引擎并回到监听。
  未实现播放中插话、流式 TTS 或主动广播。
- TTS 下载上限 8 MiB、网络时限 30 秒、播放上限 120 秒。
  生成的回复只暂存应用私有缓存，正常播放/服务退出时删除，下次启动也清理残留。
- 断线清理当前请求后从 2 秒至 30 秒退避重连，不重放命令。
  认证、中文管线或 TLS/DNS 配置错误直接停止本次运行，避免重复无效认证。
- 本开发服务最长运行一小时，不设开机自启。停止时清理网络、录音与 wake lock。
  这些生命周期及录放音组合尚未做带真实 HA 认证的 R1 验收。

## 安全配置和启动

`tools/assist/run-r1-assist.py` 使用终端隐藏输入，或从专用标准输入管道读取一个令牌；
不提供把令牌放在命令参数中的选项。全部 ADB 子进程的标准输入被隔离，避免消耗或转发
令牌管道内容。配置经 ADB 转发至应用的 LocalServerSocket，只接受 root/shell UID。
令牌不进入 Intent、仓库文件、APK、日志或持久配置，只用于当前运行内存中的认证和重连。

在开发机终端执行，仅核验认证、不打开麦克风：

```bash
python3 /path/to/phicomm-r1-satellite/tools/assist/run-r1-assist.py \
  192.0.2.10:5555 \
  --url https://home-assistant.sewellzhong.com \
  --pipeline 01m04j14wzw45d4094qn1s6x68
```

提示时输入 HA 访问令牌，不要把令牌发到聊天或写在命令行中。认证成功后工具自动退出并
关闭该连接。如需直接进入语音运行，在同一命令后加：

```text
--listen --isolate-audio
```

listen 模式会在核对 R1 固件和既有备份后，临时停止当前两个音频修改包。
退出或 Ctrl+C 时停止独立服务、移除 ADB 转发并恢复原音频服务。
该工具必须保持运行；当前不是脱离开发机的生产常驻方案。

## 验证

执行了 `testDebugUnitTest lintDebug assembleDebug`、Python 语法检查，
38 项主机测试及 lint/构建通过。新增根证书校验和默认 hostname verifier 保持检查。
R1 安装成功；不开麦验证了控制通道、无效令牌的认证拒绝及不匹配地址的 TLS 拒绝。
实际中文识别、控制指令、TTS 可闻回复、重连后的语音效果仍未验证。

[本轮构建、产物哈希和验证汇总](../test-results/README.md)。

## 用户启动后的状态确认

用户终端显示 connecting → listening；通过既有 ADB 内存控制通道仅发送 status 查询，确认当前仍为 listening。真实认证和中文管线校验通过。未读取、保存或记录令牌，未中断正在运行的服务，未启动额外 KWS 测试。见 [状态记录](../test-results/README.md)。


## 版本 37：运行事件和音频计数

用户确认灯具尚未安装，并报告说灯控命令、时间问答后终端均无 listening 以外的新状态。
旧版只提供当前状态，不能据此确定是漏唤醒、请求失败还是短暂状态被轮询遗漏。
不把这一现象标记为语音闭环通过，也未因设备缺失忽略时间问答的问题。

版本 37 增加最多 32 条枚举事件和累计音频帧数、峰值、最高模型原始分数、
有效唤醒/STT/TTS 次数。事件仅包含序号和阶段，不包含令牌、URL、识别正文或录音。
主机工具按序号补齐两次轮询之间的事件，每 10 秒显示一次音频计数，并输出安全错误码。
这属于运行诊断，不调整模型、阈值或音频格式。

40 项主机测试、lint、构建通过；R1 安装完成。不开麦检查确认控制通道返回完整字段，
waiting_configuration 时音频帧与检测计数均为 0。为升级已让原启动工具正常退出并恢复
音频修改包；需要用户重新执行启动命令、隐藏输入令牌。原“无状态输出”的原因仍待新日志定位。
[版本 37 证据](../test-results/README.md)。

HA 发现的 Phicomm_R1_D537 / DLNA Digital Media Renderer 用于媒体播放控制，
当前 APK→Assist WebSocket→APK TTS 路径不依赖该集成。未添加 DLNA 不会阻断此路径，
也不能通过补加它来证明唤醒/上传成功。参见
[HA 官方 DLNA DMR 说明](https://www.home-assistant.io/integrations/dlna_dmr/)。


## 版本 37：首个回复的软件事件闭环

用户重新启动并输入令牌后，只读查询观察到 wake_detected → upload_started →
stt_complete → tts_ready → run_finished → playback_started → playback_finished → listening。
累计唤醒/STT/TTS 各 1 次，last_error 为空。软件请求和播放生命周期已完成一轮，
服务保持运行，未要求重新录制样本或改变模型参数。实际中文回复的内容和可闻性仍待用户确认，
不将该单轮事件等同于阶段 2 的 30 次命令验收。
见 [当前运行快照](../test-results/README.md)。


用户随后提供完整终端事件，并确认 R1 实际播报“抱歉，找不到名为xxx的设备”。
因此单轮 Alexa → HA 处理 → 中文 TTS → R1 可闻回复的基础通路已实机完成。
用户随后确认本轮说的是“Alexa，现在几点？”。问时收到设备未找到回复，
本轮意图验收失败，不能用灯具尚未安装解释。当前客户端仅统计 STT 完成次数，
没有保留识别文本，因此尚不能区分 Whisper 识别偏差与 HA 意图匹配问题。
已只读核实当前管线为中文 Whisper + conversation.home_assistant；下一步查看 HA 本轮
管线调试记录中的识别文本和意图结果，无需重新开展唤醒测试。
此记录不计为灯控成功或正式阶段 2 成功率验收。


## 版本 38：句首 Alexa 进入设备名的修复

用户提供 HA 调试文字 `alexa现在几点？`，回复为“抱歉，找不到名为 alexa现在 的设备”。
HA Core 2026.8.2 的 `wake_word_phrase` 只负责重复唤醒去重，不删除 STT 文字中的唤醒词。
版本 38 改用 STT→STT 请求，收到 stt-end 后在内存中删除句首 Alexa（忽略大小写，
支持紧邻中文和分隔标点），等该请求 run-end 后发起 intent→tts 请求。
保留原有两秒音频缓冲，避免剪掉紧接唤醒词的命令；不删除句中 Alexa 或 Alexander 等其他名称。
仅有唤醒词则返回监听，不发起空意图。两个请求通过各自 ID 隔离，只有第二个完成才报告整轮完成。
不保存识别正文或令牌，不改变 HA 配置及 Alexa 模型。

`testDebugUnitTest lintDebug assembleDebug` 通过，含本轮原句回归、旧事件隔离、
STT 失败不提交意图、空命令及会话保留。Python 编译检查通过。
升级需结束原内存认证会话，用原启动命令重新输入令牌。修复后问时意图结果见下方用户反馈；未安排额外 KWS 测试。
证据见 [版本 38](../test-results/README.md)。
依据：[HA 2026.8.2 pipeline 源码](https://github.com/home-assistant/core/blob/2026.8.2/homeassistant/components/assist_pipeline/pipeline.py)
及 [WebSocket schema](https://github.com/home-assistant/core/blob/2026.8.2/homeassistant/components/assist_pipeline/websocket_api.py)。


版本 38 后续用户反馈：命令“现在几点？”正确调用 `HassGetCurrentTime`，显示结果“下午5点55分”。本轮 HA 问时意图成功，原 Alexa 前缀混入设备名的问题在该请求中未再出现。本轮 R1 是否实际播报时间尚未明确确认，时间准确性未独立核对；单次成功不等同于正式阶段 2 成功率或稳定性验收。证据来源为用户提供的调试文字，未采集新音频。


## 开发机会话后台运行

已新增 [tmux 后台管理入口](./2026-09-05-assist-background.md)，可在关闭 SSH 窗口后保持启动器运行。令牌仅在内存、一小时服务上限、开发机和 ADB 依赖均保持不变。


## 版本 39：等待窗口和误转写

见 [命令窗口修正](./2026-09-05-assist-command-window.md)。用户报告停顿后只识别唤醒词及中文混合误转写；修正缩短上传预缓冲并由客户端控制录音结束，包含 8 秒最短窗口带来的响应延迟代价。
