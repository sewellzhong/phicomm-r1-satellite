# r1-sample01 v14 代理与 v82 原厂音频实机记录（2026-09-11）

## 范围与结论

本轮按[首台免拆分级授权](2026-09-11-r1-no-disassembly-authorization.md)继续 R3，只从现场双读
的当前 boot 生成仅替换自有代理的 v14 候选，部署 v82 APK，并取得无本机播放、60% 和
接近 90% 的受控播放采集。没有修改 system、recovery、Loader、参数/分区表或物理首 4 MiB，
没有擦除、格式化或整盘写入。R0 继续为 `pending`。

v14 boot、v82 APK 和三次采集均完成各自门禁。原厂接口运行时返回两个交错输出通道，但本轮
三次采集中两路均逐样本完全相同，生产单声道同时匹配两路。这个结果只证明运行时输出形状和
映射，不代表四支原始麦克风独立可见。

受控播放确实落在相同采集窗口内，输出残留随实际音量明显增加。代理健康字段仍明确报告 AEC
参考通道为 0、AEC 未证明，因此本轮不计算或宣称 AEC 消除量。四麦独立响应、AEC 消除量和
DSP 质量保持未验证。

## boot 与 APK 门禁

- ADB 序列：`CBEAU1116K01314`；设备代号：`r1-sample01`。
- fingerprint：`Android/rk322x_echo/rk322x_echo:5.1.1/LMY49F/3448:user/release-keys`。
- 目标分区：`boot`，Loader image 起始扇区 98,304，长度 24,576 扇区/12,582,912 字节。
- 现场 boot A/B 双读均为 v13 `09c89752f388bf09797251c819f7629a39f5ac5a24e93df7a5995154e187a787`。
- 新代理为 `d06325edb1b048bec990c822a015986b762a27263cc8d5ffd0e9a7ad337e5843`。
- 增量构建器确认唯一声明变化为 `ramdisk_agent`；v14 boot 为
  `53911d71787d3e8f4dc9b31b73b0b4dafde569d30795023a2712a43bcb5e7110`。
- v14 单次写入后、复位前完整读回与候选一致。Android 正常启动，ADB、3448 fingerprint、
  Wi-Fi、原厂音频只读预检和 SELinux Enforcing 均通过，代理 init 服务为 `running`。
- v80 回退 APK 已从设备读取，SHA-256 为
  `5883f28d2eb11aed9b6b14581b848b2b1fd628a876e4628f813f8a3bc6876b35`。
- v82 使用固件 3448 已验证的显式 API 22 `pm.jar` 入口覆盖安装；设备端读回 APK 为
  `b115b5077da502a7fbe9efd8a21e2cee6c2e5ae084e8c176d8ace79d52db1c73`，versionCode 82、
  UID 10010、API 22 和原签名证书均匹配。原厂 device/player 包的隐藏状态保持。
- 安装验证后的 `force-stop` 曾按预期停止卫星服务；最终按原有配置恢复 `--listen`，状态为
  `listening`、`audio_opened=true`、连接数 1、失败数 0。该最小运行检查不恢复已暂停的语音回归。

普通 `pm` 子进程被该固件受限 adbd 拒绝，标准 `adb install` 会等待设备；这与既有阶段 0
结论一致，不是 v14 启动失败。中止等待进程后改用已验证兼容入口，返回 `Success`。

## 三次采集

参考为工具生成的 5 秒、1 kHz、20% 满幅合成 WAV，固定为 16 kHz、单声道、S16LE，
SHA-256 为 `8d5c24a6fef3d1cd90faa44d593f8d72d4a352724a4e72ca033c667fa6696089`。
媒体音量为 15 档，故第二播放档使用 14/15，即设备实际记录的 93%，不伪称精确 90%。

| 条件 | 帧/缺口/代理丢帧 | DOA 有效 | 输出通道 | 每路 RMS | 审计报告 SHA-256 |
|---|---:|---:|---|---:|---|
| 无本机播放 | 500 / 0 / 0 | 500/500，全部落在 0～9° bin | 2，逐样本相同 | 6.7362 | `7f44fd549074c1c0e339b550e1c5f751f17ee85afa685ee5e4548bd42c49e611` |
| 9/15，60% | 500 / 0 / 0 | 500/500，全部落在 0～9° bin | 2，逐样本相同 | 267.9447 | `ee072c5b4263f99b6533175cf5f4ab92564e9680b6d36d6c65b20b3ec50423f1` |
| 14/15，93% | 500 / 0 / 0 | 500/500，全部落在 0～9° bin | 2，逐样本相同 | 1294.4624 | `facbc72d79805f594a9a23c5e31784ee4c24e5a793787b328930ed0705f07215` |

三份审计报告及 WAV 只保存在仓库外。播放结束后媒体音量恢复到本轮前实际索引 2。

首次按旧文档只传参考文件名时，应用在写录音前以 `playback_path_outside_diagnostics` 拒绝。
代码实际要求 diagnostics 内的绝对规范路径；文档已修正。两次成功播放的设备 wall-time
耗时比单调时钟端点差值约多 1.5 ms，旧审计门槛只允许 1 ms，造成证据拒绝。审计器现明确
允许最多 10 ms 的量化/时钟偏差，并增加上下界回归；超过 10 ms 仍拒绝。

## 验证与下一入口

定向测试已运行：

```bash
python3 -m unittest tools.factory_audio.tests.test_validation_capture
bash tools/factory_audio/check.sh
ANDROID_SDK_ROOT=/home/sewellzhong/.local/share/android-sdk \
  R1_GRADLE_OFFLINE=1 bash tools/dev/check.sh
```

定向测试 8 项及原厂音频检查 62 项通过。统一检查通过 Android 单元测试、lint和hostcheck构建、
native 32 项、R0 73 项与演练、原厂音频 62 项、HA 44 项及 HA 2026.8.2 配置加载；公开扫描
364 个文件为 0 发现，凭据扫描无泄漏。

下一步先查明原厂配置声明双参考与代理运行时 `aec_reference_channels=0`、`aec_active=false`
之间的接口边界，并取得可校准的处理前/处理后或无 AEC 对照后计算消除量。四方向 DOA 和
四麦独立刺激需要受控物理声源位置，继续保持待实机操作；当前固定 5° 结果不能替代方向矩阵。
