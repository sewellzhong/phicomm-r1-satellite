# r1-sample01 Type-C 与 Maskrom 入口识别（2026-09-09）

## 范围与前置状态

目标仅为识别第三方加装的 Type-C 刷机口，不读取或写入 eMMC。测试前确认
`r1-sample01` 通过网络 ADB 在线，v79 为 `listening`、`audio_opened=true`、
`factory_isolation=packages_hidden`，路由器上的 R1 IPv4/IPv6 WAN 阻断规则仍生效。

最初使用的线材只能为手机充电，Linux USB 层没有收到手机或 R1 的设备事件。更换线材后，
同一 Linux 主机和 USB 端口成功枚举 Huawei Android 手机并建立 ADB，证明主机控制器、
端口和新线的数据通道可用；不记录手机序列号。有效线连接正常运行的 R1 时，两个 Type-C
方向均没有枚举，R1 Gadget 状态保持 `DISCONNECTED`。

## RockUSB 枚举结果

保持有效 A-to-C 数据线及原装电源，通过网络 ADB 发送标准
`adb reboot bootloader`。Linux 实时 udev 监视随后捕获：

- VID:PID `2207:320b`；
- USB ID 数据库描述为 `RK3228/RK3229 in Mask ROM mode`；
- USB 2.0 High Speed，480 Mbps；
- 厂商接口类/子类/协议 `ff/06/05`；
- Bulk OUT `0x02` 与 Bulk IN `0x81`，最大包 512 字节；
- 描述符声明 Bus Powered、最大 400 mA。

本轮没有安装或运行 `rkdeveloptool`/`upgrade_tool`，没有发送 Rockchip 厂商命令，也没有
执行读取、下载 Loader、复位、写入、擦除或刷机。测试结束时设备保持 RockUSB 状态，
因此网络 ADB 离线属于预期状态。

后续固定工具查询补充证明：USB描述符 `bcdUSB=2.01`，Debian `rkdeveloptool list` 从首次
运行起报告 `Loader`。该工具源码以 `bcdUSB` 最低位区分模式，`2.00` 为 Maskrom、`2.01`
为 Loader；因此 `lsusb` 的产品名称只是静态ID数据库标签，不能作为运行模式判定。本次
`adb reboot bootloader` 实际进入的是设备已有 Loader，不是纯 BootROM Maskrom。此前文档
和状态摘要中将其写作“停留在Maskrom”的表述由此更正。

## 固定工具后的只读查询

随后固定并按源码审计 Debian `rkdeveloptool
1.32+pine64git20240226.17823e9-1`。`.deb` SHA-256 为
`18958ac375221ad94ef38a12608f6ec6cd41ff4a81c90e8e899337dd1d9d899d`，解包后可执行文件
SHA-256 为 `f654a31633ddc83411b19405e8c4afb5fb024f1d869f6a86b4ab0a5bae71e7b4`；对应 Debian
源码提交为 `eae601ed47d35fd5965188942077df377c4b02b7`。工具未安装到系统，也未应用其 udev
规则。

新增的 `tools/recovery/r1-rockusb-readonly.py` 只接受上述二进制和固定 `probe` 操作，
不使用 shell，逐条设置 15 秒超时并复核唯一 `2207:320b` 设备及 `bcdUSB` 模式。实机
查询实际发生在已有 Loader 中，结果为：

- `list` 成功，确认一个 Loader 设备；
- `read-chip-info` 成功，原始 16 字节值只保存在被 Git 忽略的本地证据中；
- `read-capability` 返回 `Reading capabilities failed`，设备仍保持 Loader；
- `read-flash-id` 15 秒无响应，探测器按设计终止；
- 因停止条件已触发，没有执行 `read-flash-info` 或分区表读取。

超时后确认没有残留 `rkdeveloptool`/`sudo` 进程，设备仍枚举为 `2207:320b`、
`bcdUSB=2.01` Loader。本次没有
执行 RAM Loader 下载、测试、存储切换、复位、LBA读取、写入或擦除。原始探测记录及工具
日志只保存在 `local-recovery/r1-sample01/2026-09-09-rockusb-probe/`，不进入公开仓库。

