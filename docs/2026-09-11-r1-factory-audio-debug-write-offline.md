# 原厂调试文件写入路径离线复核

日期：2026-09-11  
范围：固件3448原厂Unisound APK、`libUni4micHalJNI.so`、`libuni4michal.so`和已取得的脱敏实机结果。原厂二进制及反汇编全文只保留在本地。

## 结论

固定`waking/waked 4mic/2aec/out`文件的有效载荷由`libuni4michal.so`内部MicArray处理线程写入，不是Java/JNI的`readData`或公开`uni_4mic_pcm_read`调用者写入。因而调整代理读取缓冲、接受tinyalsa的0成功返回值或继续增加VFAT权限，都不能解释或修复当前0字节载荷。

3448原厂服务在真实唤醒后已经复现“三个waking文件0字节、三个waked文件只有WAV头且0帧”；v20特权代理又在正确目录权限和无相关AVC时生成三个0字节waking文件。两条独立实机路径共同说明，固定调试文件在当前首台/3448上不能提供处理载荷证据。此结论不等于原厂MicArray没有处理音频：原厂服务可由真人输入触发唤醒，特权代理也持续取得非零PCM；只是不能再用固定调试文件验收四麦、AEC或DSP。

## 静态证据

- 原厂`pcm_hw_config.txt`把`debug_file_path`固定为`/sdcard/unidata/`。
- 原厂Java四麦管理器默认`debug=1`、`closeAlgorithm=0`、`wakeStatus=0`，并按`init -> set4MicDebugMode -> close4MicAlgorithm -> set4MicWakeUpStatus -> open/start/read`运行。
- `set4MicDebugMode`在`libuni4michal.so:0x3554`把参数写入内部对象偏移`0x1ec`。
- 内部处理线程在`0x2204`读取同一debug标志；启用后，从`0x2226`、`0x224a`和`0x2508`三个调用点分别写4mic、2aec和运行时输出缓冲。结合PLT重定位，它们均为`fwrite`；固定块大小分别为`0x800`、`0x400`和运行时输出长度。
- `uni_4mic_pcm_read`在`0x2a80`只校验句柄和缓冲后调用tinyalsa`pcm_read`，非负时原样返回；该函数没有固定文件写入调用。Java仅在JNI返回正值时回调的冲突仍保留，但它与内部调试文件写入是两条路径。

上述字段及精确锚点已加入`docs/references/r1-3448-factory-audio-abi.json`，离线材料审计会在原厂二进制变化时失败关闭。

## 下一入口

停止继续尝试固定调试文件。下一候选改为原厂MicArray处理边界的诊断旁路：先离线固定`Unisound_MicArray_Process`的完整ARM ABI、各输入/输出指针、样本数和生命周期，再由自有代理以只读复制方式导出4mic、2aec和处理输出到既有本地IPC诊断通道，同时原调用必须原样转发，生产入口默认关闭。

该旁路不得写公共存储、不得把原厂库打包进APK、不得改变算法输入或返回值；需要先有主机替身测试证明调用转发、长度边界、并发与关闭清零，再按boot双读/单写/复位前读回门禁进行最小实机验证。在取得真实同窗口载荷前，AEC消除、四麦独立响应和DSP质量继续为未验证。
