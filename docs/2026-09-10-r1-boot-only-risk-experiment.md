# r1-sample01 boot-only 高风险原厂音频实验（2026-09-10）

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
- boot构建器解析并重建newc+gzip ramdisk，更新Android boot header的ramdisk长度和SHA-1 ID，
  并复核kernel、second、地址、16 KiB页大小和12 MiB分区长度不变。

私有v2候选从原boot A/B分别独立构建且逐字节一致。初次诊断固定按静态契约以2通道读取、
选择通道0输出；这只是验证假设，不构成运行时通道、AEC或DSP证明。

主机统一检查通过Android 170项、lint、native 32项、恢复73项及演练、原厂音频47项、
HA 44项、API22 ARMv7构建、公开审计和凭据扫描。hostcheck APK SHA-256为
`661ccc32b74b62b26cb2263fd9f93687e3a365ddaf0c3f941022979d8ecb1348`，ARMv7代理为
`263c463c86ff92e122dfd4031de9cc7c0289f89d0d560a904e53236a41313780`，专用policy v2为
`339867203ffeec71f4c99674fdd124793892f9007d76a330a9549d9dbc4a234c`，boot v2为
`aaa5b96686a89bd025b752ce6be1e038565c0ec2d6457707576ca419c5f3131c`。

## 写入与验收

私有写入器固定ADB序列、完整fingerprint、原/候选/tool/risk哈希，以及Loader image LBA
98304和24576扇区。现场顺序为Android身份确认、进入2.01 Loader、原boot双读、单次写入、
复位前读回、重启、Android/ADB/Enforcing检查。任一步不匹配即停止；写入后启动失败没有
已验证恢复承诺。

启动通过后才触发最长20秒诊断采集，检查非零PCM、帧连续性、DOA字段和正确释放。之后再
比较四麦响应、播放参考、AEC消除量和DSP质量。在实机证据齐全前生产采集继续失败关闭。
