#!/system/bin/sh
# Operates only on a NEW regular image file. Never fsck or resize userdata itself.
set -eu
raw=${1:?raw bytes} selected=${2:?selected bytes}
# Android mksh numeric comparisons can wrap byte counts at 32 bits (10 GiB
# compares equal to 2 GiB). Keep all arithmetic in MiB; bytes are strings only.
raw_mib=${3:?raw MiB} selected_mib=${4:?selected MiB}
for size in "$raw" "$selected" "$raw_mib" "$selected_mib"; do
    case "$size" in ''|*[!0-9]*) exit 2 ;; esac
done
[ "$raw_mib" -gt 0 ] && [ "$raw_mib" -le 2147483647 ] &&
    [ "$selected_mib" -ge "$raw_mib" ] &&
    [ "$selected_mib" -le 2147483647 ] || exit 2
D=/data/e5linux
image=$D/openwrt.ext4.part
mkdir -p "$D"
[ ! -L "$D" ] && [ ! -e "$image" ] && [ ! -L "$image" ] || {
    echo 'staging image already exists or path is unsafe; inspect before retrying' >&2; exit 1;
}
stage=$(mktemp -d /data/local/tmp/e5-ext4.XXXXXX)
mounted=0
bound=0
devbound=0
procbound=0
ok=0
cleanup() {
    rc=$?
    trap - EXIT HUP INT TERM
    if [ "$mounted" = 1 ]; then
        umount "$stage/view" || exit 1
    fi
    if [ "$bound" = 1 ]; then
        umount "$stage/images" || exit 1
    fi
    [ "$procbound" = 0 ] || umount "$stage/proc" || exit 1
    [ "$devbound" = 0 ] || umount "$stage/dev" || exit 1
    [ "$ok" = 1 ] || rm -f "$image"
    rm -rf "$stage"
    exit "$rc"
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM
tar -xf /data/local/tmp/e5-ext4-tools.tar -C "$stage"
(cd "$stage" && sha256sum -c SHA256SUMS)
mkdir "$stage/images"
mkdir "$stage/dev" "$stage/proc" "$stage/etc"
mount --bind /dev "$stage/dev"
devbound=1
mount --bind /proc "$stage/proc"
procbound=1
ln -s /proc/mounts "$stage/etc/mtab"
mount --bind "$D" "$stage/images"
bound=1
tools() { name=$1; shift; chroot "$stage" "/usr/sbin/$name" "$@"; }
gzip -dc /data/local/tmp/openwrt.ext4.gz > "$image"
[ "$(stat -c %s "$image")" = "$raw" ]
chmod 600 "$image"
# Write actual zeroes rather than promising capacity with a sparse file.
if [ "$selected_mib" -gt "$raw_mib" ]; then
    dd if=/dev/zero of="$image" bs=1048576 seek="$raw_mib" \
        count=$((selected_mib - raw_mib)) conv=notrunc,fsync
fi
[ "$(stat -c %s "$image")" = "$selected" ] || {
    echo 'image allocation did not reach the selected capacity' >&2; exit 1;
}
tools e2fsck -f -p /images/openwrt.ext4.part || { rc=$?; [ "$rc" = 1 ] || exit "$rc"; }
tools resize2fs /images/openwrt.ext4.part "${selected_mib}M"
tools e2fsck -f -n /images/openwrt.ext4.part
[ "$(stat -c %s "$image")" = "$selected" ]
sync
mkdir "$stage/view"
mount -t ext4 -o loop,ro,noload "$image" "$stage/view"
mounted=1
for name in sbin/init usr/sbin/ModemManager etc/openwrt_release etc/e5/device-profile; do
    chroot "$stage/view" /bin/busybox test -s "/$name"
done
chroot "$stage/view" /bin/busybox true
umount "$stage/view"
mounted=0
umount "$stage/images"
bound=0
umount "$stage/proc"
procbound=0
umount "$stage/dev"
devbound=0
sync
ok=1
rm -f /data/local/tmp/openwrt.ext4.gz /data/local/tmp/e5-ext4-tools.tar
echo "USERDATA-IMAGE-OK $selected"
