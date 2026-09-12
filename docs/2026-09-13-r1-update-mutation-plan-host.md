# R1 包管理变更计划门禁主机记录（2026-09-13）

## 范围与结论

U7 已取得 3448 上生产包 v102 的只读身份与实际 APK SHA-256，但真实安装和显式降级取证会改变设备包状态。本轮新增 `tools/update/prepare-r1-package-manager-mutation.py`，先把候选、精确回滚包、只读证据和后续停止条件封存为不可覆盖的本地计划。工具不包含 ADB 调用，不会推送、安装、降级、提权或改写设备；结果是主机门禁，不是更新、回滚或真实 PackageManager 后端交付。

## 已实现边界

- 必须显式确认 `r1-sample01`，只接受 U7 的 `read_only_package_manager_evidence` 且状态为 `pass` 或 `pass_with_access_limits`；固件必须为 3448、API 为 22、SELinux 为 Enforcing，生产包固定为 `dev.sewellzhong.r1probe`，已安装版本与 APK 哈希必须完整。
- 候选与回滚 APK 必须是 4 KiB～64 MiB 的本地普通文件。使用固定 `aapt dump badging` 和 `apksigner verify --print-certs` 参数数组独立读取身份；拒绝 hostcheck 标记、多签名、错误包名、非递增候选版本和签名不一致。
- 回滚包的版本及实际 SHA-256 必须同时等于只读实机证据中的当前包；历史 v101 备份不能代替当前 v102。输入证据、候选和回滚包均记录实际 SHA-256，计划以 0600、`O_EXCL` 写入，已有路径不覆盖。
- 封存计划列出未来唯一顺序：变更前身份/哈希/AVC，固定私有路径暂存候选，固定包管理升级调用，独立回读升级结果，再暂存精确回滚包并执行显式降级，最后要求版本、哈希和签名全部恢复后清理暂存文件。身份漂移、哈希变化、非 Enforcing、意外重启、升级或回滚未被独立观察及异常无界输出均立即停止。
- 计划生成的确认文本绑定设备、固件、`v102→候选→v102` 和计划摘要；当前工具只生成确认文本，不消费它，也没有执行器。因此不能由生成计划这一动作触发设备副作用。

## 本轮实际结果

- `python3 -m unittest discover -s tools/update/tests -v`：新增后共 19 项通过；计划门禁覆盖无 ADB 正常封存、错误设备、回滚版本/哈希不等于实机、候选不递增、签名不一致、多签名、hostcheck 包和不覆盖已有计划。
- `bash tools/update/check.sh`：更新监督器 Release 构建、CTest 5/5 与 Python 19 项全部通过。
- `ANDROID_SDK_ROOT=/home/sewellzhong/.local/share/android-sdk python3 tools/dev/prepare.py` 及 `ANDROID_SDK_ROOT=/home/sewellzhong/.local/share/android-sdk R1_GRADLE_OFFLINE=1 bash tools/dev/check.sh`：完整通过；公开扫描 501 文件/0 发现、凭据扫描 0 泄漏、Android 单元测试/lint/hostcheck APK、原生工具 47 项、R0 73 项及合成演练、原厂音频 117 项、更新 CTest 5 项及 Python 19 项、HA 102 项与 HA 2026.8.2 配置生命周期均通过。隔离 hostcheck APK SHA-256 为 `02576ab2b098e32d0490389618757dcbf02c1e8f905d4fb8c6d302f63cdd7243`，禁止部署到设备。
- 使用私有提示素材在 API 22/armeabi-v7a 配置构建生产包 v118 成功。仓库外候选为 `local-recovery/r1-sample01/2026-09-13-v118-update-backend-evidence/candidate-v118.apk`，大小 23,945,001 字节，SHA-256 为 `d9262dbd730fea4134bc08a1b7c9d5fc38823982888b13d6dabdc8e3381ad890`；包名、版本 118 和单一签名摘要均已用构建工具回读。该私有 APK 不提交仓库。
- 以现有 `2026-09-12-v102-http-wav-deployment/previous-satellite.apk` 尝试封存时按预期以 `rollback_version_not_current` 停止，因为该文件实际是 v101；没有生成计划、没有调用 ADB，也没有更改 R1。这证明旧部署目录名称不能替代内容身份门禁。

## 未完成项与下一入口

当前缺少与 U7 实机证据完全匹配的 v102 回滚 APK（版本 102、SHA-256 `3ab44785ce54e2a2830de1f2d5d4d1d9198c867e1c8ec0588cf9e21a7b98f0f4`）。下一次受控实机窗口只能先只读导出当前 `base.apk` 到仓库外新路径，在主机复算哈希、用 `aapt`/`apksigner` 复核版本/包名/签名，并再次确认设备仍是相同 serial、3448、Enforcing 和 v102；随后才能生成有效计划。真实执行器仍须单独实现并消费完整确认令牌，固定记录升级/显式降级返回值、前后身份/哈希和 AVC。未满足这些条件前不得安装 v118，也不得以 v101 作为回滚包。
