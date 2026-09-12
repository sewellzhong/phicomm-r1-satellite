# R1更新监督器进程闭环主机记录（2026-09-13）

## 范围与结论

本轮在U1～U5基础上实现U6常驻监督器运行循环，受测实现提交为`3cec49dccdfa88d0eea5a6b8da5584cef871b13b`。独立主机监督器进程已通过真实Unix socket完成申请与健康确认，并验证畸形连接隔离和跨boot恢复回滚；没有连接R1、ADB或HA，没有安装候选，也没有调用3448 PackageManager。主机可执行文件及伪后端只属于测试目标，因此本结果是代码/主机通过，不是设备root守护进程、OTA或实机回滚交付。

## 已实现边界

- `run_update_supervisor`启动时先恢复U2持久事务，再轮询已经安全建立的listener；单个协议/传输错误只关闭该客户端，不终止后续服务。循环以1秒为上限复查健康截止时间，测试可用有界请求数退出，设备入口后续可接init生命周期与停止信号。
- 监督器使用`CLOCK_BOOTTIME`并读取规范的kernel boot UUID。事务格式升级为v2，在`installing`持久化、任何PackageManager替换副作用发生前同时保存boot ID；健康成功或已验证回滚后才清除。v1仍可读取，但没有同boot证据的等待健康事务会按不同boot处理并回滚。
- 主机伪包管理可执行文件运行在独立子进程；测试先发送一个畸形短帧，随后重新连接，以真实`SOCK_SEQPACKET`和`SCM_RIGHTS`发送4096字节固定候选，回读`awaiting_health`，再由新连接发送四项健康并回读`idle`。这证明一次坏客户端不会阻断后续合法更新请求。
- 另一场景先持久化`awaiting_health`事务，再以不同boot ID启动监督循环；循环在接受任何新客户端前进入回滚，伪后端恢复旧版本并由编排器再次核对身份。
- host伪后端只提供确定性身份和内存包状态，不解析APK、不执行命令、不代表Android返回语义。真实实现仍只能通过固定argv或Binder契约调用包管理，不能接受客户端命令、路径或shell文本。

## 已执行检查

- `bash tools/update/check.sh`：通过，Release构建及CTest 5/5通过。
- `ANDROID_SDK_ROOT=/home/sewellzhong/.local/share/android-sdk bash tools/build-r1-update-client.sh`：通过，API 22/armeabi-v7a库成功链接，SysV/GNU双hash均存在。
- `ANDROID_SDK_ROOT=/home/sewellzhong/.local/share/android-sdk R1_GRADLE_OFFLINE=1 bash tools/dev/check.sh`：完整通过；公开扫描493文件/0发现、凭据扫描0泄漏、Android 269项及lint、native工具47项、R0 73项及合成演练、原厂音频117项、更新CTest 5项、HA 102项及HA 2026.8.2配置生命周期均通过。hostcheck APK SHA-256为`33f31d2949f082fa9c46f922611df03e2a56c8502ca73a3f2e2a907ed1df1a63`，仅为隔离包名与合成素材构建，禁止部署到设备。
- 文档更新后再次运行`python3 tools/dev/audit-public.py`：通过，494文件、0发现。

首次定向CTest因boot ID校验错误地覆盖了尚未进入安装副作用的`staged`持久化而失败；修正为staged保持v1、`begin_install`原子升级v2后，既有4项和新增监督器测试全部通过。该失败没有连接设备或执行包安装。

## 未完成与下一入口

当前没有设备侧root可执行main、真实3448 PackageManager安装/显式降级后端、init服务、root-owned事务/socket目录或专用Enforcing策略，也没有签名候选的R1成功及注入失败回滚证据。host伪后端和hostcheck APK都不得部署；应用私有inbox仍只是本地维护边界，不是远程OTA下载入口。

下一步先在现行授权内以只读方式采集3448的已安装包路径、固定包管理调用返回值和相关AVC，再据实实现最小后端、init继承socket及专用Enforcing权限。未取得证据前不预写宽泛SELinux allow，也不把主机进程闭环记为实机通过。
