# v95 O3 实际家庭路由流式能力核查

日期：2026-09-12

受测卫星源码：`a189fb007d3ef362d9ca1d06ff28b5b8628db3e7`

范围：仓库外保留的 2026-09-06 家庭路由与模型中心源码快照，以及公开 `r1_input_guard`
会话适配层；不连接家庭 HA、模型服务、TTS、R1 或 ADB。

## 固定输入

- Home Assistant Core 2026.8.2 镜像：`ghcr.io/home-assistant/home-assistant@sha256:56690a89c79a0de98035e1719f8324a92d5859c1192ff45adb0230ea81cb42a5`
- `conversation_router/const.py`：`3fdc73c1287e8784996c1c209f1b04d3076abf6fce25d189d816c4961ef9aeca`
- `conversation_router/conversation.py`：`f42dd2a6d2b0373323b6d5a69d66eb0397d36de9b14e20a3c97af53e7bcef315`
- `domestic_ai/hub.py`：`4e448dd5b917884988d55ad3f7808a363f1eb728fbb89748517a939b1e491bb3`
- `domestic_ai/rules.py`：`1c8b6e53547d6ea6b91691d44150668009c19ec94f2f5eac573d7d0280d2f466`

私有源码只在本地以只读方式挂载，不复制到公开仓库或构建产物。测试对外部模型/
网络依赖使用内存替身，执行的是保留路由源码的原始控制流。

## 自动核查

```text
ANDROID_SDK_ROOT=/home/sewellzhong/.local/share/android-sdk python3 tools/dev/prepare.py
docker run --rm --network none --entrypoint python \
  -e PYTHONPATH=/work/integrations/home_assistant -v "$PWD:/work:ro" \
  ghcr.io/home-assistant/home-assistant@sha256:56690a89c79a0de98035e1719f8324a92d5859c1192ff45adb0230ea81cb42a5 \
  -m unittest discover -s /work/tools/ha/local_tests -p 'test_*.py' -v
```

路由源码显式不声明流式能力。本地回归现在将这一事实与卫星适配器的能力判定绑定：

- 实际路由 `supports_streaming == false`；
- `r1_input_guard` 也必须报告 `supports_streaming == false`，不得向 Assist 伪报增量能力；
- 普通模型请求仍通过该路由执行，并保留来源绑定的 hub 会话；
- 本地控制拒绝仍失败关闭，不会退回模型伪装成功。

最终结果：私有固定源码回归 2 项通过；加入能力断言后仍为 2 项，因为断言被纳入现有
实际路由会话场景。完整 `check.sh` 也通过：公开扫描 397 文件/0 发现，Android 188 项、lint
和 hostcheck APK，原生工具 32 项，恢复 73 项及演练，原厂音频 117 项，HA 51 项及 HA 2026.8.2
加载检查。hostcheck APK SHA-256 仍为
`cc6bd0ad8b8069be2a6e6b30bfc75aac52c4736b43d9e3e813b03ff51fcb3fe2`；Android 源码未变，该 APK 不是设备候选。

## 结论与交接

本次得到的是可复核的“当前实际后端不支持流式，卫星正确失败关闭”结论，不是 O3 通过。
v91～v94 的增量透传、Assist/TTS 替身和 63 秒 PCM 结果仍属于公开契约/主机支持。

下一步必须在家庭路由/模型中心项目中提供真实增量文字、完成/失败、取消、会话期限与结构化
工具结果契约；更新本地固定快照及哈希后，重跑本回归和 v93/v94 管线测试。之后才能在真实 HA/R1
采集首段、TTS 首块、播放写入/排空、取消和至少 60 秒墙钟长回答证据。
