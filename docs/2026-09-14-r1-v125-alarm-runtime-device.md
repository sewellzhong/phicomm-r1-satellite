# R1 v125闹钟自然触发、DND策略与整机重启实机记录（2026-09-14）

## 结论

首台`r1-sample01`已完成两个无需真人操作的本地闹钟运行时场景。DND手动生效且明确禁止
闹钟时，单次闹钟跨自然分钟边界只增加闹钟控制器和DND的抑制计数，未进入ringing、未启动
本地铃声。随后改为DND允许闹钟，保存另一只单次闹钟并经HA注册的同一Noise系统管理服务
触发真实整机重启；ADB确实离线、Linux boot identity变化，DND策略和闹钟在新boot保留，
可信时间恢复后闹钟自然响铃并由本地管理入口停止。

测试结束后两个随机测试ID均删除，DND七个配置字段恢复原值。抑制、触发和停止诊断计数按
真实历史保留，不伪造回退。设备APK仍为v125，HA集成仍为0.15.0，本轮未修改boot、APK或
HA代码。

## 自动验证边界

提交`c75217f`新增`tools/native/validate-alarm-runtime.py`和4项主机测试。验证器：

- 开始前要求R1为`listening/audio_opened`、原包隔离安全、无错误，可信时间可用且闹钟列表
  为空；有用户闹钟或正在响铃时停止，不修改既有项目。
- 使用R1回报时区计算下一个完整分钟，只创建当天、唯一随机ID的单次测试闹钟；所有写入
  使用精确版本锁。
- 第一轮保存原DND配置，临时设置`manual=true/alarms_allowed=false`，要求到时后
  `suppressed`和`suppressed_alarms`各增加1，同时`ringing_count=0`且
  `ringer_active=false`。
- 第二轮设置`manual=true/alarms_allowed=true`，先回读闹钟已持久化及
  `next_wall_ms`非空，再经唯一`*_system_management` response-only服务提交关联的
  `reboot_device`请求。响应必须先确认`requested`，随后必须观察ADB不可用、新boot、
  `listening/audio_opened`、可信时间、闹钟及DND策略恢复。
- 自然响铃要求`fires`精确增加1、`ringing_count=1`且真实ringer active；停止后要求
  `stops`精确增加1并清除ringing。
- 任何失败路径都尝试恢复R1服务、停止测试铃声、只删除两个精确测试ID并恢复原DND配置。
  令牌继续只从用户指定的0600仓库外文件读取并按用户决定保留；证据不保存令牌、操作ID、
  闹钟名称或boot identity。

## 实机结果

- 初始设备闹钟版本41、0项、0 ringing、历史fires 3/stops 2/suppressed 0；DND版本4、关闭、
  允许闹钟且`suppressed_alarms=0`。
- DND禁止轮自然到时后，两级抑制计数各增加1，未启动铃声；测试项随后删除。
- DND允许轮的闹钟和策略在重启前均持久回读；系统管理请求ID与响应关联且响应状态为
  `requested`。
- 重启期间实际观察ADB不可用，重连后boot identity不同；设备重新进入
  `listening/audio_opened`，原包隔离安全、可信时间恢复，测试闹钟仍存在且DND仍为手动生效、
  允许闹钟。
- 闹钟自然触发后fires增加1，ringing和本地ringer均活动；本地停止后stops增加1且铃声退出。
- 最终设备闹钟版本47、0项、0 ringing、fires 4/stops 3/suppressed 1；DND版本7，七个配置
  字段恢复为关闭/22:00～07:00/允许闹钟，历史`suppressed_alarms=1`保留。
- 最终HA闹钟实体为0项、0 pending、`sync_status=synced`、`last_error=null`；R1为
  `listening`、音频打开、无封锁、原包隔离安全、连接1/失败0，SELinux Enforcing且三个
  专用代理均running。

脱敏结果位于被忽略的
`test-results/2026-09-14-r1-sample01-v125-alarm-runtime/result.json`，SHA-256为
`b11a00532421956399de436f05754c06bc78f4b43b9876e3afc20b455e87c70a`。

## 主机门禁与下一入口

本轮工具加入后完整`prepare.py`/`check.sh`通过：公开扫描561文件/0发现、凭据扫描0、Android
构建、native新增4项及全套、R0、原厂音频、更新监督器、系统控制和HA 103项均通过。

下一入口是媒体、主动播报、计时器和闹钟之间尚未覆盖的音频所有者抢占/恢复矩阵，重点验证
闹钟抢占正在播放的普通媒体、停止闹钟后只恢复系统暂停的媒体，以及用户已停止媒体不复活。
随后进入v79安卓/iPhone自助配网复测。网络/IP恢复与72小时稳定性仍留到最终候选，R0保持
`pending`。
