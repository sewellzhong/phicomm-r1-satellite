# R1 APK候选提交与健康客户端主机记录（2026-09-13）

## 范围与结论

本轮在U4定长私有协议之上实现v118/U5 APK侧客户端，受测实现提交为`c3ad4d642f276155d9e5ac385ece4b569dc7cf4e`。候选提交、同boot替换标记和四项健康门闩已接入Android服务生命周期，并通过API 22/armeabi-v7a构建及主机测试；没有连接R1、ADB或HA，没有安装候选，也没有调用真实Android PackageManager。因此本结果是代码/主机通过，不是OTA、签名更新或实机回滚交付。

## 已实现边界

- 候选只能按32位小写十六进制操作ID从应用`MODE_PRIVATE` inbox解析；Java复核严格递增版本、4 KiB～64 MiB实际文件长度、规范SHA-256、签名摘要和30～600秒健康窗口。候选路径不进入监督器协议，JNI只向固定`/dev/socket/r1_update_supervisor`传一个只读FD。
- JNI复用U4的网络字节序定长帧、`AF_UNIX/SOCK_SEQPACKET`和`SCM_RIGHTS`实现，固定API 22与`armeabi-v7a`，产物同时含SysV及GNU hash。普通控制入口仍只接受内核回读的root/shell UID；远程网络不能直接提交本地候选。
- 自更新会让PackageManager杀死旧APK，因而申请只在`sendmsg`完整发送后回报`submitted`，不把旧进程能否收到安装响应作为成功门槛。监督器仍须独立落盘、核验、安装并持久等待新包健康。
- 只有`MY_PACKAGE_REPLACED`记录健康待报；`BOOT_COMPLETED`不会新建标记。标记绑定Linux boot identity和单调时间，确认前重启会清除而不发送健康，报告循环最长620秒。
- 新APK动态检查服务工作/管理线程（启用时还要求监听socket建立）、关键持久状态加载、原厂音频代理只读health可达及原包隔离。四项未全部为真时不向监督器发送任何健康帧，避免部分健康立即触发错误回滚；成功或监督器已进入idle/rollback/failed后清除标记。
- 候选及健康Java逻辑通过可替换transport测试，覆盖候选字段、摘要规范、部分健康不发送、传输失败重试、同boot成功、跨boot拒绝及终止阶段停止重试。真实socket framing继续由U4 CTest覆盖。

## 已执行检查

- `bash tools/update/check.sh`：通过，Release构建及CTest 4/4通过。
- `ANDROID_SDK_ROOT=/home/sewellzhong/.local/share/android-sdk bash tools/build-r1-update-client.sh`：通过，生成API 22/armeabi-v7a JNI库并验证双hash。
- 同固定SDK运行Gradle `testDebugUnitTest lintDebug assembleDebug`：通过。
- `ANDROID_SDK_ROOT=/home/sewellzhong/.local/share/android-sdk R1_GRADLE_OFFLINE=1 bash tools/dev/check.sh`：完整通过；公开扫描489文件/0发现、凭据扫描0泄漏、Android 269项/lint/hostcheck APK、native工具47项、R0 73项及合成演练、原厂音频117项、更新CTest 4项、HA 102项及HA 2026.8.2配置生命周期均通过。hostcheck APK SHA-256为`0522694be62e0036608efd470c22b8a7bb98a04a9dbbec37abef0674191e3886`，仅含合成提示音且包名隔离，禁止部署到设备。

首次定向Gradle命令误指向不存在的`/opt/android-sdk`，在依赖解析前因SDK路径无效退出；改用仓库文档固定的现有SDK后通过，不属于源码或测试失败。

## 未完成与下一入口

当前没有常驻root监督器main、真实3448 PackageManager安装/降级实现、init与专用Enforcing策略，也没有签名候选的R1成功/失败回滚证据。应用私有inbox仅是root维护提交边界，不是经Noise认证的远程候选传输或下载功能。

下一步实现常驻监督器main，以子进程主机伪包管理后端验证跨进程申请、旧APK提交后断线、新APK健康及回滚闭环。真实设备后端必须先采集3448的包路径、安装/降级返回值和AVC，再按最小权限实现；不得预写宽泛SELinux权限或把主机替身记为实机通过。
