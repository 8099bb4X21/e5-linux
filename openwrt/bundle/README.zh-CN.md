# OpenWrt 一键刷入包（E5 / T551M / VIPME M8）

> English: [`README.md`](README.md)

请使用与机型对应的包，不能跨机型刷入。包内 `files/device-profile.json` 标明目标机型；
安装和升级会检查机型。没有此文件的旧包仅适用于 E5。

把 OpenWrt 25.12（带 5G 上网、热点、LuCI 和屏幕信息屏）装到设备上，与原来的 Android
共存：Android 不动，OpenWrt 装到 **SD 卡**（独立分区，卡上其余空间保留）上，从 `boot_b` 启动。
随时可以回到 Android。加 `--data` 则装到手机存储里——即改用 SD 卡之前的做法。

## 需要

* 与安装包对应的设备，**bootloader 已解锁**，Android 已用 **Magisk** 获取 root；
* Android 在 slot a 运行（出厂状态就是）；
* 卡槽里插一张 **4 GB 以上的 SD 卡**（建议 8 GB）：它会被重新分区并清空，其余空间留给以后加分区。
  用 `--data` 则不需要卡，但要手机存储至少 2.5 GB 可用；
* 一台 Windows、macOS 或 Linux 电脑，装有：
  * **Python 3.8 或更新版本**（Windows 从 https://www.python.org/downloads/ 安装，勾选“Add python.exe to PATH”）；
  * **adb**（Android platform-tools：https://developer.android.com/tools/releases/platform-tools ，
    解压后把目录加入 PATH，或者把 `platform-tools` 文件夹放到刷机包目录里）；
  * Windows 还需要设备的 USB 驱动（多数情况下系统会自动安装）；
* USB 数据线。

## 刷入

1. 在设备上打开 USB 调试，用数据线连上电脑，在手机上允许调试；
2. 在 Magisk 里给 **Shell** 超级用户权限（第一次运行时手机会弹窗，选允许）；
3. 解压刷机包，在目录里运行：

   * **Windows**：双击 `flash.cmd`（或在命令提示符里运行 `flash.cmd`）；
   * **macOS / Linux**：`./flash.sh`

   想先确认设备没问题、什么都不写入，可以先运行 `flash.cmd --check` / `./flash.sh --check`。

   脚本会询问 APN、热点名称和密码。APN 直接回车即可：OpenWrt 会按 SIM 卡的运营商自动选择
   （移动 `cmnet`、联通 `3gnet`、电信 `ctnet`、广电 `cbnet`；其他运营商用网络默认的 APN），
   换卡后也会自动更新。密码直接回车会生成随机密码并在最后显示。也可以写在命令行里：

   ```sh
   flash.cmd --ssid E5-OpenWrt --wifi-key 12345678 -y        (Windows)
   ./flash.sh --ssid E5-OpenWrt --wifi-key 12345678 -y       (macOS / Linux)
   ```

   在分区、格式化 **SD 卡** 之前会再确认一次，需要输入 `yes`；输入别的或不回答都会中止，
   卡不会被改动。（`-y` 跳过所有询问。）

4. 等脚本显示“完成”，再手动重启进入 OpenWrt；安装器不自动重启，第一次启动约 2 分钟。

脚本做的事情：

* 检查刷机包完整性、设备状态（root、slot a、已解锁、启动控制块）和剩余空间；
  启动控制块按本机 BCAB 格式、CRC 和槽位状态检查，不再要求与打包设备逐字节相同。
* **从这台设备自己的 Android 里提取** Wi-Fi/蓝牙/音频固件和启动基带所需的 vendor 文件，打包成
  `/data/e5linux/device-files.tar`。刷机包里不带任何设备的固件：这些文件属于厂商，而且带有
  每台设备自己的信息（蓝牙地址、序列号），所以每台设备用自己的；
  固件提取、转换及镜像上传均在清卡之前完成，缺文件或上传失败不会先清卡。
* 检查两槽的 `uboot/sml/teecfg/trustos/vbmeta`。Android 释放 TF 后，对有差异的
  启动链先备份 A、B 两份至 `/data/adb/e5-bootchain/`，再从 A 同步到 B 并回读校验。
  相同项不重写；失败尝试恢复 B 原内容，任何失败都不会继续切槽。不会同步 NV。
* 给 **SD 卡** 分区（GPT，一个 Linux 分区）并把 OpenWrt 镜像写上去：这个分区**就是**根文件系统，
  initramfs 直接挂载它（卡上写有 `/etc/e5/sd-root` 标记）。分区只做到镜像大小，卡上其余空间保留，
  留给以后加更多系统或独立的存储分区；
