> 历史记录：本文版本、命令及“下一步”反映记录当时状态；当前排期以[根 README](../README.md)为准。原始产物迁移见[归档说明](../test-results/README.md)，原验收结论不变。

# R1 v47：可配置时间、音量、语速与对话提示

## 已部署行为

R1 sample01 已安装版本47，HA 的 `r1_input_guard` 升级到0.4.0。原有非root `hide/unhide` 隔离和Noise认证保留。

| HA配置 | 默认值 | 范围与生效方式 |
| --- | --- | --- |
| 等待开口时间 | 20秒 | 1～120秒，步长1秒；首次唤醒和连续对话共用 |
| 讲话结束停顿时间 | 1.8秒 | 0.2～10秒，步长0.1秒 |
| 单条命令总时长 | 30秒 | 5～120秒，步长1秒 |
| 音量 | 沿用设备当前值 | 0～100%；R1实际为15档，回传实际百分比 |
| 语速 | 0.85倍 | 0.5～1.5倍，步长0.05倍；统一控制本地提示与HA回答 |

前三项和语速使用数值输入框，音量使用滑块；另提供只支持音量设置/增减的 `media_player.音箱` 实体。设备端使用固定协议生成的Number消息和稳定实体键；数值在R1私有配置中持久保存，音量由Android媒体音量服务保存。没有新增网络管理端口或硬编码凭据。

等待开口从提示播放完成、尾音衰减且麦克风重新采集后开始计时；检测到人声后等待计时停止。连续停顿达到阈值或命令总时长达到上限时提交，以先到者为准。每个命令窗口持有独立配置快照，新设置不改变已开始的窗口。首次唤醒后未开口保持静默退出，不调用STT/对话服务。

原生传输的输入上限扩展为121秒音频（容纳120秒命令及起始缓冲），输入总期限130秒；HA输入流同样设定边界，5秒输入停滞仍失败，识别总期限190秒。播放绝对上限300秒，重复事件不会续期；上下文保留期延长至900秒，避免慢回答与长等待过早使R1会话映射失效。旧WebSocket模式保持原有计时配置。

## 声音与HA配置

进入连续监听提示：

- 我在听呢，你接着说。
- 你说吧，我听着呢。
- 我还听着呢，不着急。
- 好嘞，我听着，你继续。

结束提示：

- 那这次就聊到这儿，有事再叫我。
- 好嘞，这轮结束啦，想聊再叫我。
- 我先不听啦，有事再叫我。
- 咱们先聊到这儿，下次叫我再聊。

每组随机、不连续重复。沿用原生“回答后可继续说”的交互策略，在回答排空后播放进入提示，然后重新开麦；连续等待超时或明确“结束对话”时播放结束提示，回到仅检测Alexa。异常不伪装成正常结束。提示播放时释放录音，清空缓冲并留200毫秒尾音衰减时间。

原有10条唤醒回应及新增8条提示，每条生成21个语速档位，共378个WAV资源；仅包含批准的固定合成文案。资源按当前语速选择，不在R1上加载变速引擎。所有资源已核对格式、哈希及APK未压缩存储，确保API22的AssetFileDescriptor可访问。资源约21MiB，APK约24MiB；资源总大小不是常驻内存占用。

