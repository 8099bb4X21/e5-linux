# 三机型 TF 与 userdata 安装包

`openwrt/build-profile-tf.py` 是主仓库的打包入口，支持 `e5`、`t551m`、`m8`。设备程序与配置由各独立仓库提供，共享的干净根组装逻辑位于 `device/openwrt_device_common/shared/prepare-root.py`。

它在 Linux / WSL 下以 root 执行，只操作明确指定的离线输入与新工作目录，不访问连接设备。需要 Docker、Python、ARM64 交叉编译器、e2fsprogs、gzip 和 binutils。

输入包括：

- `--base`：从未在设备上启动的通用 OpenWrt 根目录，已包含 infoscreen、字体及所需包；不得含厂商运行库、NV、主机密钥或设备配置。
- `--defaults`：校验过的 OpenWrt armsr/armv8 官方 rootfs tar，供重建初始 UCI 配置。
- `--kernel`：对应机型的内核输出目录，含 `Image`、`Image.lk`、modules、kernel.release 和容器支持清单。
- `--stock-boot`、`--misc-head`、`--busybox`：用于该机型的启动模板与静态 BusyBox。
- `--block-apk`：本次源码构建的 guarded block-mount APK，配套 `.build-id` 和 `.sha256` 必须匹配。
- `--work`：尚不存在的工作目录；`--output`：成品目录。

示例（路径均为准备好的离线输入）：

```sh
git clone --recurse-submodules https://github.com/sprd-linux-devs/e5-linux.git
cd e5-linux
E5_JOBS=4 bash openwrt/build-modemmanager.sh
sh openwrt/build-block-mount.sh
sudo python3 openwrt/build-profile-tf.py \
  --profile e5 --base work/clean-openwrt-root \
  --defaults work/openwrt/openwrt-25.12.5-armsr-armv8-rootfs.tar.gz \
  --kernel out/e5/kernel --stock-boot work/templates/e5-boot.img \
  --misc-head work/templates/e5-misc-head.bin \
  --busybox work/busybox/ext/usr/bin/busybox \
  --block-apk out/openwrt/block-mount-guarded.apk \
  --work work/e5-tf-package-new --output out/profile-packages
```

T551M / M8 必须同时改用对应 profile、内核与启动模板，不能只改包名。ARM64 Linux 可用 `--cc gcc`；其他主机默认 `aarch64-linux-gnu-gcc`。`--apk-image` 默认为 `e5-openwrt-base:25.12.5`。

组装器安装来源指纹已验证的 ModemManager / RPCD APK、guarded block-mount、OpenSSL、msmtp 和文件系统工具；使用选定设备的硬件程序。它生成约 2 GiB 的 ext4 镜像，并记录主仓库、子仓库 SHA、源码摘要、编译辅助工具摘要、内核和软件包信息。

包内 `flash.cmd` / `flash.sh` 默认安装到 TF；`install-userdata.cmd` / `install-userdata.sh` 或 `flash.py --userdata-image --image-size 6.5` 选择内部存储镜像大小。大小按 GiB 解释并以 MiB 对齐，安装器在写盘前检查剩余空间、旧镜像与目标路径。

首次 Android 安装验证机型、已解锁的 A 槽及 live boot-control CRC；完整备份有差异的 A/B 启动链后同步允许的 B 槽组件，写后校验，失败则恢复。Android A 槽和 NV 不写入。系统、固件与 boot_b 校验完成后才设置 B 槽试启动。已运行 Linux 的 `--update` 保留配置和 SD 回退分区，旧式单系统 SD 保留既有启动选择及只读 userdata。

测试分为离线逻辑、完整成品校验和目标设备实测。三机型的干净根组装与边界检查通过，不代表三机型完整 Android 安装均已实测；公开构建记录应分别注明状态。
