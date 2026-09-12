# v93 O3 Assist流式播放管线主机记录（2026-09-12）

## 结论

提交 `86d6d1d94a747c2a80c325f79a7d2445482e71d2` 在固定 Home Assistant
2026.8.2 容器内补齐两项自动测试，实际执行 HA 的 `PipelineInput`、
`PipelineRun.recognize_intent`、流式启动阈值和 TTS message stream。合成流式路由先发送
超过当前阈值的第一段文字，再由异步门闩阻塞全文完成；确定性 TTS/播放替身已写入首个
S16LE PCM 样本时，路由全文任务仍未完成。释放门闩后，第二段按顺序写入且没有回退为
全文一次性 TTS。

取消场景在首个 PCM 写入后取消完整管线，随后通过路由保留的旧内层聊天日志引用注入迟到
文字；TTS/播放替身没有产生第二个写入，会话适配的旧输出隔离继续生效，管线 `end` 也被
执行。

这通过了固定 HA 版本下的合成 Assist 管线门槛，但确定性 PCM 替身不是实际 TTS 后端、
HTTP 音频传输或 R1 扬声器。未连接家庭 HA、模型中心、ADB 或 R1，未安装 APK，不能据此
宣称真实后端或实机流式回答通过。

## 主机检查

运行：

```sh
ANDROID_SDK_ROOT=/home/sewellzhong/.local/share/android-sdk python3 tools/dev/prepare.py
ANDROID_SDK_ROOT=/home/sewellzhong/.local/share/android-sdk bash tools/dev/check.sh
```

结果：

- 公开扫描 394 个文件、0 发现，密钥扫描无泄露；
- HA 测试由 47 项增至 49 项，HA 2026.8.2 配置流、平台加载与卸载检查通过；
- Android 188 项、lint、hostcheck APK、原生工具 32 项、恢复工具 73 项、原厂音频
  117 项及合成 R0 演练通过；
- hostcheck APK SHA-256：
  `cc6bd0ad8b8069be2a6e6b30bfc75aac52c4736b43d9e3e813b03ff51fcb3fe2`。

Android 源码未变化；hostcheck 包名和合成提示音不能用于设备部署，该 APK 不是新的设备
候选。

## 待自动验证与下一入口

1. 固定实际家庭路由、模型中心和 TTS 后端版本，核验增量、完成、失败、取消、会话期限和
   工具结果契约；工具真实结果前不得产生成功确认；
2. 在真实 HA 与 `r1-sample01` 上证明 TTS 首个真实音频块和播放器写入早于全文完成，取消
   后旧音频不再写入；
3. 最终候选执行至少 60 秒长回答，记录分段顺序、丢句/重播、缓冲高水位、欠载、排空和
   终态。真人听感继续标记用户跳过/未验收。
