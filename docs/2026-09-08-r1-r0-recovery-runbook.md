# r1-sample01 R0 完整备份与回刷操作手册

## 范围与安全边界

本手册服务于[原厂四麦与音频调校优先路线](2026-09-08-r1-factory-audio-root-plan.md)的 R0 门槛。当前主机工具只读取已经导出的本地镜像，生成哈希清单并判断门槛状态；它没有 ADB、Loader、Maskrom、擦除或写入能力。完整备份、低层恢复入口和受控完整回刷均须在 `r1-sample01` 真机完成，因此当前状态仍是“待验证”。

任何永久 Root、补丁 boot、SELinux、recovery、system 或分区改写都必须等待本手册的最终门槛报告为 `pass`。不得把普通 ADB 文件备份、公开 OTA 或旧版 APK 回退基线当成完整 eMMC 恢复基线。

所有实际镜像放在仓库外的加密存储。建议在本地使用已忽略的 `local-recovery/` 只保存清单草稿和脱敏报告，不放镜像、凭据、原厂库、APK、DSP 固件、校准或修改镜像。

## 无设备阶段

1. 在两块独立本地介质上准备不同的存储标识；标识表示物理介质，不得用两个目录冒充两份独立副本。
2. 准备版本为 `1` 的布局 JSON。每个 eMMC 地址空间都必须包含一份完整镜像和从偏移 `0` 连续覆盖到末尾的区域；未分配区域也显式登记，不能留下未解释缺口。原厂 APK、Audio HAL、四麦库、DSP 固件和校准文件可放入顶层 `files`，分别记录长度、双副本和读取工具版本。
3. 把包含 `data`、`config`、Wi-Fi 或其他家庭数据的区域，以及覆盖这些区域的完整镜像标记为 `sensitive`。每个副本同时声明 `encrypted_storage: true`。
4. 使用合成文件运行工具和测试，不填写真实家庭凭据或私有绝对路径。

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
4. 任何失败均记录为 `fail`，停止 Root 和系统修改；不得改写门槛或静默使用公开 OTA 补齐未知区域。

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

只有报告为 `pass` 后，才进入 R1 临时 Root、补丁 boot 和受限 SELinux 环境实验。`pending` 不代表失败，但绝不授权写入；`fail` 必须先闭环恢复问题。
