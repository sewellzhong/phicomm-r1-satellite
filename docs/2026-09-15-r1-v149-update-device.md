# R1 v149→v150→v149签名更新与回滚实机记录

日期：2026-09-15

设备：`r1-sample01`，3448 / API 22 / SELinux Enforcing。

## 结果

首台设备在不修改boot、system、recovery、Loader或分区表的前提下，完成一次受控的
同签名APK升级和显式降级：

- 变更前：v149，APK SHA-256
  `10b63f9492202221eb348d7373da67b7e0b367ca954abd0efddc421dbc4811ac`。
- 升级候选：v150，仅版本名/版本号用于烟测，APK SHA-256
  `ee40fc55ff0055bc960558808d8a3c36e1d6371fd5dca19824d665b5bd84ffc1`。
- 升级返回：固定API22 `app_process` PackageManager argv，退出码0，输出`Success`；
  独立回读为v150，哈希与候选一致。
- 显式回滚返回：固定`install -r -d` argv，退出码0，输出`Success`；独立回读恢复
  v149，哈希与变更前一致。
- 执行报告保存在本地 `test-results/2026-09-15-r1-sample01-v149-update/plan/`，状态
  `pass_backend_evidence_only`，`rollback_restored=true`；证据目录索引见
  [`test-results/README.md`](../test-results/README.md)。

候选、回退包和设备实时身份在推送前均重新计算；升级、回滚和最终回读均绑定同一
计划ID。计划外输出路径和首次缺少PATH中的`aapt`均在设备副作用前失败关闭，未产生
安装动作。升级器完成后暂存文件已清理，设备端未留下候选或回退临时包。

## 最终健康

回滚后设备包版本为v149，APK哈希连续两次回读一致；签名保持既有摘要
`0be7a3643442658354c185ec53cb50e73bc1516a56f2760ca46f2c932c1d2639`。设备最终为
`listening`、Noise连接1、音频打开、`last_error=null`、失败计数0，音量保持4%；
生产播放中取消仍关闭，未因更新测试改变对话行为。

这证明的是3448固定argv包管理后端的真实升级/降级证据，不等同于已经完成公网OTA；
监督器健康门闩和此前已记录的失败注入仍按原记录保留。R0继续为`pending`。
