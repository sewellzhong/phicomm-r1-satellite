# R1更新包管理只读证据工具主机记录（2026-09-13）

## 范围与结论

U6之后的真实后端设计依赖3448的包路径、包管理入口和SELinux事实。本轮先新增`tools/update/collect-r1-package-manager-evidence.py`，初始受测实现提交为`b57d176427a18a6a9736421b02f083bc0b2f2d24`，把受控实机窗口所需的只读采集固化为失败关闭工具。2026-09-13用户随后明确要求查询，工具在唯一在线的`r1-sample01`上执行，并依据实机差异在`d6772ecfe6e76b0e4baba534bc42b7b2f2331886`修正；查询和工具修正均未执行安装、降级、push、root、remount或分区操作。最终只读核心证据为`pass_with_access_limits`，但仍不是真实PackageManager安装后端、OTA或回滚交付。

## 已实现边界

- 运行者必须同时给出非空ADB serial、`--confirm-device r1-sample01`和全新输出路径。输出父目录按0700建立，JSON以0600及`O_EXCL`写入，已有证据不会覆盖。
- 首先核对`rk322x_echo`、`rk30board`、3448、Android 5.1.1/API 22、`uid=2000(shell)`及`Enforcing`；任一不符均在包管理采集前停止，并保留失败记录。
- 生产包固定为`dev.sewellzhong.r1probe`。正常路径交叉核对`pm path`与`dumpsys package`的包名、versionCode、userId及codePath；若`pm path`不可用，只允许从唯一`codePath`和唯一`split=[base]`推导`base.apk`，并要求`ls -l`回读为普通文件。APK路径只接受无shell元字符的绝对`.apk`路径；冲突、重复字段、多split或非普通文件均失败关闭。
- 先验证独立`sha256sum`输出格式；不可用时尝试设备BusyBox的同名命令。两者均必须返回“64位小写摘要+完全相同路径”的精确格式，否则记录访问限制并把哈希置空，不使用旧shell不可信的退出码，也不用dumpsys摘要替代APK哈希。
- `pm help`只保存退出码、输出摘要及install/`-d`表面能力，不保存整段帮助文本，也不把它解释为安装或显式降级已经运行。dmesg/logcat只保留包含`avc:`的行，每来源最多400行；原始日志中的无关内容不写入结果。
- 所有ADB调用均使用参数数组、`shell=False`和超时；工具源码没有安装、卸载、传输、提权、重挂载或写设备命令。

## 已执行检查

- `python3 -m unittest discover -s tools/update/tests -v`：实机修正后10项通过，新增覆盖3448 `pm`关闭后的受限回退、base.apk普通文件失败关闭、BusyBox摘要和可选logcat超时。
- `bash tools/update/check.sh`：通过；更新监督器Release构建、CTest 5/5及上述Python 7项均通过。
- `ANDROID_SDK_ROOT=/home/sewellzhong/.local/share/android-sdk python3 tools/dev/prepare.py`：通过，固定依赖及API 22/armeabi-v7a JNI重新生成并校验。
- `ANDROID_SDK_ROOT=/home/sewellzhong/.local/share/android-sdk R1_GRADLE_OFFLINE=1 bash tools/dev/check.sh`：完整通过；公开扫描498文件/0发现、凭据扫描0泄漏、Android 269项及lint、native工具47项、R0 73项及合成演练、原厂音频117项、更新CTest 5项及采集器7项、HA 102项及HA 2026.8.2配置生命周期均通过。hostcheck APK SHA-256为`33f31d2949f082fa9c46f922611df03e2a56c8502ca73a3f2e2a907ed1df1a63`，仅含隔离包名和合成素材，禁止部署到设备。
- 文档完成前后运行`python3 tools/dev/audit-public.py`：前次通过，498文件、0发现；最终结果见文档提交前复核。

首次未设置`ANDROID_SDK_ROOT`的`prepare.py`调用在依赖检查处以缺少固定NDK停止；显式使用仓库已有固定SDK后通过，没有连接设备，也不是源码测试失败。

## 2026-09-13实机查询结果

- 唯一在线设备经显式目标确认后匹配`rk322x_echo`、`rk30board`、3448、Android 5.1.1/API 22、`uid=2000(shell)`和`Enforcing`。
- `dumpsys package`确认生产包为v102、UID 10010，`codePath=/data/app/dev.sewellzhong.r1probe-1`，唯一split为`base`；`ls -l`确认`base.apk`为普通文件。设备BusyBox实算SHA-256为`3ab44785ce54e2a2830de1f2d5d4d1d9198c867e1c8ec0588cf9e21a7b98f0f4`。
- 该3448的`pm path`和`pm help`均退出1并返回`error: closed`；系统没有独立`sha256sum`，且旧ADB shell会把“命令不存在”错误文本放入stdout并在主机侧显示退出0，因此后端不得依赖当前`pm` CLI或该退出码语义。
- `service list`可见`android.content.pm.IPackageManager`，进程表可见`/system/bin/installd`；这仅证明服务存在，不证明任何安装、升级或降级调用成功。
- dmesg可读并按上限保留最近400条AVC（已截断），内容主要是当前未信任应用访问input节点的既有拒绝；`logcat -d`在30秒内不退出，记录为访问限制。最终0600证据位于被Git忽略的`test-results/2026-09-13-r1-sample01-update/package-manager-read-only-v4.json`。先前`pm path`、旧userId格式和logcat超时触发的三份`stopped`证据均原样保留，未覆盖。

## 后续入口与未完成项

后续受控窗口使用明确serial并把原始JSON保留在Git忽略的本地目录，例如：

```bash
python3 tools/update/collect-r1-package-manager-evidence.py <adb-serial> \
  --confirm-device r1-sample01 \
  --output test-results/2026-09-13-r1-sample01-update/package-manager-read-only.json
```

只读结果排除了直接假设当前`pm` CLI可用的做法，但尚不足以在固定argv和Binder后端间定案。真实安装、同签名升级、显式降级及其返回值不是只读操作，下一步须先固化使用设备签名候选、已核验v102 APK备份、精确身份、操作前后哈希以及明确确认门槛的取证步骤；本工具不会暗中执行这些步骤。当前也没有设备root守护进程、远程候选下载、真实成功/失败回滚或签名更新实机证据。
