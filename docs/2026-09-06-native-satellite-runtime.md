> 历史记录：本文版本、命令及“下一步”反映记录当时状态；当前排期以[根 README](../README.md)为准。原始产物迁移见[归档说明](../test-results/README.md)，原验收结论不变。

# R1 原生卫星运行与恢复（2026-09-06）

后续进展：版本46通过非root `hide/unhide` 持久隔离及三次重启恢复。最新状态见 [非root隔离报告](./2026-09-06-r1-nonroot-isolation.md)；本文保留当时的实机结果。

本轮目标为首台 R1 的独立原生语音链路。用户确认现有 WebSocket 链路可用；后续整体语音验证统一放在原生开发之后，不重复开展 KWS 专项测试。用户选择包含开机自启、断线恢复和卫星专用模式。

## 运行结构

`NativeSatelliteService` 是 API22 前台服务，监听 TCP 6053，使用 NSD 发布 `_esphomelib._tcp`。HA 主动以 ESPHome 集成连接；R1 不保存 HA 长期令牌。身份、每台独立 Noise PSK、监听/启用状态与 Alexa 开关保存在 Android 应用私有 SharedPreferences 中，禁用 Android 备份。协议 MAC 是随机生成的本地单播标识，不读取硬件 MAC。

语音能力只声明 VOICE_ASSISTANT、SPEAKER 和 API_AUDIO（aioesphomeapi 45.6.1 对应位）；HA 自动创建卫星和管线选择实体。不声明计时器、通知插播、音乐播放器、远程启动对话或多通道音频。schema 仍固定 ESPHome 2026.8.0；消息 ID 继续生成。

新服务接入既有 NativeAudioRuntime、AudioRecord、AudioTrack 和原生会话组件。音频仍为 PCM S16LE/16kHz/单声道/20ms，保持 Alexa → 随机回应 → 6秒等开口 → 1.2秒尾部静音、最长20秒。回复后须等待网络会话结束与实际播放排空，再按既有规则续听。120秒上下文由独立 HA 会话适配维护。没有播放中插话。

服务持有可释放、定时续期的 CPU 唤醒锁，取消一小时开发上限；开机及 APK 更新后仅在持久启用时启动。连接断开清理旧录音/播放，等待线程退出后接受下一连接，不重放命令。与 WebSocket 服务使用进程内音频互斥，旧服务在原生启用时拒绝运行。

管理通道为 `r1-native-control` 本地 socket，仅允许 shell/root UID；任何网络客户端都不能使用它。首次初始化默认不开麦，`start` 默认也不开麦。状态只含身份、连接/音频计数和固定错误代码，不包含密钥、识别正文或录音。`pairing` 只向此受限本地通道提供密钥，由工具直接通过 SSH 私有管道送到 HA。

## 管理命令

在仓库目录执行（首台设备地址是当前开发地址，重配后应使用实际地址）：

```bash
python3 tools/native/deploy-r1-native.py install 192.0.2.10:5555 --evidence test-results/2026-09-06-r1-sample01-native-runtime
python3 tools/native/manage-r1-native.py initialize 192.0.2.10:5555 --name r1-sample01
python3 tools/native/manage-r1-native.py start 192.0.2.10:5555
python3 tools/native/manage-r1-native.py pair 192.0.2.10:5555
python3 tools/native/manage-r1-native.py status 192.0.2.10:5555
```

固件3448的普通 `adb install`/`pm` 包装入口不可靠。工具使用 `adb push` 和显式 `pm.jar` 安装，并核对 `Success`，删除本次临时 APK；安装前保留旧 APK、摘要和两个冲突包原状态。再次安装不覆盖最初回退基线。

HA SSH 插件没有 Core API 权限、关闭转发；本工具不改变这些设置。使用与现有 Home AI 项目一致的一次性配置管理员初始化：写入0600权限的 `/config/.r1_native_commission.json`，检查配置后重启 HA。组件先删除一次性文件，再通过 HA 配置流创建独立原生 STT/会话入口、通过管线存储 API 创建“R1 原生中文助手”、通过官方 ESPHome 配置流完成加密配对。报告为 `/config/.r1_native_commission_result.json`，不含密钥。原默认助手和已有管线逐项比对保留；失败不自动改用原管线。

