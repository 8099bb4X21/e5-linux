# PR #3 迁移审查

审查对象：[PR #3](https://github.com/sprd-linux-devs/e5-linux/pull/3)，提交 `cf9693e2d5502ed0943d4fef23cfd00fa9f47d57`。本地重构基线为 `4f3e0f8`。

建议按功能迁移剩余补丁到子仓库，再更新主仓库固定 SHA。不要整批 cherry-pick，也不要将 PR 的旧目录直接合并回来。PR 分支与主分支的共同祖先是 `e4cfda0`，其中一部分变更已经由 PR #2 的 `36d219f` 合入。只看 PR 提交列表会把这些变更重复计算。

本地 `git merge-tree --write-tree --name-only HEAD origin/pr-3` 返回冲突，涉及旧 `devices/`、`openwrt/overlay/`、`rootfs/` 路径以及已经迁出的发布 workflow。模拟没有修改工作区或分支。

## 已有内容

- `8cd558d` 的 Wi-Fi 生命周期、站点指标、看板 RPC 隔离、升级锁已经存在。公共 Wi-Fi 修改器和站点指标脚本与 PR 对应文件一致；测试在拆仓时调整过路径。
- `2b2a916` 的 DFS 回退到信道 36、保留请求带宽已经存在于公共网络 staging。
- 旧 `device-install.sh` / `device-install-image.sh` 的相关保护在 PR #2 后已包含，不应重复迁移。
- OpenSSL CLI、msmtp 依赖已经加入公共软件包清单。新 E5 测试镜像验证了 Base64 与 HMAC-SHA256。PR 新增三机型 TF 打包器中的依赖检查仍需要随该打包器迁移。
- 设备 UI 已直接编入 infoscreen；PR 的 `infoscreen/base/` 锚点替换和整文件覆盖不符合现在的结构。

## 剩余内容与目标仓库

| 功能 / 提交 | 迁移位置 | 处理建议 |
| --- | --- | --- |
| 充电接入事件唤屏 `5b8f5a4` | `openwrt_device_common` 的 `e5_power_events.py`、屏幕 RPC；infoscreen 的 transport/mobile | 搬入事件处理和测试；保留现有锁屏设置及电话插件安装状态门控。其他设备的实测文档不能作为此次 E5 验证结果。 |
| APN 管理 `8d6c81f` | 公共 LuCI、network-startup、e5-apn-auto；infoscreen 的 API/settings/APN UI；`debian_device_common` 的 MM patch | 作为一个完整功能迁移，保留 SIM 身份检查、密码权限、PAP/CHAP 能力检查。重新编译 MM，并更新软件包来源指纹；不能只搬前端。 |
| 长短信持久化 `854ac66` | `openwrt_device_common` 的 sms_pdu、e5-sms-receive、对应测试 | 优先迁移。现有代码已有多段组装，但 PR 进一步将未完成片段持久化，完整后才发布、提醒及转发。验证跨扫描、重启、删除、同参考号复用和旧记录迁移。 |
| Android 启动链保护、TF / userdata 安装 `3478c95`、`8d6c81f` | 主仓库的 boot、tools、Magisk、安装器；各设备 stager；公共 block-mount 构建 | 单独迁移并检查写盘边界。PR 的打包器仍引用旧目录和旧镜像名，需要改为当前设备布局和明确输入。不要将整个 prepare-root/configure-rootfs 覆盖回去。 |
| 启动优化 `cf9693e` | 公共端口通知及网络 staging；infoscreen session；主仓库 boot/init | 拆开端口通知、session 等待和串口日志优化。保留目前 SD 等待上限；PR 的 4 秒上限只在无卡 T551M 上测试，尚不足以证明 E5 / M8 的 SD 枚举余量。 |
| 发布构建与审计 | `sprd-linux-devs/release` workflow；主仓库工具 | workflow 的新测试、block-mount 缓存及 SDK 的 x86 模拟需求应移入 release 仓库。保留当前 recursive submodule checkout、来源 SHA、发布时间及发布仓库的 tag target。 |

## 推荐顺序

1. 长短信持久化，独立迁移并跑完整短信回归。
2. 充电事件和启动端口通知，分别提交；infoscreen 与公共设备仓库同步固定 SHA。
3. APN 全链路，先后端及 MM，再 LuCI / 屏幕，最后实机验证。
4. Android 启动链与多机型安装包，单独验证备份、写后校验、失败恢复和目标机型检查。
5. 在 release 仓库补齐对应构建及审计。

用户确认后已按此顺序迁移剩余功能，保留原 PR 的提交来源；迁移结果见 [PR3-MIGRATION.zh-CN.md](PR3-MIGRATION.zh-CN.md)。此前 E5 测试镜像仍可按其固定 SHA 重现。