HA新增R1专用 `tts.r1_zhong_wen_hui_ying`，复用Piper声音，使用FFmpeg `atempo` 保持音调地变速。按请求开始时的设备语速处理流式音频，输出仍为PCM16/16kHz/单声道；其他助手继续使用原Piper设置。没有通过改变AudioTrack采样率降低音调。[FFmpeg说明](https://ffmpeg.org/ffmpeg-filters.html#atempo)

原“助手2”“唤醒词2”和不生效的HA端“讲话完毕检测”已隐藏而非删除。针对HA2026.8.2，适配层读取真实ESPHome唤醒配置并通知已有实体更新，主Wake word已显示Alexa。该适配使用固定版本的配置刷新方法，没有声明尚未实现的ANNOUNCE能力。

音量语音命令由R1原生会话入口进行明确、设备绑定的匹配，支持“把R1音量调到百分之三十”“声音大一点”“小声一点”等。没有指定其他目标时只控制发起会话的R1；不扩大家庭AI模型的设备操作权限。相对增减目标为10个百分点，但实际按15档量化；例如50%对应第8档、约53.33%，答复采用设备回读值。

## 验证结果与限制

证据目录：`test-results/2026-09-06-r1-sample01-interaction/`。

- Android119项测试通过，覆盖新的时间边界、临近超时开口、30秒协议上传，以及播放绝对超时；lint和APK构建通过。
- HA32项测试通过，覆盖120秒输入、超长拒绝、变速时长/格式/音调、音量识别及目标限制、平台重载和实体标识匹配。
- 实际HA/R1验证将等待、停顿、命令上限、语速分别写成23、2.4、42、1.05并成功回读；音量实际写入约53.33%。固定文本“声音小一点”经真实R1会话入口将音量降低到40%，随后恢复测试前约33.33%。这是HA固定文本测试，不是麦克风语音验收。
- 同一句固定TTS测试文本在0.5倍与1.5倍时分别为3.665625秒、1.296秒，格式为PCM16/16kHz/单声道。没有保存音频样本。
- HA实测确认三个旧选项已隐藏、主唤醒词为Alexa。配置和语速最后恢复为默认值。
- R1普通重启后约18秒自行恢复连续收音，时间/语速配置和各媒体输出路由音量保持一致，原两包仍隐藏且无进程。
- 当前完整真人音量指令、提示可闻性和主观语速体验等待用户确认；未启动72小时稳定性验收。

初次实机升级暴露并修复了三项兼容问题：新增平台后按实际已加载平台卸载；匹配HA当前的Number实体标识格式；管线更新传入完整配置。音量验证还修复了浮点步长在50%边界产生的档位偏差，改用整数硬件档数计算。失败结果保留在相应 `ha-upgrade*.json`、`ha-live-verification.json`，通过结果为 `ha-final-verification.json`；修正音箱实体设备归属后的复验为 `ha-device-verification.json`，最终实体归属和隐藏状态见 `ha-ui-entities.json`。

实际命令：

```sh
python3 tools/assist/prepare-interaction-prompts.py
JAVA_HOME=/home/developer/.sdkman/candidates/java/17.0.19-tem ANDROID_SDK_ROOT=/home/developer/.local/share/android-sdk android/r1-probe/gradlew -p android/r1-probe --no-daemon testDebugUnitTest lintDebug assembleDebug
docker run --rm --network none --entrypoint python -e PYTHONPATH=/work/integrations/home_assistant -v /path/to/phicomm-r1-satellite:/work:ro ghcr.io/home-assistant/home-assistant:2026.8.2 -m unittest discover -s /work/tools/ha/tests -p 'test_*.py' -v
python3 tools/native/deploy-r1-native.py install 192.0.2.10:5555 --evidence test-results/2026-09-06-r1-sample01-interaction
python3 tools/native/pair-home-assistant.py --upgrade-interaction 02:00:00:00:00:01
```

`--upgrade-interaction` 是配置管理员通过私有一次性标记执行的显式升级及设备测试，会重启HA并暂时修改配置后恢复；不是日常调节入口。日常配置直接使用HA设备页面。

## 回退基线

- 本轮 `deployment-baseline.json` 与 `previous-satellite.apk` 保存v46，原包隐藏状态仍为true。
- HA升级前组件备份：`/config/r1_component_backups/20260906T064301Z-d99dabf4/r1_input_guard`，原始文件哈希在 `ha-before-hashes.json`。
- 回退时先停止原生运行；通过HA正常助手设置把“R1 原生中文助手”的TTS改回 `tts.piper`，再恢复组件备份并重启HA，之后回退APK并恢复原生监听。原身份、Noise密钥及原包隐藏状态保持。
- 不应单独回退APK而保留依赖新数值实体的R1专用TTS配置。整套回退本轮未实际执行；备份和原包恢复基线不等于固件回刷验证。

最终APK SHA-256：`b1f1a461c576e422be3582ec45cb10420aa2eef00bde5e67ef3dbd2acdb8b4fc`，已与R1现装文件一致核验。
