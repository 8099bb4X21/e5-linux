# op系统切换器

适用于 E5、T551M、VIPME M8 的 Android A／OpenWrt B 安装布局，需要 root。
APK 文件为 `op-system-switcher.apk`，包名保留 `com.minikano.e5switch`，可覆盖安装旧版。

点开应用选择 OpenWrt 或 Android，确认后只设置下次启动，再选择是否立即重启。
弹窗跟随系统深浅色，文字、按钮和背景使用明确配色。

## 切换范围

- 读取 misc、当前 Android 槽位，以及 B 槽启动镜像标识；拒绝不支持的槽位、无效控制块和错误 CRC。
- 只修改 misc 偏移 2048 的 32 字节启动控制块并回读校验。
- 不挂载 OpenWrt 分区或镜像，不写 `boot-os`、`default-boot`，不修复文件系统或同步启动链。
- 不更改原有默认启动策略。需要永久默认启动时，进入 OpenWrt 后在网页／屏幕设置。
- 临时文件只放 Android 的 `/data/local/tmp`，完成后删除。
- OpenWrt 启动镜像存在不等于根文件系统完好；存储缺失或系统损坏仍可能启动失败并回退 Android。

旧版 `e5-switch.apk` 会读写挂载 e5root 来改变默认启动设置，请换成新版。
本工具不能用于 MU300／F50／V50，其槽位和启动规则不同。

## 安装

三机型发布包包含 `extras/android/op-system-switcher.apk`，在 Android 中打开安装，
首次使用时授予 root。也可在电脑上执行：

```sh
adb install -r op-system-switcher.apk
```

## 构建与测试

Windows Git Bash，Android SDK + JDK：

```sh
./build.sh
```

构建运行启动控制块 Java 测试，使用原有 debug.keystore 签名，并生成 APK 源码／二进制指纹。
不要删除自己的 keystore，否则不能覆盖原来签名的安装。
`openwrt/bundle/finalize-package.py` 校验指纹后才把 APK 加入发布包。

```sh
python3 test/test_switcher.py
```

测试检查深浅色文字／按钮对比度，并在 WSL 的临时普通文件上执行实际写入命令，
核对只改 misc 的 32 字节、回读一致、临时文件清理、OpenWrt 根内容不变。
构建与静态检查通过不代表已在真机验证每种厂商主题。
