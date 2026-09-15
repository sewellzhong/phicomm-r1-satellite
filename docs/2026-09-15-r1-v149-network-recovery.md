# R1 v149网络恢复实机记录（2026-09-15）

设备：`r1-sample01`，3448 / API 22 / SELinux Enforcing，v149，音量 4%。

## 操作与结果

本轮只使用 ADB 的 `svc wifi disable`（保持 8 秒）和 `svc wifi enable`，没有改写网络配置、凭据、密钥或 HA 数据。操作前后保存了脱敏 Wi‑Fi/路由状态及 Native 状态到本地忽略目录：
`test-results/2026-09-15-r1-sample01-v149-network-recovery/`。

- 断开前：`listening`、Noise 连接 1、音频打开、`last_error=null`、失败 0。
- 恢复后首次轮询即回到同一状态；连续观察轮询均保持该状态。
- 恢复后 Wi‑Fi 为 enabled、Supplicant `COMPLETED`、网络 `CONNECTED`。
- 脱敏前后路由无变化，因此本轮证明了链路断开/恢复，不证明 DHCP 导致的 IP 变化恢复。
- 音量仍为 4%，设备端服务未重启，未留下临时文件。

## 结论

网络链路恢复通过；IP 变化、HA 生产路由在地址变化后的重连仍未验证。下一步为在可控网络环境执行一次真实 DHCP/IP 变化并回读 Noise、HA 实体和音频状态，之后再启动 72 小时稳定性观察。

本轮进一步检查了设备侧非特权 DHCP 续租入口；3448 的 shell 未提供可用的 `dhcpcd`、`netcfg` 或 `ip` 命令，因此没有强行改写接口或使用 root。IP 变化子项安全保持 `blocked_safe`，仅保存脱敏前地址摘要，未泄露地址。
