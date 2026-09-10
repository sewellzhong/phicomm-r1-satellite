# r1-sample01 boot-only 高风险原厂音频实验（2026-09-10）

> 历史边界说明：本文记录2026-09-10当日仅boot范围的授权与结果。后续开发授权已由
> [2026-09-11免拆分级授权](2026-09-11-r1-no-disassembly-authorization.md)取代；本文中的
> system/recovery禁止项不再是后续开发的现行绝对边界，但实验事实、哈希、风险和R0
> `pending`结论均不改变。

## 决策与边界

用户决定跳过拆机和物理Maskrom，仅对`r1-sample01`接受缺少完整eMMC、独立恢复入口及
受控回刷时修改boot可能永久变砖或丢失数据的风险。R0继续为`pending`。本豁免只允许修改
boot ramdisk；原kernel、RSCE/DTB、second、system、recovery、Loader、分区表和物理首4 MiB
均不得改变，也禁止全局Permissive。

风险接受文件、策略产物、修改镜像和写入执行器保存在仓库外。公开模板不包含签名镜像、
原厂二进制或设备凭据。

## 主机实现

- overlay渲染器在R0 pending时要求外部风险文件精确绑定设备身份、原boot哈希、日期、
  `scope=["boot"]`及四项风险；R0通过时拒绝混用风险文件。
- ARMv7/API22代理支持Android init继承的命名socket，仍以`SO_PEERCRED`限定卫星UID 10010，
  完成初始化后降到audio UID/GID 1041。
- 固定`setools-android`提交和仓库补丁生成策略工具；它只在ADB临时目录重写原策略副本，
  从不加载策略。生成的policy v26新增单一专用domain及最小文件、音频设备、socket和降权权限，
  没有permissive、网络或块设备授权。
- boot构建器解析并重建newc+gzip ramdisk，强制ramdisk四字节对齐，按Rockchip 2014.10
  `SecureNSModeBootImageShaCheck`扩展规则更新SHA-1 ID，并复核kernel、second、地址、
  16 KiB页大小和12 MiB分区长度不变。

初次诊断固定按静态契约以2通道读取、
选择通道0输出；这只是验证假设，不构成运行时通道、AEC或DSP证明。

主机统一检查通过Android 170项、lint、native 32项、恢复73项及演练、原厂音频47项、
HA 44项、API22 ARMv7构建、公开审计和凭据扫描。hostcheck APK SHA-256为
`661ccc32b74b62b26cb2263fd9f93687e3a365ddaf0c3f941022979d8ecb1348`，ARMv7代理为
`263c463c86ff92e122dfd4031de9cc7c0289f89d0d560a904e53236a41313780`，专用policy v2为
`339867203ffeec71f4c99674fdd124793892f9007d76a330a9549d9dbc4a234c`。该旧policy和v2 boot
只保留为失败证据，不再是部署候选。

## 写入与验收

私有写入器固定ADB序列、完整fingerprint、原/候选/tool/risk哈希，以及Loader image LBA
98304和24576扇区。现场顺序为Android身份确认、进入2.01 Loader、原boot双读、单次写入、
复位前读回、重启、Android/ADB/Enforcing检查。任一步不匹配即停止；写入后启动失败没有
已验证恢复承诺。

启动通过后才触发最长20秒诊断采集，检查非零PCM、帧连续性、DOA字段和正确释放。之后再
比较四麦响应、播放参考、AEC消除量和DSP质量。在实机证据齐全前生产采集继续失败关闭。

## 实机执行结果（2026-09-10至2026-09-11）

v2 boot `aaa5b966…f3131c`完成写前双读、写入和复位前读回，但复位后进入原厂recovery。
从recovery回到Loader后再次读回确认boot仍为候选，再写回原boot `f904c534…0ad58`并读回
一致，Android、ADB、原音频链和Enforcing恢复。第二次受控复现同样回落recovery并完成相同
回滚。U-Boot本地二进制及同代公开源码均显示厂商会复算扩展boot SHA；原厂头内SHA按该
算法完全匹配，而v2只计算标准Android字段且新ramdisk长度模4为2，因此v2判定失败。
公开复核固定到Rockchip衍生U-Boot提交
[`8fe3a66f`](https://github.com/geekboxzone/lollipop_u-boot/blob/8fe3a66fcbea782e404c3d011eb383dcecec876f/board/rockchip/common/SecureBoot/SecureVerify.c#L156-L219)。

修复后从原boot A/B独立构建的镜像逐字节一致。v3首次正常进入Android，证明Rockchip SHA
和四字节对齐修复有效。随后只依据每轮实机AVC增量收紧专用Enforcing策略：init socket、
rootfs入口、Android 5动态链接、本地logd和audio设备；没有允许网络、块设备、Permissive或
原厂库尝试的`/system/bin/sh`。最终v13 boot SHA-256为
`09c89752f388bf09797251c819f7629a39f5ac5a24e93df7a5995154e187a787`，每轮均执行当前boot
双读、候选单写、写后读回、正常启动、fingerprint及Enforcing检查。

v80 APK通过相同证书覆盖v79，SHA-256为
`5883f28d2eb11aed9b6b14581b848b2b1fd628a876e4628f813f8a3bc6876b35`。最终10秒诊断调用设备
已有`libuni4michal.so`，原厂日志报告HAL 1.1、MicArray v2.3.0、4麦、2路回声参考和AEC开启；
APK收到500个20 ms单声道帧，序号1至500、0缺口、0代理丢帧、500帧有效DOA。WAV含
160,000个S16LE样本，其中140,383个非零；离线审计pass，报告SHA-256为
`961f6b2f80b41584e0861105433b8bf624c442f343b16af919524f37298d57be`。录音及原厂材料仅在
仓库外私有目录保存。

本结果通过R1权限环境、R2代理运行和R3的“实际PCM传输/DOA字段”子项；不把日志声明等同于
AEC效果证明。四麦独立响应、DOA方向变化、实际通道形状、播放参考覆盖、AEC消除量及DSP
质量仍为未验证，生产`startCapture()`继续失败关闭。R0仍为`pending`，boot回滚成功也不等于
完整eMMC、独立低层入口或完整回刷门槛通过。
