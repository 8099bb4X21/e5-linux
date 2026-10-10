# userdata 故障恢复、充电器插拔亮屏与 E5 OTG 部署

## 自动修复的边界

按用户补充要求，TF 启动默认跳过。普通 userdata 启动仍直接 mount；只有已选择
userdata 根系统、正常 F2FS 挂载失败后，才加载修复脚本和执行检查。没有每次
开机 fsck、全盘扫描、新增 sleep 或额外等待。早期固件读取和启动选择的只读
mount 失败也不触发修复，避免为了 TF 启动而写 Android userdata。

故障流程：确认块设备的 PARTNAME 为 userdata、F2FS magic 正确、没有挂载
（按设备号检查，含别名）和 holders，且非块设备只读；先只读 dry-run。
仅文件系统错误返回码 1/4 允许执行修复；工具/参数/I/O 类错误及干净检查不会
进入写修复。每次启动最多尝试一次。修复后再设块设备只读，复查必须返回 0，
日志不能含 Fail/ASSERT。通过后保存诊断日志、指定下一次 Linux，重启一次，
让之前可能失败的 WiFi/蓝牙早期固件加载也重新进行。

不格式化，不处理 ext4 镜像内部，不触碰物理 NV。失败保留原有救援/回退路径。
原来的 600 秒启动保护计时器会等待正在执行的检查/修复，避免中途重启打断写入。
日志进入启动镜像原有保留区域；正常 TF / userdata 启动不创建修复日志。

这是遇到已知元数据错误时的恢复措施，不能证明 F2FS 反复损坏根因已消除，也
不能恢复已经被覆盖的文件内容。正常路径没有 fsck 开销；initramfs 增加约
0.56 MiB 压缩工具包，不承诺物理加载耗时绝对为零。

## 构建

从已有 OpenWrt ARM64/musl rootfs 或工具目录准备 fsck.f2fs 及动态库：

```sh
python3 boot/prepare-f2fs-tools.py --root /path/to/arm64-openwrt-root
```

默认输出 `out/boot/f2fs-tools`。构建器校验 bundle 的 SHA256，缺失则报错，
避免发布声称支持恢复但缺工具的镜像。可用 `--f2fs-tools` 或环境变量
`E5_F2FS_TOOLS` 指定目录。必须使用兼容 ARM64/musl 的整套工具与库，不能
混入宿主机库。本次使用已用于前次人工恢复的 OpenWrt fsck.f2fs 1.16.0。
工具放在独立 `/repair` 目录，不替换正常 initramfs 的运行库。

## 充电器插入和拔出亮屏

共享屏幕 UI 根据已有状态轮询中的 `battery.online` 的布尔边沿唤醒屏幕，
插入和拔出都生效。首个状态样本只建立基线；Charging / Full / Not charging、
电流变化、充电阈值暂停均不单独触发。未增加轮询。

复用现有亮屏流程：保持锁屏、保持用户手动禁用触控的设置；正常触控随背光
恢复。屏幕已亮时只重置原有息屏计时，不弹出充电器连接通知。

## 验证

- BusyBox ash 执行真实启动函数：6 项恢复边界测试通过；既有早期固件 7 项、
  WCN handoff 6 项回归通过。
- 在 `/tmp` 中构造 128 MiB F2FS 普通文件，修改 checkpoint 节点计数并保持
  CRC 正确。在 E5 上执行即将嵌入的 ARM64 工具：dry-run 返回 1 且文件哈希
  不变，修复返回 1，复查返回 0、无 Fail/ASSERT。没有破坏实机分区来测试。
- 专项 Chromium 测试通过：四次供电边沿均亮屏且锁屏保持；满电/暂停不唤醒；
  用户关闭触控时仍保持关闭；初始化样本不误唤醒；无 JS 错误。
- 既有全量屏幕浏览器测试在 DOM mutation 断言处失败；对 HEAD 原版脚本和
  原版 mobile.js 复测得到相同结果（unchanged=200, dark=10），属于既有断言
  与当前 UI 行为不一致，不能记为本次全量测试通过。专项测试覆盖本次行为。

## E5 部署

