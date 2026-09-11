# r1-sample01 原厂调试文件探测与特权候选（2026-09-11）

## 实机结论

用户明确确认进行一次 5 秒录音探测后，在当前 `r1-sample01`、3448、v82 APK 与 v14 boot
代理上运行无刷写入口。设备身份、fingerprint、API 22、APK versionCode 82 和设备端 APK
SHA-256 `b115b5077da502a7fbe9efd8a21e2cee6c2e5ae084e8c176d8ace79d52db1c73` 均通过。

第一次运行暴露主机探测器的编排缺陷：原生停止请求返回时旧音频仍为打开状态，同包旧 Activity
可能只被置前而不接收新 extras，工具又未验证 `am start` 结果，最终超时。本次没有开始录音，
`/sdcard/unidata` 与 `/data/unidata` 均无固定调试文件。仓库外结果 SHA-256 为
`e99b6090442ad012a519efb0b57282d0148fb9d998d0671da96fdaffece220cf`。

探测器随后改为先 force-stop 同包进程、验证 Activity 确实以新 nonce 启动，并轮询完整恢复
`listening/audio_opened/listen/enabled`。第二次运行成功触发原厂四麦入口，但立即收到：

```text
R1_FOUR_MIC_RECORD_FAILED ... error=IllegalStateException message=four_mic_open_failed_0
```

该次只有启动时的一次路径快照，两个固定目录始终为空，没有 WAV 可导出或清理。仓库外结果
SHA-256 为 `b2c8c9c7ac7f90afa4cb65c752d7a8f369740c5536ea0626d17514864fadec46`。
工具结束后卫星在约 1 秒内依次经过 `disabled`、`waiting_ha` 并恢复为 `listening`；最终
`audio_opened=true`、连接数 1、失败数 0。没有安装 APK、刷写分区、解除原厂包隔离或连接 HA。

因此普通 APK 的 `set4MicDebugMode(1)` 路线没有进入可用的打开/关闭生命周期，原厂
`4mic/2aec/out` 权限、落盘和格式门槛为**实机失败**，不是未运行，也没有取得 AEC 证据。

## v84 特权诊断候选

依据 2026-09-11 免拆分级授权中“较低权限路线已有可复现实机不足证据后可进入特权服务”的
边界，主机端已实现 v84 候选，但尚未部署设备：

- `StartCapture.vendor_debug_files` 是单次验证请求的显式开关；必须同时请求诊断输出。
- boot 代理还必须显式带 `--allow-vendor-debug-files`，否则以权限错误拒绝请求。
- 健康状态新增 `vendor_debug_files_active`；APK 在该字段不为 true 时拒绝继续。
- 普通卫星采集和旧验证请求默认关闭调试文件。停止、断开或释放时代理先把原厂 debug mode
  重置为 0，再释放私有库。
- overlay 渲染器只有显式传入 `--allow-vendor-debug-files` 才把开关写入候选 init，并在私有
  manifest 中记录该事实。

主机检查通过 Android 单元测试、lint 和 hostcheck，native 32 项、R0 73 项与演练、原厂音频
72 项、HA 44 项及 HA 2026.8.2 配置加载；公开扫描 367 个文件为 0 发现，凭据扫描无泄漏。
API 22 ARMv7 代理 SHA-256 为
`9be23acfd2c78d90549a9f801610f46ab2f93f2c50155e75a38a955ff37a87ce`。hostcheck APK
SHA-256 为 `c9b6f4189b5578989de3fb23daebb5f9d2065be80d1a9c05ea59f91bd375ad41`，独立包名，
不可部署 R1。

## 下一入口

v84 源码已固定于 `68562aaf0d143434dc9fba517bff8bb4cdd70771`。提交
`c4260c1385b1355abe9aac805a25a7c0af502c8b` 的增量构建器还会绑定
当前与候选 overlay manifest，验证 boot 中仅代理二进制和 init 服务的单个
`--allow-vendor-debug-files` 参数发生变化；任何其他 init 内容或 overlay 契约变化均拒绝生成。
现场再用当前设备 boot 双读、v14 哈希匹配、单次 boot 写入和复位前完整读回门禁生成特权
代理候选；另以原签名构建设备 APK 并执行安装/读回哈希
门禁。只有代理健康状态确认本次请求的 debug mode 实际启用，才进行新的明确短时录音窗口，
导出并校验同一窗口的 `4mic/2aec/out` 后删除设备端固定文件。当前结果不计算消除量，R3 与
R0 状态均不改变。

## v84/v15 实机后续

上述候选已于同日继续部署。现场 boot 双读、单次写入、复位前完整读回、Enforcing 启动、
原签名 v84 APK 安装与设备端回读均通过；显式 5 秒请求也确认
`vendor_debug_files_active=true`。但固定 `4mic/2aec/out` 文件仍未生成，内核 AVC 显示
`mediaserver` 对 `vfat:/sdcard/unidata` 的写入被 Enforcing 拒绝。该结果保持为落盘失败，
下一步转入临时最小专用策略，不重复当前录音。完整哈希、数据清理和恢复状态见
[v84 实机记录](2026-09-11-r1-factory-audio-v84-device.md)。
