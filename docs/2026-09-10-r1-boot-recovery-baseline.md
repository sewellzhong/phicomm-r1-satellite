# r1-sample01 原厂 boot/recovery 离线基线（2026-09-10）

## 范围

用户决定跳过当前物理Maskrom验证后，本步只处理已经从设备读取并通过A/B整体复核的Loader
image副本，不连接R1、不生成修改镜像，也不执行Root、刷写或分区写入。该image缺少物理
eMMC首4 MiB，因此本步不能替代完整eMMC备份、独立低层入口或受控回刷门槛。

## 分区提取与双份复核

Android盘点给出的物理扇区减去Loader image固定偏移8,192扇区，得到以下只读提取范围：

| 分区 | image起始扇区 | 长度 | A/B SHA-256 |
| --- | ---: | ---: | --- |
| kernel | 73,728 | 12,582,912字节 | `0c5a68e77346e290250c655bbad782fec731346bc0263ee997fdf1e575ef8169` |
| boot | 98,304 | 12,582,912字节 | `f904c534e62323dbbcaccf159056c5dcb3797cfcce6eaf2edcbd39c0ed50ad58` |
| recovery | 122,880 | 33,554,432字节 | `05bdb5266fb0c3e326b7d884687e05f27680bd6751890225c54c7fd24c33209e` |

三个分区均分别从copy-a和copy-b提取，尺寸正确且逐字节一致。原始镜像、ramdisk内容、设备树
及清单只保存在被Git忽略的
`local-recovery/r1-sample01/2026-09-10-boot-recovery-baseline/`，不进入公开仓库。

## boot image结构

`boot`和`recovery`均为Android boot image，页大小16,384字节；二者共用：

- 7,735,864字节ARM zImage，SHA-256
  `9ae541809bf9f05ae00145876814fbc4d049e19801bf15a23c6a579b0d5d40a8`；
- 271,360字节Rockchip `RSCE` second stage，SHA-256
  `3f0b6aa367b5c9bc8a2f357d759fb60fab4106748ebd59552226395eabe9bf1d`；
- second stage内唯一DTB位于偏移2,048，长度79,298字节，SHA-256
  `ac5f7f3b6a4612486ab348a3bdb6aabb41439b9999115dc540720f76e0f44993`。

boot ramdisk为1,492,140字节，recovery ramdisk为2,962,916字节，均通过gzip完整性检查和
cpio路径检查后离线解包。boot ramdisk的 `default.prop` 为 `ro.secure=1`、
`ro.debuggable=1`、持久ADB；这与2026-09-06标准 `adb root` 返回提示但实际UID仍为2000的
实机结果一致，不构成新的免刷Root入口。

## 硬件约束

DTB根兼容项为 `rockchip,rk3229`，启动参数为
`vmalloc=496M psci=enable rockchip_jtag`。音频相关已启用节点包括I2S0/1/2、SPDIF、
RK322x codec、ES7243、ES8323、AK7755音频卡及对应pinctrl；DTB还包含但禁用的NAU8540和
MA4音频卡描述。任何未来补丁boot必须保留相同内核、RSCE/DTB、页大小、地址、硬件节点和
启动参数，除非单独形成可回退且有实机证据的变更。

## 判定与下一步

原厂kernel/boot/recovery的本地双份基线已建立，可用于未来补丁构建前的输入校验与回退
比对。它不补齐物理首4 MiB，也不改变R0 `pending`。在用户恢复R0物理入口/完整回刷验证或
明确作出降级决定前，不生成可部署修改镜像，不执行Root或刷写。

公开参考 `docs/references/r1-3448-boot-baseline.json` 只记录设备身份、结构和哈希，不包含
原厂字节。新增的验证器会复读私有清单、三份来源证据、kernel/boot/recovery A/B文件、
Android boot头、内核、second stage和DTB：

```bash
python3 tools/recovery/r1-boot-baseline.py verify \
  --reference docs/references/r1-3448-boot-baseline.json \
  --manifest local-recovery/r1-sample01/2026-09-10-boot-recovery-baseline/baseline-manifest.json \
  --output local-recovery/r1-sample01/2026-09-10-boot-recovery-baseline/verification-report.json
```

真实本地复读结果为 `pass`；报告SHA-256为
`7986e876221664a4858bc8c191068361f5038ee3fa77a37978ae82e938827808`。私有overlay渲染器
现在除R0、ABI和实机预检外，还要求该报告的设备fingerprint、公开参考哈希及私有清单哈希
全部匹配。R0为 `pending` 时仍在第一道门禁停止，不生成overlay或修改镜像。
