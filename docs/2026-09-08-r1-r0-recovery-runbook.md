# r1-sample01 R0 完整备份与回刷操作手册

## 范围与安全边界

本手册服务于[原厂四麦与音频调校优先路线](2026-09-08-r1-factory-audio-root-plan.md)的 R0 门槛。`r1-recovery.py` 只读取已经导出的本地镜像，生成哈希清单并判断门槛状态；它没有设备传输、擦除或写入能力。`r1-rockusb-readonly.py` 提供固定只读查询；`r1-rockusb-ram-loader.py` 只允许离线构建校验和在确认 `bcdUSB=2.00` Maskrom 后单次加载RAM。两者都不提供复位、存储切换、写入或擦除入口。完整备份、低层恢复入口和受控完整回刷均须在 `r1-sample01` 真机完成，因此当前状态仍是“待验证”。

默认情况下，任何永久Root、补丁boot、SELinux、recovery、system或分区改写都必须等待本手册的最终门槛报告为`pass`，或用户明确例外对应的`pass_with_exception`。2026-09-11的[免拆分级授权](2026-09-11-r1-no-disassembly-authorization.md)另行允许当前`r1-sample01`/3448基线在R0 pending时，按目标分区双读、候选固定、单次写入和复位前完整读回门禁推进必要的boot/system/recovery修改；这不会让本工具报告通过。不得把普通ADB文件备份、公开OTA或旧版APK回退基线当成完整eMMC恢复基线。

默认要求所有实际镜像放在仓库外的两份独立加密存储。建议在本地使用已忽略的 `local-recovery/` 只保存清单草稿和脱敏报告，不放镜像、凭据、原厂库、APK、DSP 固件、校准或修改镜像。

用户已针对首台 `r1-sample01` 决定接受“当前单主机、明文存储”例外。这同时存在
家庭凭据明文泄露和单点丢失两项风险，不能写成默认安全基线。工具要求提供完整、
设备限定的例外 JSON；即使所有恢复项通过，报告也只能是
`pass_with_exception`。例外不放宽完整 eMMC、低层入口、受控回刷或回刷后功能检查，
也不适用于其他设备。模板为
`tools/recovery/templates/single-host-plaintext-exception.example.json`。

## 无设备阶段

1. 默认在两块独立本地介质上准备不同的存储标识；标识表示物理介质，不得用两个目录冒充两份独立副本。若采用已确认的单主机明文例外，只提供一个实际存储标识，并保留上述风险确认文件。
2. 准备版本为 `1` 的布局 JSON。每个 eMMC 地址空间都必须包含一份完整镜像和从偏移 `0` 连续覆盖到末尾的区域；未分配区域也显式登记，不能留下未解释缺口。原厂 APK、Audio HAL、四麦库、DSP 固件和校准文件可放入顶层 `files`，分别记录长度、副本和读取工具版本；默认策略要求双副本。
3. 把包含 `data`、`config`、Wi-Fi 或其他家庭数据的区域，以及覆盖这些区域的完整镜像标记为 `sensitive`。默认策略下每个副本同时声明 `encrypted_storage: true`；明确的单主机明文例外则必须如实声明 `false`，不能伪报加密。
4. 使用合成文件运行工具和测试，不填写真实家庭凭据或私有绝对路径。

仓库提供 `tools/recovery/templates/layout.example.json` 和
`tools/recovery/templates/recovery-state.example.json` 作为现场副本。模板中的
`replace-*`、长度、偏移和区域名全部必须由实机只读枚举结果替换，不能当作 R1
实际布局。离开设备时可反复运行以下无副作用桌面演练：

```bash
python3 tools/recovery/rehearse.py
```

演练只在临时目录生成 8 字节合成镜像，依次证明双副本校验通过、不完整恢复状态
保持 `pending`、完整合成证据可得到 `pass`；它不连接设备，也不代表 R0 实机通过。

最小布局结构如下；数值和分区名只是格式示例，不代表 R1 实际布局：

```json
{
  "schema_version": 1,
  "areas": [{
    "name": "user",
    "size": 8,
    "full_image": {
      "name": "full-emmc",
      "classification": "sensitive",
      "copies": [
        {"storage_id": "media-a", "path": "full.img", "encrypted_storage": true},
        {"storage_id": "media-b", "path": "full.img", "encrypted_storage": true}
      ]
    },
    "regions": [{
      "name": "observed-region",
      "offset": 0,
      "length": 8,
      "classification": "sensitive",
      "copies": [
        {"storage_id": "media-a", "path": "region.img", "encrypted_storage": true},
        {"storage_id": "media-b", "path": "region.img", "encrypted_storage": true}
      ]
    }]
  }],
  "files": [{
    "name": "factory-audio-file",
    "length": 3,
    "classification": "non_sensitive",
    "source": {"tool": "<只读提取工具>", "version": "<固定版本>"},
    "copies": [
      {"storage_id": "media-a", "path": "factory-audio-file.bin", "encrypted_storage": false},
      {"storage_id": "media-b", "path": "factory-audio-file.bin", "encrypted_storage": false}
    ]
  }]
}
```

