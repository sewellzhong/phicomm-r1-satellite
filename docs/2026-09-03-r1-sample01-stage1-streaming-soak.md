> 历史记录：本文版本、命令及“下一步”反映记录当时状态；当前排期以[根 README](../README.md)为准。原始产物迁移见[归档说明](../test-results/README.md)，原验收结论不变。

# R1 真机 r1-sample01 阶段 1 增量处理长时 Soak

- 日期：2026-09-03
- 设备 ID：r1-sample01
- 固件：3448 / Android 5.1.1 / API 22
- 真机调试 APK：`dev.sewellzhong.r1probe` versionCode 11
- 结论：不保存音频的 20 秒回归和第二轮 30 分钟正式 soak 通过；这只通过增量处理稳定性子项，不能替代阶段 1 声学子门槛或 KWS 验收。

## 实现和安装

versionCode 11 将实时稳态路径中的 FFT real/imaginary、AudioRecord 解码、处理输出和可选 WAV 编码缓冲改为复用工作区。长测由受 `android.permission.DUMP` 保护的独立 Service 承载，处理后 PCM 直接丢弃，只生成统计元数据。JVM 单元测试共 14 个，`lintDebug` 和 `assembleDebug` 均通过。

最终安装 APK SHA-256 为 `edc663363638ff6034a5145ac92227af69ff4eeb4ef1df13294b1f8d8872ae11`。固件兼容安装入口完成覆盖升级和启动验证，证据位于 [`test-results/2026-09-03T030942-r1-sample01/stage0/apk-install/`](../test-results/README.md)。同日较早的安装记录对应修正 20 秒 smoke 下限前的同版本构建，不作为最终 APK 证据。

## 真机结果

20 秒无留存回归输入/输出均为 320000 样本，部分读取、处理超时和削波均为 0，最长处理块 32.333 ms，PSS 约 9.8 MB。证据位于 [`test-results/2026-09-03T031012-r1-sample01/stage1/streaming-smoke/`](../test-results/README.md)。

首次 30 分钟运行的设备侧处理完整，输入/输出均为 28800000 样本且音频指标无失败；但主机把每次 AudioFlinger 快照的约 18 秒耗时叠加到采样周期，只得到 23 个 PSS 样本，低于预定 25 个证据点，因此该轮自动状态保留为失败，不降低门槛掩盖工具问题。证据位于 [`test-results/2026-09-03T031103-r1-sample01/stage1/streaming-soak/`](../test-results/README.md)。主机工具随后改为按真实经过时间追赶 60 秒刻度。

第二轮正式 30 分钟结果：

| 指标 | 结果 |
| --- | ---: |
| 输入 / 输出样本 | 28800000 / 28800000 |
| 设备侧经过时间 | 1802.717 秒 |
| 部分读取 / 处理超时 / 削波 | 0 / 0 / 0 |
| 最长处理块 | 42.558 ms |
| 总处理线程 CPU | 228.698 秒，约单核 12.7% |
| 总处理墙钟 | 235.320 秒，实时率约 0.131 |
| PSS 样本数 / PID 数 | 31 / 1 |
| 最大 PSS | 11842 kB |
| 首 5 / 末 5 PSS 中位数 | 9686 / 9690 kB，增长 4 kB |
| 音频留存 | `false` |

自动门槛全部通过，证据位于 [`test-results/2026-09-03T034212-r1-sample01/stage1/streaming-soak/`](../test-results/README.md)。Logcat 中 5 次 GC 全部出现在处理完成标记之后，均为诊断快照触发的 explicit GC；处理运行期间没有记录到 GC 或分配失败。SHA-256 清单复核通过，设备端元数据已删除，未生成 WAV；退出后当前语音包、播放器包及全部播放器子进程已恢复。

## 边界和下一步

本轮证明固定工作区的标准 AudioRecord 增量处理可在首台 R1 上连续运行 30 分钟，不证明原始采集增益、处理后自然度、AEC、播放中唤醒或 KWS 已通过。阶段 1 仍停留在音频声学子门槛：下一次采集必须由用户以 1 米正常交谈音量朗读固定中文短语，同时保留原始和处理后诊断样本，复核同源静音差、逐字可懂度、自然度和漏字；通过后才进入 KWS 对照。
