# v94 O3 长流式回答与工具结果顺序主机记录

日期：2026-09-12

受测源码：`a213d6bf4f0cf99bc147ac783642e68595aac847`

范围：固定 Home Assistant 2026.8.2 Assist 管线中的确定性长 PCM 输出和工具结果顺序契约；不连接家庭 HA、模型中心、真实 TTS、HTTP 或 R1。

## 实现与自动检查

- 使用 HA 2026.8.2 的真实 `PipelineInput`、意图流式阈值和 TTS message stream。
- 三段不同文字分别生成 21 秒 PCM S16LE、16 kHz、单声道确定性载荷，总输出时长 63 秒。
- 首段 PCM 写入时，后续生成仍由门闩阻塞；释放后核对三段文字顺序、每段字节数和不同 SHA-256，证明替身链路没有丢段、重播或提前回退到全文 TTS。
- 工具契约使用显式结果门闩：结果到达前播放列表只有“正在执行”段，结果到达后才出现成功段并正常排空。
- 该工具检查证明管线能够保持一个遵守契约的上游所给顺序；它不代表适配器能够从任意自然语言中判断工具状态，也不证明当前家庭路由已提供结构化工具事件。

执行：

```text
ANDROID_SDK_ROOT=/home/sewellzhong/.local/share/android-sdk python3 tools/dev/prepare.py
ANDROID_SDK_ROOT=/home/sewellzhong/.local/share/android-sdk bash tools/dev/check.sh
```

结果：`prepare.py` 通过；完整检查时公开扫描 395 文件、0 发现；Android 188 项、lint 和 hostcheck APK 通过；原生工具 32 项、恢复 73 项及演练、原厂音频 117 项、HA 51 项及 HA 2026.8.2 配置加载检查通过。文档加入后的最终独立公开扫描为 396 文件、0 发现，secret scan 也为 0。hostcheck APK SHA-256 为 `cc6bd0ad8b8069be2a6e6b30bfc75aac52c4736b43d9e3e813b03ff51fcb3fe2`；Android 源码未变，该 APK 不是设备候选。

## 结论与边界

v94 通过了确定性替身下 63 秒流式输出的顺序、唯一性、完整排空和工具结果顺序契约。它不证明 63 秒真实墙钟连续播放、真实模型边生成、真实 TTS/HTTP 延迟或 R1 扬声器输出，也不改变 v28 boot/v88 APK 的设备状态。

下一步固定实际家庭路由、模型中心和 TTS 版本，先证明其真实流式与结构化工具结果行为；随后在真实 HA 与 R1 上自动采集首块、播放写入、完成/失败/取消/期限及至少 60 秒长回答证据。上述外部组件未提供前，不把 O3 标为实机或真实后端通过。
