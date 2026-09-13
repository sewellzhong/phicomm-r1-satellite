# R1 v119～v122核心功能自动实机回归（2026-09-13）

## 结论

首台`r1-sample01`以固定合成音、真实HA 2026.8.2 REST/Noise链路、ADB事件注入和状态回读
完成第一组核心回归。v119上的主动播报双段与本地计时器通过；媒体404暴露Android 5.1
`MediaPlayer.prepareAsync()`可长期不回调，v121加入15秒单调准备截止并在首台证明释放和
`media_prepare_timeout`。媒体播放/暂停/继续/停止/音量、失败URL及公告抢占恢复通过，免打扰
对普通公告的本地抑制与策略恢复通过。

真实HA原部署实际为`r1_input_guard` 0.6.2而不是冻结记录中的0.14.0，缺少闹钟、免打扰和
系统sensor。旧目录经逐文件哈希固定后备份到
`/config/r1_component_backups/20260913T151049Z-2e4e22f8`；0.14.0逐文件校验、`ha core check`
和重启通过，新实体及Noise状态同步恢复。该偏差不再按旧冻结记录视为已部署。

设备Android系统时间仍停在2018年。v122通过固定ESPHome 2026.8.0生成协议在Noise鉴权后
发送`GetTimeRequest`，接收HA UTC秒并以`CLOCK_BOOTTIME`同源的单调时间推进，不修改系统
时钟。异常/过期时间失败关闭；服务进程仍存活时，HA断连后本地时间继续推进，整机重启且
尚未重连HA时不伪造可信时间。首台已观察`clock_trusted false→true`和
`clock_pending true→false`。

## 受测版本与结果

- v121源码`147d476d6e977dc5a77157afaacc4f176c3677f9`，APK
  `451914c53cf1086bf2a009630813ebe1a829aee1f2f8bf2be1c00c7086b1b37f`；同签名监督更新及
  独立安装包回读通过。验证器活动态修正为`fa36f0bfbcb57aebd02657d93b0b79063a766f30`。
- v122源码`0a00900d14796fa19b4d2d124de0cb48a2580486`，APK
  `18fb607908ad8667a9e2fcf740f3c2f1201aa5227c248f20c159db642c2fa627`，签名仍为
  `0be7a3643442658354c185ec53cb50e73bc1516a56f2760ca46f2c932c1d2639`；监督更新、四项健康、
  实际版本/哈希回读通过。
- 主动播报：两段均开始/完成，0失败，播放时钟满足首次写入≤排空≤释放。
- 计时器：真实中文HA入口产生started/finished，本地响铃及停止通过。
- 媒体与免打扰：完整生命周期、15秒失败关闭、公告抢占恢复、免打扰抑制及原策略恢复通过。
- 闹钟：HA创建/删除、本地到时、中央键单击停止、双击稍后提醒且不先停止通过；停止HA Core
  后R1在`waiting_ha`状态仍本地响铃，HA恢复并同步后删除通过。首次恢复后过早删除未生效，
  保留为重连管理同步竞态，第二次在`synced`回读后成功。
- 设备管理：中文入口改名、分配已有Area、稳定设备ID和写后回读通过；Area可由语音清除，
  名称没有语音清除语义，本轮用认证设备注册表API恢复原`null`值。
- 强制软件静音：本地双击进入`authenticated_no_microphone`、停止采集、HA只读不可解除，第二次
  本地双击恢复监听通过。真实灯节点仍为`privacy_led_not_confirmed`，不得标记灯效通过。
- 系统管理：服务重启的新实例确认通过；整机重启明确失败为
  `system_reboot_permission_denied`，设备未重启且监听保持正常。

完整`prepare.py`与`check.sh`通过：公开扫描0发现、凭据扫描0、Android测试/lint/hostcheck、
native、R0、原厂音频、更新监督器及HA 102项均通过。脱敏实机材料位于被忽略的
`test-results/2026-09-13-r1-sample01-v119-core-regression/`、
`test-results/2026-09-13-r1-sample01-v121-media-timeout/`和
`test-results/2026-09-13-r1-sample01-v122-clock/`；不保存令牌、媒体URL或对话正文。

## 下一入口

先实现仅允许卫星UID、固定操作、专用Enforcing策略和真实回读的最小特权桥，分别解决整机
重启和两组LED节点；不得给普通APK宽泛sysfs或任意命令权限。随后补齐闹钟分页/离线待同步
冲突、免打扰时段、重启持久化和其余音频所有者的自动场景，再复测v79安卓/iPhone自助配网。
最终网络/IP恢复及72小时稳定性顺序不变。R0仍为`pending`。
