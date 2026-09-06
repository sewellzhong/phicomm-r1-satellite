> 历史记录：本文版本、命令及“下一步”反映记录当时状态；当前排期以[根 README](../README.md)为准。原始产物迁移见[归档说明](../test-results/README.md)，原验收结论不变。

# R1 真机 r1-sample01 阶段 1 同源原始/处理语音验收

- 日期：2026-09-03
- 设备 ID：r1-sample01
- 固件：3448 / Android 5.1.1 / API 22
- 真机调试 APK：`dev.sewellzhong.r1probe` versionCode 12
- 固定短语：`你好小智，请打开客厅的灯`
- 结论：versionCode 12 的两轮原始 A 和实时处理 B 均由用户确认清楚可懂，但整段 10 dB 分离门槛未通过；修正门控后的 versionCode 13 同源复测中，原始与处理后整段分离均通过 10 dB，用户确认处理后 B 清楚且比 A 好，阶段 1 音频子门槛通过。

## 方法

versionCode 12 对同一次 `VOICE_COMMUNICATION` / PCM S16LE / 16 kHz / 单声道采集同时保存原始 WAV并送入固定工作区实时处理器，避免用不同说话内容比较 A/B。每轮先完成 2 秒校准和 5 秒静音基线，语音轮在内部初始化完成后播放 5 秒 1 kHz 提示音，提示音结束才开始 10 秒录音。设备端 WAV 在校验拉回后删除，本地文件由 `.gitignore` 排除。

## 第一轮

| 指标 | 原始 A | 处理后 B |
| --- | ---: | ---: |
| 静音 RMS | -65.33 dBFS | -40.64 dBFS |
| 语音 RMS | -56.97 dBFS | -34.83 dBFS |
| 整段语音/静音差 | 8.36 dB | 5.81 dB |
| 100 ms 活跃窗口 P95 差 | 12.45 dB | 7.13 dB |
| 削波 | 0 | 0 |

原始活跃语音分离超过 10 dB，但包含停顿的整段指标未达到门槛。处理后绝对电平提高约 22 dB，但静音基线同时被抬高约 25 dB，导致分离度下降；因此不能把“更响且可懂”解释为处理算法客观改善。用户回听原始 +18 dB 的 A 和不额外放大的 B，确认两者都能听清。

证据：[`test-results/2026-09-03T043103-r1-sample01/stage1/processed-speech-acceptance/`](../test-results/README.md)、[`A 回放`](../test-results/README.md)和[`B 回放`](../test-results/README.md)。

## 第二轮

第二轮语音原始 RMS 为 -55.02 dBFS、活跃窗口 P95 为 -48.84 dBFS，与第一轮分别相差约 2.0 和 1.4 dB，说明说话样本本身大致可重复。但静音原始样本第 3 秒出现 -41.91 dBFS 的单次瞬态，其余四秒约为 -67～-68 dBFS；该瞬态把整段静音 RMS 抬到 -48.85 dBFS，使整段差变为 -6.16 dB。因此本轮静音对照无效，不用于门槛结论，也不据此判断硬件或算法退化。

用户回听第二轮 A/B 后再次确认两者都能听清，感觉都好，没有特别注意到明显自然度差异。证据：[`test-results/2026-09-03T043541-r1-sample01/stage1/processed-speech-acceptance/`](../test-results/README.md)、[`A 回放`](../test-results/README.md)和[`B 回放`](../test-results/README.md)。

## versionCode 12 判定

- 固定短语主观可懂度：通过，两轮 A/B 均清楚。
- 处理自然度：未发现明显问题，但用户未做针对性伪影辨识，不能等同严格自然度盲测。
- 整段 10 dB 分离：未通过；第一轮原始为 8.36 dB，第二轮基线无效。
- 当前 balanced + 自适应增益：不选为生产默认，因为它提高绝对响度但降低本轮语音/静音分离。

据此决定先修正活动门控，使静音帧不被固定增益和自适应增益抬高，再使用同一套提示时序复测；该修正和复测已由下述 versionCode 13 完成。

## versionCode 13 门控复测

versionCode 13 将非活动帧增益设为 `1 / 7.943`，抵消频谱处理后的固定 +18 dB；活动阈值由噪声 RMS 的 1.5 倍收紧到 2.0 倍，语音起音使用 0.65 的快速跟随、回落使用 0.25，避免为了压低静音而采用更高阈值吞掉轻声字。15 个 JVM 单元测试、lint 和 APK 构建通过，最终安装 APK SHA-256 为 `f87139aca8bf57a40a5652c149deb1b18ab84fab1b4d12f0b88a7096348e78c1`，安装证据位于 [`test-results/2026-09-03T044705-r1-sample01/stage0/apk-install/`](../test-results/README.md)。

同源复测结果：

| 指标 | 原始 A | versionCode 13 处理后 B |
| --- | ---: | ---: |
| 静音 RMS | -67.00 dBFS | -57.57 dBFS |
| 语音 RMS | -55.68 dBFS | -28.05 dBFS |
| 整段语音/静音差 | 11.32 dB | 29.52 dB |
| 100 ms 活跃窗口 P95 差 | 14.82 dB | 46.50 dB |
| 削波 | 0 | 0 |

原始和处理后整段分离均超过 10 dB，处理后分离不低于原始，输入/输出各 160000 样本且部分读取、处理超时和削波均为 0。用户回听原始 +18 dB 的 A 与不额外放大的 B 后确认 B 能听清且比 A 好；未单独报告吞字或伪影，因此只记录已确认的可懂度和相对偏好，不扩展为严格伪影盲测结论。

证据：[`同源采集与分析`](../test-results/README.md)、[`A 回放`](../test-results/README.md)和[`B 回放`](../test-results/README.md)。结合此前测试音实际可闻、30 分钟流式稳定性以及本轮 1 米固定短语结果，阶段 1 音频子门槛通过；这不代表 AEC、播放中唤醒、KWS 或阶段 1 总门槛已通过。

同一 APK 随后完成 20 秒无音频留存回归，输入/输出各 320000 样本，部分读取、处理超时、削波和运行期 GC 均为 0，最长处理块 30.341 ms，PSS 约 10.4 MB；设备端元数据已删除，原服务恢复。证据位于 [`test-results/2026-09-03T045222-r1-sample01/stage1/streaming-smoke/`](../test-results/README.md)。
