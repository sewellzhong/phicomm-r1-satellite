# R1更新包管理只读证据工具主机记录（2026-09-13）

## 范围与结论

U6之后的真实后端设计依赖3448的包路径、包管理入口和SELinux事实。本轮新增`tools/update/collect-r1-package-manager-evidence.py`，受测实现提交为`b57d176427a18a6a9736421b02f083bc0b2f2d24`，把下一次受控实机窗口所需的只读采集固化为失败关闭工具；按仓库规则没有自动连接R1、ADB或HA，也没有执行安装、降级、push、root、remount或分区操作。因此本结果只是工具/主机通过，不是3448证据、真实PackageManager后端、OTA或回滚交付。

## 已实现边界

- 运行者必须同时给出非空ADB serial、`--confirm-device r1-sample01`和全新输出路径。输出父目录按0700建立，JSON以0600及`O_EXCL`写入，已有证据不会覆盖。
- 首先核对`rk322x_echo`、`rk30board`、3448、Android 5.1.1/API 22、`uid=2000(shell)`及`Enforcing`；任一不符均在包管理采集前停止，并保留失败记录。
- 生产包固定为`dev.sewellzhong.r1probe`。工具交叉核对`pm path`与`dumpsys package`的包名、versionCode、userId及codePath，APK路径只接受无shell元字符的绝对`.apk`路径；冲突或重复字段失败关闭。
- 设备存在`sha256sum`时记录已安装APK实际SHA-256；命令不可用时只记录访问限制并把哈希置空，不用dumpsys摘要替代APK哈希。
- `pm help`只保存退出码、输出摘要及install/`-d`表面能力，不保存整段帮助文本，也不把它解释为安装或显式降级已经运行。dmesg/logcat只保留包含`avc:`的行，每来源最多400行；原始日志中的无关内容不写入结果。
- 所有ADB调用均使用参数数组、`shell=False`和超时；工具源码没有安装、卸载、传输、提权、重挂载或写设备命令。

## 已执行检查

- `python3 -m unittest discover -s tools/update/tests -v`：7项通过，覆盖只读固定命令、0600输出、身份错配、非Enforcing、包路径冲突、哈希能力缺失及不覆盖既有证据。
- `bash tools/update/check.sh`：通过；更新监督器Release构建、CTest 5/5及上述Python 7项均通过。
- `ANDROID_SDK_ROOT=/home/sewellzhong/.local/share/android-sdk python3 tools/dev/prepare.py`：通过，固定依赖及API 22/armeabi-v7a JNI重新生成并校验。
- `ANDROID_SDK_ROOT=/home/sewellzhong/.local/share/android-sdk R1_GRADLE_OFFLINE=1 bash tools/dev/check.sh`：完整通过；公开扫描498文件/0发现、凭据扫描0泄漏、Android 269项及lint、native工具47项、R0 73项及合成演练、原厂音频117项、更新CTest 5项及采集器7项、HA 102项及HA 2026.8.2配置生命周期均通过。hostcheck APK SHA-256为`33f31d2949f082fa9c46f922611df03e2a56c8502ca73a3f2e2a907ed1df1a63`，仅含隔离包名和合成素材，禁止部署到设备。
- 文档完成前后运行`python3 tools/dev/audit-public.py`：前次通过，498文件、0发现；最终结果见文档提交前复核。

首次未设置`ANDROID_SDK_ROOT`的`prepare.py`调用在依赖检查处以缺少固定NDK停止；显式使用仓库已有固定SDK后通过，没有连接设备，也不是源码测试失败。

## 实机入口与未完成项

后续受控窗口使用明确serial并把原始JSON保留在Git忽略的本地目录，例如：

```bash
python3 tools/update/collect-r1-package-manager-evidence.py <adb-serial> \
  --confirm-device r1-sample01 \
  --output test-results/2026-09-13-r1-sample01-update/package-manager-read-only.json
```

取得结果后才能据实选择固定argv或Binder后端并规划最小init/Enforcing权限。真实安装、同签名升级、显式降级及其返回值不是只读操作，仍需单独使用设备签名候选、已核验旧APK备份、精确身份与回退门槛；本工具不会暗中执行这些步骤。当前也没有设备root守护进程、远程候选下载、真实成功/失败回滚或签名更新实机证据。
