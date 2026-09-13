# R1 3448包管理升级与显式降级实机记录（2026-09-13）

## 范围与结论

U9首次消费封存计划`81c96655ceed62c50faf32870f40fb4802cff980feec47e178aeed8694523768`。
设备、3448/API 22、shell UID、Enforcing、候选v118及精确v102回滚包均通过实时门禁；两包推送后设备端
SHA-256也与计划一致。执行只替换`dev.sewellzhong.r1probe`，没有修改boot、system、recovery、Loader、
分区表或SELinux状态。

真实3448 `app_process`包管理入口完成了同签名v102→v118及`-d`显式v118→v102，但它的成功输出是
固定两行`pkg: <本次APK路径>`和`Success`。初始执行器只接受单行`Success`，因此在已经独立观察到v118
后保守进入紧急回退；回退实际恢复v102后又因同一解析差异把报告记为失败。不可覆盖的0600证据位于
Git忽略目录`test-results/2026-09-13-r1-sample01-update/mutation-execution-81c96655ceed62c5.json`。

## 恢复核对

- 独立回读为v102，APK SHA-256仍为`3ab44785ce54e2a2830de1f2d5d4d1d9198c867e1c8ec0588cf9e21a7b98f0f4`。
- SELinux保持`Enforcing`，两个固定远端暂存APK均已清理。
- `NativeSatelliteService`已重新启动；管理状态为`listening`、`audio_opened=true`、
  `factory_isolation=packages_hidden`、`last_error=null`。
- 报告中的`rollback_restored=false`只表示旧解析器没有接受回退返回，不能覆盖上述独立设备回读；
  同时也不能把该次失败报告改写为通过。

## 解析修正与重试门槛

执行器现在只接受两种有界成功格式：单行`Success`，或路径逐字等于本次固定远端APK的
`pkg: <路径>`后紧跟`Success`。错误路径、额外文本及非零退出码仍失败关闭。新增测试覆盖3448格式、
错误路径和多余输出。

首次计划及失败证据不覆盖、不删除、不重复消费。重新只读采集的v6证据仍确认v102/3448/Enforcing，
并据此封存新的`mutation-plan-v2.json`。只有解析修正完成统一主机门禁并提交后，才允许用新计划再执行
一次v102→v118→v102；该结果仍只是固定argv后端取证，不是独立监督器自动更新/回滚交付。
