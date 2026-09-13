# R1更新监督器3448设备后端主机与只读实机记录（2026-09-13）

## 结果

在固定argv实机取证通过后，更新监督器新增API 22/ARMv7设备可执行main和
`AndroidPackageManagerBackend`。后端只执行固定参数数组，不接收客户端命令或任意路径；候选和备份路径
必须是监督器事务目录内由32位操作ID派生的`candidate-*`或`previous-*` APK。

独立Java helper通过系统`package` Binder回读已安装包，并使用3448本地`PackageParser`解析归档；两条路径
分别计算实际APK SHA-256和唯一签名摘要。helper不依赖候选APK进程，不使用HA或网络。安装后端采用已实机
证明的固定`app_process ... com.android.commands.pm.Pm install -r [-d]`，只接受单行`Success`或与本次
事务APK路径精确绑定的两行成功格式。

## 构建与验证

- `bash tools/update/check.sh`：CTest 6/6通过，新增后端测试覆盖固定helper调用、3448返回格式、错误路径拒绝、
  事务目录逃逸拒绝及旧APK不覆盖备份。
- `ANDROID_SDK_ROOT=/home/sewellzhong/.local/share/android-sdk bash tools/build-r1-update-supervisor.sh`：
  生成API 22/ARMv7监督器、只读探针和DEX helper；监督器SHA-256为
  `46d5666d7cbf92cbf1503262ed4e69f5ee3d78524afc49a6ff689a1e8b0812d6`，helper为
  `05756e6a06a32afcb3f6263bc9d3c803d8be3027024ff6beacde2eb1695b3869`；固定DEX时间后连续两次构建摘要一致。
- 在`r1-sample01`仅向`/data/local/tmp`临时推送helper、候选及只读探针。探针通过实际原生子进程分别回读
  v102和v118，两个APK哈希匹配既有基线，签名摘要均为`0be7a364…d2639`；返回
  `R1_UPDATE_BACKEND_READ_ONLY_PASS`后临时目录已清理。

## 部署边界

仓库新增init及专用Enforcing策略模板，但尚未写入boot。模板没有网络、块设备、Loader、分区、mount、
ptrace或permissive能力。下一步先把监督器、helper、init及策略作为仅增加自有文件的boot候选进行离线门禁，
再按当前boot双读、单次写入和复位前完整读回流程做失败关闭启动探针。取得真实AVC前不得预写宽泛权限；
当前结果不是独立监督器更新/自动回滚实机通过。
