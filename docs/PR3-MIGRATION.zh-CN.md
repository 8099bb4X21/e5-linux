# PR #3 功能迁移记录

来源：[sprd-linux-devs/e5-linux#3](https://github.com/sprd-linux-devs/e5-linux/pull/3)，固定 head `cf9693e2d5502ed0943d4fef23cfd00fa9f47d57`。按用户确认的审查方案拆分迁移，没有恢复旧 `devices/` 和 `infoscreen/base/` 目录，也没有整体 cherry-pick。

| 功能 | 迁移结果 |
| --- | --- |
| 已有 Wi-Fi、DFS、看板隔离、升级锁 | 跳过重复代码，保留 PR #2 后的实现。 |
| 长短信持久化 | 公共设备仓库独立提交：持久保存片段，完整后才发布、提醒及转发；迁移旧未完成记录，保留删除与去重语义。 |
| 充电唤屏 | 公共内核事件观察 / WebSocket 与 infoscreen transport/mobile 同步迁移；保留锁屏、触摸设置和电话卸载门控。 |
| 启动优化 | 通知已有 SIPC 端口，session 采用有界 100 ms 等待，冷启动无多余清理等待；NV 准备等待保持约 12 秒并使用支持小数的静态 BusyBox；降低串口信息日志，SD 等待仍为 10 秒。 |
| APN | 公共 LuCI、私有拨号 resolver、网络 staging、屏幕编辑器与 MM PAP/CHAP 一同迁移；保留 SIM 身份、防并发、旧 MM 能力和密码权限检查。新 MM r923 已编译。 |
| 共享源码补丁 | Debian-origin 包补丁归入 `debian_device_common/patches`，两种发行版构建使用固定子仓库；旧目录作为兼容链接，历史不重写。 |
| 安装器 | Android 启动链备份、写后校验和失败恢复；可选大小的 userdata 镜像；保留现有旧 SD 只读修复。 |
| 多机型打包 | 共享干净根组装，T551M staging 与私有配置分离，M8 保留默认入口；显式 profile / 内核 / 模板、子仓库来源摘要和模型校验。 |
| block-mount | 真实 APK 补丁在打开路径前过滤设备类型，避免探测 Unisoc 字符通信通道；构建与来源审计纳入工具。 |
| 发布 | 新测试、浏览器回归、SDK x86 模拟与 guarded APK 缓存迁入 release workflow；保留递归检出、来源 SHA、UTC+8 时间及发布仓库自己的 tag target。 |

离线验证包含 36 项短信、15 项 Python APN、70 项 ucode APN 检查、屏幕 / LuCI 浏览器流程、三机型干净根边界、15 项启动链、13 项安装诊断、6 项 userdata 大小与 17 项发布审计。端口通知、事件过滤及 session 等待检查通过；电话卸载回归继续保留。

E5 目前未插入 SIM，真实蜂窝拨号、PAP/CHAP 运营商认证和短信转发无法据此宣布实测通过。三机型完整 Android 安装与 T551M / M8 硬件验证仍需分别记录，不沿用 PR 中其他设备的测试结论。

E5 已刷入 `359ae54` 并通过迁移后的实机回归，详见 [E5-PR3-TEST-20261013.zh-CN.md](E5-PR3-TEST-20261013.zh-CN.md)。release workflow 已更新至 `7c6dd90`；未自动发布新的 GitHub Release。