音频后端如果在清理时超过5秒仍未退出，服务保存 `audio_blocked`，结束自身进程，由 Android 恢复为不开麦的管理/认证模式。只有管理员再次执行 `start --listen` 才清除此阻断标记。固件音频的阻塞调用不会在协议线程执行；`listening` 只在真正收到完整音频帧后出现。该保护已经在R1的真实阻塞场景验证，不等于阻塞根因已解决。

密钥轮换：先 `stop`，再 `rotate`、不开麦 `start`、`pair`，配对完成后才恢复 `start --listen`。轮换不改变设备 ID/协议 MAC；旧密钥立即失效。新密钥只存在 R1 私有配置、传输进程内存及 HA 配置流正常保存的位置。

## 音频切换与回退

临时隔离与开启监听：

```bash
python3 tools/native/deploy-r1-native.py isolate 192.0.2.10:5555 --evidence test-results/2026-09-06-r1-sample01-native-runtime
python3 tools/native/manage-r1-native.py start 192.0.2.10:5555 --listen
```

工具先核对设备/固件和已备份冲突 APK 哈希，仅临时停止 `com.phicomm.speaker.device`、`com.phicomm.speaker.player`。生产 `commit` 要求同设备、同 APK 的 `switch-readiness.json` 中真实收音、播放、开机入口、健康检查和恢复检查均通过，并确认当前原生监听；不允许用主机测试填充实机结果。预期切换操作为 `disable-user`，不卸载；但本机已实测缺少修改系统包状态的权限，`commit` 现增加权限预检并拒绝执行。此前实际切换失败后已核对恢复原启用状态。其他受支持环境中，部分禁用失败会先停止原生监听，再尝试恢复原状态与服务。

恢复冲突包及关闭原生自启：

```bash
python3 tools/native/deploy-r1-native.py restore 192.0.2.10:5555 --evidence test-results/2026-09-06-r1-sample01-native-runtime
```

恢复旧卫星 APK 则使用同一工具的 `rollback`。此操作保留原厂 APK，使用旧卫星 APK 的安装降级选项，不清除数据。3448缺少 `pm default-state`，工具以 shell 身份运行只允许两个已核对包的 `FactoryPackageState`，尝试通过 API22 系统包管理接口恢复默认状态；该接口同样受固件权限约束，不能绕过系统UID限制，也不赋予卫星服务 shell 权限。本机已验证的是启用状态未改变时，恢复临时停止的两个原音频服务；不能据此宣称任意系统包状态都可修改。

HA 回退时先解除该 R1 的 ESPHome 接入，再删除独立原生助手和原生模式条目，保留原通用过滤条目和两条旧助手。需要恢复组件代码时，使用本轮最初备份 `/config/r1_component_backups/20260905T195209Z-14228ec0/r1_input_guard`，完成 `ha core check` 后重启。不要先恢复旧组件而留下引用新实体的助手。

## 验证边界

证据目录：`test-results/2026-09-06-r1-sample01-native-runtime/`。最终状态以该目录汇总与 README 为准。

- 主机及合成协议检查涵盖消息能力、配置切换、双向PCM、播放排空、连续会话及加密拒绝。
- `check-runtime.py` 仅用于尚未配对的设备：实际服务初始化幂等、重启保留身份/密钥、唤醒开关持久化及密钥轮换。它会轮换密钥，不能对正在使用的配对执行而不重新配对。
- `audio-check` 仅在原生停止后由本地管理员显式启动，读取1秒真实麦克风样本并立即丢弃，播放固定200ms低幅度测试音，核对AudioTrack播放头。来源为当时首台R1麦克风，用途为录放资源与API22排空检查；不保存、不上传采样。该结果不等于用户确认可闻、识别准确或AEC验收。
- 正式中文问答、连续对话体验、回复延迟及72小时稳定性须分别以实际结果记录，不由音频自检、合成检查或开机成功替代。未知认证来源仍不能使用家庭工具；不因卫星配对伪造 `Context.user_id`。

## 实机结论与未完成项