## 外部 RAM Loader 准备与停止

根据 Rockchip 官方历史提交，离线重建了 RK322A DDR v1.04、USBPlug和MiniLoader v2.32
组合。下载输入、许可证及 `boot_merger` 均通过固定SHA-256校验，打包后又反向解包验证
entry顺序、有效载荷和零填充；本次本地Loader SHA-256为
`cb7c4953b96c129a86a2df919d62844df8919fdc3c1845eba6f094748ac349f4`。二进制及清单只在
被Git忽略的 `local-recovery/` 保存。

受限执行器要求初始状态必须为 `bcdUSB=2.00` Maskrom，才允许发送唯一一次 RAM `boot`。
实机前置 `list` 明确返回 Loader，执行器以 `expected_maskrom_mode` 停止；证据中只有一条
`list`，没有 `boot`，候选Loader从未发送到R1。随后工具进一步增加sysfs `version` 的前置
判定，使未来在已有Loader状态下会在任何厂商命令之前停止。

## 判定

第三方 Type-C RockUSB 数据通道、已有 Loader 枚举以及 SoC 信息读取已经通过。当前已有
Loader 对能力查询失败，Flash ID 查询会挂起，尚不能证明它可访问 eMMC；外部历史官方
Loader已完成离线准备，但因设备并非Maskrom而按安全设计没有发送。由于本次入口依赖
正常 Android 的 `adb reboot bootloader`，它只证明低层通道可达，尚不能满足 R0 所要求的
“Android 无法启动时仍可进入”门槛。完整 eMMC/区域读取、清单与副本校验、独立物理入口、
受控完整回刷及回刷后功能检查仍全部待完成，R0 状态保持 `pending`。

下一步先审计与 RK3229 老版本协议匹配的主机读取实现，解释当前 Loader 下能力失败和
Flash ID挂起，不重复无界查询。只有实际进入 `bcdUSB=2.00` Maskrom时，才重新评估已经
验证的外部 RAM Loader；不得为了使用候选Loader而复位、破坏或改写现有引导。取得实际
容量和布局后才生成完整读取计划。

## 已有 Loader 的定向存储查询

源码复核发现固定版 `rkdeveloptool` 的 `CMD_TIMEOUT` 为 `0`，其普通USB批量读写会无限
等待。为避免重复Flash ID问题，只读工具新增固定 `loader-storage` 路径：要求
`bcdUSB=2.01`和工具同时报告Loader，仅执行一次FlashInfo；使用root侧8秒终止、2秒强制
清理及主机侧12秒保险。只有FlashInfo返回7000～9000MB，才允许读取两份固定34扇区磁盘头
并枚举分区。该路径不接受操作者提供偏移或长度。

实机 `list` 在0.018秒内成功，`read-flash-info` 随后8秒无任何输出，由 `/usr/bin/timeout`
以退出码124终止。停止后：

- 没有执行两次磁盘头读取或 `list-partitions`，证据目录中没有扇区文件；
- 没有重复FlashInfo，没有调用Flash ID、外部Loader、复位、写入或擦除；
- 没有残留 `rkdeveloptool`、`timeout` 或 `sudo` 进程；
- 设备仍为 `2207:320b`、`bcdUSB=2.01` Loader。

由此可复现地确认：当前通过 Android 进入的已有Loader可枚举并读取SoC信息，但能力、
Flash ID和FlashInfo均不能提供可用的存储访问证据。下一步改为物理断电启动Android后，
读取 `/sys/block/mmcblk0/size`、`/proc/partitions`、by-name映射和启动参数；在取得真实容量及
布局前不继续USB LBA读取。

## 正常 Android 存储真值

物理断电并正常启动后，受限工具
`tools/recovery/r1-adb-storage-inventory.py` 先核对 `r1-sample01` 的
`rk322x_echo`、`rk30board`、固件3448、Android 5.1.1/API22身份，再以普通
`uid=2000(shell)` 执行固定只读查询。实机结果为：

- eMMC `8GTF4R`，15,269,888个512字节扇区，共7,818,182,656字节（约7.28 GiB）；
- sysfs枚举分区1～16，依次为 `uboot`、`trust`、`misc`、`baseparamer`、`resource`、
  `kernel`、`boot`、`recovery`、`backup`、`cache`、`userdata`、`metadata`、`kpanic`、
  `system`、`private`、`user`；
