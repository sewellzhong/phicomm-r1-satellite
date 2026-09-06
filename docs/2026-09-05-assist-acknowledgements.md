> 历史记录：本文版本、命令及“下一步”反映记录当时状态；当前排期以[根 README](../README.md)为准。原始产物迁移见[归档说明](../test-results/README.md)，原验收结论不变。

# 版本 40：随机唤醒回应与分段命令收音

## 用户选定的回应

日常组：诶，叫我啦？／来了来了。／好嘞，什么安排？／说来听听。／你说，我接着。／好，接下来听你的。

偶尔组：我就知道你会叫我。／终于轮到我啦。／好巧，我正等着呢。／小助手到位。

随机选择不连续重复，不连续选择偶尔组。偶尔组长期目标占比15%，组内均匀；
日常组之后以3/17概率选择偶尔组，偶尔组之后必须选日常组，平衡后约85%/15%。
使用现有 HA Piper `zh_CN-huayan-medium` 合成固定应用文案，转换为 PCM S16LE/16k/单声道 WAV。
10条总计约0.4MiB，单条约0.9～1.7秒；随APK打包，不在每次唤醒时请求TTS服务。
文案、音频时长与哈希在 `android/r1-probe/app/src/main/assets/ack/manifest.json`。
生成工具：`python3 tools/assist/prepare-acknowledgements.py`，经授权SSH访问既有Piper，不读取HA令牌。

## 交互状态

1. `listening`：只做本地Alexa检测，不上传日常背景录音。
2. `acknowledging`：释放AudioRecord，清掉唤醒录音，随机播放本地回应。
3. 回应播放完成后留200ms扬声器尾音衰减时间，重建录音，进入 `waiting_command`。
4. 6秒开口窗口内，WebRTC VAD连续4帧（80ms）判定人声后，上传最近300ms命令起始缓冲。
   起始缓冲全部来自回应后的新录音，不包含Alexa或提示语。
5. 开始说话后不再受6秒开口窗口限制；VAD连续60帧（1.2秒）非人声结束，单条最长20秒。
   HA仍使用 `no_vad=true`，接收端点由R1发送的EOF控制。
6. 未开口超时：仅报告 `command_timeout`，清空本地缓存，回到 `listening`。
   不启动HA管线、不调用STT/TTS、不播退出语或提示音。

本版取消版本39固定等待至少8秒的策略，也移除版本38/39的硬编码唤醒词/误写前缀删除；
命令阶段保留原始识别文字，避免误删真实设备名。
当前交互需要等回应结束再说命令；不支持回应中插话，也不保证Alexa与命令连说的内容会被保留。
WebRTC VAD仍可能把电视人声/噪声误判为命令，不将“未检测到人声时静默退出”扩大为任何环境绝无误触发。

## VAD来源与许可

使用 WebRTC VAD 独立库 libfvad，固定提交 `532ab666c20d3cfda38bca63abbb0f152706c369`。
16kHz、20ms帧，mode=2；在每次命令等待开始时重置。替代版本39的固定RMS能量阈值。
源码在忽略目录 `local-deps/src/libfvad`，构建脚本 `bash tools/build-r1-vad.sh`；
NDK 27.0.12077973，armeabi-v7a，android-21，对API22兼容，保留SysV HASH表。
JNI库仅依赖系统libm/libdl/libc。
BSD-3-Clause许可与PATENTS已随APK打包；不增加新的训练数据或唤醒模型。
[固定源码](https://github.com/dpirch/libfvad/tree/532ab666c20d3cfda38bca63abbb0f152706c369)。

Piper huayan MODEL_CARD标注其数据集许可Unknown，原文保留于APK assets/licenses。
本轮沿用用户已有语音服务合成内部开发提示语，不把该记录视为公开或商业分发的许可审核通过。

## 验证及边界

- 50项主机单元测试、lint、APK构建通过；新增随机组占比/不重复/偶尔不连发检查。
- 状态机覆盖6秒无输入不START、短瞬态不START、临近超时开口仍可继续、短命令不等8秒、20秒上限。
- 10条提示语PCM格式、时长、SHA256及APK内未压缩资源检查通过。
- Python编译检查通过，JNI交叉编译通过。
- 新版完整录放音交互、实际提示语可闻性、人声判定及房间回声待真实使用反馈。
  本轮不要求真人KWS测试、不采集家庭诊断录音、不改HA配置。
- 内存令牌、开发机/ADB依赖、一小时开发服务上限不变。升级后需重新隐藏输入令牌。

证据：`test-results/2026-09-05-r1-sample01-assist-acknowledgements/`。

R1已安装版本40并验证Activity启动；`CommandVadSmoke` 在API22上完成401帧合成静音及重置检查，未开启麦克风。JNI链接器提示未使用GNU/version DT条目，但SysV HASH加载和执行成功。后台会话已准备，等待用户隐藏输入令牌。


后续版本41：用户报告未输入命令时STT为“。”仍收到回复。新增识别结果文字检查，纯标点不提交意图/TTS；VAD误触发来源尚未确定。见 [无命令修正](./2026-09-05-assist-empty-command.md)。
