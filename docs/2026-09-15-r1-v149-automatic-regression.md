# R1 v149最终候选自动回归（2026-09-15）

设备：`r1-sample01`（3448 / API 22 / SELinux Enforcing），现装 v149，音量 4%。

## 主机门禁

执行 `ANDROID_SDK_ROOT=/home/sewellzhong/.local/share/android-sdk bash tools/dev/check.sh`，结果通过：

- 公开文件扫描 596 个、0 findings；凭据扫描无泄漏。
- Android 单测、构建、Lint 通过。
- Native 118 项、Recovery 73 项、原厂音频 118 项、更新 41 项、HA 容器 107 项及系统控制门禁通过。
- HA 容器结果明确为 `production_HA=false`、`real_microphone=false`，不把主机替身升格为实机结论。

## 首台只读状态/数据/链路回归

使用 `tools/native/manage-r1-native.py` 的 `status`、`capability-status`、`alarm-status`、`dnd-status`，未写入配置、未发送语音、未改动密钥或网络。脱敏 JSON 保存在本地忽略目录：
`test-results/2026-09-15-r1-sample01-v149-automatic-regression/`。

- 包身份为 v149，服务 `listening`，Noise 连接 1，`audio_opened=true`，`last_error=null`，运行失败 0，音量 4%。
- 音频数据计数非空（累计 22,710 帧），播放欠载 0；生产回答取消和直接插话仍按安全策略关闭。
- 闹钟为 0 条、`pending=false`、持久化失败 0；DND 关闭、闹钟例外开启、持久化失败 0。
- 能力回读确认原厂配网桥、BLE/蓝牙、热点能力和系统控制服务处于可查询状态，监听灯状态回读为 `listening`。
- `input_event*`、`led*` 和实体环输入在当前权限/硬件路径报告不可读；这不是通过证据，保留为硬件能力待补项。

## 结论与下一步

主机自动回归通过，首台只读运行/数据/链路健康通过；本轮未宣称 HA 生产后端或全部硬件控制功能通过。下一步按顺序执行网络/IP 变化恢复（含 HA/Noise 重连和状态回读），随后才启动 72 小时稳定性观察；两项均未开始，单台 release gate 仍未解锁。
