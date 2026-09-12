# v102 O3 真实流式回答与播放中取消实机记录

日期：2026-09-12

设备：`r1-sample01`，Android 5.1.1 / API 22，固件增量 `3448`，SELinux Enforcing；boot 仍为 v28，未改写 boot、system、recovery、Loader、分区表或数据分区。

## 结论

O3 在当前固定版本的真实 HA、模型、TTS 与首台 R1 上通过自动链路验证：真实 DeepSeek 增量先于全文完成，HA 在意图尚未结束时通知早期 TTS，R1 立即读取 HA 在 `RUN_START` 下发的有签名 URL，边接收边解析 WAV 并写入扬声器。最终长回答首次写入比同一会话的 HA `RUN_END` 早 3,131 ms，连续播放 219,128 ms，完整排空并释放，缓冲无 underrun。播放中取消在首次写入后 148 ms 完成本地释放，旧回答未计为完成，HA 会话正常结束且无需断线重连。

该结论只覆盖自动固定输入、协议、真实后端、HTTP/WAV 与 R1 播放数据链，不覆盖真人听感、唤醒率或识别率；这些项目按现行决定为“用户跳过/未验收”。它也不表示全部首台功能齐备，网络/IP 恢复与 72 小时稳定性仍按最终候选统一执行。

## 固定版本与部署

- R1 源码提交：`28cfe08`，包含固定 PCM 验证入口、播放时钟、取消释放证据、早期 HTTP TTS、WAV 严格解析与格式协商；前置实现提交为 `e85a845`、`4ceba55`、`b0f36f9`、`86faa63`、`1d5f373`。
- APK：versionCode `102`，versionName `1.02-http-wav-negotiation`，SHA-256 `3ab44785ce54e2a2830de1f2d5d4d1d9198c867e1c8ec0588cf9e21a7b98f0f4`；签名证书 SHA-256 `0be7a3643442658354c185ec53cb50e73bc1516a56f2760ca46f2c932c1d2639`，与原回退包一致。
- 私有回退目录：`local-recovery/r1-sample01/2026-09-12-v102-http-wav-deployment/`；部署器确认旧 APK 已保存、候选安装成功、原厂包保留且继续隔离。
- HA Core `2026.8.2`。`domestic_ai` 2.2.0、`conversation_router` 2.1.0 与当前 `r1_input_guard/conversation.py` 均按哈希部署；旧卫星适配文件备份在 HA 的权限 0700 私有目录中。
- HA 源码回退包均为 0600：`streaming-before-v96-20260912T1317.tgz`（13,523 字节）和 `streaming-probe-before-20260912T1326.tgz`（2,433 字节）。

## 真实 HA 证据

HA 一次性 `verify_streaming` 使用真实家庭路由和 DeepSeek，不保存生成文字：

- `supported=true`，错误为空；
- 229 个有序增量，共 368 个字符，最终结果也是 368 个字符；
- 首增量 1,459 ms，全文完成 2,902 ms，首增量明确早于完成；
- 结果文件权限 0600，`text_saved=false`。

部署文件哈希与 v96 固定源码一致：`api.py` 为 `f5c19e8d…3db9`、`conversation.py` 为 `97678e48…6e47`、`router.py` 为 `bbdc6630…8cce`、家庭路由会话为 `a5b57230…74814`；一次性流式探针 `commissioning.py` 为 `c7cc6e90…0a3d`。HA 配置检查和重启均成功。实际 HA 原先仍部署非流式 `r1_input_guard/conversation.py`（`2bebac6e…cd38`）；只替换为当前 `7a733da4…7780` 后才收到早期流式标记，其余适配文件哈希原本即一致。

## R1 自动实机结果

固定输入为 Piper 合成、Whisper 直接复核的 16 kHz/S16LE/单声道 WAV，不含家庭录音。最终输入 SHA-256 为 `8d2fece40745993392e7fe6c5b346ebe77736cc19f8f2d2724b6a0ae94379d24`，时长 6.1185 秒；其含义是要求生成至少一千个汉字的太阳系科普文章。验证工具不保存 STT 或模型正文。

长回答运行：

- STT、TTS 流、完成与固定 PCM 运行计数均精确增加 1；错误为空；
- `tts_stream_start_ms=49956561`，R1 `first_write_ms=49958022`，HA `run_end_ms=49961153`，首写早于运行结束 3,131 ms；
- 播放 `219128 ms`，`drained_ms=50177150`，`released_ms=50177152`；
- 缓冲高水位 32,656 字节，小于固定 32 KiB 容量；underrun 0，HTTP 错误 `none`。

播放中取消运行：

- STT、TTS 流、固定 PCM 运行和取消计数各精确增加 1，完成计数不增加；
- `first_write_ms=50205125`，`released_ms=50205273`，首写后 148 ms 完成释放；
- `drained_ms=0`，证明旧回答没有伪装为完整排空；HA `run_end_ms=50205300`，最终回到 `listening`；
- underrun 0、HTTP 错误 `none`、未发生连接重建。

短回答回退也已验证：没有达到 HA 流式阈值时，R1 在 `TTS_END` 使用同一有签名 URL，播放 4,299 ms 并完整排空。v100 首次 HTTP 尝试因 HA 默认编码不是 WAV 而以 `tts_wav_header_invalid` 失败关闭；v102 通过无控制能力的内部媒体格式实体只协商公告 WAV/16 kHz/单声道/S16，修复后没有重复 API 音频流。

## 主机门禁与边界

完整 `python3 tools/dev/prepare.py && bash tools/dev/check.sh` 通过：最终公开扫描 401 个文件/0 发现、secret scan 0、Android 构建/单元测试/lint 成功（193 项）、原生工具 35 项、恢复 73 项及演练、原厂音频 117 项、HA 51 项与固定 HA 2026.8.2 加载检查。相邻`home-ai`仓库检查为0错误/0警告，69项测试通过（其中37项按设计只在固定HA镜像执行）；固定HA 2026.8.2中的完整69项此前已全部通过。

早期 URL 仅来自已通过 Noise PSK 认证的 HA 会话；只允许无 user-info、无 fragment 的 HTTP(S)，禁止重定向，连接/读取/总时长、WAV 块与总字节均有上限。只接受 PCM S16LE、16 kHz、单声道；32 KiB 环形缓冲施加背压。取消同时中断 HTTP、清空缓冲、停止并释放 AudioTrack，再由单一协议线程发送远端取消。

## 下一步

按当前顺序进入主动播报与计时器，再实现本地闹钟及免打扰。O3 的失败样本和修复过程保留为诊断；不提前恢复网络/IP、72 小时稳定性或真人语音验收。
