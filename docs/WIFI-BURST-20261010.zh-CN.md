# 热点突发流量与自动重启修复（2026-10-10）

## 结论

本次捕获到 Wi-Fi 发送线程在不可抢占内核中长时间不让出 CPU，最终引发
soft lockup 看门狗重启。给发送循环增加 `cond_resched()` 后，配合下述
ARP/DNS 分流及 skb 所有权修正，真实手机客户端完成三轮各 50 秒的反向
TCP 压测，共约 5.09 GiB；平均速率依次为 258、308、308 Mbit/s，后两轮
零 TCP 重传，未重现热点卡死、固件断言或自动重启。原故障版本在约 2–10 秒
内停止传输。这里记录的是三轮测试，不能等同于一次连续 180 秒或长期稳定性验证。

## 故障范围与上游核对

实机使用 SC2355/Marlin3 lite 的 SDIO 通路。原始故障日志中，热点发送期间
`CMD_GET_STATION` 超时，驱动调用 `sc2355_assert_cmd`，WCN 断电复位后留下
`hif->exit`，随后 `NETDEV WATCHDOG` 持续报告发送队列超时。USB 管理连接及
蜂窝接口仍可用，不能据此归为基带或 NV 故障。

已核对：

- E5 系统上游 `Enceka/e5-linux` 的 `fd89c05eff02` 已在当前分支历史中。
- 内核上游 `Enceka/linux-lts-e5` 的 `e5-6.18` 仍为 `020b970e351e`，
  与当前构建基线相同；没有遗漏更新的 Wi-Fi 提交。
- 该内核 Wi-Fi 驱动来自 `2984a2381621`，WCN SDIO 来自 `b639d8804107`。
- E5 上游 `docs/FINDINGS.md` 第 38 节记录的蓝牙关电后仍发送 HCI，导致
  SDIO 锁阻塞的问题已有修复；本次复现前未出现相同的蓝牙关电过程。
- MU300 的 PCIe RX DMA 修复不能代替本机 SDIO 排查，当前 Wi-Fi 源码中对应
  的 `dma_sync_single_for_cpu()` 也已经存在。

## 改动

`devices/t551m/wifi.py` 由 `prepare-kernel.py` 调用，重复执行不重复打补丁。

1. 参考 MU300 的 `7e0acce0a01b` 和 `f4f5e760cfa6`：AP/GO 的 ARP、普通
   UDP DNS 回包走数据队列，避免它们占用固件命令通路。DNS 在修改校验和之前
   返回数据通路；保留 DHCP、EAPOL/WAPI、VoWiFi、RTSP 和原有组播策略。
2. 修正上游 `iface_prepare_xmit()` 的 skb 所有权：原实现不足 headroom 时
   新建 skb 并释放原对象，后续若消息池满而返回 `NETDEV_TX_BUSY`，网络栈会
   重试已经释放的原对象。改用 `skb_cow_head()`，保留 skb 对象，并为桥接或
   TCP 克隆包取得可写的独立头部。分配失败正常释放并计入丢包；独占且空间
   足够的报文不额外分配。不修改发送队列大小、频率、带宽上限或查询周期。
3. 在 `sc2355_tx_thread()` 每轮处理之后调用 `cond_resched()`。高流量下每个
   报文/信用通知会增加 completion，而一轮批量发送仅消费一次；积压时
   `wait_for_completion_interruptible()` 不会睡眠。当前 `CONFIG_PREEMPT_NONE=y`
   内核中，信用耗尽后的忙轮询可能长期不给接收线程运行机会；补上调度点，
   只在内核需要重新调度时让出 CPU，不加入固定延迟或限速。

依据内核 `Documentation/networking/driver.rst`，返回 `NETDEV_TX_BUSY`
不能释放原 skb；`include/linux/skbuff.h` 定义了 `skb_cow_head()` 的语义。

## 已验证与尚未验证

- `test_wifi_tx.py --expect-bug` 对原始 C 函数复现释放原 skb 后仍返回可发送
  状态的问题；修正版通过所有权、共享头部、无需分配及四条失败路径测试。
  测试编译实际提取的函数，使用 ASan/UBSan，skb/分配器由测试替身提供。
- Wi-Fi 模块编译通过，vermagic 与现有 CPU5 内核一致，实机模块 BTF 加载正常。
- 第一版仅包含 ARP/DNS 分流，仍能在 iperf3 下复现，**不足以解决全部掉网**。
  新一轮现场显示 SDIO RX 持有传输锁时停滞，随后查询超时；没有将延长命令
  超时或强制忽略断言当作修复。
- 第二版包含 skb 修复，已热加载；5 秒内发送 5,000 个局域网 ARP 探测帧，
  无新断言。探测的发送 IP 为 0.0.0.0、目标为文档保留地址，不更新客户端的
  网关缓存，不通过蜂窝 WAN。
