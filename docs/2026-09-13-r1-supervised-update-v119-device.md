# R1 独立监督器 v119 更新与自动回滚实机记录（2026-09-13）

## 范围与结论

首台 `r1-sample01` 已在 3448 / Android 5.1.1 / API 22 / ARMv7 / SELinux
Enforcing 下，通过独立于候选 APK 的 `r1_update` 监督器完成同签名 v118→v119 更新。
监督器先备份并回读旧包，安装后再从 PackageManager 独立回读实际版本、APK SHA-256
和签名；新包四项健康确认完成后清除事务。一次普通整机重启后 v119、原厂音频代理、
Noise 连接和卫星监听均恢复。

成功更新后又使用同签名 v120 探针执行两条自动故障路径：四项健康不完整直至 30 秒窗口
到期，以及 v120 已安装但未确认时整机重启。两次监督器均自动显式降级并独立回读恢复
精确 v119。健康超时和事务中整机重启的自动回滚因此通过；监督器进程单独崩溃及回滚安装
自身失败仍未注入，不能宣称所有失败路径完成。R0 保持 `pending`。

## 候选与设备身份

- 设备 ADB 序列：`CBEAU1116K01314`；代号：`r1-sample01`。
- 固件 fingerprint：
  `Android/rk322x_echo/rk322x_echo:5.1.1/LMY49F/3448:user/release-keys`；
  hardware 为 `rk30board`，全程保持 `Enforcing`。
- v119 候选大小为 23,945,006 字节，SHA-256 为
  `b1368d2bed2c1f0f8f210628ca8c215a955550f274f96f623c8483e50cb2b9c7`；
  单一签名证书 SHA-256 为
  `0be7a3643442658354c185ec53cb50e73bc1516a56f2760ca46f2c932c1d2639`。
- 更新前为 v118 `1.18-update-diagnostic`；更新后 PackageManager 报告 v119
  `1.19-supervised-update`。从 `/data/app/dev.sewellzhong.r1probe-1/base.apk`
  拉回的实际安装包大小、SHA-256 和签名均与候选精确一致。

## boot 与策略变更门槛

为兼容 3448 的包安装读取域，新候选只在已有 U11 ramdisk overlay 内增加固定临时桥目录、
监督器所需的最小 `shell_data_file` 权限和更新后的监督器二进制；私有事务目录继续保持
0700 和专用类型。临时桥固定为
`/data/local/tmp/r1_update_install_v2/candidate.apk`，目录启动后实测为
`0711 root:root u:object_r:shell_data_file:s0`。监督器只在调用固定 PackageManager
入口的子进程中不可逆降至 UID/GID 2000，父监督器保持独立专用域；桥文件仅在调用窗口
开放为 0644，之后无条件删除并对目录 `fsync`。

- ARMv7 监督器 SHA-256：
  `b38dddcb6cbdbf5c6926f6a361fabde2a235523b882575f9c07440db2c2e1c8e`。
- helper SHA-256：
  `2f28f4ef21ebe872357e85a4a892d2297b1000cea64d4d354d0c750ab99c91bd`。
- Enforcing policy SHA-256：
  `fff48ec433aed89c173f08dd96896920cba8d9593e08a4313808e6b55c6752c0`。
- candidate 52 boot 及复位前完整读回 SHA-256：
  `fce6776789944d086421eb72799043649d9ba72c80d1e4a3058e3d5bc3d3837b`。

写入前从 Loader 对当前 boot 的 12 MiB 范围独立读取两次，两份均为 candidate 51
`17557dd509d6c8f94b1b1bcb821413c0c344ba6fc8d2a55b7481815084137271`，
且逐字节相同；随后只执行一次 sector 98304 的 boot 写入，并在复位前完整读回、哈希及
`cmp` 候选。没有写入 system、recovery、Loader、参数/分区表或物理首 4 MiB，没有擦除、
格式化或启用 Permissive。

## 3448 安装兼容路径与结果

真实 `PackageInstaller` session 已创建，但该固件的 `Session.openWrite()` 对监督器域固定抛出
`android.os.TransactionTooLargeException`，提交空 session 后精确返回
`INSTALL_PARSE_FAILED_NOT_APK`。监督器仅在该精确分类下启用有界旧入口；其他安装失败不
触发兼容路径。本轮随后记录：

1. `update_legacy_install_started`；
2. `update_legacy_install_finished`；
3. `update_install_finished`；
4. `update_install_result_accepted`；
5. 独立已安装包身份回读完成。

