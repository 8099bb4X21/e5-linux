# OpenWrt for E5 / T551M / VIPME M8 -- one-click flash package

> 中文：[`README.zh-CN.md`](README.zh-CN.md)

Use the package matching your device. `files/device-profile.json` identifies
the target; installation and upgrades check it. Legacy packages without that
file are for E5 only. Never flash a different model's package.

Installs OpenWrt 25.12 (5G WAN, hotspot, LuCI and the info screen on the
panel) next to Android: Android stays as it is, OpenWrt
goes onto the **SD card** (a partition of its own; the rest of the card is left
free) and boots from `boot_b`.  Android is always one step away.  `--data`
installs into the phone's storage instead -- the form before the card.

## You need

For installation without an SD card, run `install-userdata.cmd` (Windows) or
`bash install-userdata.sh` (Linux/macOS). The installer shows userdata free
space and asks for an image size in GiB; `--image-size 4` selects 4 GiB.
It reserves at least 1 GiB for Android plus temporary payload space, allocates
and resizes a new ext4 file, then verifies it read-only before committing.
userdata itself is not formatted. Existing images remain in a timestamped
`/data/e5linux/previous.*` directory. A fresh install uses default OpenWrt
settings; the previous image is kept as a backup. Reboot manually when done.

* a matching device with an **unlocked bootloader** and Android rooted with **Magisk**;
* Android running from slot a (as it comes from the factory);
* an **SD card of 4 GB or more** (8 GB recommended): it is partitioned and erased, and
  its free space stays free for more partitions later.  With `--data` instead,
  no card is needed and 2.5 GB must be free on the phone's storage;
* a Windows, macOS or Linux computer with:
  * **Python 3.8 or newer** (on Windows from https://www.python.org/downloads/, tick
    "Add python.exe to PATH");
  * **adb** (Android platform-tools, https://developer.android.com/tools/releases/platform-tools:
    add its directory to PATH, or put the `platform-tools` folder into the package's);
  * on Windows the device's USB driver (usually installed by Windows itself);
* a USB data cable.

## Flash

1. Turn on USB debugging on the E5, connect it, allow debugging on the phone.
2. Grant **Shell** superuser access in Magisk (the phone asks the first time).
3. Unpack the package and run, in its directory:

   * **Windows**: double-click `flash.cmd` (or run `flash.cmd` in a command prompt);
   * **macOS / Linux**: `./flash.sh`

   To see first that the device is fine, with nothing written: `flash.cmd --check` /
   `./flash.sh --check`.

   It asks for the APN, the hotspot's name and key.  For the APN just press
   Enter: OpenWrt picks it from the SIM's operator (China Mobile `cmnet`,
   Unicom `3gnet`, Telecom `ctnet`, Broadnet `cbnet`; the network's default
   for others), again after a SIM change.  Enter for the key: a random one,
   shown at the end.  Or give them on the command line:

   ```sh
   flash.cmd --ssid E5-OpenWrt --wifi-key 12345678 -y        (Windows)
   ./flash.sh --ssid E5-OpenWrt --wifi-key 12345678 -y       (macOS / Linux)
   ```

   It asks once more before it partitions and formats the **SD card** -- type
   `yes`.  Anything else, or no answer, stops it with the card untouched.  (-y
   skips the questions.)

4. When it says done, reboot manually into OpenWrt. Installation does not
   automatically reboot; the first boot takes about two minutes.

What it does:

* checks the package, the device (root, slot a, unlocked, the boot control
  block's live BCAB format/CRC and fallback state) and the free space;
* **pulls this device's own** Wi-Fi/BT/audio firmware and the vendor files
  that boot the baseband off its Android, as `/data/e5linux/device-files.tar`.
  The package carries no device's firmware: those files are the vendor's, and
  they carry each unit's identity (BT address, serial number), so every
  device uses its own. Collection, conversion and payload uploads finish before
  erasing the card;
* after Android releases the card, backs up differing `uboot/sml/teecfg/trustos/vbmeta`
  images from both slots under `/data/adb/e5-bootchain/`, then copies A to B and
  verifies readback. Identical images are not rewritten. On failure it attempts
  to restore changed B images and stops without switching slots. NV is excluded;
* partitions the **SD card** (GPT, one Linux partition) and writes the OpenWrt
  image onto it: the partition *is* the root filesystem, which the initramfs
  mounts straight (the card is marked `/etc/e5/sd-root`).  The partition is only
  as large as the image, so the rest of the card stays free for more systems or
  a store of its own;
* unpacks this device's files into it and writes the first boot's settings to
  its `/etc/e5/install.conf`. Unmounts, flushes and remounts read-only to check
  critical files and firmware hashes before writing boot;
* writes the boot image to `boot_b`, verifies it, and points the next boot at
  slot b. **Slot a's Android is not touched.** It also saves the boot target in
  `e5linux/boot-os` on userdata. Finally it backs up the live 32-byte misc boot
  control block, derives B's trial state from it and verifies the bounded write;
* `--data` instead writes the image to `/data/e5linux/openwrt.ext4` and the
  first boot's settings to `/data/e5linux/openwrt-install.conf`, and asks three
  times before it writes anything.

## Using it

* Hotspot: the name and key set while flashing; or the USB cable (USB network).
* LuCI (in Chinese, Argon theme; System -> System -> Language and Style): `http://192.168.9.1`, user `root`, password `root` -- **change it**
  (LuCI -> System -> Administration, or `passwd` over SSH).
* SSH: `ssh root@192.168.9.1`.
* The panel: left/right turn the pages, confirm presses, back goes back; 高级
  (Settings) has the network mode, bands, APN, charge control and more.

## Back to Android

* On the panel: 高级 -> 系统 -> 下次启动 Android (Settings -> System -> Boot Android once);
* or over SSH: `e5-next-boot android && reboot`.

From Android back to OpenWrt, with nothing reinstalled (the settings stay,
and OpenWrt is the default boot again): connect the E5 and run

```sh
flash.cmd --boot-openwrt          (Windows; macOS / Linux: ./flash.sh --boot-openwrt)
```

A failed OpenWrt boot falls back to Android on its
own after two tries.

`--boot-openwrt` and the Magisk switch module check/synchronize the chain before
switching slots and rebooting. Android A/Linux B and the GPT layout with reserved
update space remain required; reverse-slot installation and whole-partition
formatting are not enabled by this change.

If installation fails, keep the complete terminal error. It identifies the
failed stage (partitioning, writing, mounting, extracting device files or
verifying content), the device's error/exit code and relevant SD/ext4 kernel
messages. Content verification lists the missing, empty or non-executable
files. Capacity and write protection are checked before repartitioning; an
Android volume that remains mounted stops installation before the GPT changes.

## Update

With the E5 running OpenWrt and connected over USB, run the new package's:

```sh
flash.cmd --update                (Windows; macOS / Linux: ./flash.sh --update)
```

It updates the boot image and the OpenWrt image over the USB network and
**keeps OpenWrt's settings** (`/etc/config`, passwords, SSH keys, the traffic
records, the info screen's apps); packages added with `apk` are not kept.

On an **SD card install** (the default) the new system goes into a second
partition of the card -- made in the card's free space by the first update,
reused after that -- while the old one keeps running; userdata is not touched.
The reboot starts the new one.  Its first boot is a trial: if it does not come
up, the next start of Linux goes back to the previous system, settings as they
were (if the E5 fell back to Android meanwhile: `./flash.sh --boot-openwrt`).
The update needs about the image's size free on the card (1 GiB and a little
more).

On an install in the phone's storage (`--data`) the new image takes over at the
reboot; the old one stays as `/mnt/e5-data/e5linux/openwrt.ext4.old`.

## Uninstall

Back in Android, in a root shell: `echo android > /data/e5linux/boot-os` (or
delete that file) so the card is no longer the system to boot, then take the
card out; its partition can be wiped with any partition tool.  A `--data`
install leaves `/data/e5linux/openwrt.ext4`, `device-files.tar` and
`openwrt-install.conf` to delete.  The boot image in `boot_b` does not bother
Android, which boots from slot a.

## Disclaimer

Unofficial software, not affiliated with or endorsed by Rongyue or the makers
of the device and its chips.  Flashing needs an unlocked bootloader and root,
and can void the warranty, lose data or leave the device unusable; changing
the network, bands, AT commands or charging can cut the connection or upset
the device.  Provided "as is", without warranty of any kind: **at your own
risk**.  Back up what matters first, and keep to the local rules for the
bands and radio settings you choose.

## Maintainer and licences

Enceka <enceka@yeah.net>.  The scripts and e5-linux's parts are MIT
(`LICENSE`); OpenWrt, the Linux kernel and the other components are under
their own licences (GPL and others), with their sources at OpenWrt and in the
e5-linux repository.