以 CID、设备 profile、AW322 驱动和 TF 根挂载核对本机。写入 E5 mobile4
内核及匹配模块、更新 mobile.js；仅覆盖 boot_b 前 56 MiB，保留启动日志尾部。
原启动头和 mobile.js 保存在设备 `/root/e5-otg4-rollback`。
userdata 始终只读；未写物理 NV。原来的默认 Android 选择保留，指定单次
OpenWrt 用于实机验证。第一次重启因 --rearm 在默认 Android 下为 no-op 而
进入 Android；已通过本机 ADB 校验 CID，仅重设下一次启动为 slot B。

E5 启动镜像：`out/e5/boot-mobile4-recovery.img`，SHA256
`676f8d88409eabf500fd97262ac0b0e059182d71a10f0f3786852cef35c5287d`。
T551M 对应镜像：`out/t551m/boot-otg10-recovery.img`；E5 验证时仅完成构建，
随后已按用户要求部署，结果见下文。

### 最终实物验证与离线同步

用户完成三轮 OTG 网卡插拔及熄屏后充电器插入、拔出测试，回复“没问题”。
`work/e5-port/otg4-charge-replugs.txt` 记录三次 host 接入、三次 carrier on、
三次向电脑 192.168.9.43 的 DHCPACK，设备时间为 22:21:00、22:21:28、
22:21:46；`musb_suspend_busy` 为 0。接回电脑后 gadget configured，
无残留主机总线。日志捕获到一次拔线后背光由 0 恢复 255；两种边沿的屏幕
效果及保持锁屏由用户实测确认。临时日志采集已停止。

TF 根文件系统、只读 userdata 及 `/run` 无修复记录再次核对通过。
E5 离线 rootfs、匹配模块、正式 `out/e5/kernel` 和 `out/e5/boot-mobile.img`
已同步；旧输出保存在 `out/e5/release-before-otg4`。历史初次移植用的
features-update.tar.gz 不是本次重新打包的发布物。
T551M 离线 rootfs 候选为 `out/t551m/openwrt-t551m-recovery-wake.ext4.gz`，
完成 ext4 五阶段检查及压缩文件校验；随后随 T551M 部署提升为正式输出。

### T551M 后续部署

核对设备 profile、eMMC CID、OTG10 内核、userdata 内 ext4 根镜像路径及
当前 boot_b 校验值后部署。现有模块逐个校验通过，内核及模块无需更换；
只更新启动镜像和 mobile.js。旧启动头与屏幕文件保存在设备
`/mnt/e5-data/e5linux/recovery-wake-rollback`，boot_b 尾部日志区保留。
没有操作 NV，默认及下次启动均保持 Linux。

重启后读取 boot_b 前 56 MiB 和 mobile.js 校验一致，boot ID 已改变。
启动日志显示 userdata checkpoint 为 clean-unmount，10.47 秒直接挂载成功，
16.33 秒 switch-root，45 个早期模块全部加载成功；没有 f2fs 检查/修复阶段，
`/run` 没有修复标记或日志。健康 userdata 启动未执行 fsck。
电脑 USB DHCP 恢复后 SSH 正常；蜂窝 WAN 的 sipa_eth0 为 up、热点为 AP，
USB gadget configured，无残留主机总线，全局 autosuspend 仍为 2。
屏幕 API 返回供电状态布尔值，cog/WPE 进程正常，新 mobile.js 已加载部署。
验证记录：`work/t551m/recovery-wake-verified.txt`。

本轮没有再次进行 T551M 的物理充电器插拔或 OTG 网卡三轮测试；OTG10 内核
保持此前已通过实物测试的版本，共享亮屏逻辑已在 E5 实测及浏览器专项测试通过。
没有人为破坏 T551M 分区来触发恢复。

正式 `out/t551m/openwrt-persistent-boot.img`、对应 manifest/init、离线
`openwrt-t551m-persistent.ext4.gz` 及 `SHA256SUMS-persistent` 已同步。
旧正式产物保存在 `out/t551m/release-before-recovery-wake`。
新启动镜像 SHA256 为
`64c14981b48587aca97d41a9ce4b1baec6dc10466c4595b69ac02977ab4b6a24`。
