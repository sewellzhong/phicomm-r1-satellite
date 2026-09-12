# Linux 开发与实机验证

## 环境准备

支持 Linux x86_64（参考 Ubuntu 24.04）、JDK 17、Python 3.12、Git、CMake、C/C++ 编译器、make、ripgrep、7-Zip、Docker Engine。安装 Android command-line tools，接受 Android SDK 许可后安装：

```bash
sdkmanager 'platforms;android-35' 'build-tools;34.0.0' 'ndk;27.0.12077973'
git clone https://github.com/sewellzhong/phicomm-r1-satellite.git
cd phicomm-r1-satellite
export JAVA_HOME=/your/jdk17
export PATH="$JAVA_HOME/bin:$PATH"
export ANDROID_SDK_ROOT=/your/android-sdk
python3 tools/dev/prepare.py
docker pull ghcr.io/home-assistant/home-assistant@sha256:56690a89c79a0de98035e1719f8324a92d5859c1192ff45adb0230ea81cb42a5
bash tools/dev/check.sh
```

准备流程需要互联网；Gitleaks 8.30.1、TFLite AAR、protobuf 与测试 JAR 均按固定 SHA-256 下载，ESPHome互操作Python依赖使用带发行包SHA-256的完整版本锁安装到`local-deps/esphome-interop-venv/`。检查只扫描公开文件，不读取被忽略的私有资料。HA 测试容器禁网，不连接实际设备服务。SDK/依赖下载失败、版本不符或校验失败会中止。Gradle wrapper 固定 8.9，协议/TFLite/原生源码版本不随环境自动升级。依赖在 `local-deps/` 重建，不能依赖工作站遗留的虚拟环境；CMake 每次重新配置当前 SDK/NDK 路径，不复制私有密钥。

`check.sh` 构建包名为 `dev.sewellzhong.r1probe.hostcheck`，提示音是短测试音，不是中文回答。所有原生运行库和 Alexa 权重仍参与编译打包。该包只作主机构建检查，不安装到 R1，也不作为可交付 APK。GitHub Actions 使用相同入口，仅保留测试报告。统一检查还运行 `tools/recovery/tests/` 的合成镜像安全回归；恢复工具本身没有设备连接和刷写接口。

主机套件当前包含171项Android、32项部署/诊断工具、73项R0恢复工具、R0桌面演练、54项原厂音频代理/策略/ABI/离线审计测试和44项HA测试，以及lint、hostcheck APK、API 22 ARMv7代理交叉构建和HA配置加载检查。原厂代理测试包括断连释放、1,000/90,000帧的20秒及30分钟预算加速演练；离线审计测试覆盖跨分块提取、双份不一致、篡改、路径逃逸、符号链接、未知通道失败关闭和四方向DOA相对响应。首次在线检查会准备Gradle/AGP自身依赖；相同版本已缓存且 `prepare.py` 已成功后，可用 `R1_GRADLE_OFFLINE=1 bash tools/dev/check.sh` 排除远端仓库波动。另两项既有HA私有路由源码测试位于 `tools/ha/local_tests/`，本地准备原 `local-deps/ha-live-routing-2026-09-06/` 后显式执行；不计入公开套件，不以模拟替身替换其真实源码结论。

## 日常开发

1. 开工先 `git switch main`、`git pull --ff-only`，再 `git switch -c feat/<name>`。
2. 编写功能和与风险相称的测试；无设备时继续完成独立代码工作，不运行部署或实机探测。
3. 执行主机检查，填写 [待验证清单](device-validation.md)，提交并 `git push -u origin HEAD`，创建 PR。
4. 主机检查通过后可合入 `main`，硬件相关功能保持待验证。通过提交、推送和拉取同步分支，保持源码及验证记录可追溯。

不依赖设备的工作可完成。依赖尚未知硬件能力的部分注明假设与阻塞，继续其他可独立开发内容，不将未知能力当成已具备。

## 优化任务与交接

后续任务按[优化分析 O1～O8](2026-09-07-r1-chain-optimization.md)关联到已有功能组：O1随功能记录，O2为播放基础，O3/O5/O6协同流式与HA接入，O4随双入口管理，O8依据机器测量评估；O7使用固定输入、协议事件和状态回读闭环。硬件/配网/蓝牙仍须最小实机功能检查，无设备时可继续独立开发。

PR 与交接记录应注明任务编号、行为变化、依赖与未验证项；协议优先固定版本标准能力，不手写编号。涉及家庭路由/模型中心时，区分本仓库适配与外部实现，记录所需行为契约、实际受测版本及证据，不将替身或旧私有源码测试视为现场能力。诊断默认仅保留有界时间、关联 ID、结果码及计数，不记录正文/凭据。

纯文档变更执行 `git diff --check` 与 `python3 tools/dev/audit-public.py`，并人工检查任务覆盖、链接、历史状态和指标一致性，无需因此构建 APK。功能代码变更仍使用统一 `prepare.py` / `check.sh` 入口并做风险相称检查；不得用文档扫描代替功能测试。

## 实机验证

先保存当前工作，再 fetch 并检出待验证的确切提交。使用原有签名和 `local-deps/private-prompts/assets/`，省略 `-PhostCheck=true` 构建原独立包名。公开 clone 默认缺少中文素材，此构建会明确失败；原素材经校验保留在本地。

```bash
android/r1-probe/gradlew -p android/r1-probe --no-daemon testDebugUnitTest lintDebug assembleDebug
git rev-parse HEAD
sha256sum android/r1-probe/app/build/outputs/apk/debug/app-debug.apk
```

安装前核对 API 22 / 固件 3448、已有签名、原厂备份与回退 APK；使用既有部署工具。保留原有 Android debug keystore，禁止共享到 Git/CI；签名不匹配时停止，不卸载应用绕过。hostcheck 包会被部署工具拒绝。

按清单执行必要最小实机检查，记录日期、设备代号、固件、提交、APK 哈希、命令、预期/实际及失败项。将脱敏结果另作提交推送，记录中的受测提交保持原值。修复后生成新受测提交，不把之前的通过直接沿用。

最终功能/数据/链路自动回归、网络/IP恢复和72小时验收仍等待功能齐备；不恢复KWS训练、非专业真人体验或专项声学测试。依赖受控真人的旧检查由[2026-09-12现行验证边界](2026-09-12-r1-vendor-native-functional-validation.md)取代。本次仓库整理不安装设备。
