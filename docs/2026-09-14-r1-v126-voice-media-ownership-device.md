# R1 v126语音与媒体跨重连所有权实机记录（2026-09-14）

## 结论

首台`r1-sample01`已通过固定PCM管理入口完成普通媒体与VOICE所有者的两条自动实机路径。
第一轮在真实HA媒体播放时开始固定PCM语音会话，媒体真实进入paused；取消会话及Native API
连接恢复后，只有系统暂停的媒体恢复playing。第二轮再次暂停媒体后先由HA用户停止媒体，再
取消语音；媒体连续5秒保持idle，没有复活旧播放。

本轮先在v125上复现了连接生命周期缺陷，修复后才升级v126并得到通过结果。测试未发送PCM
帧、未触发STT或保存话术，因此只证明语音会话占用、取消、重连及普通媒体条件恢复，不把它
表述为中文识别或回答内容复验。v102的固定输入长流回答证据保持独立。

## v125失败与修复

新增验证器提交`5195504`。首个媒体URL使用`home-assistant`主机名，R1端未进入播放态，工具
在30秒前置门槛停止；没有启动固定PCM。改用设备可达的`192.168.94.230`后，媒体和语音暂停
均成立，但取消后的Native API连接重建会销毁连接内`NativeMediaController`及
`NativeUrlMediaPlayer`，媒体最终为idle，验证以`voice_cancel_release_not_confirmed`失败。
失败轮没有生成通过证据，历史结果未改写。

修复提交`8880988`将URL播放器和媒体所有权状态提升到`NativeSatelliteService`生命周期：

- Native API连接关闭只解绑sender/subscription并释放连接范围的VOICE、ANNOUNCEMENT所有者；
- 媒体后端、失败/请求计数、嵌套ALARM所有者和`resumePending`跨连接保留；
- 连接关闭后仅在其他所有者为空且策略允许时恢复系统暂停的媒体；
- HA用户pause/stop仍清除`resumePending`，后续所有者释放不得恢复；
- 卫星服务真正销毁时仍关闭媒体后端，不把资源泄漏到服务生命周期之外。

Java定向测试新增连接丢失后的系统恢复和用户停止不恢复两条断言。Python验证器还要求设备
处于监听、原厂隔离安全、无公告/计时器且媒体idle；只控制明确指定的HA媒体实体，失败时
停止测试媒体并尝试取消本轮固定PCM。令牌只从用户要求保留的0600仓库外文件读取。

## v126更新与实机结果

设备候选为`1.26-media-reconnect-ownership`、24,043,286字节，SHA-256为
`cc2bb44e4a6098c24eb67a46ec56b7637085684b608e886f7f8cc2d9aac56cbc`，签名摘要仍为
`0be7a3643442658354c185ec53cb50e73bc1516a56f2760ca46f2c932c1d2639`。一次误将统一门禁留下的
4,137,833字节hostcheck APK提交给监督器，固定包身份校验失败关闭，设备保持v125；该精确
候选随后删除。重新以私有提示资源构建设备包后，通过独立监督器更新到v126，四项健康标记
清空，设备安装包读回哈希与候选一致；未修改boot/system/recovery。

测试媒体为仓库外ffmpeg生成的180秒低音量440 Hz WAV，PCM S16LE、16 kHz、单声道，
5,760,078字节，SHA-256为
`ec93d37b15e5f00f93af173de840a5113f56248c0254cdbaed7f7d47a4056d24`。它经HA
`/local`和真实R1媒体实体播放：

- 第一轮媒体playing，`fixed-pcm-start`后状态为`injecting_fixed_pcm`且媒体paused；取消、
  连接恢复及所有者释放后媒体恢复playing。
- 第二轮语音再次使媒体paused；HA `media_stop`先得到idle，取消语音后连续5秒保持idle。
- 固定PCM runs/cancels各增加2；没有发送PCM frame；媒体failures/rejected增量均为0。
- 最终R1为v126、`listening/audio_opened=true`、`audio_blocked=false`、原包
  `packages_hidden`、连接1/失败0、媒体idle、计时器0项且无`last_error`。

脱敏证据位于被忽略的
`test-results/2026-09-14-r1-sample01-v126-voice-media-ownership/result.json`，SHA-256为
`972df2b2baebd1ce0824a9230f93a4dbe09a0b904c13b4ae66c79023a7cf462b`。本轮两个精确更新
候选、主机/HA临时WAV均已删除；HA `/config/www`目录和用户指定的令牌文件保留。

## 门禁与下一入口

修复树执行统一`prepare.py`及`check.sh`，最终公开扫描568文件/0发现、凭据扫描0，Android构建、
单元测试、lint、native、R0 73项、原厂音频117项、更新监督器、系统控制及HA 103项/容器
生命周期通过。设备候选另以非hostcheck配置重新构建并核对包名、v126、大小、签名和哈希。

下一入口是标准计时器到期与普通媒体的同样两条条件恢复路径，再补主动播报中计时器到期的
嵌套抢占和释放。完成这些自动场景后进入v79安卓/iPhone自助配网复测。网络/IP恢复和72小时
稳定性仍留到最终候选，R0保持`pending`。
