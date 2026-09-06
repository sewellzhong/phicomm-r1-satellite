> 历史记录：本文版本、命令及“下一步”反映记录当时状态；当前排期以[根 README](../README.md)为准。原始产物迁移见[归档说明](../test-results/README.md)，原验收结论不变。

# Alexa 预训练模型接入（2026-09-05）

## 决策与范围

用户指定使用现有成熟唤醒词 Alexa，覆盖先前 Camila 固定词要求。停止 Camila 自训练路线；旧模型、录音和失败证据保留，不删除，也不计入 Alexa 验收。唤醒后仍使用中文 STT、对话和 TTS。

采用 ESPHome 官方模型库的 Alexa microWakeWord v2。此处“现有预训练”表示使用上游发布权重，不表示 R1 声学验收已通过。

- 上游：https://github.com/esphome/micro-wake-word-models
- 固定提交：`05b65922cc433c9df13e98e32a7fe520758c837e`
- 清单：https://github.com/esphome/micro-wake-word-models/blob/05b65922cc433c9df13e98e32a7fe520758c837e/models/v2/alexa.json
- 权重 SHA-256：`9011a8155b04de858c48038529235cbc0e42e9fca05a55bf588cb80a653a723b`
- 上游参数：probability_cutoff=0.9，sliding_window_size=5，feature_step_size=10 ms。
- 输入 INT8 [1,3,40]，量化 scale=0.1019607857、zero point=-128；输出 UINT8 [1,1]，scale=1/256、zero point=0。
- 继续使用现有 microfrontend、TFLite 2.10.0、API 22 和 armeabi-v7a；外部 PCM 仍为 16 kHz/单声道/S16LE/20 ms 帧，内部特征步长为 10 ms。

版本 31 的探针仅执行加载、静音流推理或 WAV 原始最大分数。版本 32 已新增滑窗检测和限时前台监听服务，见 [监听接入记录](./2026-09-05-alexa-listener.md)。分数按 1/256 解量化；但检测阈值为上游 int(0.9×255)=229，最近 5 次原始输出之和严格大于 1145 时触发，并满足上游冷却条件。不能套用 Camila 阈值或把 0.9×256 当成上游判定规则。

## 许可记录

- 模型库根 LICENSE 为 Apache-2.0，固定提交的 LICENSE 与清单下载保存在忽略目录 `local-deps/alexa-microwakeword-r1/`；权重按该仓库声明记录。
- 模型为单词分类器，不附带外部解码词表。
- 沿用既有 microWakeWord / microfrontend / TensorFlow 运行路径及其许可审计，见 Camila 候选审计记录；不能把框架许可直接等同于训练数据许可。
- 固定 Alexa 清单未列出逐数据集来源和授权。训练数据许可及权重适用范围的完整审计仍待补足，尚未作公开/商业分发结论。

## 可复现命令

在仓库根目录：

```bash
python3 tools/kws/prepare-alexa-microwakeword.py
JAVA_HOME=/home/developer/.sdkman/candidates/java/17.0.19-tem ANDROID_SDK_ROOT=/home/developer/.local/share/android-sdk android/r1-probe/gradlew -p android/r1-probe --no-daemon testDebugUnitTest lintDebug assembleDebug
bash -n tools/kws/run-r1-alexa-load.sh
bash tools/install-r1-probe.sh <adb-serial> android/r1-probe/app/build/outputs/apk/debug/app-debug.apk
bash tools/kws/run-r1-alexa-load.sh <adb-serial> --confirm-device r1-sample01
```

下载校验、单元测试、lint、APK 构建、shell 语法检查通过。APK versionCode=31，独立包名 dev.sewellzhong.r1probe；保留原厂系统及音频包。下载权重和构建产物仍在忽略目录。

## R1 实机加载结果

r1-sample01（API 22 / 固件 3448）安装及加载通过。38 个特征帧、12 次静音流推理，末尾分数 0，观察到的最大单次推理耗时 5.252 ms。此短时检查不代表声学识别或长期性能验收。APK 内容检查确认只含 Alexa TFLite 权重。

证据：[实机目录](../test-results/README.md)，包含结果标记、模型/APK 哈希、主机构建日志及资产清单。

## 未验证项与下一阶段入口

2026-09-05 用户决定直接采用本模型，停止追加 KWS 测试并推进阶段 2。以下未验证项不标为通过；原采集/盲测计划不再执行。

Alexa 真人识别率、近音误触发、环境 FAPH、远场、播放中唤醒、CPU/PSS 长期表现、后台稳定性及跨说话人效果均未验证。阶段 1 总门槛未通过。检测事件已在版本 32 接入；下一步冻结模型/参数、采集独立 Alexa 验证与盲测样本，按技术方案第 14 章验收。
