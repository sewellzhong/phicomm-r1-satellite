# 仓库深度清理与原生入口收敛（2026-09-07）

按用户确认的方案执行：清理可再生产物、将历史原始证据移至仓库外、精简当前文档，并移除旧 Assist WebSocket 备用运行入口。工程根目录没有 `.git`；修改前建立完整源码和文档快照，复制后逐文件校验再删除原文件。

## 代码与文档

- 当前版本改为 v63 / `0.63-native-cleanup`。移除旧 WebSocket 服务、连接/会话/HTTP 客户端、旧 TTS 播放与遥测、专用测试、启动及管理工具、专用根证书，共 14 个文件；移除 Manifest 注册和 OkHttp/Kotlin 直接依赖。
- 原生链路共用的输入策略、命令窗口、提示选择和音频处理代码保留。`ack/` 仍是当前提示音生成工具的源素材，保留两项生成工具和所有当前提示素材。
- 部署工具保留对已安装旧 WebSocket 服务的冲突检查；包名、协议、认证与持久配置兼容。
- 根 README 改为当前状态、开放问题和操作入口；Android README 改为当前构建/运行说明；清理前入口全文保存在 `docs/history/`。各历史报告的结论保持原样，增加历史排期提示，详见[文档索引](README.md)。
- 技术方案增加本次入口移除说明，阶段门槛与第 14 章指标未改。

## 归档与保护

[清单](../test-results/README.md)记录 658 个快照文件和 709 个归档文件。归档中 583 个文件为旧源码副本及禁用 Noise Java 源码，126 个为历史音频/诊断导出/旧 APK。原路径、归档路径、大小和 SHA-256 均可追溯。

原厂阶段 0 备份、非 root 隔离恢复基线、v62 诊断目录以及本次部署回退 APK 保留原位。文字报告和 JSON 证据保留；早期失败没有改成通过。模型、运行库、固定版本源码及其 Git 元数据、protoc、主机互通库、HA 测试参考源码与互通虚拟环境保留。

删除项目内 Gradle/Python 缓存、Android 构建结果及三个可再生 JNI 中间构建目录；保留 `fvad-host` 和 `r1-noise-host`，现有诊断工具仍直接加载它们。忽略规则原已覆盖构建目录、缓存、APK、录音和本地依赖，本次无需扩大规则。

仓库外归档根目录为 `/path/to/phicomm-r1-satellite-archive/2026-09-07-cleanup/`（0700）；恢复步骤见[归档说明](../test-results/README.md)。搬移不计为实际释放空间。

## 主机验证

从仓库根目录实际执行：

```bash
JAVA_HOME=/home/developer/.sdkman/candidates/java/17.0.19-tem ANDROID_SDK_ROOT=/home/developer/.local/share/android-sdk android/r1-probe/gradlew -p android/r1-probe --no-daemon testDebugUnitTest lintDebug assembleDebug
python3 -m unittest discover -s tools/native/tests -v
docker run --rm --network none --entrypoint python -e PYTHONPATH=/work/integrations/home_assistant -v /path/to/phicomm-r1-satellite:/work:ro ghcr.io/home-assistant/home-assistant:2026.8.2 -m unittest discover -s /work/tools/ha/tests -p 'test_*.py' -v
docker run --rm --network none --entrypoint python -e PYTHONPATH=/work/integrations/home_assistant -v /path/to/phicomm-r1-satellite:/work:ro ghcr.io/home-assistant/home-assistant:2026.8.2 /work/tools/ha/tests/check_guard_setup.py
```

结果：132 项 Android 测试（无失败/跳过）、lint、构建通过；28 项部署与诊断工具测试通过；46 项 HA 测试通过；HA 配置入口、平台加载/卸载、重复/嵌套过滤拒绝检查通过。Android 测试数量降低来自删除旧链路专用测试，不是跳过当前功能测试。

APK DEX 核对确认旧服务/专用类及 OkHttp/Kotlin 不存在；Alexa 模型哈希未变，三类 ARMv7 原生库齐全。首次辅助审计将打包后原生库直接与未剥离调试符号的输入比较，断言不一致；按 Gradle 的 stripped 输出复核后通过，未因此改动运行库。

完整日志、JUnit XML、lint XML、APK 审计和源文件变更清单见[主机证据目录](../test-results/README.md)。

## 实机验证与空间统计

实机结果记录在[本次部署目录](../test-results/README.md)。v63 已部署至 r1-sample01（Android API 22、固件 3448），安装前原厂备份与旧 APK 哈希通过、签名一致；安装后 APK 哈希匹配、旧服务入口不存在。原生连接认证恢复，身份及音量、语速、两阶段等待等设置一致，服务最终 `listening`、`last_error=null`、真实录音帧增长。两原厂包仍隐藏且无进程，APK 哈希未变。

真实 AudioRecord 采集 50 帧（1 秒）、200 毫秒合成 AudioTrack 播放头排空通过，不保存音频；诊断关闭。全部打包素材和四个原生库与先前已安装 v62 逐字节相同。

首次辅助检查错误地在 `stop_native_audio` 同时停止控制服务后直接发请求，收到 `invalid_control_response`；已立即恢复监听，修正脚本为先重启控制服务后检查。原始失败日志保留为 `attempt1-smoke.log`，修正后 `smoke.log` 与 `summary.json` 记录通过；APK 代码未因此修改。

实际执行部署命令：

```bash
python3 tools/native/deploy-r1-native.py install 192.0.2.10:5555 --evidence test-results/2026-09-07-r1-sample01-cleanup-v63
```

预检和最小验证使用本次部署目录中保存的 `device-check.py`、`device-smoke.py`（执行时位于归档目录）。保留 `previous-satellite.apk`（v62）、`current-satellite.apk`（v63）、部署基线、签名核对与验证证据。若需回退，使用该部署基线执行 `rollback`，然后显式 `start --listen`；本次未执行降级安装验证：

```bash
python3 tools/native/deploy-r1-native.py rollback <adb-serial> --evidence test-results/2026-09-07-r1-sample01-cleanup-v63
python3 tools/native/manage-r1-native.py start <adb-serial> --listen
```

验证后保存 JUnit/lint 报告和当前 APK，清除重新生成的 Gradle/Python 缓存。全部 1367 个快照与归档文件重新校验 SHA-256 一致；检查范围内 Markdown 文件链接无缺失，旧命令中的原始产物通过归档清单恢复。

本次不恢复真人语音回归、断网/IP 变化检查、72 小时稳定性验收或 KWS 专项测试。合成播放头排空不等于用户已确认可闻，最小实机检查不替代正式验收。

空间统计见[机器可读结果](../test-results/README.md)。按文件实际分配空间（不含目录自身），仓库从 638.9 MiB 降至 282.5 MiB，减少 356.4 MiB；归档及快照占 267.0 MiB。仓库加归档净减少 89.4 MiB；文件系统可用空间观测增加 82.0 MiB（包含构建期间仓库外缓存变化，不能把搬移量算成释放量）。
