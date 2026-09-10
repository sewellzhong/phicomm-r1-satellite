# r1-sample01 system 与原厂音频离线审计（2026-09-10）

## 范围与安全边界

用户暂缓物理Maskrom验证后，本步只读取已经完成A/B复读的Loader image分块，不连接R1，
不调用ADB或RockUSB，不生成修改镜像，也不改变R0 `pending`。system镜像、原厂APK、库、
固件、配置和反汇编只保存在Git忽略的 `local-recovery/`；公开仓库只记录自有工具、哈希、
接口事实和未验证边界。

## system双份提取

`audit-offline-chain.py extract-system`先复核设备ID、3448 fingerprint、Android盘点、Loader
image清单与整体复读报告，再把物理system分区范围换算到缺少首4 MiB的Loader image坐标。
提取过程逐个复核所有相交分块的尺寸和SHA-256，禁止绝对路径、目录逃逸、符号链接及覆盖
已有输出。

- 物理起始扇区：2,727,936；Loader image起始扇区：2,719,744；
- system大小：805,306,368字节；
- A/B SHA-256：`51f125c7b385a9d9306897d733f3d5674f7efc7ac79b36433138a50b9ad0d242`；
- 私有提取清单SHA-256：
  `e5a85ed76a3f721502357d9df31b7482b669fadc912c7a948f90618f8c3bb648`。

两份均为同一UUID、卷名为 `system` 的ext4文件系统。该结论只覆盖system分区，不能补齐
物理首4 MiB或完整eMMC。

## 原厂材料与静态接口

固定白名单从system copy A提取14项：原厂 `Unisound.apk`、JNI、圆形/线性MicArray、两种
四麦HAL、软件AEC库、四麦配置、`wopt.bin`和AK7755 data2固件。四麦相关库均与公开3448
参考哈希匹配；未提取提示音、家庭录音、调试WAV/PCM或凭据。随后使用SDK 34
`dexdump`、NDK 27 `llvm-objdump` Thumb模式和系统 `readelf` 生成私有静态证据。
更新后的私有材料与分析清单SHA-256为
`288d2b9ce72e0c5bd22a1c7858e2abec003a2bbc2f59b035103739b709b60ca4`；清单同时绑定审计器、
公开契约参考及四个分析工具的可执行文件哈希，并在出具通过状态前自动复核5份分析文件中的
37个精确语义锚点。旧清单保留为历史证据，但不再作为当前静态契约结论。

离线证据新增确认：

- 原APK的 `com.unisound.sdk.x` 四麦路径依次调用JNI `init(1)`、默认
  `set4MicDebugMode(1)`、保持算法开启、`openAudioIn(2)`、start/read、stop/close/release；
  当前自有代理为避免产生原厂调试录音而显式使用debug 0，两者必须区分；
- JNI ABI为 `readData(long, byte[], int): int`。机器复核纠正早期人工结论：管理器默认包长
  字段为1,200样本，四麦分支乘2后默认申请2,400字节，且该包长可由运行时选项修改，
  因此不能静态声称固定4,800字节；
- 原APK类证据偏移和输入哈希已写入
  `docs/references/r1-3448-factory-audio-abi.json`；
- Java四麦循环仅在JNI `readData` 返回正值时执行 `onRecordingData`；JNI透传HAL返回值，
  HAL在底层读取返回非负时原样返回、失败时返回-1。该路径与常见tinyalsa成功返回0的约定
  存在静态语义矛盾，必须由实机调用返回值解释，不能据此宣称原厂回调已取得PCM；
- 原APK还有独立的软件 `IAudioSourceAEC`/`libaec.so` 路径，不能据此证明四麦HAL输出已消费
  双播放参考。

这些静态事实确定调用接口和默认申请长度，但不能确定运行时包长、有效通道布局或处理输出，
也不能证明代理应选择单声道或双声道输出。`runtime_output_channels`和读取返回语义继续为
`pending`，代理仍报告AEC未证明，APK生产链证明继续拒绝采集。

## 复现入口与下一步

```bash
python3 tools/factory_audio/audit-offline-chain.py extract-system \
  --copy-manifest <private-loader-image-copy.json> \
  --copy-verification <private-verification.json> \
  --inventory <private-android-inventory.json> \
  --output-dir <new-private-system-output>

python3 tools/factory_audio/audit-offline-chain.py audit-materials \
  --extraction-manifest <private-system-extraction.json> \
  --reference docs/references/r1-3448-factory-audio-abi.json \
  --output-dir <new-private-audit-output> \
  --seven-zip <pinned-7z> --dexdump <sdk-34-dexdump> \
  --readelf <readelf> --llvm-objdump <ndk-27-llvm-objdump>
```

下一现场入口不变：用户恢复R0物理入口和完整回刷验证后，才允许部署受限代理并取得实际
读取返回值、PCM、DOA和播放参考。届时必须用实机数据决定输出通道，不能用本次静态缓冲
长度代替。当前统一主机检查通过Android 168项、lint、native 32项、恢复73项与桌面演练、
原厂代理/策略/ABI/离线审计39项、HA 44项、API 22 ARMv7交叉构建、公开审计及凭据扫描；
本步未连接R1，也未执行实机验收。
