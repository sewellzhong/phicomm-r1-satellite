# R1 原厂 AEC 配置与验收边界（2026-09-11）

## 结论

v82 元数据中的 `aec_reference_channels=0` 和 `aec_active=false` 不是原厂库查询返回的
运行时拓扑，而是自有代理在尚无消除证据时故意硬编码的保守验收声明。3448 固定配置与
原厂初始化日志分别声明 `SpeakerNum = 2`、`echo_num=2` 和 `aec_on=1`；这只能证明原厂
MicArray 被配置为两路回声参考并开启 AEC，不能证明本轮本机播放实际到达参考、时延匹配，
或代理输出已经产生可量化的消除效果。

离线 ABI 复核还确认，当前代理调用的 `libuni4michal.so` 导出采集、读取、MicArray处理和
DOA接口，但没有供卫星直接注入播放 PCM 的公开入口。代理协议中的 `PlaybackReference`
因此仍被原厂后端明确拒绝；它不能被当成原厂两路硬件参考的来源。原厂库内部存在
`file_4mic`、`file_2aec`、`file_out` 三组诊断对象，表明后续可以尝试取得处理前、参考和
处理后对照，但当前还没有非空、同窗口且可校准的三组实机数据。

## v83 主机修正

协议健康状态新增两个只描述固定 3448 原厂拓扑的字段：

- `configured_aec_reference_channels=2`
- `aec_configured=true`

原有验收字段继续保持：

- `aec_reference_channels=0`
- `aec_active=false`

Android 诊断元数据与离线审计同步记录并强制区分这两组字段。审计器会拒绝把“已配置”
改写为“已证明”，因此本次修正不放行生产原厂采集，也不改变 R3、R0 或 v82 历史结果。
APK 版本升为 v83；设备仍运行 v82 APK 与 v14 boot 代理，本步没有连接 ADB 或修改设备。

## 验证与下一入口

已运行：

```bash
python3 -m unittest tools.factory_audio.tests.test_validation_capture
ANDROID_SDK_ROOT=/home/sewellzhong/.local/share/android-sdk \
  bash tools/factory_audio/check.sh
ANDROID_SDK_ROOT=/home/sewellzhong/.local/share/android-sdk \
  R1_GRADLE_OFFLINE=1 bash tools/dev/check.sh
```

定向 9 项及原厂音频 63 项通过；后者同时完成主机代理和 API 22 ARMv7 代理构建。统一检查
通过 Android 175 项、lint/hostcheck、native 32 项、R0 73 项与演练、原厂音频 63 项、HA
44 项及 HA 2026.8.2 配置加载；公开扫描 365 个文件为 0 发现，凭据扫描无泄漏。hostcheck
APK SHA-256 为 `b7b0a2537ed3da33cfe5b59df6552ddaa4f9d1f6f58fefda89d946d4f320e059`，
不可部署到 R1；ARMv7 代理 SHA-256 为
`282afaff8d69bb58577ec8b7f336537f90449c3573a74381ca6fd15047701ca6`。

下一步是在不把家庭录音写入仓库的前提下，为首台建立显式、短时、可清理的原厂
`4mic/2aec/out` 诊断窗口；必须先证明诊断文件的权限、生命周期和关闭后落盘行为，再生成
新的 boot/APK 候选。取得同一受控播放窗口的非空三路证据后，才校准参考时延并计算消除量。
在此之前，配置为双参考不等于参考覆盖或 AEC 通过。

## v82 无刷写调试文件探测入口

提交 `5c37a4324b1150c8053c9ae93f35bf92bd9cef4b` 新增
`tools/factory_audio/probe-vendor-debug-files.py`，先复用当前设备已安装且 SHA-256 精确匹配的
v82 APK，不安装新 APK、不改 boot，也不解除原厂包隔离。工具严格绑定 `r1-sample01`、API 22、
3448 fingerprint 和 v82 APK 哈希；开始前若 `/sdcard/unidata` 或 `/data/unidata` 下任一固定
`waking/waked_file_{4mic,2aec,out}.wav` 已存在就拒绝运行，避免覆盖历史录音。

得到明确录音确认后，工具才暂时停止卫星监听，通过 v82 既有的 `set4MicDebugMode(1)` 路径运行
5 秒有界采集，观察完整关闭或预期 watchdog 关闭标记，并在关闭后间隔采样确认文件大小稳定。
每个新文件必须成功拉到仓库外的新建 `0700` 目录、匹配设备端 SHA-256、满足 16 kHz/16-bit
以及 `4/2/2` 通道形状，之后才逐个删除对应固定设备文件；至少 `waking` 或 `waked` 一组三文件
均含非零帧才通过。最后确认固定路径已清空并恢复原先的 `listening/audio_opened` 状态。

主机定向测试 5 项及更新后的原厂音频检查 68 项通过，包含 API 22 ARMv7 代理构建。统一检查
也通过 Android 175 项、lint/hostcheck、native 32 项、R0 73 项与演练、原厂音频 68 项、HA
44 项及 HA 2026.8.2 配置加载；公开扫描 367 个文件为 0 发现，凭据扫描无泄漏。本步没有运行
ADB、没有采集录音，也没有生成 boot/APK 候选；因此权限、生命周期和关闭落盘仍是实机待验证。
实机入口为：

```bash
python3 tools/factory_audio/probe-vendor-debug-files.py <adb-serial> \
  --output-dir /仓库外/新目录 \
  --confirm-device r1-sample01 --confirm-recording
```

只有该探测结果为 `pass`，才继续设计新的特权代理诊断窗口；探测失败时保留精确失败项，不把
空 WAV、配置声明或仅能创建文件解释为 AEC 证据。

## 实机补充：普通 APK 路线失败与 v84 候选

用户随后明确确认 5 秒录音探测。修正首次 Activity 编排问题后，v82 普通 APK 可复现返回
`four_mic_open_failed_0`，两个原厂固定目录均未产生 WAV；监听已完整恢复。该低权限不足证据
允许按 2026-09-11 分级授权设计特权代理窗口，但不使调试文件、AEC 或 R3 通过。完整记录见
[原厂调试文件探测](2026-09-11-r1-vendor-debug-probe.md)。

当前 v84 主机候选以 boot 参数和单次协议字段双重显式启用原厂 debug mode，默认生产路径继续
关闭；健康状态必须回报实际启用，停止或断开时强制复位。源码与主机检查已完成，尚未生成、
部署或实机验证 boot/APK 候选。
