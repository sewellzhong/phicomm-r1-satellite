> 历史记录：本文版本、命令及“下一步”反映记录当时状态；当前排期以[根 README](../README.md)为准。原始产物迁移见[归档说明](../test-results/README.md)，原验收结论不变。

# HA 中文报时自然句式补充

用户提供STT“现在什么时间？”，但HA返回找不到名为“现在”的设备。此例识别文字正确，
应处理中文句式匹配，不修改唤醒模型或删除命令中的“现在”。

HA Core 2026.8.2固定依赖hassil 3.11.0、home-assistant-intents 2026.7.30。
在同版本报时意图上重现：“现在什么时间？”未匹配HassGetCurrentTime，“现在几点？”能匹配。
新增 `config/home-assistant/custom_sentences/zh-CN/r1_time.yaml`，扩展10个明确的报时句式，
使用已有HassGetCurrentTime和默认响应，时间仍由HA产生，不在客户端编造或缓存时间。
本地10条正例和3条负例通过。验证范围为报时意图单独识别，非真实全管线验收。
HA默认代理为自定义句式设置metadata并在选择匹配结果时优先使用该标记。

部署位置：HA `/config/custom_sentences/zh-CN/r1_time.yaml`，新文件采用防覆盖写入，SHA256已比对。
`ha core check` 成功。当前SSH管理环境的Supervisor凭据调用HA API未认证成功，未打印或保存凭据；
使用Core重启加载新句式。若回退，移除此新增文件并重载conversation或重启Core即可。

依据：
- [HA自定义句式](https://www.home-assistant.io/voice_control/custom_sentences_yaml/)
- [Core 2026.8.2对话组件依赖](https://github.com/home-assistant/core/blob/2026.8.2/homeassistant/components/conversation/manifest.json)
- [Core 2026.8.2默认代理的自定义句式加载与优先匹配](https://github.com/home-assistant/core/blob/2026.8.2/homeassistant/components/conversation/default_agent.py)

证据：`test-results/2026-09-05-ha-time-sentences/`。未启动新声学测试，实际问时效果仍待使用确认。