- 分区无重叠或越界，最后的 `user` 恰好结束于整盘末尾；扇区0～16,383的前置8 MiB，
  以及扇区2,711,552～2,719,743的中间4 MiB不属于内核公开的16个分区，完整备份必须按
  整盘覆盖，不能只逐分区读取；
- 实际SELinux状态为Enforcing，普通shell不能读取 `/proc/cmdline`、根目录fstab或遍历
  `/dev/block/platform/.../by-name`。sysfs `PARTNAME` 给出全部名称，`/proc/mounts`另行确认
  system、cache、metadata、userdata和private映射；没有尝试绕过权限。

本地证据 `inventory-v2.json` 仅保存在忽略提交的 `local-recovery`，SHA-256为
`d4aca94a305d683982e19ad0f6f9a62adfaa1811a1730cc0db8b4b0f5213ebad`。本步只证明Android
所见容量和布局，不是完整镜像、独立低层入口或回刷证据；R0继续保持 `pending`。

## 已知布局下的固定头部复读

只读工具新增 `loader-known-header` 路径。它必须先校验上述Android盘点文件的设备ID、
15,269,888扇区容量、512字节扇区和16分区末端边界，随后只允许执行一次 `list`，以及两次
固定的 `read 0 17408`；不接受外部偏移、长度或其他命令。实机两次读取分别约0.021秒，
17,408字节文件SHA-256均为
`c08d07d28418244174f1e6cc58bdaae5160c2e4de34acc191a38a825fd186337`。

结果不是GPT，而是以 `PARM` 开头的Rockchip参数块，包含固件5.0.0、rk3228和完整
`mtdparts`。参数内所有分区起点均比Android sysfs观察值少 `0x2000` 扇区。例如参数中的
`uboot` 为 `0x2000@0x2000`，Android `mmcblk0p1` 实际从 `0x4000` 开始。固定版工具源码将
普通 `read` 原样传入 `RKU_ReadLBA`，但默认子码为 `RWMETHOD_IMAGE`；另有
`RWMETHOD_LBA` 直接模式，设备能力查询又无法返回。因此当前证据只能证明Loader的image
逻辑地址可读，不能证明它覆盖物理eMMC首4 MiB，也不能据此直接确定整盘读取长度。

本轮没有调用FlashInfo、Flash ID、分区枚举、外部Loader、复位、写入或擦除；设备仍为
`bcdUSB=2.01` Loader。下一步需用经源码审计、固定范围且有界超时的直接LBA探针，区分两种
地址语义并证明首4 MiB覆盖，然后才能开始完整镜像读取。

## 地址语义与 Loader image 空间双副本

从固定上游提交 `17823e99898131a234ccdb39ad114dbaeebb7fc3` 构建仅把普通读子码由
`RWMETHOD_IMAGE` 改成 `RWMETHOD_LBA` 的本地审计版工具；公开仓库只保存单行补丁，不保存
第三方二进制。补丁SHA-256为
`cbf3bc5a12e01c27d98000a28ae8ee3ac658b24c4004b936b0270697dc6214d8`，本地二进制SHA-256为
`9f7c6fa417406f9fd0a1f13c95a6ce4b3497ce888832585295b68914705c25e1`。直接模式LBA 0两次结果
与image模式完全相同，仍为同一 `PARM` 块。

随后image和direct模式分别对参数起点 `0x2000` 与Android sysfs起点 `0x4000` 各读取4 KiB、
各复读两次。两种模式在每个地址仍逐字节相同；`0x2000` 以 `LOADER` 开头，`0x4000` 以
`TOS` 开头，严格对应参数表的uboot与trust起点，而非Android sysfs中整体加 `0x2000` 后的
起点。由此确认现有Loader的两种读子码都暴露跳过物理首4 MiB的image地址空间。推导出的
image末端34扇区也复读一致，SHA-256为
`3f1f6f76c52276c865bae097486a0ce164cd509c98c6410b677f516084ad7c3c`。

