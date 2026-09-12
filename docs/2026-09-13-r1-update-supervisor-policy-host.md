# R1 独立更新监督策略主机记录（2026-09-13）

## 本轮范围

开始实现签名更新、健康检查及失败回滚，先固定不能由候选APK自身承担的事务策略。新策略位于`android/update-agent/`，与卫星APK和启动后永久降权的原厂音频代理分离。这样即使候选服务启动失败，回滚决定仍属于独立生命周期。

受测实现提交为`bdbf33bebbcc482748d633abbc58edb3ed7066ec`。

本轮没有实现或部署root守护进程、包字节传输、PackageManager调用、事务落盘、init/SELinux模板，也没有连接R1、ADB或HA。现有ADB人工回退工具不因此变成自动OTA。

## 策略边界

- 只接受`dev.sewellzhong.r1probe`，来源版本必须等于当前已安装版本，目标版本必须严格递增。
- 清单值和候选文件实际值分别传入；包名、版本、APK SHA-256和签名摘要必须完全一致。候选签名还必须等于当前安装包签名。
- APK限制为4 KiB～64 MiB，健康窗口限制为30～600秒，操作ID固定为32位小写十六进制。
- 安装完成后重新核对实际包名、目标版本、APK哈希和签名，不能把PackageManager返回成功直接当作更新完成。
- 健康门闩要求卫星服务已就绪、持久状态可读、原厂音频代理可达、原包隔离安全四项同时成立。
- 安装后健康失败或超时、安装阶段监督器重启、健康确认前整机重启、安装后身份漂移均转入回滚。
- 回滚完成必须回读来源版本、安装前保存的旧APK SHA-256和原签名；任何不一致进入`failed`，不得清除为成功。

## 已执行检查

- `bash tools/update/check.sh`：通过；CMake Release构建通过，CTest 1项（内部覆盖成功、准入拒绝、超时、部分健康、重启和回滚失败场景）通过。
- `python3 tools/dev/audit-public.py`：469个公开文件，0发现。
- `python3 tools/dev/scan-secrets.py`：0泄漏。
- `bash tools/factory_audio/check.sh`：117项通过，证明新增独立目录未破坏原厂音频门禁。
- `python3 tools/dev/prepare.py && bash tools/dev/check.sh`：未进入构建；当前主机未配置含`ndk/27.0.12077973`的`ANDROID_SDK_ROOT`。因此不把历史Android、HA或恢复测试写成本轮结果。

## 下一入口

实现监督器的原子持久状态和崩溃恢复、只允许固定卫星UID的本地socket、候选字节上限与落盘复核，以及可在主机伪后端测试、在3448实机收集权限证据的PackageManager安装/降级后端。专用Enforcing策略不得赋予网络、块设备、Loader或分区写权限。完成这些以后，卫星APK才能提交候选并回报四项健康；再以签名候选自动注入错误哈希、错误签名、启动失败和健康超时，验证旧版本真实恢复。
