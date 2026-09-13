# R1 v125闹钟分页、离线待同步与冲突实机记录（2026-09-14）

## 结论

首台`r1-sample01`和真实HA 2026.8.2已完成闹钟同步的三项剩余核心回归。验证器经HA实体
服务创建5个远期禁用测试闹钟，再调用实际ESPHome response-only服务，以同一版本取得
`page_offset=[0,4]`的两页Noise响应；HA实体同时发布完整5项列表。

R1卫星服务禁用而HA Core保持在线时，HA修改明确进入`offline→pending`，错误为
`not_delivered`，没有反馈设备已收到。随后通过仅shell可达的本地管理socket修改同一测试
闹钟，恢复R1连接后HA进入`conflict/remote_changed`，pending项被锁定且R1本地修改未被
覆盖。丢弃冲突后HA重新同步，五个测试ID全部删除，HA和R1均恢复测试前零闹钟基线。

本轮没有改Android APK或boot，设备仍为v125。执行中发现并修复了HA离线时隐藏同步状态的
真实缺陷，因此HA集成从0.14.0升级为0.15.0。

## 自动验证器与安全边界

提交`d5c68a8`新增`tools/native/validate-alarm-sync.py`及主机测试；提交`c21d2b1`按用户决定
把令牌策略调整为严格只读保留。工具要求令牌文件是当前用户拥有、0600、普通非符号链接、
单行且不超过4 KiB；令牌不进入argv、输出、证据或仓库。当前令牌文件按用户要求保留供
后续开发验证，模式0600；`/tmp`仍可能被操作系统重启或清理机制移除。

验证器的其他边界：

- 从HA状态和服务列表唯一识别闹钟实体及`*_alarm_sync`，歧义时停止；不按显示名称猜测。
- 开始前要求R1监听、音频未封锁、没有响铃、HA无pending且设备/HA基线逐字段一致；只有
  剩余容量至少5项时继续。
- 测试ID使用本轮随机前缀；五项均为2099-12-31、默认铃声/音量且禁用，不会在测试期间
  响铃。失败恢复只丢弃或删除本轮五个精确ID。
- 分页响应必须关联请求ID、每页最多4项、偏移连续、版本固定、完成标志及总数一致；组合后
  必须与HA完整实体列表逐项一致。
- 离线测试只停R1卫星服务，不停止HA Core，不改变Wi-Fi或IP。恢复必须重新达到
  `listening/audio_opened`、原包隔离安全且无错误。
- 证据只保存计数、页偏移、同步状态和恢复结论，不保存闹钟名称、令牌或HA响应正文。

## 实机发现与HA修复

第一次使用错误的8123端口在首次HA请求前失败，没有设备或HA副作用；只读核对确认当前HA
实际监听端口为80。改用正确端口后，初次自动轮次在离线状态回读停止：HA的
`R1Alarms.available`仅在`synced`时为真，实体变为`unavailable`后Home Assistant移除了
`sync_status`、`last_error`、`pending_changes`和最后确认列表。这使已有的离线/冲突状态机
无法向用户或自动化展示，不符合现行需求。

提交`aef88f9`将可用性改为“存在最后确认的`alarm_state`”：已有基线时继续展示
offline/pending/conflict及最后确认列表；从未成功同步、没有可信基线时仍为unavailable。
HA定向测试新增离线、pending、conflict和无基线四个分支，集成版本提升为0.15.0。

部署前，HA上的0.14.0目录已复制到
`/config/r1_component_backups/20260914-alarm-visible-aef88f9/`，逐文件清单SHA-256为
`dd8e05b5fa90a89919d70e59be9e4d51a6bc397a0af84760c76a1b419ff118c1`。只替换自有
`manifest.json`和`sensor.py`，远端哈希分别为
`2efa4752665dda76d1dc0eedc647fd592c618956ad3efb9a434277d2d81195d8`和
`f393445701bc3b9f81869fc24c875c322414ea629416b48beeb199a97e0e1e4c`；`ha core check`和
重启成功，0.15.0加载且R1恢复同步。

## 最终实机结果

- 测试前HA/R1闹钟数均为0、无pending、同步状态`synced`。
- 5项写入后HA完整列表为5；真实Noise页偏移为`[0,4]`，固定版本35，两页组合与HA列表
  一致。
- 断开R1后HA显示`offline`；离线启用请求进入`pending/not_delivered`，期望项未阻塞。
- R1本地改名并改时后恢复连接，HA显示`conflict/remote_changed`、pending项
  `blocked=true`；HA回读的远端项目与R1本地修改一致，未自动重写。
- 丢弃pending并刷新后恢复`synced`；删除测试项后HA为0项、pending为0、`last_error=null`，
  R1为0项、无响铃、无`r1-validation-*`残留，最终设备闹钟版本41。
- 最终R1为`listening`、`audio_opened=true`、`audio_blocked=false`、
  `factory_isolation=packages_hidden`、`last_error=null`、连接1次/失败0次。

脱敏证据位于被忽略的
`test-results/2026-09-14-r1-sample01-v126-alarm-sync/result.json`，SHA-256为
`0ac6ad084987d60eddce23c572ac2e9d41b73fb0ed24c110c746bf2ce3ee32ab`。目录名沿用计划中的
“v126回归批次”标识，不表示设备APK已升级；受测APK仍是v125
`d85175740da67c5262f2ddc2c1f24ec03d0c29365fe576d262e3bd92afeca903`。

## 主机门禁与下一入口

验证器加入后完整`prepare.py`/`check.sh`通过：公开扫描558文件/0发现、凭据扫描0、Android
构建、native 57项、R0 73项、原厂音频117项、更新监督器41项、系统控制及HA 102项通过。
离线可见性修复后再次完整通过，HA增至103项；最终公开审计仍为0发现。

下一入口是其余音频所有者的自动抢占/恢复场景，以及闹钟自然触发、整机重启和DND允许/
屏蔽边界；随后复测v79安卓/iPhone自助配网。网络/IP恢复和72小时稳定性继续留到最终候选，
R0保持`pending`。
