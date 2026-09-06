# Git 公开与异地开发整理（2026-09-07）

## 变更

- 初始化 Git `main`，目标为 `sewellzhong/phicomm-r1-satellite` 公开仓库，自有代码使用 Apache-2.0。第三方协议/素材许可单独记录。
- 新增 Linux x86_64 依赖准备、主机检查与固定版本 GitHub Actions；SDK 由环境变量提供，固定提交重建三个 ARMv7 库，校验 TFLite/protoc/Gradle/Gitleaks 下载。
- 原中文提示素材校验后移至家中 `local-deps/private-prompts/assets/`；388 个公开构建所需音频路径由脚本生成短测试音。hostcheck 包名隔离并带标记，两个安装入口均在任何 ADB 操作前拒绝此包。
- 原始证据不入 Git，515 份 JSON 通过保守字段白名单公开结构化副本及来源哈希。公开文档脱敏了本机路径、内网地址和 MAC；历史失败与验收状态保持原结论。
- `AGENTS.md`、README、技术方案及开发指南明确无设备开发边界，新增绑定源码提交和 APK 哈希的实机交接模板。

## 本地主机验证

实际执行（JDK/SDK 环境变量指向本机已安装工具；完整原始日志仅本地保留）：

```bash
python3 tools/dev/prepare.py
bash tools/dev/check.sh
python3 tools/dev/audit-public.py
python3 tools/dev/scan-secrets.py
bash -n tools/install-r1-probe.sh tools/dev/check.sh tools/build-r1-microfrontend.sh tools/build-r1-vad.sh tools/build-r1-noise.sh
```

132 项 Android 测试，失败/错误/跳过均为 0；lint、APK 构建通过。30 项部署/诊断工具测试、44 项公共 HA 测试与 HA 配置加载/卸载检查通过。新增两项测试验证 hostcheck 标记拒绝和普通归档通过标记检查；标记检查不替代既有设备、备份及签名核验。

两个安装入口分别使用 `no-device` 与 hostcheck APK 调用，均直接返回 `host_check_apk_not_deployable`，没有创建指定部署证据目录或连接 ADB。

独立执行 `tools/ha/local_tests/` 的两项测试使用原有私有路由源码、禁网 HA 容器和内存设备替身；其结果另记，公开 CI 不运行或静默跳过这两项测试。没有连接家庭 HA。

## 干净环境与公开审计

通过 `git checkout-index` 导出仅公开文件的副本，未复制 `local-deps/`、私有素材或证据。依赖重新下载、原生库重新编译，使用独立 `GRADLE_USER_HOME` 运行完整主机套件。首次 Gradle 下载遇到 TLS `AEADBadTagException`；保留失败日志，重试标准命令后下载成功。未关闭 TLS 校验或添加本机仓库镜像。

Gitleaks 8.30.1 归档 SHA-256 校验后扫描公开文件。初次三个 generic-api-key 命中均为固定上游 SHA-256；`.gitleaks.toml` 仅针对确切文件与这三个哈希设置例外，复查无命中。自有公开文件审计同时检查禁止路径、二进制/密钥扩展名和常见凭据形式。此扫描不读取被忽略的家庭资料。

整理前 649 个源码/文档/素材文件建立仓库外受保护快照，清单哈希回读通过；迁移后的私有提示素材与原件逐文件一致。原厂备份和旧部署基线保留原位。

## 验证边界

本次没有安装或操作 R1，家中设备仍为原 v63。当前源码的家中构建、签名检查及最小实机验证列入待验证清单，不继承历史通过状态。不恢复语音回归、网络/IP 恢复、72 小时验收或 KWS 专项测试。

远程首次推送与 GitHub Actions 结果在执行后补记；不把本机通过当成云端通过。
