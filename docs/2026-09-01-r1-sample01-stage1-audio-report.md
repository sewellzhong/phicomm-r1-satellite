> 历史记录：本文版本、命令及“下一步”反映记录当时状态；当前排期以[根 README](../README.md)为准。原始产物迁移见[归档说明](../test-results/README.md)，原验收结论不变。

# R1 真机 r1-sample01 阶段 1 音频开发首轮报告

- 日期：2026-09-01
- 设备 ID：r1-sample01
- 固件：3448 / Android 5.1.1 / API 22
- 真机调试 APK：`dev.sewellzhong.r1probe` versionCode 7
- 结论：独立 APK 的录放音链路在隔离当前两个第三方修改音频包后可用；这些更新包运行时独立录放音均阻塞。声学质量、AEC 和生产共存路线尚未通过。

## 实机结果

| 场景 | VOICE_COMMUNICATION | VOICE_RECOGNITION | MIC | WAV 回放 |
| --- | --- | --- | --- | --- |
| 当前第三方语音/播放器更新包运行 | `audio_read_timeout` | `audio_read_timeout` | `audio_read_timeout` | 首次 `AudioTrack.write()` 阻塞 |
| 临时停止当前第三方语音/播放器更新包 | 10 秒完整 | 10 秒完整 | 10 秒完整 | 2 秒合成音写入及 drain 完成 |

隔离场景三份 WAV 均为 PCM S16LE、16 kHz、单声道，每份 160000 帧/320000 PCM 字节，录制耗时约 10.26 秒，无部分读取和削波。系统框架报告 AEC、NS、AGC 全部不可用。

| 输入源 | RMS | 峰值 | 削波率 |
| --- | ---: | ---: | ---: |
| VOICE_COMMUNICATION | -58.75 dBFS | -32.30 dBFS | 0% |
| VOICE_RECOGNITION | -60.28 dBFS | -32.36 dBFS | 0% |
| MIC | -60.91 dBFS | -31.43 dBFS | 0% |

三份样本电平均很低，只能证明数据链路连续，不能据此判定远场语音可用。合成 WAV 的 `AudioTrack` 完成日志证明写入和播放头推进；是否从扬声器实际可闻仍需现场人工确认。

## 固件偏差与安全措施

- 固件 3448 的物理 FAT 主存储即使是应用专属目录也需要 `WRITE_EXTERNAL_STORAGE` 才能获得 `sdcard_rw`；探针只访问自身 `Android/data/.../diagnostics` 子目录。
- `AudioRecord.read()` 和 `AudioTrack.write()` 都可能永久阻塞；探针加入设备端看门狗，自动流程另有宿主超时与 force-stop 回收。
- 初版目录异常曾触发一次未捕获崩溃；观察到系统异常上报服务会收集带设备标识的崩溃遥测。后续错误已全部转换为调试 APK 日志，该次遥测未保存到测试证据。
- 停止当前包前补充备份了 `/data/app` 更新层文件并验证 SHA-256。后续来源复核确认这些文件是前置 DEX/后置 APK ZIP 的第三方修改结构，不能称为原厂更新包。隔离测试通过 trap 恢复 `EchoService`、`WindowsService` 和当前语音主 Activity；恢复后的全部播放器子进程和两个前台服务已复核。
- 采集成功后，WAV 拉回本机并校验，R1 上的诊断录音随即删除。本机 WAV 由 `.gitignore` 排除，不默认提交。
- 隔离运行的录放音操作均成功，但后续追加分析文件后，旧证据目录曾出现一次 `run.log: FAILED` 的清单复核输出，外层流程因此退出 1。该异常不改变 WAV、元数据和播放完成标记本身的结果，但说明旧清单不能被描述为整目录持续有效。后续工具改为只对已关闭的不可变证据生成清单，并排除仍在写入的运行日志。

## 证据

- 当前第三方音频包运行时失败矩阵：[`test-results/2026-09-01T234530-r1-sample01/stage1/audio-probe/`](../test-results/README.md)
- 隔离后成功的 WAV、分析和日志：[`test-results/2026-09-01T235327-r1-sample01/stage1/audio-probe/`](../test-results/README.md)
- 停止前、停止后和恢复后的服务状态：[`test-results/2026-09-01T235322-r1-sample01/stage1/isolation-control/`](../test-results/README.md)
- 当前更新层 APK 备份：[`test-results/2026-09-01-r1-sample01/stage0/current-installed-apps/`](../test-results/README.md)

## 下一步门槛

1. 在 1 米安静环境下，隔离当前第三方音频包后对三种源录制同一句固定中文短语，人工确认可懂度并比较 RMS、噪声和频谱。
2. 确认合成音确实从 R1 扬声器可闻，记录音量设置；当前只有 AudioTrack 完成证据。
3. 逐个隔离当前语音更新包与播放器更新包，确定输入、输出分别由哪个包独占，避免生产方案永久停用不相关服务。
4. 若无法复用原厂 AEC，进入播放参考信号和 WebRTC APM 可行性实验；未通过播放中唤醒前不进入生产验收。

阶段 1 的执行顺序固定为：先完成上述音频可懂度、实际可闻和独占边界门槛，再开始 WenetSpeech INT8 与双语 KWS 对照。音频数据链路成功不能替代人工可懂度或生产声学验收。
