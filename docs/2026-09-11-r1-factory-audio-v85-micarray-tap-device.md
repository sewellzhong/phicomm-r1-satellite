# R1 v85 MicArray 处理边界旁路实机记录（2026-09-11）

## 结论

`r1-sample01` 已部署 v21 boot 与 v85 APK，并完成首次 5 秒 MicArray 只读旁路窗口。
动态符号绑定、旁路激活、调用连续性以及同窗口 4 麦、2 参考、ASR、VAD 载荷均通过；
旁路 313 次调用序号为 1～313，0 缺口、0 dropped、0 invalid。卫星输出同时取得 250 帧、
0 缺口、0 代理丢帧和 250 帧有效 DOA。

这证明固件 3448 的 `Unisound_MicArray_Process` 八参数 ABI 已在真机命中，卫星能够通过
专用代理读取原厂 MicArray 处理调用的只读副本。它不证明四个麦克风各自的物理响应、受控
播放参考覆盖、AEC 消除量、DOA 方向性或 DSP 质量；R3 和 R0 状态不变。

## boot 与 APK 门禁

- 设备序列号 `CBEAU1116K01314`，fingerprint
  `Android/rk322x_echo/rk322x_echo:5.1.1/LMY49F/3448:user/release-keys`；写前及写后均为
  SELinux Enforcing。
- 写前当前 v15 boot 两份 SHA-256 均为
  `29dcdb3bdcf85a15a875c6f87a100b9799a57323b111f8223449f9387a12b77e`。
- v21 候选与复位前完整读回 SHA-256 均为
  `9aefde04d52968a0e4690a0812f09c7399f45f76e4afaeafef57cfcb929afcda`。
- 候选只替换自有代理并为 init 增加一个 `--allow-micarray-diagnostic-tap` 参数；保留 v15
  已有但本次未请求的 vendor-debug 参数，不含 v16～v20 临时 VFAT 策略。未修改 system、
  recovery、Loader、分区表或物理首 4 MiB，未擦除或格式化。
- APK 受测源码提交为 `1c733e1929d60667c235eae275218ce69710e9c3`；v85 设备 APK
  SHA-256 为 `9b97e70ea35b06de7e4c5ba21a5549363678b4c396df40931fd180a1f8eb5f38`，
  versionCode 85、targetSdk 22，v1/v2 签名通过，证书 SHA-256 仍为
  `0be7a3643442658354c185ec53cb50e73bc1516a56f2760ca46f2c932c1d2639`。
- v84 回退 APK、部署基线、boot 双读、候选、写后读回和一次性执行状态均保存在仓库外。

## 5 秒结果

| 项目 | 实测 |
| --- | ---: |
| 卫星输出帧 / 序号缺口 / 代理丢帧 | 250 / 0 / 0 |
| MicArray 调用 / 序号范围 / 缺口 | 313 / 1～313 / 0 |
| 旁路 dropped / invalid | 0 / 0 |
| 4 麦原始载荷 | 641,024 字节；480,323 个非零字节 |
| 2 参考载荷 | 320,512 字节；108,941 个非零字节 |
| ASR 输出 | 160,256 字节；107,933 个非零字节 |
| VAD 输出 | 160,256 字节；107,933 个非零字节 |
| DOA | 250/250 有效；仍全部落在 5° bin |
| 既有诊断输出 | 2 通道，但 80,000 个样本逐样本相同 |

2 参考缓冲的非零结果只证明 ABI 调用中的缓冲存在有效数值，不能归因于本机受控播放，
也不能据此计算或宣称 AEC 消除。旁路载荷只在 APK 内存中计数，没有提交原始 4 麦或家庭
对话内容；本轮 WAV 和元数据经设备/主机 SHA-256 一致校验后保存在仓库外，并从设备精确删除。

## 验证与恢复

- `bash tools/factory_audio/check.sh`：100 项通过，含 ARMv7/API 22 代理构建。
- Android `testDebugUnitTest lintDebug assembleDebug` 通过；新增客户端用例覆盖双重显式授权、
  未激活拒绝和畸形 MicArray 载荷拒绝。
- `bash tools/dev/check.sh` 通过公开文件/密钥扫描、Android 构建测试、native、R0、原厂音频、
  HA 及配置加载检查。
- 更新后的 `audit-validation-capture.py` 对私有实机材料返回
  `micarray_symbol_binding_continuity_and_nonempty_payloads`；不会提升 AEC 或 R3 结论。
- 采集后卫星恢复为 `listening`、`audio_opened=true`、连接数 1、失败数 0；SELinux 保持
  Enforcing，原厂 device/player 包继续隐藏。

## 下一入口

下一步为受控物理声源 R3 准入。先扩展仅诊断、仓库外导出的 4 麦/2 参考原始旁路材料，
再按四个固定方向分别采集，验证四麦独立响应和 DOA 变化；AEC 必须另用同步受控扬声器参考
比较消除前后能量。当前非零参考缓冲、固定 5° DOA 和相同双输出都不能替代这些测试。

仓库侧扩展现已形成 v86 主机候选，见
[MicArray sidecar 主机记录](2026-09-11-r1-factory-audio-micarray-sidecar-host.md)。该候选尚未部署，
不改写本报告的 v85 实机结果或未验证项。
