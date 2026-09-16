# 播放中打断门控与配网状态实现

日期：2026-09-16

## 本次实现

- 新增 `PlaybackBargeInGate`，直接插话只有在原厂 AEC 有有效输出、当前帧不是播放参考匹配、语音经过能量/VAD 门控、连续强语音达到门槛且 AEC 输出未饱和时才允许进入取消状态机。
- 播放期原厂 AEC-KWS Alexa 检测改用独立取消授权：检测到有效唤醒、AEC 输出就绪且未饱和即可取消，不再被普通直接插话 VAD 门槛拦截；无唤醒直接插话仍保留原门控。
- `NativeAudioRuntime` 启用受门控保护的直接插话分支，并在诊断中报告当前阻断原因；按键停止和再次说 `Alexa` 的既有取消路径保持不变。
- 配网页面提交 Wi-Fi 后不再把 HTTP `202 accepted` 当成连接成功；新增认证 `/api/status` 查询，页面根据设备实际阶段和 Supplicant 状态显示连接、失败或恢复结果。
- 配网切换移到后台线程，保留 HTTP 服务线程用于状态查询；凭据仍通过已有加密 handoff 保存，不写入日志或响应正文。

## 验证

- `PlaybackBargeInGateTest`：4 项通过。
- `PlaybackWakeCancelGateTest`：2 项通过。
- `python3 -m unittest discover -s tools/validation/tests -v`：13 项通过。
- `git diff --check`：通过。
- Android `testDebugUnitTest lintDebug assembleDebug`：通过。
- 完整 `ANDROID_SDK_ROOT=/home/sewellzhong/.local/share/android-sdk ANDROID_HOME=/home/sewellzhong/.local/share/android-sdk bash tools/dev/check.sh`：通过；HA 109 项、原生/更新/恢复/系统控制检查通过。

## 首台候选构建

- 候选源码提交：`d7cb438f74a756af26d650a33d1921b9051f42ac`；该提交包含本次播放中打断门控、配网状态实现和验证记录。
- 生产包构建参数：`-PprobeVersionCode=172 -PprobeVersionName=1.72-playback-barge-provisioning assembleDebug`。
- APK：包名 `dev.sewellzhong.r1probe`，API 22，versionCode `172`，SHA-256 `57417123e6cbad67e3528ed9df58950be9456a67fb055c3d56f73d37b3a055f0`。
- 签名证书 SHA-256：`0be7a3643442658354c185ec53cb50e73bc1516a56f2760ca46f2c932c1d2639`，与现有设备候选签名一致。
- 当前状态：候选已冻结并提交；未部署、未连接 ADB/HA、未形成首台实机证据。

## 未验证项

- 尚未在 `r1-sample01` 正确麦克风朝上姿态验证直接插话的真实人声/扬声器回声区分、AEC 输出稳定性和播放取消效果。
- 尚未验证安卓/iPhone 从热点切回家庭 Wi-Fi 后的完整网页轮询、错误密码和失败恢复流程。
- 本文不改变首台 release gate；实机证据、最终候选统一回归、IP 变化和 72 小时稳定性仍待执行。
