# 第三方内容与分发边界

自有代码与文档采用 [Apache-2.0](LICENSE)，不改变第三方授权，也不授予厂商品牌权利。

| 内容 | 固定来源与许可 | 仓库中的处理 |
| --- | --- | --- |
| ESPHome API | 2026.8.0，提交与文件哈希见 `protocol/esphome/manifest.json`；协议等非 C++ 文件为 MIT；C++ runtime 为 GPL-3.0（见原文） | 保留协议原文件及 `protocol/esphome/LICENSE`，不以项目 Apache 许可重新授权 |
| Protobuf descriptor / Java Lite | 3.25.5；BSD-3-Clause | descriptor 原文头及 `android/r1-probe/app/src/main/assets/licenses/protobuf-LICENSE` 保留 |
| Gitleaks（仅开发工具） | 8.30.1；MIT，下载归档 SHA-256 固定 | 下载到忽略目录，用于公开文件扫描，不随 APK 分发 |
| Gradle wrapper | 8.9；Apache-2.0 | wrapper 脚本原版权头保留，JAR 仅用于启动构建 |
| libfvad | `532ab666c20d3cfda38bca63abbb0f152706c369`；BSD-3-Clause、PATENTS | 下载重建，APK 素材目录保留 LICENSE 和 PATENTS |
| noise-c | `b3da54dc1020150237054004c5fdbffc63a23538`；MIT | 下载重建，保留 `noise-c-LICENSE` |
| pymicro-features / TensorFlow microfrontend | `96bd69cfad79aa67697e176570d3dd87052c3def`；源码中各自 Apache-2.0/BSD 声明 | 固定提交下载，保留下载源码的许可与版权头 |
| TensorFlow Lite | 2.10.0；Apache-2.0 | AAR 固定 SHA-256 下载，不入 Git |
| Alexa microWakeWord v2 | 固定来源见 `docs/2026-09-05-alexa-pretrained.md`；仓库声明 Apache-2.0，完整训练数据审计未完成 | 权重及构建 APK 不公开上传，不宣称完整分发审核已通过 |
| Piper huayan 合成提示音 | 模型卡的数据集许可为 Unknown | 原中文素材只留家中 `local-deps/private-prompts/`，不上传；原模型卡保留审计用途 |
| 主机测试提示音 | 本项目生成的 440 Hz 正弦音 | 准备脚本生成到忽略目录，不包含语音；仅用于隔离包名的 hostcheck 构建 |

公开仓库不包含原厂 APK、固件、音频底层库、家庭录音、HA 私有路由源码或签名密钥。公开源码不等于已授权分发包含全部依赖的产品 APK；本次不创建二进制 Release。
