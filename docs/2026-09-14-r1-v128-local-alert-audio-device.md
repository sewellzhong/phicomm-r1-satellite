# R1 v128本地闹钟音乐与自定义计时提示实机记录（2026-09-14）

## 结论

首台`r1-sample01`已在3448 / API 22 / SELinux Enforcing下完成本地提醒音频核心链路验证。
HA 2026.8.2集成升级到0.16.1，两段不同的低音量合成WAV经认证Noise分块上传；R1实算并
回报的大小、SHA-256均与HA源文件一致。计时器自然到时和本地闹钟自然到时均实际进入
`local_audio`输出，降级增量为0、输出错误为空，停止成功。服务重启后内容和计时器绑定保持。

本轮证明核心功能可运行，不替代整机重启、断网、DND、媒体所有权、损坏降级和72小时门禁。
R0继续为`pending`。

## 首次v127失败与修复

源码基础`d3c4fc9`的v127和HA0.16先通过监督更新及配置检查，但首次真实上传在首个24 KiB
块超时。设备Native API加密帧上限是8192字节，连接因`frame_too_large`失败关闭；HA随后
执行abort，R1回读缓存项为0、无活动上传。该失败保留，不改写为通过。

修复提交`94d07c95d67ab7e6b23ca89f50a5867e62f218a6`把原始块降至4 KiB、HA和设备请求上限
降至7 KiB，并将版本提升为v128 / HA0.16.1。修复树完整`tools/dev/check.sh`通过：公开扫描
585文件/0发现、凭据扫描0、Android 282项/构建/Lint、native、R0 73项、原厂音频117项、
更新、系统控制及HA107项/容器生命周期均通过。

## 更新与部署证据

- v127监督更新前，现装v126被拉回两次，两份SHA-256一致为
  `cc2bb44e4a6098c24eb67a46ec56b7637085684b608e886f7f8cc2d9aac56cbc`；
- v127实际安装包为`2d6ebafc792554b6a1cf8548074bd4c06c2fbdffbe5de3cce3246aadc6c97a8f`，
  仅作为失败诊断版本；
- v128候选和安装包回读均为
  `796cbb10db66e06ac3c10997ed3eba565be9d12f07a4bd27b863a4ac29ee0ce7`，签名摘要保持
  `0be7a3643442658354c185ec53cb50e73bc1516a56f2760ca46f2c932c1d2639`；
- 两轮均由独立监督器安装，v128四项健康标记最终清为空映射；没有修改boot、system、
  recovery、Loader或分区表；
- HA0.16.1部署前逐文件核对0.16，`ha core check`通过，回退目录为
  `/config/r1_component_backups/20260914T130058Z-b2f33b53`，重启后服务重新注册。

## 核心实机结果

- 闹钟音乐测试WAV：192078字节，SHA-256
  `9f469ba14645cc4d56dea0ad008f4146d86a8ce6f9aa6f5fde03801febf43917`；
- 自定义计时提示WAV：128078字节，SHA-256
  `6fced0a3818a53e937d65ea265f18cf5f83e4cb4c3734eb28a2854771e02a688`；
- 两者均为PCM S16LE、16 kHz、单声道，分别为6秒音阶和4秒间歇提示音，不含语音或家庭录音；
- 上传后设备回读两项的ID、大小和哈希完全匹配，`upload_active=false`；计时器绑定回读为
  `timer_custom_test`；
- 10秒计时器自然到时：`alarm_mode=local_audio`、`custom_audio_fallbacks`增量0、
  `alarm_failure=null`，本地停止通过；
- 单次闹钟自然到时：`ringer_active=true`持续复核2秒，共享输出`alarm_mode=local_audio`、
  降级增量0、`ringer_failure=null`，停止与删除通过；
- 受关联ID约束的服务重启后，两项缓存、哈希及计时器绑定保持，监听与原厂音频恢复；
- 计时提示仍被绑定时删除返回失败；解绑后两项均可删除。

最终HA/R1均为0缓存、0计时器、0闹钟、0 pending，测试WAV已从HA及主机删除；设备保持
v128、`listening/audio_opened=true`、`audio_blocked=false`、原包隔离、连接1、失败0且无
`last_error`。应用inbox中的本轮两份已安装候选仍保留为0600私有文件，未把删除失败误报为
清理完成，后续随现有更新inbox清理机制统一处理。

脱敏结构化证据位于被忽略的
`test-results/2026-09-14-r1-sample01-v128-local-alert-audio/result.json`，SHA-256为
`f932228b67496886c8efaabbf1b52ee0a721ba18e7a6ed07f3dc00f1fc87e985`。

## 后续入口

按现行顺序，在最终候选回归中补：整机重启后缓存、HA/网络离线到时、DND闹钟例外、与媒体
抢占/条件恢复、内容缺失或损坏的内置声兜底。之后才进入网络/IP恢复及72小时稳定性门禁。
