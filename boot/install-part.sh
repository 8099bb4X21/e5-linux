# The internal-partition install (flash.py --part), finished from the
# initramfs because this is the only place userdata is unmounted: the vendor
# F2FS is shrunk with raw tools only (docs/FINDINGS.md 48), the partition
# table is changed with e5-gpt, the image written into the new partition, and
# the boot then restarts once into the new system (a partition created in
# this boot has no kernel node yet, so it cannot be started in this boot).
#
# Order is the safety property: the filesystem shrinks BEFORE the partition
# table changes, so any failure leaves a disk that Android can still mount
# (a partition larger than its filesystem is normal for Android).  A failed
# run keeps /data/e5linux/part-install.conf, and the next boot retries; the
# steps check their own outcome before continuing.
#
# Sourced by boot/init; install_part_pending DEV is called once per boot with
# userdata's device.  Logs through the caller's log().
install_part_pending() {
    local dev=$1 node=${1##*/} disk=${1%p*}
    local mp=/part-install img dft lo rc cur target need low hi pstart pend found out
    [ -b "$dev" ] || return 0
    # The request: sizes chosen by flash.py on the Android side.
    mkdir -p "$mp"
    mount -t f2fs -o ro,norecovery "$dev" "$mp" 2>/dev/null || return 0
    [ -f "$mp/e5linux/part-install.conf" ] || { umount "$mp"; part_stop; return 0; }
    PART_MIB= DATA_MIB= GROW_FS=
    for kv in $(cat "$mp/e5linux/part-install.conf"); do
        case "$kv" in
            PART_MIB=*) PART_MIB=${kv#*=} ;;
            DATA_MIB=*) DATA_MIB=${kv#*=} ;;
            GROW_FS=*) GROW_FS=${kv#*=} ;;
        esac
    done
    case "$GROW_FS" in 1) ;; *) GROW_FS=0 ;; esac
    umount "$mp"
    case "${PART_MIB:-}" in ''|*[!0-9]*) log "stage=part-install bad-conf"; return 0 ;; esac
    case "${DATA_MIB:-}" in ''|*[!0-9]*) log "stage=part-install bad-conf"; return 0 ;; esac
    [ "$PART_MIB" -ge 2048 ] && [ "$DATA_MIB" -ge 2048 ] ||
        { log "stage=part-install bad-sizes"; part_stop; return 0; }
    target=$((DATA_MIB * 2048)) need=$((PART_MIB * 2048))
    log "stage=part-install start data=$((DATA_MIB >> 10))G part=$((PART_MIB >> 10))G"

    # On-screen progress: the framebuffer console is bound, but the long steps
    # log to files, and the screen shows nothing for minutes otherwise.  A
    # On-screen progress: the long steps log to files, and without this the
    # framebuffer console shows nothing for minutes.  A five-second heartbeat
    # that names the step and counts the seconds makes the install watchable.
    # Everything on the console is plain ASCII: the framebuffer console font
    # has no CJK.  (The backlight is not touched here.)
    part_start=$(cut -d' ' -f1 /proc/uptime)
    echo "1/5 checking userdata" > /run/part-status
    ( while [ -e /run/part-status ]; do
        echo "<3>E5-LINUX: installing, step $(cat /run/part-status 2>/dev/null) ($(($(cut -d' ' -f1 /proc/uptime) - part_start))s)" > /dev/kmsg
        sleep 5
      done ) &
    part_beat=$!
    part_stop() {
        rm -f /run/part-status
        kill "$part_beat" 2>/dev/null
    }

    # 1. the filesystem, raw and unmounted. Its own superblock, not the
    #    tool's chatter, decides whether the shrink landed.
    [ "$(od -An -tx4 -j 1024 -N 4 "$dev" | tr -d ' \n')" = f2f52010 ] ||
        { log "stage=part-install no-f2fs"; part_stop; return 0; }
    awk -v n="$(cat /sys/class/block/$node/dev)" \
        '$3 == n { found = 1 } END { exit !found }' /proc/self/mountinfo &&
        { log "stage=part-install busy"; part_stop; return 0; }
    low=$(od -An -tx4 -j 1060 -N 4 "$dev" | tr -d ' \n')
    hi=$(od -An -tx4 -j 1064 -N 4 "$dev" | tr -d ' \n')
    [ "$hi" = 00000000 ] || { log "stage=part-install huge-fs"; part_stop; return 0; }
    cur=$((0x$low * 8))
    if [ "$cur" != "$target" ]; then
        echo "2/5 shrinking userdata (fsck)" > /run/part-status
        log "stage=part-install shrink cur=$((cur / 2048))MiB target=$((target / 2048))MiB"
        blockdev --setrw "$dev" || { log "stage=part-install ro"; part_stop; return 0; }
        /repair/lib/ld-musl-aarch64.so.1 --library-path /repair/lib \
            /repair/sbin/fsck.f2fs -f "$dev" >/run/part-fsck.log 2>&1
        rc=$?
        case "$rc" in 0|1) ;; *) log "stage=part-install fsck-fail rc=$rc"; part_stop; return 0 ;; esac
        /repair/lib/ld-musl-aarch64.so.1 --library-path /repair/lib \
            /repair/sbin/resize.f2fs -s -t "$target" "$dev" \
            >/run/part-resize.log 2>&1 </dev/null
        low=$(od -An -tx4 -j 1060 -N 4 "$dev" | tr -d ' \n')
        cur=$((0x$low * 8))
        [ "$cur" = "$target" ] ||
            { log "stage=part-install shrink-failed now=$((cur / 2048))MiB (see /run/part-resize.log)"; part_stop; return 0; }
        log "stage=part-install shrunk $((target / 2048))MiB"
    fi

    # 2. the partition table, only now.  ucode is called by its absolute path
    #    and its own output is checked: a piped `list` once hid a ucode that
    #    could not start (a missing library) behind awk's exit status.
    echo "3/5 creating the e5root partition" > /run/part-status
    list=$(/usr/bin/ucode /usr/share/e5-gpt list "$disk") ||
        { log "stage=part-install gpt-list-fail"; part_stop; return 0; }
    found=$(echo "$list" | awk '$4 == "e5root" { print $1 }')
    if [ -z "$found" ]; then
        /usr/bin/ucode /usr/share/e5-gpt resize "$disk" userdata "$target" >/dev/null ||
            { log "stage=part-install gpt-resize-fail"; part_stop; return 0; }
        set -- $(/usr/bin/ucode /usr/share/e5-gpt add "$disk" e5root "$need") ||
            { log "stage=part-install gpt-add-fail"; part_stop; return 0; }
        pstart=$2 pend=$3
        log "stage=part-install partition $1 sectors $pstart-$pend"
    else
        set -- $(echo "$list" | awk '$4 == "e5root" { print $1, $2, $3 }')
        pstart=$2 pend=$3
        log "stage=part-install partition exists $pstart-$pend"
    fi
    [ $((pstart % 2048)) = 0 ] || { log "stage=part-install unaligned"; part_stop; return 0; }

    # 3. the image, through the whole disk at the partition's offset (the
    #    kernel's table for this boot predates it)
    echo "4/5 writing OpenWrt into the partition" > /run/part-status
    mount -t f2fs -o ro,norecovery "$dev" "$mp" || { log "stage=part-install remount-fail"; part_stop; return 0; }
    img="$mp/e5linux/part-install.img.gz" dft="$mp/e5linux/device-files.tar"
    [ -f "$img" ] || { umount "$mp"; log "stage=part-install no-image"; part_stop; return 0; }
    log "stage=part-install write $((pstart / 2048))MiB"
    dd if=/dev/zero of="$disk" bs=1048576 seek=$((pstart / 2048)) count=4 conv=fsync 2>/dev/null
    gunzip -c "$img" | dd of="$disk" bs=1048576 seek=$((pstart / 2048)) conv=fsync 2>/run/part-dd.err ||
        { umount "$mp"; log "stage=part-install write-fail"; part_stop; return 0; }

    # 4. the new root: the device's files and the markers
    echo "5/5 finishing the new root" > /run/part-status
    lo=$(losetup -f) && losetup -o $((pstart * 512)) "$lo" "$disk" ||
        { umount "$mp"; log "stage=part-install loop-fail"; part_stop; return 0; }
    mkdir -p /part-root
    if mount -t ext4 "$lo" /part-root; then
        if [ "$GROW_FS" = 1 ]; then
            # "use the whole partition": grow the image's filesystem to the
            # partition's exact 4 KiB block count (the loop device has no
            # sizelimit, so a bare resize would run into the backup GPT).
            log "stage=part-install growfs $((need / 8192))MiB"
            /usr/sbin/resize2fs "$lo" $((need / 8)) >/run/part-growfs.log 2>&1 ||
                log "stage=part-install growfs-fail (see /run/part-growfs.log)"
        fi
        if [ ! -f /part-root/lib/firmware/wcnmodem.bin ] && [ -f "$dft" ] &&
           tar -xf "$dft" -C /part-root; then
            sha256sum "$dft" | cut -d' ' -f1 > /part-root/etc/e5/device-files.stamp
            log "stage=part-install device-files"
        fi
        mkdir -p /part-root/etc/e5linux
        cp /etc/misc-bc-slot-a.bin /etc/misc-bc-slot-b-trial.bin /part-root/etc/e5linux/ 2>/dev/null || true
        [ -f "$mp/e5linux/part-install.settings" ] &&
            cp "$mp/e5linux/part-install.settings" /part-root/etc/e5/install.conf
        rm -f /part-root/etc/e5/sd-root /part-root/etc/e5/sd-trial
        printf 'e5root %s\n' "$disk" > /part-root/etc/e5/part-root
        echo 1 > /part-root/etc/e5/part-trial
        sync
        umount /part-root
    else
        log "stage=part-install newroot-fail"
    fi
    losetup -d "$lo"
    umount "$mp"

    # The payloads are done with. Removing them is the one write the whole
    # flow makes to the vendor F2FS from Linux; a few unlinks with a clean
    # unmount, the same bargain boot/init takes for one-boot choices.
    if mount -t f2fs -o noatime,nodiratime "$dev" "$mp" 2>/dev/null; then
        rm -f "$mp/e5linux/part-install.img.gz" "$mp/e5linux/part-install.conf" \
              "$mp/e5linux/part-install.settings" "$mp/e5linux/device-files.tar"
        sync
        umount "$mp"
        log "stage=part-install cleaned"
    else
        log "stage=part-install clean-skipped"
    fi
    sync
    part_stop
    log "stage=part-install done"
    # A partition the install created exists in the kernel's table only from
    # the next boot (this boot read the table before it existed), so the
    # selection cannot start it now: restart once, cleanly, into it.  The
    # part-trial marker protects the first start; e5-boot-ok clears it.
    # LK counts slot b's tries down as it boots it, and one try left on a slot
    # that is not successful rolls back at once (nowhere to land but Android):
    # this install boot consumed one, so refill the trial before the restart
    # -- the next boot is the system's first, and e5-boot-ok rearms from there.
    write_misc_bc /etc/misc-bc-slot-b-trial.bin part-install-rearm
    log "stage=part-install rebooting into the new system"
    reboot -f
    return 0
}
