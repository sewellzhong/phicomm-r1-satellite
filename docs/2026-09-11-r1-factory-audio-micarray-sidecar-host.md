# R1 MicArray 原始 sidecar 受控导出主机记录（2026-09-11）

## 结论

v86 主机候选已将 v85 只在内存中计数的 `Unisound_MicArray_Process` 旁路载荷保存为同一有界
采集窗口内的四个 WAV sidecar：4 麦交织输入、2 路参考、ASR 输出和 VAD 输出。该入口只在
`micarray_diagnostic_tap=true` 时创建文件；普通卫星采集和其他诊断路径不创建这些材料。

每个 sidecar 的文件名、声道数、PCM 字节数和 SHA-256 都写入元数据。离线审计要求四个文件
同时提供，并逐个复核 16 kHz、S16LE、未压缩、固定声道形状、载荷长度、非零字节计数和
SHA-256；缺失、替换、截断、声道错误或哈希不符均拒绝。采集、WAV 头定稿或元数据写入失败
时会清理本轮输出。

本步没有连接 ADB、没有安装 v86、没有修改 boot，也没有采集家庭录音。因此这里只能声明
代码和主机模拟检查通过；4 麦独立物理响应、2 路参考对本机播放的覆盖、AEC 消除量、DOA
方向变化和 DSP 质量仍未验证，R3、R0 状态不变。设备继续运行 v21 代理和 v85 APK。

## 受控导出入口

新增 `tools/factory_audio/export-micarray-tap-capture.py`。工具只接受 `r1-sample01`，要求显式
录音确认、3448 fingerprint、API 22、SELinux Enforcing、v86 versionCode 和调用方提供的
已安装 APK 精确 SHA-256。输出目录必须是仓库外尚不存在的新目录，创建权限为 `0700`。

工具要求卫星开始时处于 `listening/audio_opened`，暂时停止监听后触发最长 30 秒的受保护
诊断广播。它只解析应用返回且位于固定诊断目录内的七个精确路径，逐个拉取并比较设备端与
主机端 SHA-256，再调用离线审计器。无论审计成功与否，只要已识别本轮路径就尝试精确删除；
最后恢复原监听状态并写入 `result.json`。它不提供安装 APK、刷写 boot、删除通配路径或访问
其他设备的入口。

完成私有签名并记录候选 APK SHA-256 后，实机命令为：

```bash
python3 tools/factory_audio/export-micarray-tap-capture.py <adb-serial> \
  --output-dir /仓库外/新目录 \
  --expected-apk-sha256 <已安装v86-apk-sha256> \
  --confirm-device r1-sample01 --confirm-recording
```

该命令必须由用户明确确认录音后人工执行；本次主机开发未执行它。

## 主机验证

已运行：

```bash
python3 -m unittest \
  tools.factory_audio.tests.test_validation_capture \
  tools.factory_audio.tests.test_micarray_tap_export
ANDROID_SDK_ROOT=/home/sewellzhong/.local/share/android-sdk \
  R1_GRADLE_OFFLINE=1 ./gradlew testDebugUnitTest lintDebug assembleDebug
ANDROID_SDK_ROOT=/home/sewellzhong/.local/share/android-sdk \
  bash tools/factory_audio/check.sh
```

定向 Python 17 项通过；Android 单元测试、lint 和 hostcheck APK 构建通过；原厂音频 107 项
通过，并完成主机代理与 Android API 22/`armeabi-v7a` 代理构建。统一检查通过 Android 179 项、
lint/hostcheck、native 32 项、R0 73 项与演练、原厂音频 107 项、HA 44 项及 HA 2026.8.2
配置加载；公开扫描 384 个文件为 0 发现，凭据扫描无泄漏。最终统一检查生成的 hostcheck APK
SHA-256 为 `c3d6c630ca9ba666bb96f66c45033dcbdfa6578595e002312e259ac4f4f6eecd`，独立包名且使用
合成音，不得部署到 R1。

## 下一入口

先用私有签名生成 v86 设备候选并固定 SHA-256；部署仍须保持当前 v21 boot、不修改分区，随后
在明确录音确认下运行上述受控导出。导出和离线审计通过后，才以四个固定物理方向采集四组
同规格材料并进入四麦独立响应与 DOA 方向矩阵分析。AEC 的受控播放窗口和消除量计算仍是
后续独立步骤，不能由非零 2 参考 sidecar 直接推断通过。
