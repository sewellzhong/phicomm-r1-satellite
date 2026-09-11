# R1 v87 MicArray sidecar 受控导出实机记录（2026-09-11）

## 结论

`r1-sample01` 保持 v21 boot，在用户明确确认录音后完成一次 5 秒静默环境的 MicArray
sidecar 受控导出。v87 取得 250 个连续卫星帧和 313 次连续 MicArray 调用；4 麦、2 参考、
ASR、VAD 四个 WAV sidecar 均为非空，设备端与主机端 SHA-256 一致，离线审计通过。
调用序号为 1～313，序号缺口、代理 dropped 和 invalid 均为 0。

本轮证明原厂 `Unisound_MicArray_Process` 同一窗口的四类载荷能够受控保存、导出和审计。
它不证明四支麦克风各自的物理响应、DOA 方向性、AEC 消除量或 DSP 输出质量；R3 和 R0
状态不变。

## v86 失败与 v87 修复

- v86 APK SHA-256 为
  `900a6c0f1101ec70a09facc2d03ca758866503c1c9ac39138cb0f22ad7116e40`。首次窗口在创建
  4 麦 WAV 时明确失败：`unsupported_channel_count_4`。应用清理了本轮输出，设备诊断目录
  无残留；该次不能算录音导出通过。
- 同一轮还发现恢复工具把服务启动后的短暂 `disabled/audio_opened=false` 过渡态立即判为
  失败，而设备随后实际恢复 `listening/audio_opened=true`。
- 修复提交 `40e329593ee746e5db7afea880fddb0409cd5022` 只为 WAV 头增加明确的 4 声道 PCM
  形状、保留对其他声道数的拒绝，并在恢复阶段轮询完整监听状态。版本提升为 v87。
- 修复后定向 Python 19 项、原厂音频 109 项、Android 单元测试、lint、设备构建和统一检查
  均通过；公开文件扫描 384 个文件为 0 发现，凭据扫描无泄漏。

## APK 与部署门禁

- 设备序列号 `CBEAU1116K01314`，fingerprint
  `Android/rk322x_echo/rk322x_echo:5.1.1/LMY49F/3448:user/release-keys`，API 22，
  SELinux Enforcing。
- v87 私有签名候选 SHA-256 为
  `7ee18773d2ce80795f98d5ab8073161f7fcf125daba8e84db693f6013602279f`；包名
  `dev.sewellzhong.r1probe`、versionCode 87、min/target API 22，只含 `armeabi-v7a`，不含
  `HOST_CHECK_ONLY`。
- v1/v2 签名通过，证书 SHA-256
  `0be7a3643442658354c185ec53cb50e73bc1516a56f2760ca46f2c932c1d2639`，与 v85/v86
  一致。安装后从设备读回 APK 的 SHA-256 与候选一致。
- v85 回退 APK 已保存在仓库外/忽略目录，SHA-256 为
  `9b97e70ea35b06de7e4c5ba21a5549363678b4c396df40931fd180a1f8eb5f38`。本轮未修改
  boot、system、recovery、Loader、参数/分区表或物理首 4 MiB，未擦除或格式化。

## 5 秒导出结果

| 项目 | 实测 |
| --- | ---: |
| 卫星帧 / 序号缺口 / 代理丢帧 | 250 / 0 / 0 |
| MicArray 调用 / 序号范围 / 缺口 | 313 / 1～313 / 0 |
| MicArray dropped / invalid | 0 / 0 |
| 4 麦载荷 | 641,024 PCM bytes；501,109 非零 bytes |
| 2 参考载荷 | 320,512 PCM bytes；108,880 非零 bytes |
| ASR 载荷 | 160,256 PCM bytes；112,785 非零 bytes |
| VAD 载荷 | 160,256 PCM bytes；112,785 非零 bytes |
| DOA | 250/250 有效；全部为 5° |

4 麦 sidecar 为 16 kHz、S16LE、4 声道，2 参考 sidecar 为相同格式的 2 声道；ASR/VAD
为单声道。四个 sidecar 的形状、PCM 长度、非零计数和 SHA-256 均由离线审计器复核。
既有双路诊断输出仍逐样本相同，ASR 与 VAD sidecar 本轮哈希也相同，这些事实不提升为
独立麦响应、DOA 或 AEC 结论。

私有 WAV 仅保存在仓库外。公开记录只保留脱敏汇总；`audit.json` SHA-256 为
`296a1464fc54d8bb8f2f91473d9634713539467ac38f15c110a82a06718178a9`，`result.json`
SHA-256 为 `5790559b8688a6fc9f84eab4efbc1470c3debca13cc8df87e923c55a67ebb886`。
设备端七个精确文件均已删除，最终为 Enforcing、`listening`、`audio_opened=true`、连接 1、
失败 0。

## 下一入口

设备当前运行 v21 boot 与 v87 APK。下一步在用户配合固定声源位置后，分别从设备前、右、
后、左四个方向采集同规格材料，比较 4 麦各通道响应并运行 DOA 方向矩阵审计。同步本机受控
播放、AEC 消除量和 DSP 质量仍作为后续独立窗口，不由本次非零参考载荷推断通过。
