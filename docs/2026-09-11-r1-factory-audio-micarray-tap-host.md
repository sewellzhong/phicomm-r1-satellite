# R1 原厂 MicArray 诊断旁路主机门槛（2026-09-11）

> 后续状态：v21 boot 与 v85 APK 已完成本文所列首次实机门槛，结果见
> [v85 实机记录](2026-09-11-r1-factory-audio-v85-micarray-tap-device.md)。本文保留部署前主机结论与当时入口。

## 结论

已完成 README 指定的实机前主机门槛：从固件3448中保留DWARF的
`libUniMicArray.so`固定`Unisound_MicArray_Process`完整ARM ABI，并实现默认关闭、原调用
原样转发、只读复制到既有本地IPC的诊断旁路。主机替身验证覆盖双重显式授权、4麦输入、
2路AEC参考、ASR/VAD输出、返回值、并发调用、长度边界、停止清零以及生产请求不输出诊断
载荷。

这只证明代码与主机替身契约，不证明R1上的动态符号绑定、真实4麦独立响应、AEC参考覆盖、
消除量或DSP质量。没有连接ADB、没有安装APK、没有刷写boot，也没有采集实机录音；R3和R0
状态不变。

## 固定ABI

固件3448的函数签名固定为：

```text
int Unisound_MicArray_Process(
    void *handle,
    const int16_t *in,
    int in_len,
    int16_t *echo_ref,
    int is_waked,
    int16_t **out_asr,
    int16_t **out_vad,
    int *out_len)
```

DWARF参数名、指针层级与基础类型已加入
`docs/references/r1-3448-factory-audio-abi.json`的有序锚点。结合3448配置和内部固定写块，
旁路只接受每通道256样本、4路交错麦克风和2路交错参考；输出最多256个单声道样本。边界
不符只累计`invalid`，不会跳过或改写原函数调用和返回值。

## 实现边界

- boot端必须带`--allow-micarray-diagnostic-tap`，客户端的`StartCapture`还必须同时请求
  `include_diagnostic_output`和`micarray_diagnostic_tap`；任一缺失均失败关闭。
- 生产捕获不启用旁路。禁用时不复制MicArray载荷；停止、释放和下一次启动会清空固定容量
  队列、序号及计数器。
- 原始调用先执行，返回值原样返回。旁路使用固定容量槽位和`trylock`；竞争或队列满时丢弃
  诊断副本并计数，不阻塞原厂处理线程。
- IPC新增每次调用的4麦、2参考、ASR、VAD、样本数、唤醒状态与原返回值，并在健康状态中
  暴露active/dropped/invalid。它不写公共存储，也不把原厂库打包进APK。
- overlay与增量boot构建器只允许精确增加一个已审计诊断参数，MicArray旁路不需要旧固定
  文件路线的VFAT组或临时SELinux写权限。

## 验证

```bash
ANDROID_SDK_ROOT=/home/sewellzhong/.local/share/android-sdk \
  R1_GRADLE_OFFLINE=1 bash tools/factory_audio/check.sh
```

结果：ARMv7/API22代理构建通过，原厂音频99项测试通过。替身MicArray函数返回`73`，IPC中
保持`73`并得到预期4麦、2参考及ASR/VAD样本；并发替身完成且停止后的生产请求没有旁路记录。
本次ARMv7代理SHA-256为
`ef9c46e2757e1795a3a8b3d1dd97675b4ebcc93b5e8a1b86d1fde0c05651770e`。

使用现有双份system基线重新执行私有离线材料审计也通过；私有报告保存在仓库外/忽略目录，
报告SHA-256为`0ae61b93c7243e5b377b2d2615a99e1721bc06d8d48417ca2c05a9361e6378f4`。

## 下一入口

统一主机检查和公开材料审计已经通过。随后以两个独立保存且哈希一致的历史v15输入完成
离线候选演练；增量门禁确认只改变代理和init中的单个MicArray旁路参数，kernel、second、
地址、页大小及其他ramdisk条目不变。候选SHA-256为
`9aefde04d52968a0e4690a0812f09c7399f45f76e4afaeafef57cfcb929afcda`，只保存在私有目录，
不等于已经满足现场写入门槛。当前v15本来就带默认不触发的旧vendor-debug允许参数，但不含
临时VFAT策略；候选保留该现状，没有新增公共存储权限。

若继续实机，现场仍须执行
设备身份/3448 fingerprint核对、当前v15 boot双读、候选固定、单次写入、复位前完整读回及
Enforcing/Android/ADB/Wi-Fi/音频恢复门禁。首次只验证符号绑定、旁路active、连续性、
dropped/invalid为零和短时同窗口载荷，不直接宣称AEC或R3通过。
