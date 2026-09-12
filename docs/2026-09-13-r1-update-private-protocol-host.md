# R1 私有更新协议与监听闭环主机记录（2026-09-13）

## 本轮范围

在U2候选落盘和U3包替换编排之上，实现版本化、本地、定长的监督器协议以及一次请求的监听、认证、分发和响应闭环。受测实现提交为`cbc2908155e6d2c3479de34c9f9235cf0292e60a`。

本轮没有连接R1、ADB或HA，没有构建设备APK，没有调用真实Android PackageManager，也没有生成init或SELinux部署件。主机socket和伪PackageManager只验证协议边界与副作用编排，不作为3448固件更新或回滚证据。

## 已实现边界

- 协议版本固定为1，使用`AF_UNIX/SOCK_SEQPACKET`和网络字节序；申请和响应各固定128字节，健康请求固定16字节，不接受流式拼帧、尾随字节或未知版本/类型。
- 申请帧固定携带32位小写十六进制操作ID、来源/目标版本、APK长度、APK SHA-256、签名SHA-256和健康超时；生产包名不由客户端传入，由监督器固定为`dev.sewellzhong.r1probe`。
- 申请必须且只能通过`SCM_RIGHTS`携带一个FD；健康帧禁止FD。截断的控制消息、多个FD、未知控制消息、非法布尔值、非零保留位或响应填充均失败关闭；接收FD立即设置`FD_CLOEXEC`，所有拒绝路径关闭已收到FD。
- 候选路径永不进入协议。已认证FD继续经过U2的普通文件、4 KiB～64 MiB、精确长度、SHA-256及不覆盖发布检查，随后才进入U3的独立包身份读取、备份、安装和健康门闩。
- 监听路径必须是绝对且有界的Unix路径；父目录必须是真实目录、由监督器有效UID拥有且不可被group/other写入。已有任何路径时拒绝启动，不自动删除或替换；新socket节点归配置卫星UID所有且固定0600。
- 每次连接通过内核`SO_PEERCRED`取UID，只接受与配置卫星UID精确相等的调用者；root和其他特权UID没有旁路。认证后的收发均限时5秒，避免异常候选无限占住单次服务。
- 一次服务调用执行“accept→UID认证→解码→候选落盘/健康确认→U3编排→响应”。合法请求的操作失败以固定响应返回失败token和当前持久阶段；传输或畸形framing失败直接关闭，不伪报操作成功。
- 同一原生库包含申请、健康与响应framing函数，供后续APK JNI接入复用；当前尚未接入Java服务生命周期。

## 主机故障与边界测试

新增协议测试覆盖申请字段与FD往返、真实候选字节落盘、U3安装编排、四项健康提交、固定响应解析、健康帧无FD、真实文件系统socket的owner/0600与内核peer UID、已有socket不覆盖、可替换父目录拒绝、错误UID准入函数及非法操作ID拒绝。

## 已执行检查

- `bash tools/update/check.sh`：通过；Release构建通过，CTest 4项全部通过。
- `python3 tools/dev/audit-public.py`：481个公开文件，0发现。
- `python3 tools/dev/scan-secrets.py`：0泄漏。
- `bash tools/factory_audio/check.sh`：117项通过，确认更新协议未破坏原厂音频安全与数据链门禁。
- `python3 tools/dev/prepare.py`：失败；当前主机缺固定的`ndk/27.0.12077973`。因此没有运行依赖准备成功的完整`tools/dev/check.sh`，不继承U3或更早Android、HA、恢复测试结果。

## 未完成及下一入口

当前交付的是可编入监督器和客户端的原生协议库，不是常驻root守护进程，也没有Java/JNI APK调用、真实3448 PackageManager后端、root-owned事务/socket目录、init服务或专用Enforcing策略。socket owner和UID主机测试使用当前测试UID，不证明Android应用UID、DAC与SELinux组合可用。

下一步先把候选打开、申请发送、响应处理和四项健康上报接入v117后续APK服务生命周期，并为操作ID、文件关闭、服务重建和失败状态补主机测试。设备侧PackageManager后端、daemon main/init及最小策略必须基于3448实机的固定包路径、命令/Binder返回值和AVC证据实现；不得为方便授予网络、块设备、Loader、分区、擦除、格式化或全局Permissive能力。