## 设备到手后的只读盘点与备份

1. 先核对设备标签为 `r1-sample01`，记录硬件、完整 fingerprint、固件 3448、当前 APK/服务状态和 v79 回退基线。任一身份发生变化即停止，建立新基线。
2. 在不改写 eMMC 的条件下实际识别 Loader、Maskrom、recovery 或等价入口；记录连接方式、读取工具来源、版本和原始输出。不得仅按 RK3229 型号预设工具、Loader 或分区名称。
   2026-09-09 的固定查询证明 `adb reboot bootloader` 后实际为 `bcdUSB=2.01` Loader，
   并非USB ID数据库所称的Maskrom；SoC信息可读，但能力查询失败且Flash ID查询超时，
   没有取得容量或布局。历史官方RAM Loader已完成离线审计，但因模式不符没有发送；不得
   通过重复无界查询或破坏现有引导来绕过停止条件。随后单独的FlashInfo也在root侧8秒
   有界超时内无输出，未触发磁盘头或分区读取。随后已从正常Android用普通shell取得块设备
   真值：15,269,888个512字节扇区、16个无重叠分区、前置8 MiB和中间4 MiB未映射范围。
   SELinux拒绝cmdline、fstab和by-name遍历，未绕过权限；完整读取必须覆盖整盘而非只读分区。
   以该盘点为前置的Loader固定34扇区复读已经通过并取得 `PARM`；参数分区偏移与Android
   sysfs固定相差 `0x2000` 扇区。普通工具读使用image子码，在直接LBA及首4 MiB语义验证
   前不得把Loader逻辑LBA结果冒充完整物理eMMC镜像。
   审计版直接子码与image模式在LBA 0、`0x2000`、`0x4000` 均逐字节相同；地址内容与
   参数表起点吻合，证明现有Loader实际暴露的是物理4 MiB之后的image空间。该空间共
   7,813,988,352字节，已经分117块从设备独立读取两遍并通过逐块及整体复核；物理首4 MiB
   仍未覆盖，必须由独立物理Maskrom/等价入口另行只读取得，不能降低完整覆盖门槛。
   免拆软件转换已实际进入 `bcdUSB=2.00` Maskrom，但该入口依赖Android和已有Loader，不算
   独立入口。首次固定v1.04.232 RAM Loader下载返回成功后仍保持Maskrom，未运行能力或存储
   读取；同一候选不得重发。2026-09-10 设备已物理断电恢复Android，新的候选固定为官方
   `RK322XMINIALL` 配置中的DDR v1.10、USBPlug v2.56和MiniLoader v2.56一致组合。官方
   `boot_merger` 会把构建时间写入头部，因此每次完整文件SHA-256不同；工具同时记录完整
   文件哈希，以及清零7字节构建时间并排除末尾CRC后的规范化内容SHA-256
   `3cae5045061df975488626361944c0147d7715a8d548d32a4a789c90d9287646`。重复门槛按候选ID、
   规范化哈希或完整哈希任一匹配即停止，不能通过重新打包绕过。该新候选实机发送一次后
   同样保持Maskrom并以 `loader_mode_timeout` 停止，未执行后续读取；设备已物理断电恢复
   Android。同一候选不得重发。随后从设备镜像中的2018-06-26 U-Boot构建标记反查同时期
   官方完整配置，选定2018-04-26的DDR v1.07、USBPlug/MiniLoader v2.38组合；该候选完成
   离线哈希、打包、解包、防重发和统一主机检查后也仅发送一次，下载成功后仍保持Maskrom，
   未执行能力或存储读取，且已禁止重发。设备随后已物理断电恢复Android。离线反汇编确认
   同一2018-04-26官方提交的 `upgrade_tool` 与固定 `rkdeveloptool` 对471/472、1 ms等待、
   4096字节分块及CRC-CCITT使用相同语义，没有证据支持换工具重发。下一步先核对本机主板
   和物理Maskrom位置；取得新的独立低层入口证据前，不再继续现场发送候选。2026-09-10
   用户决定跳过当前物理Maskrom验证；该项保持未验证，R0继续为 `pending`，不据此执行Root
   或分区改写。