固定 `loader-image-copy` 路径随后把15,261,696个image扇区（7,813,988,352字节）按64 MiB
分为117块。每块通过独立USB命令读取A/B两遍，立即核对长度和SHA-256并将本地权限设为
`0600`；不接受操作者提供地址或长度。第一次运行在首块后因root属主无法改权限停止，第二次
在首块后因相对路径记录错误停止，两轮失败证据均隔离保留。修正及测试后，第三轮117对块
全部通过。独立离线复核重新读取234个文件、每份7,813,988,352字节，整体SHA-256均为
`728dc9ca55e51f81b17b9f0042ff8d379ba22f9d651b59d43d588fa8fc02f951`。

成功证据仅在忽略提交的
`local-recovery/r1-sample01/2026-09-09-loader-image-copy-v3/`，读取记录SHA-256为
`ba784e8e248f4e9b1e8eb21fcce1ccd7f59aeeb8d7983718c88b28e376436f61`，独立验证记录SHA-256为
`aaee3fcbc0b8cf6d4825e4f3982bb19f68625447590c48ec0376e3cc8608514b`。

这两份数据覆盖Android物理4 MiB之后直到eMMC末尾，但不含物理首4 MiB的IDB/低层引导
范围，不能标为完整eMMC备份。设备保持Loader；没有发送外部Loader、复位、写入或擦除。
下一步是受控验证不依赖Android的物理Maskrom入口，并只读取得首4 MiB；在此之前R0仍为
`pending`，不得Root或改写boot/system。

## 断电恢复与物理入口线索

完成部分镜像后由用户物理断电并正常上电。ADB重新枚举同一序列设备，身份仍为
`rk322x_echo`、`rk30board`、固件3448、Android 5.1.1/API22，实际SELinux为Enforcing；
`2207:320b` 已消失，证明设备正常退出Loader。两份部分镜像的本地验证记录仍为pass。

公开R1专用社区教程给出的硬件Maskrom步骤是：设备及USB先断电，把主板屏蔽罩旁标为
`R211` 的器件端点与金属屏蔽罩地短接，保持短接上电，枚举后松开。公开拆解图确认R1主板
为RK3229和三星8GB eMMC，但没有厂家原理图证明R211网络，也不能排除主板修订差异。因此
该线索目前只用于定位，不直接作为现场短接授权步骤。执行前必须取得 `r1-sample01` 自身
清晰主板照片，核对板号、R211丝印、屏蔽罩和现有Type-C改线；任何位置不一致即停止。

现场目标仅为观察断电上电后是否出现 `2207:320b` 且 `bcdUSB=2.00`。确认Maskrom前不得
发送RAM Loader；确认后也只进入已经实现的单次、哈希锁定 `load-probe`，不运行社区教程
中的写镜像或Root步骤。

## 免拆软件 Maskrom 与首个 RAM Loader 结果

用户决定不拆机，允许一次免拆软件切换。新增
`tools/recovery/r1-rockusb-mode-transition.py`，固定核对ADB序列、完整fingerprint、固件3448
和主机工具哈希，只暴露 `to-maskrom`：执行一次 `adb reboot bootloader`，要求出现
`bcdUSB=2.01` Loader，再通过root侧8秒超时执行一次 `reboot-maskrom`，要求出现
`bcdUSB=2.00` Maskrom。它没有Loader下载、存储读写、擦除或任意命令入口。

实机转换通过：同一USB节点先确认为Loader，`reboot-maskrom` 约0.074秒返回0，随后确认为
Maskrom。转换证据SHA-256为
`ffacedb584a433cad86d0d40bd1e67b1656a5adcd50e466c20bef129d9688165`。该入口仍依赖Android
和已有Loader，不能标为独立低层恢复入口。

RAM Loader执行器同时移除Flash ID查询，所有root调用加入外部超时和强制清理，并要求
`Direct LBA`、`First 4m Access`、`Read LBA` 三项能力全部明确启用才允许首4 MiB读取。
确认Maskrom后，实机唯一一次发送SHA-256
`cb7c4953b96c129a86a2df919d62844df8919fdc3c1845eba6f094748ac349f4` 的历史官方组件组合。
主机命令在1.519秒报告下载成功，但之后10秒内固定观察始终为Maskrom，没有进入Loader，
执行器以 `loader_mode_timeout` 停止。