* 把这台设备自己的文件解包进去，首次启动的设置写到它的 `/etc/e5/install.conf`；
  卸载、刷新缓存后以只读方式重新挂载，复核关键文件和固件 SHA-256，通过后才写 boot。
* 把启动镜像写入 `boot_b` 并校验，然后让下次启动走 slot b。**slot a 的 Android 不会被改动。**
  同时记录 userdata 上的 `e5linux/boot-os` 启动目标；最后备份本机 misc 的 32 字节
  启动控制信息、生成 B 槽试启动状态并回读校验。启动链备份也保存在 Android data 内；
* 加 `--data` 则改为把镜像写到 `/data/e5linux/openwrt.ext4`、设置写到
  `/data/e5linux/openwrt-install.conf`，并在写入前**确认三次**。

## 使用

* 热点：用刷机时设置的名称和密码连接；或用 USB 线连接电脑（USB 网卡）。
* 管理页面 LuCI（中文、Aurora 主题）：`http://192.168.9.1`，用户 `root`，密码 `root`，**请尽快修改**
  （LuCI → 系统 → 管理权，或 SSH 里运行 `passwd`）。
* SSH：`ssh root@192.168.9.1`。
* 屏幕：左右键翻页，确认键按按钮，返回键返回；“高级”里有网络模式、频段、APN、充电控制等设置。

## 回到 Android

* 屏幕：高级 → 系统 → 下次启动 Android；
* 或 SSH 里：`e5-next-boot android && reboot`。

从 Android 再回到 OpenWrt（不重装，设置都在，之后默认启动也恢复为 OpenWrt）：连上电脑运行

```sh
flash.cmd --boot-openwrt          (Windows；macOS / Linux：./flash.sh --boot-openwrt)
```

如果 OpenWrt 启动失败，设备会在两次尝试后自动回到 Android。

`--boot-openwrt` 和 Magisk 切回模块也会先检查、同步启动链，再切槽重启。
本安装器仍要求 Android A、Linux B，不能在 Android B 下反向安装。
TF 仍采用预留更新空间的 GPT 布局，不采用占满第一分区的安装方式。

## 更新

安装失败时请保留完整终端报错：程序会显示失败的步骤（分区、写镜像、挂载、
解包设备文件或检查内容）、设备返回的错误和退出码，以及 SD/ext4 内核日志。
内容检查会列出缺失、空文件或没有执行权限的具体路径。分区前会检查卡容量和
只读状态；Android 卷无法卸载时会停止，尚未修改分区表。

设备正在运行 OpenWrt、用 USB 线连着电脑时，用新的刷机包运行：

```sh
flash.cmd --update                (Windows；macOS / Linux：./flash.sh --update)
```

它会通过 USB 网络更新启动镜像和 OpenWrt 镜像，**保留 OpenWrt 的设置**（`/etc/config`、密码、
SSH 密钥、流量记录、信息屏上装的应用）。用 `apk` 另装的软件包不会保留。

**装在 SD 卡上**（默认方式）时，新系统写进卡上的第二个分区——第一次更新时在卡的空闲空间里建好，
以后轮流使用——旧系统照常运行，手机存储（userdata）完全不动。重启后启动新系统。新系统的第一次
启动是试运行：如果没能启动起来，下一次进入 Linux 时会回到之前的系统，设置保持原样（如果设备
已经自动回到了 Android，运行 `./flash.sh --boot-openwrt`）。更新需要卡上
有约一个镜像大小的空闲空间（1 GiB 多一点）。

装在手机存储里（`--data`）时，新镜像在重启后生效，旧镜像保留为
`/mnt/e5-data/e5linux/openwrt.ext4.old`。

## 卸载

回到 Android 后，在 root shell 里执行 `echo android > /data/e5linux/boot-os`（或删掉该文件），
这样卡不再是启动目标，然后把卡取出来，用任意分区工具清掉它的分区即可。用 `--data` 装的则要删
`/data/e5linux/openwrt.ext4`、`device-files.tar` 和 `openwrt-install.conf`。`boot_b` 里的启动
镜像留着也不影响 Android（Android 从 slot a 启动）。

## 免责声明

本刷机包为非官方软件，与荣悦及设备、芯片厂商无关，也未获其认可。刷机需要解锁 bootloader 和
root，可能导致设备失去保修、数据丢失或无法正常使用；修改网络、频段、AT 指令和充电设置也可能
导致断网或设备异常。本软件按“原样”提供，不作任何担保，**风险由使用者自行承担**。刷机前请备份
重要数据；所选频段和无线设置请遵守当地法规。

## 维护者与许可

Enceka <enceka@yeah.net>。脚本和 e5-linux 部分为 MIT 许可（见 `LICENSE`）；OpenWrt、Linux 内核
等组件遵循各自的许可（GPL 等），源码见 OpenWrt 官方和 e5-linux 仓库。