- 第二版的 rootfs 模块及启动 initramfs 已同步到实机，157 个 rootfs 模块
  校验通过，启动分区尾部保持不变；随后自动重启时通过模块 build-id 确认
  实际加载第二版，之后再热加载第四版进行下述压测。
- 复测期间另有一次 iperf3 无法连接：当时手机仍与热点关联，热点有正常收发，
  但设备上没有 iperf3 进程或 5201 监听。已重新启动仅绑定
  `192.168.9.1:5201` 的临时服务端并记录测试日志；此现象不能当作驱动再次掉网。
- 第二版真实客户端反向 TCP 测试仍失败：手机 `192.168.9.122` 从设备接收，
  前两秒分别约 290 / 313 Mbit/s，随后降为 0。最后一条 `CMD_TX_DATA`
  为 IPv4 UDP 组播（目标端口 5353），3 秒后命令响应超时。该次 SDIO 传输锁
  的最后进入/退出均已完成，MMC 没有新增 CRC、ADMA 或超时错误；不能仅凭
  第一版的栈认定根因是 SDIO 锁死。ARP/DNS 分流与 skb 修复仍不足以解决故障。
- 现场 trace、dmesg、线程栈及 iperf3 输出已保留到 `logs/t551m/wifi2-*`；
  临时探针已自动清理，随后重新加载 Wi-Fi 模块恢复热点。
- 第三版尝试将普通组播也转入 SDIO 数据通路，反向 TCP 在约 10 秒后仍停。
  此时只有少量认证/DHCP 命令，后续 `CMD_SET_IE` 超时；这一实验没有解决问题，
  **组播改动已撤回，保留原先处理方式**。
- 在随后本地 UDP 与客户端流量并发测试中，提前捕获到 SDIO 主控保持 active、
  收发中断不再增长，发送线程持续 runnable、接收线程等待调度。机器随后自行
  重启；pstore 明确记录 `SC2355_TX_THREA` 连续占用 CPU 45 秒触发 soft lockup，
  栈位于发送线程反复清理/打印路径。该记录对应上述缺失调度点的问题。
- 第四版恢复第二版的报文分类，只增加发送循环的 `cond_resched()`，已编译、
  热加载，真实客户端三轮反向 TCP 测试完成，详见结论。第一轮前半段存在
  重传、合计 1057 次，后两轮均为零；没有通过限速消除故障。测试结果保存在
  `logs/t551m/wifi4-iperf-completed.log`，断言跟踪和内核日志保存在
  `wifi4-before-reboot.trace` / `wifi4-before-reboot.dmesg`。这些现场日志属于
  本地诊断资料，不随源码提交；重启证据为 `wifi3-panic.dmesg`。

无硬件测试可在 Linux 中执行：

```sh
python3 devices/t551m/test_wifi_tx.py /path/to/prepared/kernel
```

原始源码加 `--expect-bug` 可复现旧问题；运行 `wifi.py` 后再执行正常测试。
上述真实客户端测试的等价命令为 `iperf3 -c 192.168.9.1 -R -t 50`，服务端
只监听 LAN 地址。

测试电脑不得连接设备热点：它保留原有网络，调试使用 USB/串口，压力流量来自
另一台测试设备。临时 kprobe 只记录命令报文头及故障时的栈，最多运行 15 分钟，
退出删除自身事件和 trace 实例；不增加常驻轮询服务。

## 部署边界

启动 initramfs 也携带 `sprd_wlan_combo.ko`，只替换 rootfs 模块不会让重启生效。
发布时须同步启动镜像、rootfs、模块归档及校验清单，并保持同一内核/BTF 基线。
启动镜像仅写 `boot_b` 前 56 MiB，保留尾部 8 MiB 日志；不写 NV、misc、
Android 启动镜像，不修改 TF 启动逻辑及已有网络配置。

第四版已写入实机启动镜像，写后校验全部通过且尾部未变。模块 SHA-256：
`315842e016135f89801f0ab62b9ce0500c6917db5ec78111679399ec4d28f67c`，
build-id：`abf9bbe05d566213af34402d63db8899ad469773`。
离线 ext4 镜像完成 157 个模块校验及只读 e2fsck 检查。
主动重启后的复验已通过：运行中模块 build-id 与上述值一致，157 个 rootfs
模块及启动分区前 56 MiB 校验正确；热点桥接、USB SSH、蜂窝 WAN、屏幕、
网页、语音服务及 KVM 可用，没有新 Wi-Fi 断言或 soft lockup。这里的语音
检查为服务状态，不代表本次重新进行了实听通话测试。

正式产物 `out/t551m/kernel`、`openwrt-persistent-boot.img`、
`openwrt-t551m-persistent.ext4.gz` 及校验清单已同步；旧产物保留于
`out/t551m/before-wifi4-20261010`，未加入源码提交。没有新增开机诊断服务。