失败证据SHA-256为
`e8d3e17a4d9e1f571ee87613faa2220952c19aa2fadeceb6ce87c65cc4d8f252`：只含一次RAM `boot`
及模式观察，没有能力、FlashInfo、分区或LBA读取。没有重发同一Loader，没有写入、擦除或
首4 MiB输出；设备当前保持Maskrom，需物理断电恢复。R0继续为 `pending`。下一步只在主机
离线审计候选包构造和其他固定官方DDR/USBPlug组合，不能在没有新证据时重复发送当前候选。

## 2026-09-10 Android恢复与第二候选离线审计

用户物理断电约10秒后正常上电。主机只观察USB枚举：`2207:320b` 消失，约26秒后出现
Android USB `2207:0010`；未建立ADB连接，也未发送RockUSB命令。

第二候选固定到Rockchip官方 `rkbin` 提交
`3e288fe814e059dd06833495f845cab04ac20a5c` 的 `RK322XMINIALL.ini`：DDR v1.10、
USBPlug v2.56、MiniLoader v2.56和 `boot_merger` v1.38，不混用不同发布组合。输入
SHA-256分别为：

- DDR：`aff1848efd3993bcec8b832e1ed45cfc4d57a8be46b420c9940698a564f7af73`；
- USBPlug：`273eb4ec41a6ef6bb2b9bbc3ba3fc3bd21a668fdefeff4e0242fe48ebcde424e`；
- MiniLoader：`456ac5372a9f3e787c7f0dee3a24720247e07d015f46adc36d5922abc8f31213`。

离线打包及解包已证明载荷前缀逐字节一致、额外部分仅为零填充。`boot_merger` 会写入当前
构建时间并据此更新末尾CRC，完整文件哈希不是可复现身份；清零头部7字节构建时间并排除
末尾CRC后的规范化内容SHA-256固定为
`3cae5045061df975488626361944c0147d7715a8d548d32a4a789c90d9287646`。工具记录每次完整哈希，
并以 `rk322x-v1.10.256`、规范化哈希或完整哈希任一命中历史发送证据时拒绝再次执行。

统一主机检查通过Android构建与lint、32项native工具测试、70项恢复测试及演练、24项原厂
音频代理测试和主机/ARMv7 API 22构建、44项HA测试与配置加载。现场私有包位于忽略提交的
`local-recovery/r1-sample01/2026-09-10-ram-loader-v110256/`；本次完整Loader SHA-256为
`1fd286a5af1917b27d969203f91f295830523424bb7e2e075a25f98409497a5b`，清单SHA-256为
`4214f4ab49b4489d2911a8949a8fcfe982dcf652e4b9516d14c418b194165935`。这些私有文件不进入仓库。

该候选已完成主机离线审计。只有三项首4 MiB能力全部明确启用，才允许固定双读。R0保持
`pending`，不得Root或改写任何分区。

## 第二候选单次实机结果

用户确认在设备旁后，受限转换器重新核对ADB序列 `CBEAU1116K01314`、设备身份、固件3448
与主机工具哈希，并再次完成 Android→`2.01 Loader`→`2.00 Maskrom`。转换证据SHA-256为
`a1faa6c0f6fd94a57403a13d29991015c6fe2657c4a5a30b8eb085d98a6ff59b`。

RAM执行器先扫描三份历史证据，确认 `rk322x-v1.10.256` 未发送过，随后只执行一次RAM
`boot`。主机报告下载成功，但之后10秒内32条记录（初始列表、一次boot及30次模式观察）
始终未出现Loader，最终以 `loader_mode_timeout` 停止。证据SHA-256为
`a5e4fdbd94d4652c976ec12a2c1403c67dc6824f3920e9e3ceebb10f18d43ea4`。

本轮没有执行能力、FlashInfo、分区或LBA读取，没有生成首4 MiB文件，也没有写入、擦除或
复位。随后用同一入口进行纯主机防重发检查，工具在USB访问和输出目录创建前返回
`loader_candidate_already_attempted:rk322x-v1.10.256`。用户物理断电后，设备恢复Android
USB `2207:0010`。

