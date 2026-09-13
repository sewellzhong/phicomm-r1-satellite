# R1 v125免打扰时段、降灯与服务重启实机记录（2026-09-14）

## 结论

首台`r1-sample01`已用自动协议/状态回读完成免打扰剩余的时段核心场景。v125通过只对
shell授权本地管理socket开放的版本锁`dnd-set`设置测试策略；验证器自动保存原策略，构造
覆盖当前时刻的跨午夜区间，确认R1本地判断`source=schedule`，并通过v124最小系统控制桥
观察两组真实灯节点从普通监听`0/2`降为`0/1`。卫星服务停止并重新建立HA/Noise连接后，
策略版本、时段活动状态和实际`0/1`回读均保持；最后按最新版本精确恢复原策略。

该结果证明时段、跨午夜、本地执行、服务重启持久化和普通监听态降灯，不扩大为所有DND
边界均已通过。闹钟例外/屏蔽、时段自然起止边界、整机重启保持及其他灯状态仍可在最终
候选统一回归中复核。没有要求用户说话、按键或判断灯光听感。

## 实现与安全边界

- 源码提交：`d04ff48`；APK版本125，版本名`1.25-dnd-schedule-validation`。
- `dnd-set`只存在于ADB shell可达、按peer UID限制的`r1-native-control`本地管理socket；
  不新增公网监听、HA远程解静音入口或凭据读取面。
- 所有字段由既有`NativeDndController.configure()`校验并原子持久化；验证器传入精确
  `expected_version`，同起止时刻、越界值和版本冲突继续失败关闭。
- `tools/native/validate-dnd-schedule.py`要求设备处于监听、未静音、可信民用时间状态；任何
  中途失败都在`finally`中读取最新版本并恢复测试前的手动/时段/闹钟例外配置。证据不保存
  Noise PSK、HA令牌或其他凭据。

## 候选更新

v125设备候选大小24,042,810字节，SHA-256为
`d85175740da67c5262f2ddc2c1f24ec03d0c29365fe576d262e3bd92afeca903`，单一签名摘要仍为
`0be7a3643442658354c185ec53cb50e73bc1516a56f2760ca46f2c932c1d2639`。更新前只读回读为
v124、3448/API22/Enforcing、`listening/audio_opened`、原包`packages_hidden`且三个专用
代理均运行。

候选以固定操作ID提交给已验收的独立更新监督器；新进程四项健康完成后
`r1-update-health.xml`为空映射。PackageManager回读v125，实际安装路径
`/data/app/dev.sewellzhong.r1probe-2/base.apk`的SHA-256与候选完全一致。应用inbox中的本轮
候选已精确删除；未删除其他历史文件。更新未修改boot/system/recovery或SELinux策略。

## 自动实机结果

测试前DND版本2，`manual=false`、`schedule_enabled=false`、22:00～07:00、允许闹钟，
可信时区为`Asia/Shanghai`。验证器按当时本地时间构造23:55～00:48的跨午夜活动区间：

- 写入后`active=true`、`source=schedule`、`dim_light_requested=true`；
- 普通监听态灯写后回读为`led0=0`、`led1=1`且`confirmed=true`；
- 停止并重启卫星服务、等待HA/Noise和可信时钟恢复后，DND仍为同一版本、同一
  `source=schedule`，灯仍为`0/1`且确认；
- 恢复后策略回到测试前七个配置字段，版本按两次受控写入递增到4，DND不活动，灯恢复
  普通监听`0/2`。

最终设备为v125、`listening`、`audio_opened=true`、`audio_blocked=false`、
`factory_isolation=packages_hidden`、`last_error=null`、连接1次/失败0次；三个专用代理均
running且SELinux为Enforcing。脱敏结果位于被忽略的
`test-results/2026-09-14-r1-sample01-v125-dnd-schedule/result.json`，SHA-256为
`9ec6f05943d183e6d58d13f9c124ba33b8fcfe3e8e617fddd74e95b431427598`。

## 主机门禁与下一入口

v125当前树完成`prepare.py`与`check.sh`：公开扫描555文件/0发现、凭据扫描0、Android
单元测试/lint/hostcheck APK、native工具（含新增DND用例）、R0 73项及演练、原厂音频
117项、更新监督器、系统控制、HA 102项及HA 2026.8.2容器生命周期通过。设备候选另在
无hostcheck标记模式下clean构建并独立核对版本、API、哈希和签名。

下一入口是闹钟超过4项的真实Noise分页、HA离线待同步与远端冲突锁定，以及剩余音频所有者
抢占/恢复自动场景；随后复测v79安卓/iPhone自助配网。网络/IP恢复与72小时稳定性继续留到
最终候选，R0保持`pending`。
