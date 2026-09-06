> 历史记录：本文版本、命令及“下一步”反映记录当时状态；当前排期以[根 README](../README.md)为准。原始产物迁移见[归档说明](../test-results/README.md)，原验收结论不变。

# Assist 开发机会话后台管理（2026-09-05）

新增 `tools/assist/manage-r1-assist.py`，在开发机专用 tmux socket `r1-assist` 中运行现有启动器。
令牌仍由启动器 getpass 隐藏读取，仅留在内存；不作为 tmux 命令、参数或配置文件保存。
管理工具不更改 Android APK、HA 配置、模型或现有一小时服务上限，也不实现设备开机自启。
开发机及 ADB 仍需在线。SSH 断开不会主动关闭 tmux 会话；开发机重启后需重新输入令牌。

## 使用

本次已准备后台会话，确认停在令牌提示符。连接它：

```bash
python3 /path/to/phicomm-r1-satellite/tools/assist/manage-r1-assist.py attach 192.0.2.10:5555
```

输入令牌，看到 listening 后按 Ctrl+B、松开、再按 D 离开 tmux，此后可关闭 SSH。
不要按 Ctrl+C 来离开；Ctrl+C 会停止服务并恢复音频修改包。

查看当前后台输出：

```bash
python3 /path/to/phicomm-r1-satellite/tools/assist/manage-r1-assist.py status 192.0.2.10:5555
```

正常停止：

```bash
python3 /path/to/phicomm-r1-satellite/tools/assist/manage-r1-assist.py stop 192.0.2.10:5555
```

stop 发送 Ctrl+C，让原启动器执行恢复。最多等待 40 秒；未退出则提示 attach 检查，
不强杀会话。会话退出本身不证明设备音频恢复成功；如设备失联，应另核验原音频服务。
工具不写磁盘日志，已退出会话的终端输出不保留。

后续会话到期或停止后重新启动：

```bash
python3 /path/to/phicomm-r1-satellite/tools/assist/manage-r1-assist.py start \
  192.0.2.10:5555 \
  --url https://home-assistant.sewellzhong.com \
  --pipeline 01m04j14wzw45d4094qn1s6x68
```

start 自动进入交互终端，不允许重复创建同设备后台会话。原启动器会拒绝设备已有的前台服务；
该工具不能接管已经在普通终端输入的令牌或迁移旧进程。

## 本轮证据与边界

- Python 编译检查通过。
- `python3 -m unittest discover -s tools/assist/tests -v`：3 项通过，真实 tmux 配合模拟启动器；
  覆盖脱离客户端保持运行、无效测试标记隐藏输入、重复启动拒绝、SIGINT 清理、令牌提示时退出、
  URL 凭据拒绝。没有连接 R1/HA 或发起语音请求。
- 实际开发机 tmux 3.5a；只读确认 R1 原 AssistRuntimeService 已退出后准备新后台会话，
  已看到 `HA API token (memory only):`。尚未输入真实令牌，没有打开麦克风。
- 未在真实认证状态下验证 SSH 断开后语音；不将模拟生命周期验证标为 R1 长期稳定性验收。
- 用户不再进行 KWS 测试的决定保持有效。

用户完成隐藏输入和分离操作后，只读确认 tmux attached=0，R1 status=listening、last_error=null，累计音频帧 2838。真实认证后后台监听状态已确认；未触发额外语音请求，不能据此宣称长期稳定性或分离后的问答效果已验收。见 `test-results/2026-09-05-r1-sample01-assist-background/detached-status.json`。
