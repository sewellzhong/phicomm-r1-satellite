# R1 v119监督器剩余失败边界实机记录（2026-09-13）

## 结论

首台`r1-sample01`在3448/API22/ARMv7/SELinux Enforcing下补齐两条剩余门槛：

- 事务持久进入`installing`后，独立辅助器对生产监督器执行一次`SIGKILL`。监督器PID
  `874→1419`，新进程记录`update_transaction_recovered`，没有重试候选安装；实际包保持
  v119，SHA-256仍为`b1368d2b…b9c7`。
- v120已安装且四项健康不完整时，临时辅助器把固定旧安装桥收紧为`0700 root:root`。
  健康超时回滚及随后第一次监督器重启均真实得到`update_package_rollback_failed`；事务
  保持`failed`、实际包保持v120，没有清理事务或误报成功。恢复桥为`0711 root:root`后，
  下一监督器进程使用保留的旧包归档真实降级并独立回读精确v119。

因此成功更新、健康超时、未确认整机重启、监督器单独崩溃、回滚安装失败五条路径均已有
首台证据。R0仍为`pending`，该结论不覆盖网络/IP恢复、72小时稳定性或其他组件更新。

## 故障辅助边界与失败诊断

公开仓库新增的`r1-update-fault-helper`只构建为验证件，没有socket、网络或任意命令入口；
两个操作ID在临时boot的init参数中固定。生产`r1-update-supervisor`与helper分别保持
`b38dddcb…e1c8e`和`2f28f4ef…c91bd`，生产SELinux policy未改动。临时boot只增加自有
辅助器、init服务和file_context；每轮均执行当前boot双读、单写和复位前完整读回。

第一次回滚失败编排已真实产生`update_package_rollback_failed`，但辅助器因旧内核下
`kill(pid,0)`不能可靠判断同域进程存活而过早恢复桥；监督器随后真实恢复v119。该轮原样
保留为诊断，不计通过。修正版改为观察新PID后保持有界阻断并再次读取持久`phase=failed`。
最终有效轮记录：

1. 操作`4e38c686dc215a3732e057e0f581d527`依次观察阶段`3→4→5→6`；
2. 原监督器PID 875回滚失败后被辅助器终止；
3. 新PID 1935在桥仍受阻时再次回滚失败，证明重启未清事务、未误报成功；
4. PID 2024在桥恢复后完成`update_legacy_install_finished`、
   `update_downgrade_finished`、身份回读和`update_transaction_recovered`；
5. PackageManager最终为v119，旧包能完成精确身份回读，证明事务归档未在失败状态删除。

测试结束后重新隐藏并停止两个原厂包，明确恢复卫星监听。临时辅助boot写回前双读均为
`16da3590…3504`；生产candidate52只写一次，复位前完整读回与候选均为
`fce67767…3837b`。普通启动后`r1_update`和原厂音频代理运行，临时服务不存在，卫星为
`listening`、`audio_opened=true`、Noise连接1、隔离安全且无当前错误。

## v119冻结与回归入口

设备实际安装包再次拉回，SHA-256为`b1368d2b…b9c7`，单一签名摘要为
`0be7a364…d2639`；生产boot读回为`fce67767…3837b`。源码固定为`e670f86`，HA Core固定
2026.8.2，`r1_input_guard`为0.14.0。本地0600冻结清单位于
`test-results/2026-09-13-r1-sample01-v119-core-regression/freeze.json`。

统一核心回归已完成设备、版本、哈希、签名、服务和监听前置门禁。当前进程环境没有
`R1_HA_TOKEN`，因此第一个v103真实HA主动播报场景尚未发起；没有跳过到后续功能，也没有
把主机模拟记为实机通过。下一入口是在运行环境注入短期HA令牌，并提供现有固定实体ID和
合成媒体URL，按v103→v119顺序继续自动回归。
