# r1-sample01 原厂调试落盘 v16～v20 实机记录

日期：2026-09-11  
设备：`r1-sample01`  
固件：3448，Android 5.1.1  
范围：只验证原厂调试文件的目录访问、文件创建和生命周期，不据此验收四麦独立响应、DOA方向性、AEC消除或DSP质量。

## 安全边界

- 所有候选只修改`boot`中的自有代理、init启动参数及专用Enforcing策略；未修改system、recovery、Loader、参数/分区表或物理首4 MiB，未擦除或格式化。
- 每轮均核对设备序列号、3448 fingerprint和当前boot，执行当前boot双读一致、候选固定、单次写入、复位前完整读回一致。
- 未启用全局Permissive，也未授予代理shell执行权限。`/sdcard`实际指向VFAT挂载`/mnt/internal_sd`，不能用文件标签把权限缩到三个文件，因此临时策略的VFAT类型级风险被显式门禁，并在每轮结束后恢复。
- 原厂调试文件及本地证据不提交公开仓库；本轮没有保留家庭对话录音。

## 主机实现

相关公开提交：

- `949a2a8`：临时VFAT策略的显式风险门禁和策略增量boot更新器；
- `7064399`：代理内置严格`system()`拦截，只允许精确的`mkdir -p /sdcard/unidata/`且不启动shell；
- `b309c22`：允许在同一候选中受控替换代理和临时策略；
- `a9b4c1a`：诊断请求按原厂接口驱动`set4MicWakeUpStatus(0/1)`生命周期；
- `421a3a0`：仅诊断boot保留`sdcard_rw`附加组，并把VFAT规则绑定到`r1_factory_audio`域；
- `753c8d7`：补齐对既有诊断目录的只读`getattr`；
- `fb94c42`：探针使用`busybox stat`记录零字节文件，确保失败证据和精确清理不遗漏。

代理仍拒绝任意命令、网络权限和生产请求中的调试开关；生产入口没有放宽。

## 实机增量结果

| 候选 | 本轮新增 | 实机结果 |
| --- | --- | --- |
| v16 | 初始临时VFAT策略 | 原先的VFAT写入AVC消失，但代理的shell执行仍被拒绝；没有文件。该策略错误绑定到`mediaserver`，未继续沿用。 |
| v17 | 安全目录创建拦截器 | 不再出现相关AVC，仍没有文件。没有授予shell执行。 |
| v18 | 原厂wake状态生命周期 | 仍没有文件，说明仅补调用时序不足。 |
| v19 | `r1_factory_audio`域、诊断专用`sdcard_rw`组和纠正后的VFAT规则 | 出现精确的`r1_factory_audio -> vfat:dir { getattr }`拒绝，证明代理已走到既有目录检查。 |
| v20 | 仅增加目录`getattr` | 5秒请求取得250个连续原厂输出帧；未再发现相关AVC。`/sdcard/unidata`创建了`waking_file_4mic.wav`、`waking_file_2aec.wav`、`waking_file_out.wav`，但三个文件均为0字节。 |

v20固定材料SHA-256：

- 代理：`ff281fa91ab50caf0fafec7d4b694e720858bb12cfbf53de7d68a4e98d2f82f1`
- 临时策略：`38c249c6c4099594299295d5bde1820b9a6f77149dff52270252200fc9ea8600`
- boot候选及写后读回：`a8d2fc43758e5b1ad389f2b6ce33ebcde6636f4f023bea91562cacad44956e4b`

当时探针未把零字节文件写入快照，故自动清理没有识别它们。现场只删除上述三个精确文件；随后已增加零字节回归测试，今后会记录并清理这种失败产物。

## 验证

- `bash tools/factory_audio/check.sh`：95项通过，包含主机代理和API 22 ARMv7构建。
- 配置本地主机`ANDROID_SDK_ROOT`后运行`python3 tools/dev/prepare.py`和`bash tools/dev/check.sh`：公开扫描375个文件、0发现，密钥扫描无泄露；Android单元测试、lint和hostcheck APK构建通过；native 32项、R0 73项及合成演练、原厂音频95项、HA 44项和HA 2026.8.2配置加载全部通过。
- 最终只读ADB核对：设备在线，fingerprint仍为3448，`sys.boot_completed=1`，SELinux为Enforcing，`dev.sewellzhong.r1probe`为versionCode 84、targetSdk 22；`/sdcard/unidata`目录存在且为空。本步骤未启动采集。

## 恢复与结论

v20结束后再次双读当前boot，执行一次v15回退写入，并在复位前完整读回匹配。设备恢复Android、ADB和Enforcing；当前boot SHA-256为`29dcdb3bdcf85a15a875c6f87a100b9799a57323b111f8223449f9387a12b77e`，APK仍为v84，SHA-256为`f62e058d308495f5165f9e402b023ecfcf8e5b10104197155a0c5c43e789216c`。临时VFAT权限和v20代理均不在当前boot中。

本轮证明专用代理能够在Enforcing下到达原厂调试文件创建路径；三个零字节文件同时也证明当前调用/读取语义没有激活有效载荷写入。它们不是四麦数据、AEC参考或处理输出证据，不能计算AEC消除量。R3的四麦独立响应、四方向DOA、AEC消除和DSP质量仍未验证，R0继续为`pending`。

下一步先离线对照原厂APK的调用顺序、读返回值和包长语义，定位为何只创建文件而不写入有效载荷；在形成新的、证据驱动的最小候选前，不重复录音，也不继续增加权限。
