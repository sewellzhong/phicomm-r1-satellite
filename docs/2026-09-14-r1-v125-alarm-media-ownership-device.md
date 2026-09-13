# R1 v125闹钟与媒体所有权实机记录（2026-09-14）

## 结论

首台`r1-sample01`已完成闹钟与普通媒体的两条关键所有权路径。真实HA媒体实体播放6分钟
合成WAV时，第一只本地闹钟自然到时使媒体进入paused并启动本地ringer；停止闹钟后，只有
系统因闹钟暂停的媒体恢复playing。第二只闹钟再次暂停媒体，闹钟期间经HA发送用户
`media_stop`，随后停止闹钟后媒体持续5秒保持idle，没有被中断释放逻辑复活。

两轮均无媒体失败或命令拒绝。测试闹钟、远端及本地合成WAV已清理，HA/R1恢复零闹钟、
零pending、媒体idle和正常监听。设备APK仍为v125，HA集成仍为0.15.0，本轮没有代码缺陷、
APK/boot/HA更新或用户操作。

## 工具与验证边界

提交`8608ff6`新增`tools/native/validate-alarm-media-ownership.py`和3项主机测试。工具：

- 要求R1为`listening/audio_opened`、原包隔离安全、DND不活动、无闹钟/计时器/公告且媒体
  idle；否则在任何写入前停止。
- 只控制命令行明确给出的单一HA媒体实体；媒体URL必须是无用户名、密码、查询参数或片段的
  HTTP(S)地址，URL不进入结果证据。
- 两只当天单次闹钟使用本轮随机ID及精确版本锁，并按R1可信时区安排下一个完整分钟；失败
  恢复只停止当前测试媒体/铃声并删除两个精确ID。
- 每次中断同时要求闹钟fires精确增加、`ringing_count=1`、ringer active和媒体paused。
  第一轮释放后必须恢复playing；第二轮用户停止后必须先确认idle，释放闹钟后连续5秒每次
  回读仍为idle。
- 最终要求媒体失败/拒绝计数不变、闹钟列表为空。令牌从用户要求保留的0600仓库外文件
  读取，不保存到日志、证据或仓库。

## 合成媒体与实机结果

测试媒体由ffmpeg在仓库外生成：PCM S16LE、16 kHz、单声道、360秒、低音量440 Hz，
11,520,078字节，SHA-256为
`8096c37615b3aac46db1422c6b1cd1da377fbd238e56c253c12f148db693bd5b`。HA原先没有
`/config/www`；创建标准静态目录后需重启HA Core才注册`/local`路由。重启后主机名和
`192.168.94.230`均返回HTTP 200及相同长度，R1恢复监听。测试结束后只精确删除
`r1-validation-owner-8608ff6.wav`，`/config/www`目录保留供后续受控测试。

- 初始媒体idle、请求0、失败0、拒绝0；闹钟0项、fires 4、stops 3。
- 第一轮媒体真实playing；闹钟自然到时后媒体paused、ringer active。停止闹钟后媒体恢复
  playing，测试闹钟删除。
- 第二轮闹钟自然到时后媒体再次paused、ringer active；HA用户停止使媒体idle。停止闹钟后
  连续5秒保持idle，未恢复旧媒体。
- 最终媒体请求3、失败0、拒绝0且idle；闹钟版本53、0项、0 ringing、fires 6、stops 5。
  HA闹钟实体为0项、0 pending、`synced`且无错误。
- 最终R1为`listening`、`audio_opened=true`、无音频封锁、原包隔离安全、连接2/失败0、
  DND不活动；令牌文件仍为0600且按用户决定保留。

脱敏结果位于被忽略的
`test-results/2026-09-14-r1-sample01-v125-alarm-media-ownership/result.json`，SHA-256为
`f39d093d45266c87fc5ef01cc2d9c13815dcc68cf585fcae851c45cdf3d717eb`。

## 主机门禁与下一入口

工具加入后完整`prepare.py`/`check.sh`通过：公开扫描564文件/0发现、凭据扫描0、Android
构建、native 64项、R0 73项、原厂音频117项、更新监督器41项、系统控制及HA 103项通过。

下一入口是计时器、主动播报、语音回答与媒体之间尚未覆盖的嵌套所有权和异常释放；完成后
进入v79安卓/iPhone自助配网复测。网络/IP恢复和72小时稳定性继续留到最终候选，R0保持
`pending`。