第二候选不能取得可执行Loader，且不得重发。物理首4 MiB、完整eMMC、独立低层入口、受控
回刷及回刷后检查仍全部未完成，R0继续为 `pending`。下一步只离线审计其他官方候选或不依赖
Android的低层入口；没有新证据前不再切换Maskrom。

## 第三候选的年代匹配审计

现有Loader image副本内的设备U-Boot标记为
`U-Boot 2014.10-RK322X-06-gdea8273 (Jun 26 2018 - 11:45:15)`。Rockchip官方 `rkbin` 历史中，
紧邻该设备构建时间且同时更换RAM启动阶段471/472载荷的完整配置，是提交
`364df6ae7c88450280293616eecc554404959898`（2018-04-26）的 `RK322XMINIALL.ini`：
DDR v1.07、USBPlug v2.38和MiniLoader v2.38。较新的 `RK322XATMINIALL` 只替换MiniLoader，
不会改变 `rkdeveloptool boot` 实际发送的471/472载荷，因此不列为独立RAM启动候选；
RK322XH配置的芯片标识为RK322H，与当前RK322A/RK3228基线不符，也不使用。

第三候选固定为 `rk322x-v1.07.238`。输入SHA-256为：

- 官方INI：`bdf7b53d73ee4492cd9cc5f6e3c4c50377f7a3a3a6de79c16c2d5a6d916088d6`；
- DDR：`d4b66e9615ba7a4d3e0a5ec7f81687200b9c3dbcf69c70e258b2cf2cfa31c16f`；
- USBPlug：`ffa5e412c97d0a20a3f590b2470f0209ded8fd54da3c1658f918df66cb770681`；
- MiniLoader：`16e43c88d1747b0579a94667d7edb6c28977e96652769d0e8e18c8159b4da630`。

使用已固定的官方 `boot_merger` v1.38打包，`-d 1` 经帮助及源码复核是471阶段的1 ms延时，
对应官方INI的 `Sleep=1`，不是RC4开关；RC4由未改写默认值的 `-r` 控制。解包后三个载荷
前缀逐字节匹配，额外字节全为零。规范化内容SHA-256为
`0f0dfe0653c810474d892fc6cc95788b4007d17dd60581359d15748e34d747e1`。

统一主机检查再次全部通过。现场私有包位于
`local-recovery/r1-sample01/2026-09-10-ram-loader-v107238/`；本次完整Loader SHA-256为
`db5f267d82320bfed6d07e6b11805ac92b864b2c303a5f6ef0f66324f08cd861`，清单SHA-256为
`622e9711e60a2ae92e8ed131e0a841edcbf2e0972173422a28fc0bbd4979fe3d`。防重发预检已扫描四份
历史RAM Loader证据且未命中新候选。该候选尚未发送，设备保持Android USB `2207:0010`；
在新的现场确认前不切换Maskrom。R0继续为 `pending`。

## 第三候选单次实机结果

用户物理断电并重新正常上电后，主机只读USB枚举确认设备恢复为Android USB
`2207:0010`。随后受限转换器核对唯一ADB设备、序列 `CBEAU1116K01314`、完整fingerprint、
固件3448及固定主机工具哈希，再次通过 Android→`2.01 Loader`→`2.00 Maskrom`；转换证据
SHA-256为 `372e402cb82bbc278ac8bc1ccb861f59ba732739db853e6994df21d7e4e691f8`。

RAM执行器扫描四份历史证据，确认 `rk322x-v1.07.238` 从未发送，随后只执行一次RAM
`boot`。主机报告下载成功，但之后10秒内31次固定模式观察始终为Maskrom，最终以
`loader_mode_timeout` 停止。证据只含一次初始列表、一次boot和31次列表，共33条命令；
SHA-256为 `7b856871f064d186509d02d3843fba4d875187151fc75116d0013ad299ae95d1`。