旧进程在替换中断开响应，监督器记录 `update_protocol_send_failed`，但提交协议本来就不依赖
被替换进程接收最终结果；该日志不覆盖独立安装、身份回读和新包健康确认。新包的
`r1-update-health.xml` 已清为空映射，设备保持 v119，重启后 `/data` 可用空间由更新完成前
约 671 MiB 增至 740 MiB，符合事务归档和应用 inbox 清理结果。应用私有的两份候选副本已
精确删除。

## 重启后最小实机检查

- `init.svc.r1_update=running`、`init.svc.r1_factory_audio=running`；SELinux 为
  `Enforcing`。
- 卫星从短暂 `waiting_ha` 自动恢复为 `listening`；`connections=1`、
  `audio_opened=true`、音频帧非零增长、`factory_isolation=packages_hidden`、
  `failures=0`、`last_error=null`。
- v119 版本、安装路径、APK SHA-256 和单一签名在普通整机重启后保持不变。

## 健康超时自动回滚

故障候选 v120 `1.20-update-timeout-probe` 只改变构建版本，大小 23,945,508 字节，
SHA-256 为
`afa2ed1eedd14be405918e08ad515b369112c8e338b9a4141499bf9ebe02ecda`，
签名与 v119 相同。提交前自动临时取消两个原厂包的隐藏状态并启动其服务，卫星实际回读为
`audio_blocked=true`、`audio_opened=false`、
`factory_isolation=factory_process_running`、`last_error=factory_audio_not_isolated`；
这证明健康失败关闭来自真实隔离状态，而不是伪造健康响应。

v120 安装及身份回读完成后，新包没有发送部分健康。自申请开始的 30 秒窗口到期，监督器
记录 `update_downgrade_started`、`update_legacy_install_finished`、
`update_downgrade_finished`、`update_install_result_accepted`、独立身份回读完成以及
`update_health_timeout`。回滚后 PackageManager 为 v119，实际 `base.apk` SHA-256 精确恢复
为 `b1368d2b…b9c7`，Enforcing 和两个 init 服务保持运行。

原厂包取消隐藏属于测试环境注入，不是监督器事务的一部分，因此回滚不会擅自修改这些包。
测试编排器随后重新隐藏并停止原厂包，以显式管理员 `start --listen` 清除预期的持久音频
熔断，再删除应用 inbox 中的 v120 副本。普通重启后卫星恢复连接 1、音频打开、帧增长、
隔离安全、失败 0 和无错误。

## 未确认事务中整机重启自动回滚

第二轮复用同一 v120 内容但使用新操作 ID 和 180 秒健康窗口，再次建立可回读的真实隔离
失败状态。待 PackageManager 已明确报告 v120 后立即执行普通整机重启，确保包替换已发生而
健康尚未确认。新 boot 中独立监督器依次记录：

1. `update_supervisor_identity_ready`；
2. `update_transaction_recovered`；
3. `update_downgrade_started` 与固定兼容安装；
4. `update_downgrade_finished`、安装结果接受和独立身份回读；
5. `update_rebooted_before_health`。

回滚后实际安装包再次精确恢复为 v119 / `b1368d2b…b9c7`。测试注入清理、明确音频重试及
再一次普通整机重启后，设备为 Enforcing，两个 init 服务运行，原厂包保持隐藏，卫星为
`listening`、连接 1、`audio_opened=true`、音频帧非零、失败 0、`last_error=null`。
两轮应用 inbox 候选均已删除。

## 主机验证与下一入口

定向更新门禁通过 CTest 6/6、更新 Python 38 项和 API 22/armeabi-v7a 监督器/helper 构建。
最终统一 `ANDROID_SDK_ROOT=… bash tools/dev/check.sh` 也已通过：公开扫描 525 文件/0 发现、
凭据扫描 0 泄漏、Android 270 项/lint/hostcheck APK、native 47 项、R0 恢复 73 项及演练、
原厂音频 117 项、更新 CTest 6/6 与 Python 38 项、ARMv7 监督器/helper、HA 102 项及
HA 2026.8.2 容器生命周期均通过。私有生产 HA 路由测试未在本轮运行。

下一入口是补充监督器进程单独崩溃恢复，并用不会损坏当前 v119 基线的可恢复方法证明回滚
安装自身失败时事务保持 `failed`、归档不被误删且下一次启动不误报成功。此后把 v119 作为
统一功能回归候选，执行核心功能自动复核；网络/IP 恢复与 72 小时稳定性仍按现行顺序留到
最终候选。

上述两条下一入口已由[剩余失败边界实机记录](2026-09-13-r1-update-remaining-failures-device.md)
完成并取代；本文件前述三条路径及当时结论原样保留。
