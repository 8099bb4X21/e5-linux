# e5-switch.apk — 点开就是对话框，一键把默认启动切成 OpenWrt

给 E5 / M8 / T551M（包名 `com.minikano.e5switch`）。**没有界面**：Activity 是透明的（`Theme.Translucent`），
点桌面图标**直接弹出对话框**，没有任何自己的页面：

```
   切换到 OpenWrt？
   确认后设备下次启动进入 OpenWrt，并保持为默认系统。
   Android 用户数据、分区表和 boot 镜像都不动。
   [ 取消 ]        [ 回到 Android ]        [ 确认切换 ]
```

- **确认切换** → 写入 + 回读校验 → 报告写进去的块 → 问「现在重启？」（现在重启 / 稍后）。
- **回到 Android** → 同一个对话框反过来（确认后回到 Android，OpenWrt 不删除）。
- 取消 / 返回键 → 直接退出，什么都不做。

## 它改哪三处（都要 root，Magisk）

| 位置 | 作用 |
|---|---|
| `/data/e5linux/boot-os` | initramfs 选哪个系统（`part` / `android`） |
| `/etc/e5linux/default-boot`（**e5root 里**） | `e5-boot-ok` 只在它是 `linux` 时才每次成功启动续期 B 槽 —— 这才是"永久"的来源 |
| misc @2048，32 字节 | Unisoc LK 的 A/B 启动控制块（与厂商刷机工具 `spreadtrum_flash` 的 `set_active` 同布局） |

启动控制块（`#pragma pack(1)`，32 字节）：

```
0..3   slot_suffix[4]     5f 62 00 00 = 0x5F + "_b"
4..7   magic              42 43 41 42 "BCAB"
8..10  version / nb_slot  01 02 00
11     reserved
12..19 slot_info[4] × 2B  priority:4 | tries:3 | successful:1  (+verity:1|reserved:7)
20..27 reserved
28..31 crc32_le           CRC32 over bytes 0..27
```

切 OpenWrt：B 槽 `prio 15 / tries 2 / 未成功`，A 槽 `prio 14` 且保留 successful（可用回退）。
回 Android：A 槽 `prio 15 / successful`，B 槽 `prio 14` 不可用（等于出厂状态）。
`tries 2`（厂商用 6）是本项目一贯的取舍：只试一次，起不来让 LK 自己滚回 Android。

写 `/etc/e5linux/default-boot` 是尽力而为：老版本包装的系统里它是 `android`，mount 不上时结果弹窗会
提醒"可能只生效一次"（那种情况用新版 `reinstall.cmd` 重装一次就对了）。

## 编译

需要 Android SDK（`ANDROID_HOME` 或 `/d/Android/Sdk`）+ JDK：

```sh
./build.sh
```

`aapt2` → `javac --release 8 -classpath android.jar` → `d8` → `zipalign` → `apksigner`。
第 0 步先跑 `test/ArmedBlockTest.java`，把启动控制块的算法与仓库发布的
`files/boot-misc-slot-b.bin`（`5f6200…9e002f…9bf8546d`）和出厂块（`5f6100…9f001e…0be17146`）
逐字节对齐，算错就编不出 APK。

签名密钥是 `debug.keystore`（与 build.sh 同目录，已 gitignore）；签名与校验用的路径都写成**相对路径**，
Windows 下的 keytool/apksigner 不认 `/d/...` 这种 MSYS 路径，否则每次编译都会新生成钥匙、
`adb install -r` 就会因签名不一致失败。

产物：本目录下的 `e5-switch.apk`。

## 安装与验证状态

```sh
adb install -r e5-switch.apk
```

- **已在 M8（Android 13）验证**：点图标立刻弹出确认对话框（logcat `e5switch: ask slot=b`，
  窗口是 `ty=APPLICATION fmt=TRANSLUCENT` 的对话框 + 一个 `fmt=TRANSPARENT` 的透明 Activity，
  没有任何自己的界面）；取消/返回不写入任何东西。
- 写入这三处的内容在 T551M 上由脚本手工跑通、与发布块逐字节一致；**app 里点"确认切换"这条
  UI 路径还没在真机上点过**。
