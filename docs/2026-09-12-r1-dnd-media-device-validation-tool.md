# v110/v111 免打扰与媒体自动实机验证工具

日期：2026-09-12
范围：主机工具与模拟状态测试；未连接 HA、ADB 或 R1

## 实现

新增 `tools/native/validate-dnd-media.py`，通过 HA 的认证 REST 服务发起动作，同时只从
`r1-native-control` 回读 R1 自身状态。工具要求显式指定 `r1-sample01`、ADB serial、HA URL、
实体 ID 和由环境变量提供的临时 HA 令牌；报告仅允许新建在 `test-results/` 下，不保存令牌、
媒体 URL 或响应正文。

提供三个独立场景：

- `media-lifecycle`：用受控长媒体核对
  `idle -> playing -> paused -> playing -> idle`，核对音量回读，再以受控失败 URL 证明真实后端
  进入有界 `media_*` 错误；结束时停止播放并恢复原音量。
- `media-announcement`：播放长媒体期间并发发起一段足够长的公告，必须观测到公告活动时媒体
  为 `paused`，公告完整结束后媒体自动回到 `playing`；结束时停止媒体。
- `dnd-announcement`：只接受当前免打扰未生效且持久状态有效的设备，保留原时段和闹钟例外，
  以版本化 HA 动作临时打开手动免打扰。公告请求必须增加抑制计数且不得增加媒体段启动数，
  随后恢复原策略；异常路径也使用设备最新版本尽力恢复。

工具把 HA 请求到达与实际执行分开：媒体通过 Android 运行时的 `media_state`、请求/拒绝/失败
计数确认；免打扰通过设备持久策略版本、`active`、抑制计数和公告媒体段计数确认。灯光字段只
记录为 `dim_light_request_only`，不把尚未实现的灯效执行写成通过。

## 主机验证

定向命令：

```text
python3 -m unittest tools/native/tests/test_dnd_media_validation.py -v
python3 -m py_compile tools/native/validate-dnd-media.py
```

结果：6 项测试通过，覆盖媒体完整状态序列、后端故障、命令拒绝、公告抢占恢复、免打扰公告
抑制、既有策略拒绝覆盖、原音量和原策略恢复，并证明 HA 已确认写入但首次设备回读超时时仍会
尝试恢复原策略。以上均为模拟设备状态，不等于 R1 媒体、免打扰或灯效已经实机交付。

## 实机入口与边界

先按现有 `validate-announcement-timers.py` 执行 v103/v104 固定公告与计时器，再对同一签名候选
依次运行本工具三个场景。媒体 URL 应来自局域网受控 HTTP 服务：生命周期长媒体需有足够时长
覆盖暂停/继续，公告抢占用公告也需足够长以便自动轮询捕获重叠状态，失败 URL 必须确定返回
404 或确定无法解码的固定内容。运行前不得存在正在响铃、公告、普通媒体或已生效免打扰。

本轮没有自动连接实际 HA/ADB，没有安装 APK，也没有产生实机报告。正式执行仍须固定源码提交、
正式签名 APK SHA-256、HA 版本、R1 固件与原厂代理版本；随后补断连释放和跨重启持久化场景。
