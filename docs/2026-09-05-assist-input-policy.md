> 历史记录：本文版本、命令及“下一步”反映记录当时状态；当前排期以[根 README](../README.md)为准。原始产物迁移见[归档说明](../test-results/README.md)，原验收结论不变。

# R1 无有效输入的分层判断（版本 42）

## 结论与依据

“没有说话”“说了话但无法识别”“识别出了字但HA不支持这个意图”是不同情况。
本实现把确定无有效输入的请求静默结束，把正常文字交给HA，把真正的服务或协议故障保留为错误。
不承诺覆盖所有识别幻觉，不靠不断扩大的常见句子黑名单假装能判断用户是否说话。

检索日期：2026-09-05；使用官方文档和维护者源码：

1. [OpenAI Whisper transcribe 实现](https://github.com/openai/whisper/blob/main/whisper/transcribe.py)：
   无语音判定会结合 no_speech_prob 与 avg_logprob，不能把一个概率阈值当成绝对判定。
   默认参考值0.6和-1.0来自该库，不是本项目实测最优值，也没有伪装成R1已有置信度。
   重复率和静音片段可能参与失败回退/幻觉处理，短句或低置信度不能单独等同无意图。
2. [faster-whisper 官方说明](https://github.com/SYSTRAN/faster-whisper#vad-filter)：
   可在识别前使用Silero VAD过滤非语音音频。VAD负责语音活动，不负责理解意图。
3. [HA Assist Pipeline 协议](https://developers.home-assistant.io/docs/voice/pipelines/)：
   stt-end给出识别文字，stt-no-text-recognized与stt-stream-failed是不同错误。
4. [HA Core 2026.8.2 Wyoming STT适配器](https://github.com/home-assistant/core/blob/2026.8.2/homeassistant/components/wyoming/stt.py)：
   当前路径只把Transcript.text转换为SpeechResult，不向R1提供词级置信度或无语音概率。
5. [HA对话结果类型](https://github.com/home-assistant/core/blob/2026.8.2/homeassistant/components/conversation/models.py)：
   continue_conversation用于告知对话是否需要继续。它用于保护追问场景的短回答，不能用conversation_id存在代替。
6. [HA Whisper应用说明](https://github.com/home-assistant/addons/blob/master/whisper/DOCS.md)：
   vad_clip用于识别前剪除静音。现场应用3.5.1为language=zh、stt_library=auto、vad_clip=false。
   自动后端不能仅凭实体名就认定实际解码器。本轮没有换模型、增加模型下载或修改后端参数。

## 已实现规则（按优先级）

| 层次 | 判断 | 行为与边界 |
|---|---|---|
| 收音隔离 | 唤醒回应播放中 | 关闭AudioRecord，清除旧缓冲，回应后200ms重新录音；不把自己的回应主动上传 |
| 无开口 | 回应后6秒没有连续80ms VAD人声 | 不启动HA请求，清缓存与待追问状态，静默回到唤醒监听 |
| 空结果 | 没有Unicode字母或数字 | 空白、全角空格、零宽/格式字符、纯标点、纯符号/emoji均静默结束 |
| 非语音标记 | 整段只由已知标记组成 | `[BLANK_AUDIO]`、`[no speech]`、`(silence)`、`[音乐]`、`【噪音】`、`<\|nospeech\|>`等静默；`播放[音乐]`或普通词“音乐”保留 |
| 无人声证据 | 本轮明确测得0ms VAD人声 | 即使ASR返回文字，也不发起意图；缺失计数用-1，不能当成0 |
| 明确结束对话 | 完整句是“结束对话”“取消本次对话”“取消这次对话”“不用回答了” | 静默结束并清除conversation_id；不匹配包含这些词的长命令 |
| 日常放弃 | 无HA追问且完整句是“算了”“没事了”“不说了”“不用了” | 静默结束；HA正在追问时交给HA处理。“取消”“停止”“取消计时器”不被该规则吞掉 |
| 仅唤醒词 | 无HA追问且完整文字仅Alexa或用户报告的“奥ex斯”“欧ex萨” | 静默；不删除正常命令中的Alexa设备名或前缀 |
| 仅语气词 | 无HA追问且全文仅由嗯/呃/额/啊/唔/唉/哦/噢组成、最多6字 | 静默；HA需要继续对话时保留，含其他文字的“嗯打开灯”保留 |
| 疑似回应回声 | 无HA追问，本轮VAD人声大于0且少于300ms，识别结果与本次实际播放的回应完全相同（忽略标点/格式/大小写） | 静默；未测得时长、正常较长人声、其他回应或追问场景均不据此丢弃 |
| 疑似循环幻觉 | 同样要求弱人声证据；至少16个字母/数字，由1～8字单元完整重复至少4遍 | 静默；仅“谢谢观看”、短重复、正常人声长句不加入黑名单 |
| HA无识别文字 | STT阶段返回stt-no-text-recognized | 等待run-end后静默收尾，保持认证连接，不重放命令 |
| 其他有文字输入 | 未命中以上规则 | 原文交给HA，包括单字、数字、设备名、未知意图和正常寒暄 |
| 真正失败 | STT服务异常、协议错误、断线、HA拒绝动作/设备不存在等 | 维持原错误与恢复路径，不伪装成无输入，不一概静默 |

这些阈值和中文策略是针对当前R1的工程默认值，**不是智能音箱行业统一标准**。
策略实现在 `CommandInputPolicy.java`，收音状态机在 `CommandWindow.java`，会话接入在 `HaAssistSession.java`。

## 保护有效输入与对话上下文

- “停”“好”“不”“是”“否”“5”“５”“客厅”“蓝色”不会因为短、只有数字或没有动词就被丢弃。
- “谢谢”“谢谢观看”“播放无声电影”等正常词句不使用全局黑名单。
- Unicode NFKC、大小写及格式归一化只用于规则比较；通过的命令保留原文及设备名。
- HA最近一次明确返回continue_conversation=true时，提供120秒的短回答保护；超时/放弃清除保护。
  这是文本判断的上下文保护，不等于已经实现自动续听；当前仍按既有唤醒流程收音。
- 300ms只用于与特定可疑文字交叉验证，不是最低命令时长；80ms的“停”仍可交给HA。
- 不根据HA“无法理解”一律关闭回复。用户确实说了不支持的指令时应获知结果。

## 诊断与隐私

新增事件input_accepted/input_ignored以及枚举reason；终端显示`Assist input: empty`等原因。
status新增ignored_inputs、last_input_decision、command_voiced_ms，不保存识别正文、录音或凭据。
voiced_ms是本轮连续起音确认后累计VAD人声帧数乘20ms，不是置信度，也不等于整段录音时长。

## 验证和未覆盖范围

69项主机单元测试、Android lint及APK构建通过。覆盖空输入、标记、句中关键词、短指令、
追问短答、明确放弃、弱回声与真实重复区分、循环文字、STT无文字与服务故障区分，
以及过滤后下一次请求仍正常。音频回应文字与10条已打包资源的manifest一致性检查通过。
测试包含API22纯文本兼容入口，实际执行情况另记在证据目录。

未新增真人KWS测试或家庭录音。真实房间中的误拒率、电视人声误触发、回声残留及任意完整句子的
ASR幻觉仍需使用证据；当前接口缺少置信度，不能宣称百分之百识别“用户根本没说话”。
不要为追求静默而默认删除所有短句、所有疑似常见幻觉句，或隐藏真正的故障。

证据：`test-results/2026-09-05-r1-sample01-assist-input-policy/`。

实际部署：R1版本42安装和Activity启动通过；API22上7个Unicode/标记/上下文/弱回声纯文本用例通过。控制通道新增诊断字段已实机验证，audio_frames=0，未配置令牌、未开麦；检查后已停止该服务并准备正常后台启动窗口。