3. 从低层入口枚举全部 eMMC 地址空间、偏移和长度。将完整读取结果与 Android 可见分区表交叉核对；差异必须解释并保留证据。
4. 读取完整地址空间、全部区域、原厂 APK、Audio HAL、四麦库、DSP 固件和校准文件。读取命令必须是已核实的只读操作；任何语义不明确的子命令先停止。
5. 分别把镜像写入两块独立加密介质。完成写入后卸载并重新挂载两块介质，再由主机工具复读全部字节。

创建清单：

```bash
python3 tools/recovery/r1-recovery.py create-manifest \
  --layout local-recovery/layout.json \
  --device-id r1-sample01 \
  --hardware '<实机读取值>' \
  --fingerprint '<完整实机 fingerprint>' \
  --tool '<实际低层读取工具>' \
  --tool-version '<固定版本>' \
  --storage media-a='<第一块加密介质挂载点>' \
  --storage media-b='<第二块加密介质挂载点>' \
  --output local-recovery/manifest.json
```

仅针对已确认例外，在命令中额外加入：

```bash
  --policy-exception tools/recovery/templates/single-host-plaintext-exception.example.json
```

实际使用前复制模板到仓库外，保持 `device_id` 为 `r1-sample01`，记录真实决定日期，
并原样确认 `plaintext_sensitive_data` 与 `single_point_loss` 两项风险。不要修改公开示例
来伪造现场决定。

独立复读校验：

```bash
python3 tools/recovery/r1-recovery.py verify-copies \
  --manifest local-recovery/manifest.json \
  --storage media-a='<第一块加密介质挂载点>' \
  --storage media-b='<第二块加密介质挂载点>' \
  --output local-recovery/verification.json
```

任何尺寸、SHA-256、区域覆盖、文件身份或敏感存储声明错误都会失败。工具能排除同一文件和同一 storage ID，但无法凭路径证明两个 storage ID 确实对应不同物理介质，操作者必须现场核对。清单、校验和门槛报告均拒绝覆盖已有文件；每轮操作使用新的输出文件名，保留原始证据。

## 低层恢复与受控完整回刷

1. 在不依赖 Android 正常启动和网络 ADB 的条件下，再次进入同一低层入口并完成一次只读识别，将结果记为 `low_level_entry: pass`。仅能从正常 Android 重启进入不算完成。
2. 先制定断电、失败启动和工具中断的恢复步骤。确认两份备份仍通过复读后，才执行一次受控完整回刷；写入目标、偏移和长度必须与清单逐项一致。
3. 回刷后核对启动、ADB、Wi-Fi、蓝牙、麦克风、扬声器、中央键/音量环、灯效，以及原厂 Audio HAL、四麦库、DSP 固件和校准文件哈希。
4. 任何失败均记录为`fail`，不得改写门槛或静默使用公开OTA补齐未知区域。默认停止Root和系统修改；当前首台若继续使用2026-09-11分级授权，必须另按目标分区风险门禁记录，不能冒充R0恢复验证。

恢复状态 JSON 使用 `pending`、`pass`、`fail`，并保持设备身份与清单完全一致。每个 `pass` 必须登记仓库外证据的相对路径和 SHA-256；缺少证据的“通过”会被门槛工具拒绝：

```json
{
  "device": {"id": "r1-sample01", "hardware": "<实机值>", "fingerprint": "<完整值>"},
  "low_level_entry": {"status": "pending"},
  "controlled_full_restore": {"status": "pending"},
  "post_restore_checks": {
    "boot": {"status": "pending"}, "adb": {"status": "pending"},
    "wifi": {"status": "pending"}, "bluetooth": {"status": "pending"},
    "microphone": {"status": "pending"}, "speaker": {"status": "pending"},
    "buttons": {"status": "pending"}, "leds": {"status": "pending"},
    "factory_audio_hashes": {"status": "pending"}
  }
}
```

生成最终门槛报告：

```bash
python3 tools/recovery/r1-recovery.py gate-report \
  --manifest local-recovery/manifest.json \
  --verification local-recovery/verification.json \
  --recovery-state local-recovery/recovery-state.json \
  --output local-recovery/gate-report.json
```

默认只有报告为`pass`或与用户明确例外完全匹配的`pass_with_exception`后，才进入R1临时Root、补丁boot和受限SELinux环境实验。`pending`不代表失败。当前`r1-sample01`/3448是唯一例外：可按2026-09-11免拆分级授权推进必要的boot/system/recovery目标分区操作；Loader、分区表、物理首4 MiB、擦除、格式化和整盘覆盖仍不得执行。R0的`fail`仍须如实保留并先评估影响。
