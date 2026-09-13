# R1 独立更新监督器 Enforcing boot 实机记录（2026-09-13）

## 范围与结论

U11 已把独立更新监督器部署到 `r1-sample01` 的 boot ramdisk，并在 3448 / Android 5.1.1 / API 22 / ARMv7 / SELinux Enforcing 下完成启动、受 UID 约束的本地 socket、真实 PackageManager 只读身份回读和普通整机重启恢复。最终 boot SHA-256 为 `ae593541963c5508f7909f47921c46e4122cf8a00318abb6f064c4a00c9f380c`；监督器、DEX helper 与策略 SHA-256 分别为 `0526576c055fb9966834047cbc80436ca5ec379027e0397cfb91446fa762a122`、`2f28f4ef21ebe872357e85a4a892d2297b1000cea64d4d354d0c750ab99c91bd`、`d911d3065e9ca03502e67e3575f149c2f377ab9b38be77a3926023d587cf341e`。

本轮证明的是监督器部署和只读身份自检，不是完整签名更新交付。v118 候选提交、四项健康确认、超时/重启/部分健康失败注入及自动回滚尚未在该监督器上执行；R0 继续为 `pending`。

## 写入与回退门槛

- 每个候选写入前均从 Loader 对 boot 的 12 MiB 范围独立读取两次、逐字节比较并核对当前 SHA-256；只在精确匹配预期版本后单次写入。
- 每次写入后、复位前均完整读回 12 MiB，要求候选和读回 SHA-256 相同且 `cmp` 通过。失败候选同样先双读，再精确写回已知可启动的 candidate 7 `7d0eb8685947cf5b833a4a08984ca84359d4f2d26e802d8ad2ce7fb1682e8703` 并完整读回。
- 构建器确认 kernel、second、页大小、header 和原厂音频 overlay 不变；只改变声明的监督器、helper、init、file_contexts 与 Enforcing policy。没有修改 system、recovery、Loader、参数/分区表、物理首 4 MiB，也没有使用 Permissive。

## 失败迭代保留

候选 8～17 的失败均保留为本地诊断，不改写为通过：

| 候选 | boot SHA-256 | 结果 |
| --- | --- | --- |
| 8 | `dc676f9ed383b64f18ba7532da7000fc437cb3c3809a60b3c90b7856cb75a7d8` | 启动身份自检失败，暴露 ART/fifo/device 基础权限 |
| 9 | `4c39157d4c7f12235e1b3e2b92466a4040f37999d979b57f24e2fe7b81e3e824` | ART 初始化仍失败，暴露 ion/ashmem/sysfs/缓存边界 |
| 10 | `21752c01bad7d99aabfdbb475909e8bdcb8e97c218affebb56e26f3a979f7e17` | 暴露 app_process socket 与只读系统目录边界 |
| 11 | `9c64d147f3ddc4f73b3e5a35cd77282715c79ae2a83170c8bebd018eefd7c5f4` | 暴露 ART image 映射与自连接边界 |
| 12 | `d80335d7b60dbc6942e84b8c93c5dae721fb23c4d150bdf3049ec7201c572029` | helper 启动后 PackageManager 服务查询失败 |
| 13 | `5dee4c79e2f40f3b9f7833d8e4d124e168310698c2e4f4e17f380a8f70a9f54f` | dex2oat 执行被拒绝 |
| 14 | `5b844c2543a99d9363c319debd0cdf04bb67edfdc03b5733c4ce9217410d4b0d` | helper 有界 stderr 被旧判定误作失败 |
| 15 | `f1ae973117004b74d2465e84f4e007fb88d1bb8913609b26a0fff1906baf8200` | 严格 stdout 保持，修正 stderr 后仍确认服务句柄为空 |
| 16 | `22bc509bd867e7d5e463bac7c725155e495b71a4cfc75b48531d20091144374e` | 新日志确认 `IllegalStateException`，servicemanager 无法读取调用域上下文 |
| 17 | `c86096aa6e65d7b17e87e7c56120c4bdde41ad61f340194a5e57e1ac2db9ae34` | 上下文查询通过，servicemanager Binder reply transfer 被拒绝 |

策略只吸收真实 AVC 或 Android Binder 固定调用链所需的有界权限。trace_marker 写入、JDWP 连接、线程调度提升、`sys_nice` 和 cgroup 优化仍保持拒绝；它们没有阻止身份读取。`system_server`/shell 对新域 `/proc` 的枚举拒绝也保留，不作为放宽理由。

## 最终真机证据

- candidate 18 写前两份 boot 均为 candidate 7 精确哈希；候选和复位前完整读回均为 `ae593541…9f380c`。
- 首次启动与一次普通 Android 整机重启后均为 `Enforcing`，`init.svc.r1_update=running`、`init.svc.r1_factory_audio=running`，`/dev/socket/r1_update_supervisor` 在 `/proc/net/unix` 中监听。
- 重启后日志再次出现 `update_supervisor_identity_ready`，证明独立域内真实 helper 已通过 PackageManager 回读，而不是只证明进程存在。
- 安装包仍为 v102，设备只读导出的 APK SHA-256 为 `3ab44785ce54e2a2830de1f2d5d4d1d9198c867e1c8ec0588cf9e21a7b98f0f4`，与 U9 回退基线完全相同。
- 普通重启后卫星依次经过 `waiting_ha`、`opening_microphone`，最终恢复 `listening`；`audio_opened=true`、连接 1、失败 0、`factory_isolation=packages_hidden`、`last_error=null`，音频帧非零增长。
- 最终统一门禁通过：公开扫描524文件/0发现、凭据扫描0泄漏、Android构建/单元测试/lint、native 47项、R0 73项及演练、原厂音频117项、更新CTest 6/6与Python 38项、API 22 ARMv7监督器/helper构建、HA 102项及2026.8.2容器生命周期全部通过。

## 下一入口

以 candidate 18 为当前 Enforcing boot 基线，构建同签名的统一最终候选 APK，而不是继续使用只含分散主机功能的历史版本。随后通过私有 socket 自动执行成功更新、部分健康、健康超时、监督器/整机重启和回滚失败场景；每轮独立核对版本、APK哈希、事务状态、资源释放、原厂音频代理、隔离与最终恢复。签名更新/自动回滚通过后，再按现行顺序运行 v103～v118 的核心功能自动回归；动态闹钟文字仍为 `tone_only`，不能宣称已朗读。网络/IP 恢复与 72 小时稳定性继续留到最终候选功能齐备之后。
