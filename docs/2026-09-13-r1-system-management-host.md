# v117 系统诊断与确认式重启主机记录

日期：2026-09-13

实现提交：`1531fb3c5b222914b9ccf91b60cf5d312a67f473`

范围：Android v117、HA集成0.14.0；未连接生产HA、ADB或真实R1

## 结果

- 新增Noise认证的`system_management`响应式服务。请求固定包含32位随机`request_id`，设备响应必须回显请求与操作；未知操作、并发操作、无响应调用和畸形数据失败关闭。
- 只读状态包含APK版本、Android版本/API、固件标识、服务及设备运行时间、服务状态、Wi-Fi连接、RSSI、IP、连接/失败计数、最近故障、音频封锁、软件静音及原厂包隔离状态。不读取或返回SSID、BSSID、Wi-Fi密码、Noise PSK或其他凭据。
- HA新增系统状态sensor、卫星服务重启button和整机重启button；中文入口支持查询版本、连接、故障，以及明确指向当前R1的服务/整机重启指令。来源`device_id`不匹配时不执行。
- 两种重启严格区分。首次响应只把持久操作状态写成`requested`，不反馈完成；HA等待设备重新连接，并以同一操作ID回读到`completed`后才返回成功。服务重启以新的服务实例证明，整机重启以新的Linux boot identity证明；超时、权限不足、断线或`failed`均不反馈成功。
- 服务重启先返回响应，随后用API 22可用的`AlarmManager`重新拉起服务。整机重启调用受Android平台签名保护的`REBOOT`权限；公开hostcheck APK声明权限只用于编译，不能证明普通data APK或当前签名具备权限。

## 自动验证

执行：

```text
ANDROID_SDK_ROOT=/home/sewellzhong/.local/share/android-sdk python3 tools/dev/prepare.py
ANDROID_SDK_ROOT=/home/sewellzhong/.local/share/android-sdk bash tools/dev/check.sh
```

结果：

- 公开扫描461文件、0发现；凭据扫描0发现。
- Android 260项单元测试、lint和hostcheck APK构建通过；hostcheck APK SHA-256为`9ca2fe8df6f268804ad5e685a03ece925678916247376339e70d3ccc085b9324`。
- 系统管理定向测试覆盖响应式服务发现、请求关联、并发拒绝、服务实例确认、boot identity确认、调度失败、严格状态校验、HA按钮、sensor、中文语法及来源绑定。
- 原生工具47项、恢复73项及合成演练、原厂音频117项通过。
- 固定HA 2026.8.2容器102项通过；真实config flow、sensor/button平台注册、卸载及原有设备注册表生命周期通过。

## 证据边界与下一步

1. 以上证明代码、协议和固定HA主机状态机，不证明真实R1已授予`REBOOT`权限，也不证明服务或整机真实重启、音频资源释放、开机恢复和重新连接已经通过。
2. 设备仍运行v28 boot代理与v102 APK；不得把v117 hostcheck APK安装到设备，也不得继承v102的实机结果。
3. 实机候选须使用既有私有素材与设备签名构建，先核对设备/3448、包名、版本、签名和APK SHA-256；自动执行服务重启和整机重启，核对旧音频资源释放、新实例/新boot、Noise重连、静音与闹钟持久状态，以及失败权限不报成功。
4. 下一项独立实现APK、模型及自有用户态组件的签名更新、健康检查和失败自动回滚；现有人工ADB回退工具不等于该功能已经交付。