本轮没有执行能力、FlashInfo、分区或LBA读取，没有生成首4 MiB文件，也没有写入、擦除或
复位。现场复核确认设备仍为 `2207:320b`、`bcdUSB=2.00` Maskrom，没有残留
`rkdeveloptool`、`timeout` 或 `sudo` 设备进程。纯主机防重发复核在USB访问及输出目录创建前
返回 `loader_candidate_already_attempted:rk322x-v1.07.238`。

三枚年代不同且配置来源固定的官方候选均在主机报告下载成功后保持Maskrom。第三候选不得
重发，设备当前需物理断电恢复Android。物理首4 MiB、完整eMMC、独立低层入口、受控回刷
及回刷后检查仍全部未完成，R0继续为 `pending`。下一步停止继续现场试发候选，先离线审计
三次共同失败的主机传输、471/472载荷执行和DDR初始化证据，并重新评估已定位但尚未实机
核对的物理Maskrom入口；没有新证据前不再切换Maskrom。

## 第三次断电恢复与共同失败离线审计

用户再次物理断电约10秒并正常上电。主机只读USB枚举确认 `2207:320b` 消失、Android USB
`2207:0010` 恢复；当前sysfs节点为 `1-7.3`，udev序列仍为 `CBEAU1116K01314`。本步没有
建立ADB连接、发送RockUSB命令或访问eMMC。

三份失败证据和包头的离线交叉检查确认：

- 已有Loader中读出的16字节芯片信息以 `A223` 开头，即反序的 `322A`；三个包头芯片值均
  为 `RK322A`，可排除明显的包头芯片类型不匹配；
- 三个包均为一条471 DDR、一条472 USBPlug及两条仅供后续写入IDB的Loader entry；实机
  `boot` 路径只发送471和472，不会误发MiniLoader entry；
- 三次 `Downloading bootloader succeeded` 只证明全部USB控制传输返回预期长度。
  `rkdeveloptool` 不读取执行状态，也不在成功前验证USBPlug已接管，因此不能把该提示写成
  RAM Loader运行成功；
- 第三包471大小8,192字节、472大小77,824字节，471后等待1 ms，与固定官方
  `RK322XMINIALL.ini` 一致；包头、entry偏移/长度、RC4和整包CRC此前均已通过离线解包；
- 从第三候选同一Rockchip官方提交 `364df6ae7c88450280293616eecc554404959898` 取得的
  2018-04-26 `upgrade_tool` SHA-256为
  `440dca96fc0e75cb9b8e84fd48d18baf12765335a28900bcc2e1bb11e040b81c`。该文件为带调试信息
  的32位x86 ELF；未运行它连接设备。静态反汇编显示其 `DownloadBoot` 与
  `RKU_DeviceRequest` 同样依次发送0x471、按entry值执行1 ms等待、发送0x472，并同样按
  4,096字节分块附加CRC-CCITT。由此没有证据支持仅更换官方主机二进制后重发同一候选。

当前证据仍无法从主机侧区分471 DDR代码是否未执行、执行失败，或472接管前失败，因为三轮
都未捕获到阶段代码提供的独立状态，现有工具日志也只记录配置文件缺失而无设备端诊断。
不再增加第四个盲选Loader，也不使用官方工具重复已发送载荷。下一安全步骤是获取
`r1-sample01` 自身清晰主板照片，核对板号、R211丝印、屏蔽罩与现有Type-C改线；确认位置
一致后，再单独制定不依赖Android的物理Maskrom枚举步骤。短接前仍不得发送Loader、读取
存储、写入或擦除。

## 物理入口暂缓决定

随后启动了仅观察sysfs的10分钟USB监视器，未发送ADB或RockUSB命令。用户第一次报告短接
上电后，设备仍为原Android USB `2207:0010`，sysfs节点、设备号 `42` 均未变化，不能证明
Type-C曾断开或物理Maskrom短接生效。准备按“电源与Type-C同时断开”重新操作时，用户决定
跳过这一步验证；监视器已立即终止。

本次决定只暂停当前物理入口操作，不把独立低层入口、物理首4 MiB、完整eMMC、受控完整
回刷或回刷后检查改为通过，也不构成降级授权。R0保持 `pending`，不得据此执行Root、修改
boot/SELinux/system或写入分区。后续在用户重新决定恢复该验证前，只进行不连接或改写设备
的离线准备。
