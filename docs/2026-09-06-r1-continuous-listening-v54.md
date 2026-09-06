> 历史记录：本文版本、命令及“下一步”反映记录当时状态；当前排期以[根 README](../README.md)为准。原始产物迁移见[归档说明](../test-results/README.md)，原验收结论不变。

# v54：无开始提示的持续监听

## 需求与已知实机证据

用户于 2026-09-06 确认：首次 Alexa 唤醒保留提示；持续对话不再播放“你说吧，我听着呢”等开始提示，回答结束立即接话。首次无输入和持续会话结束均播放一次现有结束语。空识别恢复原窗口剩余等待时间。

v53 真人证据保留在 `test-results/2026-09-06-r1-sample01-interaction-fixes/human-v53-events.log`：
- “语速调到百分之八十”实机设置为 80%；“当前语速是多少”回答 80%。
- 首次无输入 10 秒正常退出（当时设计为静默退出，v54 改为有结束语）。
- 持续静默一轮正常等待 15 秒；另两轮在开始提示后检测到约 240 ms 声音，约 2 秒结束采集，STT 为空后直接退出。用户确认没有说话。疑似提示尾音回录，不能仅据能量记录判定声源。
- “现在语速多少”曾得到天气回答，未取得该次识别原文，不能认定确切错词。解析器本来支持该句。

## 当前调用链

Alexa → 本地首次提示 → R1 首次等待（默认 10 秒）→ 有效开口后按停顿检测（现有 1.8 秒）/单条命令上限结束采集 → Native API → HA Whisper＋输入过滤 → 本设备确定性控制或家庭对话路由 → 中文 TTS → R1 播放。

回答本地播放完成 → 无开始提示，直接持续等待（默认 15 秒）→ 有效开口则进入同一讲话完毕检测流程；无开口到期则播放一次结束语 → 返回 Alexa 监听。首次等待超时也播放一次结束语。

识别为空 → R1 重置候选语音检测、保留窗口类型及原始时间预算 → 恢复剩余等待；识别及处理耗时计入已消耗时间，已到期则结束。网络/服务错误不按空识别处理。正常可识别但不理解的问题仍按对话路由处理，不扩展为空识别。

## 实现与兼容

- TTS 期间保持 VOICE_COMMUNICATION 录音并持续读出/丢弃；播放头消费完已写 PCM 后标记交接，保存此后的输入，供下一窗口按顺序处理。不以网络 TTS_END 或写入完成替代本地播放完成，不增加固定开头禁听时间。
- 交接队列最多 100 个 20 ms 帧（约 64 KB），清理时擦除；异常滞留超过上限明确失败，不无限堆积。播放期间不支持打断。
- 取消持续会话开始提示调用；结束提示之后丢弃交接帧并释放录音器，清理检测历史。
- 增加 `empty_resumes`、`ending_prompts` 运行计数。HA STT 诊断增加 `control_target`、`control_operation`、`speed_homophone`，不保存原文或录音，不把天气词全局纠正成语速。
- APK v54 / 0.54-continuous-listening；HA r1_input_guard 0.6.1。仍兼容 API 22、16 kHz 单声道 PCM、既有 Native API 固定版本和 Noise 配置。HA 两项等待设置及现有值保留，计时在 R1。

## 验证与交付

证据目录：`test-results/2026-09-06-r1-sample01-conversation-v54/`。

执行命令：

```sh
JAVA_HOME=/home/developer/.sdkman/candidates/java/17.0.19-tem ANDROID_SDK_ROOT=/home/developer/.local/share/android-sdk android/r1-probe/gradlew -p android/r1-probe --no-daemon testDebugUnitTest lintDebug assembleDebug
docker run --rm --network none --entrypoint python -e PYTHONPATH=/work/integrations/home_assistant -v /path/to/phicomm-r1-satellite:/work:ro ghcr.io/home-assistant/home-assistant:2026.8.2 -m unittest discover -s /work/tools/ha/tests -p 'test_*.py' -v
```

当前构建、部署结果见下方追加记录。真人待验：回应后立即接话连续至少 3 轮、首次和持续静默各至少 5 轮、两项等待时间分别通过 HA/语音修改并恢复默认。自动或本地诊断触发的麦克风检查不替代 Alexa 真人链路验收。语速错词的真实识别原因及 TTS 边界声学表现仍需实机证据。

### 已执行结果

- Android 136 项单元测试、lintDebug、assembleDebug 通过，HA 46 项测试及真实 HA 2026.8.2 容器配置加载/卸载检查通过。
- v54 APK 已在 R1 firmware 3448 安装并恢复 HA 连接；SHA256 `b0b32f861e869188cd19fbe9cc4449e552e578b532cec166dd3095f7dad206b5`。此前 v53 APK 在证据目录保留，哈希与已知 v53 一致。HA 0.6.1 比对更新、配置检查和重启通过；组件回滚目录 `/config/r1_component_backups/20260906T133408Z-ebd03b2f`。
- 当前设置保留：音量 25%、语速 80%、首次等待 10 秒、持续等待 15 秒、讲话停顿 1.8 秒。
- 本地管理接口触发真实麦克风静默检查：首次和持续各 1 轮通过，未触发上传或 STT，分别走各自等待时长并完成一次结束提示，返回 listening，无运行错误。检查总耗时含提示语，不能把它当纯等待时长。该检查绕过 Alexa，持续窗口也未经过真实 TTS 回答；不证明回答后立即接话或真实 TTS 尾音已经通过。
- 状态观察已启动，下一步由用户真人测试实际回答结束立即接话、连续至少 3 轮，以及各 5 轮真实静默场景；两项 HA/语音等待配置复验尚未执行。语速查询错词原因仍未验证。
