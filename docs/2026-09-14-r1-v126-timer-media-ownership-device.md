# R1 v126计时器与媒体所有权实机记录（2026-09-14）

## 结论

首台`r1-sample01`已通过标准HA中文计时器与真实URL媒体的两条条件恢复路径。第一轮媒体
播放中计时器自然到期，媒体进入paused；停止计时器后，只有系统暂停的媒体恢复playing。
第二轮计时器再次自然到期并暂停媒体，随后由HA用户主动停止媒体；停止计时器后媒体连续
5秒保持idle，没有复活旧播放。

本轮验证器源码为`43b4ac1`，设备保持v126，未安装APK、未修改boot/system/recovery。
设备为serial `CBEAU1116K01314`、3448/API 22、Enforcing；APK版本126，既有实机哈希仍为
`cc2bb44e4a6098c24eb67a46ec56b7637085684b608e886f7f8cc2d9aac56cbc`。

## 前置与结果

统一`prepare.py`和`check.sh`通过：公开扫描577文件/0发现、凭据扫描0，Android构建/单测/
lint、native 72项、R0 73项、原厂音频117项、更新监督器、系统控制、HA 103项及容器生命
周期通过。首次按旧直连端口8123探测时连接被拒绝；只读网络状态确认Noise对端仍为
`192.168.94.230`，随后核验HA实际反向代理入口并通过认证API，不把端口变化记成设备通过或
网络恢复结论。

测试媒体是临时生成的360秒低音量440 Hz WAV，PCM S16LE、16 kHz、单声道，SHA-256为
`8096c37615b3aac46db1422c6b1cd1da377fbd238e56c253c12f148db693bd5b`。它只在局域网临时
提供，两轮结束后HTTP服务停止，WAV和临时目录精确删除。

- 两轮计时器均由HA中文会话入口创建并自然到期，`started/local_finished/local_stops`各增加2；
- 第一轮媒体paused后停止计时器，媒体恢复playing；
- 第二轮媒体paused后由HA执行用户停止，停止计时器后持续idle；
- 媒体失败和拒绝计数增量均为0；
- 最终0活动/响铃计时器、媒体idle、`listening/audio_opened=true`、原包保持隐藏、Noise连接1。

脱敏结果位于被忽略的
`test-results/2026-09-14-r1-sample01-v126-timer-media-ownership/result.json`，SHA-256为
`3b1adad1545f1b2bcc2e93c5a879418404c9d65ff2622f4a9db99de9568476ba`。结果不保存话术、
媒体URL或凭据；0600短期HA令牌按既有用户决定保留。

## 下一入口

下一项是主动播报过程中计时器到期的嵌套抢占、停止和所有者释放，并验证异常或用户停止
不会复活已经终止的媒体。该项通过后进入当前候选上的v79安卓/iPhone自助配网复测。
网络/IP恢复和72小时稳定性仍留到最终候选，R0保持`pending`。