- HA 加密配对成功，独立助手使用 `stt.r1_yuan_sheng_yu_yin_shi_bie`、`conversation.r1_yuan_sheng_hui_hua` 及原中文 Piper。原默认助手和两条旧管线保持不变；卫星为 `assist_satellite.r1_yuan_sheng_yu_yin_assist_satellite`。
- 不开麦服务重启保留身份/密钥、旧密钥拒绝、新密钥连接和mDNS发现通过。系统重启后原生服务会自动启动并连接HA。
- 临时隔离下，真实AudioRecord采集与NativeAudioTrackSink播放头排空检查通过；后续最终构建实际收音帧也连续增长。此为硬件/API检查，用户未确认本轮声音可闻性或完整中文问答。
- **卫星专用部署失败，不能标为完成。** 普通shell无权修改原包启用状态；临时 `force-stop` 在重启后会被原系统启动流程解除，两包均恢复运行。包权限/状态证据见 `isolation-limit.json`、`exclusive-switch.json`。
- 在原包运行场景，主动终止原生进程后只短暂看到 `listening`、帧数为0，随后出现真实 `AudioRecord.native_stop` Binder阻塞；HA重启恢复检查失败。线程证据见 `audio-stop-stall-threads.txt`。进程确实自动重启，但音频恢复未通过，已经纠正初次状态判断。阻塞根因及完整共存能力未验收。
- 后续修复将停止操作移出协议线程，实际进入 `audio_blocked` 且控制连接仍可用；再次临时隔离两原包并显式重试后，收音恢复并连续增长（`isolated-recovery-after-fuse.json`）。
- 不执行root、覆盖原厂APK、系统签名替换或分区操作。下一步必须先解决可回退系统音频隔离的权限/配置路线，或由用户明确调整专用部署范围。
- 真人中文问答/连续对话、量化成功率与延迟、网络/IP变化、72小时生产稳定性未验收。被动观察工具 `observe-runtime.py` 已提供，但不能以当前临时隔离配置的观察替代生产专用验收。

最终APK再次通过1秒实采与200ms测试音排空检查（`final-audio-health.json`）；安装文件摘要与构建产物一致。最终状态见 `final-runtime.json`：临时隔离下监听正常，真实音频帧连续增长。隔离条件下HA重启后约19.4秒恢复连接与连续收音（`ha-restart-isolated.json`）；该结论不覆盖R1重启后原包恢复的场景。

构建与测试主要命令：

```bash
bash tools/build-r1-noise.sh
cmake --build local-deps/build/r1-noise-host --parallel 4
JAVA_HOME=/home/developer/.sdkman/candidates/java/17.0.19-tem ANDROID_SDK_ROOT=/home/developer/.local/share/android-sdk android/r1-probe/gradlew -p android/r1-probe --no-daemon testDebugUnitTest lintDebug assembleDebug
docker run --rm --network none --entrypoint python -e PYTHONPATH=/work/integrations/home_assistant -v /path/to/phicomm-r1-satellite:/work:ro ghcr.io/home-assistant/home-assistant:2026.8.2 -m unittest discover -s /work/tools/ha/tests -p 'test_*.py' -v
docker run --rm --network none --entrypoint python -e PYTHONPATH=/work/integrations/home_assistant -v /path/to/phicomm-r1-satellite:/work:ro ghcr.io/home-assistant/home-assistant:2026.8.2 /work/tools/ha/tests/check_guard_setup.py
local-deps/esphome-interop-venv/bin/python tools/esphome/check-native-api.py --satellite-metadata
local-deps/esphome-interop-venv/bin/python tools/esphome/check-native-api.py --synthetic-dialogue
local-deps/esphome-interop-venv/bin/python tools/esphome/check-native-api.py --adb 192.0.2.10:5555 --synthetic-dialogue
```

最终Android为113项测试、lint及构建通过；HA为24项测试及真实配置生命周期检查通过。新增回归包括原生加密配对提示、错误密钥分类、音频所有者互斥及底层stop阻塞不得堵住协议调用。具体先后版本与实机/合成边界在 `summary.json` 中标注。旧的量化验收指标不因本轮开发结果调整。
