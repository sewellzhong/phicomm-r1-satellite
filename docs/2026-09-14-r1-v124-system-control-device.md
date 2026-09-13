# R1 v124最小系统控制桥实机记录（2026-09-14）

## 结论

首台`r1-sample01`在3448固件和SELinux Enforcing下完成最小系统控制桥部署，闭环了
v122留下的两项真实失败：两组状态灯现由专用代理写入并立即回读，整机重启现由同一代理
执行且在响应返回后真实产生新boot。v124还修复了原包隔离状态瞬时不可读时被持久误判为
不安全的问题。当前设备恢复`listening/audio_opened`，原厂音频、更新监督器和系统控制代理
均运行，未扩大到任意命令、路径或普通APK的宽权限。

这不等于R0通过，也不是最终候选的完整回归。HA页面上的“重启整机”按钮本轮没有另行人工
点击；实机重启使用的是该集成所调用的同一Noise认证`system_management`服务。网络/IP恢复
和72小时稳定性仍按既定顺序留到功能齐备后执行。

## 固定能力与安全边界

- APK JNI只连接固定`/dev/socket/r1_system_control`。请求和响应均为固定8字节
  `SOCK_SEQPACKET`记录，版本、操作、长度、保留位或参数不符即失败关闭。
- 协议只有两项操作：把两个固定3448 LED亮度节点分别设为0～4并返回实际回读；执行无
  原因、无字符串参数的整机重启。协议不能携带命令、shell参数、文件路径或分区目标。
- init创建的socket为UID 10010、模式0600；代理对每条连接再以`SO_PEERCRED`精确核对
  UID 10010，不给root或其他应用隐式旁路。
- 代理运行在专用`r1_system_control`域，只获得固定sysfs读写、`sys_boot`、动态链接、日志和
  已继承socket所需权限；无网络、块设备、包管理、更新或任意文件选择权限。生产状态保持
  Enforcing，没有全局或域级permissive。

公开仓库只包含自有代理、JNI、构建器、init/策略模板和测试；原厂boot、策略二进制及候选
镜像均保留在仓库外。

## Boot构建与写入边界

最终策略每次都从3448原始策略
`96fa3164741296482362fe9e0d126c9f55b8316421ec0cf9e79939b6cf5f269a`
重新构建，同时保留既有原厂音频/更新监督器105条注入规则，再一次性增加系统控制类型和
规则。旧setools补丁扩展为在序列化前一次重建多个新增类型；补丁SHA-256为
`c289bcf5f0011bdbfaa520d813b0103f1d878285f6750e1972a6089321ade055`。

每轮均只操作精确boot分区（LBA 98304、12 MiB）：先核对设备serial、3448/API22、
Enforcing和当前版本，在Loader只有一个设备时双读当前boot并匹配，再固定候选、单次写入，
复位前完整读回匹配。未写system、recovery、Loader、参数/分区表或物理首4 MiB，未执行
擦除、格式化或整盘覆盖。

逐轮结果原样保留：

| 候选boot SHA-256 | 实机结果 |
| --- | --- |
| `c560210652fa203f92ac8f54e350b2b21d8b0c49dfcf422c500e42b34581753f` | init拒绝17字符服务名`r1_system_control` |
| `9cb5021d522a2ef4a6cf44da78368d817775b3d4fc3858367977dfb52ee07493` | 改为`r1_sysctl`；暴露tmpfs关联、null/properties、rootfs链接和system目录访问AVC |
| `00cf279dc152897ef6295a4c8f4589d9b86e7e9c7e87ee17e349f65045884684` | 启动继续推进；动态链接器读取`/system/lib/liblog.so`被拒绝 |
| `1bef87cc5f66924e3bc0cb52566029e17d34cbfd6afefc110f85f23e0930df95` | 动态链接通过；继承socket上的`listen`被拒绝 |
| `223e74516355479b7da1466559defefe1490e28c16d1b18bd199b8c5024ce229` | 代理已运行；固定LED class链接的sysfs遍历被拒绝 |
| `cbe93da0ae1d9ccee3fd56d94ea52626e873003357402eeb2b7315ab552182f1` | 最终通过；代理、灯写后回读及整机重启均工作 |

