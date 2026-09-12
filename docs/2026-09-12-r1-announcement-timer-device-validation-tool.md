# v105 主动播报与计时器自动实机验证工具

日期：2026-09-12

## 结论

提交`e755d0a7fc0f88603ce13bac34b948c3c066c59f`补齐v103主动播报和v104本地计时器的
首轮自动实机验证入口。工具使用真实HA REST服务驱动已配对的ESPHome Native API链路，
同时通过仅限root/shell的ADB本地socket读取R1状态；不以直接构造protobuf或仅调用本地控制
接口代替HA协议命中。

本轮只实现并完成主机测试，没有连接家庭HA、ADB或R1，没有安装APK。设备仍运行v102，
因此主动播报、计时器和新增分段诊断均保持实机待验证。

## 验证行为

- `announcement`调用HA标准`assist_satellite.announce`服务。R1新增有界的分段开始/完成
  计数，使固定前置提示音和正文的两个实际播放段可由状态回读区分；工具同时要求请求、成功、
  失败计数和首次写入、排空、释放时间形成完整闭环。
- `timer-expiry`调用HA标准`conversation/process`中文入口，并绑定HA设备ID，使HA计时器管理器
  经已注册的ESPHome timer handler发送标准事件。工具要求初始没有活动或响铃计时器，观察
  `started`及活动状态、等待本地或HA `finished`产生真实铃声，再调用shell-only `timer-stop`
  并确认响铃、输出线程和停止计数恢复。
- 管理CLI现已公开已有的`timer-status`和`timer-stop`动作，但仍只通过Android localabstract
  socket接受root/shell对端；没有新增公网管理面或认证绕过。
- HA令牌只从指定环境变量读取，不支持命令行明文参数。报告不保存令牌、中文输入、媒体URL、
  HA响应正文或家庭对话；输出文件只能新建在被Git忽略的`test-results/`下。
- 计时器场景拒绝覆盖已有活动或响铃计时器。异常时尝试停止铃声并通过调用方提供的中文取消
  语句清理本轮计时器；清理失败仍保留原始失败，不把未知设备状态写成成功。

## 主机门禁

使用本地固定Android SDK运行`python3 tools/dev/prepare.py`和`bash tools/dev/check.sh`，结果：

- 公开扫描412个文件、0发现，secret scan 0；
- Android 208项单元测试、lint及hostcheck APK构建通过；
- 原生工具40项、恢复73项与合成演练、原厂音频117项、HA 51项及固定HA 2026.8.2配置
  加载检查全部通过；
- hostcheck APK SHA-256为
  `a2b0d80cdbd5aa13cb1d205b199786ed4a9c6a81a198720d302227a3937bc0f5`，不可部署首台。

新增主机测试覆盖双段播报必须全部开始并完成、缺段失败关闭、计时器到期/铃声/管理停止状态
闭环、拒绝修改已有计时器，以及管理CLI动作存在性。

## 实机入口与剩余边界

实机执行前仍须固定源码提交、使用仓库外原签名和中文素材构建设备APK、记录APK SHA-256，
按既有部署门禁核对`r1-sample01`、API 22、3448固件、回退APK和当前原厂包隔离状态。令牌应为
本轮临时环境变量，运行后立即撤销；固定合成WAV应由HA可访问的受控HTTP端点提供。

工具入口为`tools/native/validate-announcement-timers.py`。输出建议写入按日期和设备命名的
`test-results/`私有目录。当前两个场景只覆盖播报双段完成和短计时器到期/停止；updated、
cancelled、暂停恢复、断网、服务/整机重启、不可信时钟、重放去重和资源长稳仍须后续自动场景。
本工具通过也不代表这些剩余行为、R0恢复门槛或任何真人声学体验通过。
