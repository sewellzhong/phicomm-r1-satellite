# R1 包管理变更有界执行器主机记录（2026-09-13）

## 范围与结论

在 U8 已取得精确 v102 回滚 APK 和有效 `v102→v118→v102` 计划后，本轮新增 `tools/update/execute-r1-package-manager-mutation.py`。执行器已完成主机替身闭环和失败恢复测试，但没有消费真实计划、没有向 R1 推送 APK，也没有执行安装或降级。因此本结果是代码/主机通过，不是 3448 PackageManager 副作用证据、OTA、自动回滚或签名更新交付。

## 执行门槛

- 默认不运行：必须同时提供 `--execute`、计划中逐字一致的完整确认文本、计划绑定的 serial 和固定证据输出路径；缺少任一项时在 APK 工具及 ADB 调用前停止。
- 重新计算计划规范摘要，核对 schema、操作、设备、3448、包名、U7证据文件哈希及确认文本绑定。候选和回滚文件再次复算哈希，并用固定 `aapt`/`apksigner` 参数数组回读包名、版本、大小及单一签名；输入变化在 ADB 前停止。
- 证据输出固定为计划同目录的 `mutation-execution-<plan-id前16位>.json`，以 0600、`O_EXCL` 写入。调用者不能换名重复消费同一计划；成功或失败证据存在时均默认阻止再次运行。
- 实时连接后先核对 `get-state`、完整 3448/API 22 身份、shell UID、Enforcing、当前版本和设备端 BusyBox APK 哈希。任何漂移在推送前停止；此路径不执行远端清理写操作。

## 固定副作用与恢复边界

- 远端文件名只能由计划 ID 前32位派生，位于固定 `/data/local/tmp` 路径；候选和回滚包都在包替换前完成推送及设备端哈希复核。动态值不进入任意 shell 文本，ADB 和主机工具始终使用参数数组、`shell=False`及超时。
- 3448取证调用固定为 `CLASSPATH=/system/framework/pm.jar app_process /system/bin com.android.commands.pm.Pm install -r <candidate>`，显式降级只增加固定 `-d`。退出码必须为0且标准输出必须只有一行 `Success`；随后仍须通过 `dumpsys package` 与设备端实际 APK 哈希独立观察目标版本，不能只信命令返回。
- 成功路径必须先观察 v118，再执行并观察 v102 精确恢复。任一步骤失败时先回读当前包：已经是精确 v102 则不做多余降级；否则只允许一次紧急显式降级重试。最终证据区分原始错误、紧急降级返回和是否恢复，不把恢复成功改写为原操作成功。
- 只有确已开始暂存才清理两个固定远端文件。确认 v102 恢复后尝试启动固定 `NativeSatelliteService`，但服务启动返回不会替代包版本/哈希门槛。变更前后 dmesg 只保存最多400条 AVC；每条普通命令输出最多保留16 KiB，包操作和轮询均有界。

## 主机验证

- `python3 -m unittest discover -s tools/update/tests -v`：共29项通过，其中执行器10项覆盖完整升级/显式降级顺序、缺少执行开关、错误确认文本、输入篡改、实时身份漂移、固定输出与不覆盖、升级返回失败但状态未变、升级返回失败但状态已改变后的单次恢复，以及显式降级失败后的单次紧急重试。
- `bash tools/update/check.sh`：更新监督器 Release 构建、CTest 5/5及更新 Python 29项全部通过。
- `ANDROID_SDK_ROOT=/home/sewellzhong/.local/share/android-sdk R1_GRADLE_OFFLINE=1 bash tools/dev/check.sh`：完整通过；公开扫描504文件/0发现、凭据扫描0泄漏、Android单元测试/lint/hostcheck APK、原生工具47项、R0 73项及合成演练、原厂音频117项、更新CTest 5项及Python 29项、HA 102项和HA 2026.8.2配置生命周期均通过。hostcheck APK SHA-256仍为`02576ab2b098e32d0490389618757dcbf02c1e8f905d4fb8c6d302f63cdd7243`，禁止部署到设备。

## 未完成项与下一入口

真实计划 ID 仍为 `81c96655ceed62c50faf32870f40fb4802cff980feec47e178aeed8694523768`，其固定执行证据路径应为 `test-results/2026-09-13-r1-sample01-update/mutation-execution-81c96655ceed62c5.json`；该文件当前不存在，说明计划尚未消费。下一步先完成统一主机门禁和公开审计并提交执行器；之后若进入实机副作用窗口，必须再次确认设备仍为同一3448/Enforcing/v102基线，并明确接受短暂安装 v118、PackageManager 返回异常或紧急降级也可能失败而导致卫星暂不可用的风险。执行结果只能用于选择固定 argv 或 Binder 后端及最小权限策略，不能直接当作独立监督器自动回滚通过。
