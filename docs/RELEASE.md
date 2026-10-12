# 自动打包与发布

[sprd-linux-devs/release](https://github.com/sprd-linux-devs/release) 的
[发布 workflow](https://github.com/sprd-linux-devs/release/blob/main/.github/workflows/release.yml)
构建主线 OpenWrt 一键刷入包，并将产物发布到该仓库的 Releases。主仓库不再运行发布 workflow。支持两种入口：

- release 仓库的 Actions → **Build and publish OpenWrt** → **Run workflow**。可选择 e5-linux 源码 ref、OpenWrt 版本、
  内核分支、tag 或 commit；设备仓库、信息屏及插件使用主仓库固定的 submodule 提交，默认发布；关闭 `publish` 只保存构建产物。
- 在 release 仓库推送 `v*` tag。源码由 `E5_SOURCE_REF`（默认 `main`）选择，实际源码提交记录在构建清单中，编译完成后发布同名 Release。

手动构建的 Release tag 为 `build-YYYYMMDD-HHMMSS-<commit>`。包名的时间戳、
`files/VERSION`、`build.json`、内核编译时间和 Release 说明都使用同一个构建开始时间，
时区固定为 **UTC+8**，与 runner 所在地区无关。根镜像的 `/etc/e5/build-time` 保存
同一时刻的 Unix 时间戳，供信息屏按设备时区显示。

## 首次配置

现有 boot 构建器保留 E5 原始 Android boot v4 的头、vbmeta 和 AVB 尾；OpenWrt
软件源也曾移除信息屏需要的 WPE 软件包。全新 runner 需要一次性准备这些输入，不能
依赖维护者电脑上的 `dumps/` 和 `work/`。在已能打包的本机执行：

```sh
python3 tools/ci-inputs.py create
```

输出 `out/e5-ci-inputs.tar.gz` 和 `.sha256`。输入仅包括：

- 从 boot 镜像裁剪出的头、vbmeta、尾模板；原 Android 内核和 ramdisk 被清空。
- misc 中通过 CRC 校验的 32 字节 bootloader_control，其他内容清空。
- 用于 initramfs 的静态 ARM64 BusyBox。
- 从已安装包清单提取的 `cog`、`libcogcore`、`libwpewebkit` 文件、链接和依赖。

不包含 Wi-Fi/蓝牙/音频固件、Android vendor 运行库、设备身份、SSH 密钥、用户配置或
本机 kernel 对象。BusyBox 与 WPE 软件包源码分别来自 BusyBox/Ubuntu 和 OpenWrt 的
对应软件包；发布 bootstrap 时应保留对应源码和许可来源。

将输入归档放在固定的 HTTPS 下载地址，例如原 e5-linux 仓库 `build-inputs` Release 的 asset（已有下载地址可以继续使用）。
在 release 仓库的 Settings → Secrets and variables → Actions → **Variables** 配置：

| 名称 | 内容 |
|---|---|
| `E5_CI_INPUTS_URL` | `e5-ci-inputs.tar.gz` 的 HTTPS 下载地址 |
| `E5_CI_INPUTS_SHA256` | 归档的 64 位 SHA-256；用生成的 `.sha256` 文件中的值 |
| `E5_SOURCE_REF`（可选） | tag 构建使用的 e5-linux ref；默认 `main` |
| `E5_KERNEL_REF`（可选） | tag 构建使用的内核 ref；默认 `e5-6.18` |

公开下载地址不需要额外 PAT。工作流通过自带 `GITHUB_TOKEN` 发布 release 仓库的 Release，
只有发布 job 获得 `contents: write`。依赖更新时提交新的 submodule gitlink；主仓库、内核、信息屏、插件及全部设备仓库的
实际提交都记录在 `build.json` 中。输入缺失、SHA 不匹配或归档越界会在编译前停止。

## 构建和发布内容

构建使用 GitHub 原生 `ubuntu-24.04-arm` runner，编译主线发行内核、打过补丁的
ModemManager/BlueZ 和通用 OpenWrt 镜像。主线镜像只装入本次内核的音频/WWAN 模块，
不要求再构建 5.15。补丁 APK 按 OpenWrt 版本和补丁内容缓存；首次构建耗时较长。
checkout 会递归恢复设备与信息屏 submodule；OpenWrt common 的软件包清单包含 `openssl-util`，
镜像构建执行 Base64/HMAC-SHA256 自检，发布校验要求 `/usr/bin/openssl` 存在。
ModemManager 构建结束后会生成 `out/openwrt/e5-modemmanager-build.json`，记录构建脚本、
源码补丁和 APK 的 SHA-256。镜像组装前会核对这些信息；没有记录、源码发生变化或 APK
被替换时直接停止，并提示重编译，避免新镜像混入旧的单卡插件。CI 缓存包含这份记录。
运行环境见 [GitHub runner 文档](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)。

每个 Release 提供：

- ZIP 和 TAR.GZ 一键刷入包。
- `e5-linux-switch-*.zip`：Android 切回已安装 Linux 的 [Magisk 模块](../magisk/README.md)。
- `SHA256SUMS`：刷入包和 Magisk 模块的 SHA-256。
- `build.json`：UTC+8 时间、软件版本、源码提交和输入归档 SHA-256。

发布前核对源码文件、内核模块版本、包内哈希、启动镜像清单、ZIP CRC、两种归档的
逐文件一致性，并检查通用镜像中没有设备专属文件。文件先上传到 draft，全部上传成功
后才公开；已公开的 Release 不会被重跑覆盖。失败时保留诊断 artifact。CI 不连接 E5，
不会刷机或拨号；硬件验证仍在设备上进行。

当前工作流发布 OpenWrt。Debian 一键安装器仍使用独立构建的 Debian 镜像，其通用
发布准备不属于此工作流。

工作流的 tag 指向 release 仓库的提交；固件源码提交取自单独检出的 e5-linux，两者在构建说明中独立记录。旧源码仓库中的历史 Releases 保留。
