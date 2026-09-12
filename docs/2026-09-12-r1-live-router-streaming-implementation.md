# v96 O3 实际家庭路由流式契约实现

日期：2026-09-12

范围：相邻`home-ai`项目的`domestic_ai` 2.2.0、`conversation_router` 2.1.0，以及R1仓库的固定路由能力回归；不连接家庭HA、真实模型、TTS、R1或ADB。

## 结论

v95确认的“实际家庭路由不支持流式”源码阻塞已修复。OpenAI兼容提供方现解析真实SSE增量，模型中心、家庭路由和R1适配层只按实际选中候选逐层报告能力；MiniMax Anthropic兼容路径仍明确报告非流式。带家庭工具的首轮不向TTS输出，真实结构化结果写回后才允许最终回答流式合成。

这是代码和固定HA主机验证通过，不是实际后端或R1端到端通过。真实DeepSeek/TTS/HTTP/R1播放、60秒墙钟回答和设备取消仍待自动链路验证。

## 固定源码

- `domestic_ai/api.py`：`f5c19e8da3dd0ee22f512e9d9ca9c675e7990544c8116e8aad2a808137533db9`
- `domestic_ai/conversation.py`：`97678e4875efcebe1381f6cfb8156269ed3c36e47eb31a8dd9f97c40b75c0da0`
- `domestic_ai/router.py`：`bbdc6630bc2b9feb362236c61238827753b5a8aa809722d7fc9ac5d9079d8cce`
- `conversation_router/conversation.py`：`a5b5723089262a94fc17648dfc425aac6b83368c70cf874c8a7e84c037074814`
- `domestic_ai/manifest.json`：`d6e3a662055f191a663a45cef54a0b696c8c34317f785ee668f597cbdaad824f`
- `conversation_router/manifest.json`：`30e01391407487a454e994316964f06f15d3d8441878c0d3a36354f09dcbd5db`

R1本地固定路由快照的`conversation_router/conversation.py`与上述源码一致并由测试硬编码校验哈希；原`const.py`、`hub.py`和`rules.py`哈希继续固定，私有材料不进入公开仓库。

## 自动验证

- `home-ai`在固定Home Assistant Core 2026.8.2无网络镜像中68项通过：SSE任意字节分片、Unicode、usage、工具调用拼接、断流、取消释放、能力绑定、首段顺序、工具结果门闩、未提供二次工具拒绝及已输出后禁止提供方切换均有覆盖。
- `python3 tools/dev/prepare.py`与完整`bash tools/dev/check.sh`通过：公开扫描398文件/0发现、secret scan 0、Android 188项及lint/hostcheck APK、原生32项、恢复73项及演练、原厂音频117项、HA 51项与组件加载检查。
- 固定实际路由回归2项通过：路由和R1适配器均报告流式能力，来源绑定会话仍复用；控制拒绝仍不回退模型。
- R1 Android源码未变，hostcheck APK SHA-256仍为`cc6bd0ad8b8069be2a6e6b30bfc75aac52c4736b43d9e3e813b03ff51fcb3fe2`，不是设备候选。

## 下一步

先把固定版本部署到真实HA并以协议驱动自动采集真实模型增量、TTS首块、完成、失败、取消和工具结果顺序；该门槛通过后再在`r1-sample01`验证HTTP/PCM播放与排空及至少60秒墙钟长回答。无需用户说话、操作手机或评价听感。
