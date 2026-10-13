# e5-switch.apk — 一个悬浮点，切换默认启动系统

给 E5 / M8 / T551M（包名 `com.minikano.e5switch`）。**没有任何界面**：桌面图标点开是一个透明的
Activity，立刻结束；平时你能看到的只有一个**近乎透明的小圆点**浮在屏幕上（44dp，绿色描边，
可拖动）。

- **点一下圆点** → 弹出确认框「切换到 OpenWrt？」→ 确认后永久默认启动 OpenWrt。
- **长按圆点** → 菜单：切换到 OpenWrt / 回到 Android / 隐藏悬浮窗。
- 开机自动恢复（`BOOT_COMPLETED`）。
- 悬浮窗权限用 root 直接 `appops set … SYSTEM_ALERT_WINDOW allow` 授好，不用去设置里翻。

## 它改哪三处（都要 root，Magisk）

| 位置 | 作用 |
|---|---|
| `/data/e5linux/boot-os` | initramfs 选哪个系统（`part` / `android`） |
| `/etc/e5linux/default-boot`（**e5root 里**） | `e5-boot-ok` 只在它是 `linux` 时才每次成功启动续期 B 槽 —— 这才是"永久"的来源 |
| misc @2048，32 字节 | Unisoc LK 的 A/B 启动控制块（与厂商刷机工具 `spreadtrum_flash` 的 `set_active` 同布局） |

启动控制块的布局（`#pragma pack(1)`，32 字节）：

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

分区表、userdata、boot 镜像都不动；写入后会**回读校验**，不一致会在弹窗里给出期望值与实际值，
并让你先别重启。写 `/etc/e5linux/default-boot` 是尽力而为：老版本包装的系统里它是 `android`，
mount 不上时弹窗会提醒"可能只生效一次"（那种情况用新版 `reinstall.cmd` 重装一次）。

## 为什么要有前台服务

纯后台 service 在 app 退到后台一小会儿后会被系统停掉，悬浮点就没了；所以用一个最低优先级的
静音通知把它挂成前台服务（这是唯一的"多余东西"，通知在通知栏里是折叠的）。

## 编译

需要 Android SDK（`ANDROID_HOME` 或 `/d/Android/Sdk`）+ JDK：

```sh
./build.sh
```

`aapt2` → `javac --release 8 -classpath android.jar` → `d8` → `zipalign` → `apksigner`。
第 0 步会先跑 `test/ArmedBlockTest.java`，把 app 算出的启动控制块与本仓库发布的
`files/boot-misc-slot-b.bin`（`5f6200…9e002f…9bf8546d`）和出厂块（`5f6100…9f001e…0be17146`）
逐字节对齐，算错就编不出 APK。签名密钥放在 `debug.keystore`（已 gitignore），这样重复
`adb install -r` 不会因为换钥匙而失败。

产物：本目录下的 `e5-switch.apk`。

## 安装

```sh
adb install -r e5-switch.apk
```

首次运行 Magisk 会询问 root（授权它即可，之后 `appops` 授悬浮窗、读写 misc 都用这个）。若 root
没授上，会弹 toast 并把「显示在其他应用上层」的设置页打开。

## 已验证 / 未验证

- 已在 M8（Android 13）上验证：前台服务运行、root 自动授悬浮窗权限、透明悬浮窗窗口存在
  （`ty=APPLICATION_OVERLAY fmt=TRANSLUCENT fl=NOT_FOCUSABLE`）。
- 写入逻辑（三处内容 + 回读校验）在 T551M 上由脚本手工跑通、块与发布块逐字节一致；
  **"点圆点 → 确认 → 切换"这条 UI 路径还没在真机上点过**。