最终策略SHA-256为
`322d7150d4d9c0ef61dcb5e93abf528c7beaea3479cf317b110df85dec3ed783`；代理为
`ef229f10cefa27aae532a87456ee93ea30350c15a554eea8d0b7d85c0b849cc6`，JNI为
`ea47e02536926219e0c342944b3b128eaecd3da439e6c90d1c0b4a584eb4f01d`。
最终启动后`r1_sysctl`、`r1_factory_audio`和`r1_update`均为running；未出现系统控制域的
未解决功能性AVC。

## APK与实机结果

- v123源码基线`ef996d2`，APK
  `93f8a62929fc6797b780a90726f2dd59777f635fda12ccce472ba69b9ddefb60`；经独立更新监督器
  完成同签名安装和回读。
- 等待HA时灯节点实际回读`1/1`且`indicator_confirmed=true`；监听时为`0/2`。
- 两次自动注入的非闹钟中央键双击分别进入和解除强制软件静音。静音后采集停止、状态为
  muted、灯实际回读`4/0`且确认成功；第二次双击恢复监听。该结果证明项目的软件静音和灯
  状态链，不称为电气断麦，也不要求用户操作实体按键。
- 连续检查时发现原包隔离查询的瞬时`unknown`会把
  `audio_blocked=factory_audio_not_isolated`错误持久化。v124源码`cc7afa5`改为只有真实观察到
  `factory_process_running`或`factory_package_startable`才持久封锁；`unknown`仍在当次失败
  关闭，恢复`packages_hidden`后只清理该隔离专用封锁，不会清除`audio_backend_stalled`。
- v124 APK为
  `fae6bae14d5469ac9d5c6d7c9f6c6035fedc777ad68f76dd63c8f93ce9190f79`，签名摘要仍为
  `0be7a3643442658354c185ec53cb50e73bc1516a56f2760ca46f2c932c1d2639`；监督更新后设备
  `base.apk`独立回读匹配。

为避免重新生成HA长期令牌，本轮临时停止HA Core释放设备的单连接，使用内存中的Noise PSK
直连同一认证服务；PSK没有打印或落盘。整机重启响应在动作前返回，操作ID匹配，重启前
uptime为611秒。设备重新上线后uptime约66秒，81秒时回读
`last_operation=reboot_device`、`last_operation_state=completed`且无错误，证明服务响应、
真实新boot和重启后持久确认闭环。随后已恢复HA Core。

最终状态为v124、`listening`、`audio_opened=true`、`audio_blocked=false`、无`last_error`，
原包隔离为`packages_hidden`，软件静音关闭，灯回读`0/2`且确认成功，Noise连接累计2次、
失败0次；Android仍为Enforcing，三个专用代理均运行。

## 验证与剩余项

最终v124当前树已通过`python3 tools/dev/prepare.py`和`bash tools/dev/check.sh`完整统一门禁：
公开扫描553文件/0发现、凭据扫描0泄漏、Android单元测试/lint/hostcheck APK、原生工具、
R0 73项及演练、原厂音频117项、更新监督器CTest 6项及Python门禁、系统控制CTest/boot
构建门禁、HA 102项及HA 2026.8.2容器生命周期均通过。每轮策略修正还分别通过
`bash tools/system_control/check.sh`。这些是主机/构建结果，不替代尚未执行的设备场景。

下一入口是补齐闹钟分页/离线待同步冲突、免打扰时段与降灯，以及其余音频所有者的自动回归；
随后复测v79安卓/iPhone自助配网。实际HA页面按钮可在最终候选统一回归中自动调用并按新boot
回读，不要求用户手工点击。网络/IP恢复和72小时稳定性继续最后执行，R0保持`pending`。
