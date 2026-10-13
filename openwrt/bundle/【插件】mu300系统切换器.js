//<script>
/*
 * 【插件】mu300 系统切换器 v3
 * 运行环境：设备 Android 侧的网页管理面板（与飞猫系列插件同一宿主）
 *
 * 从 Android 一键切到 Linux（OpenWrt），也可以切回 Android。
 *
 * 一次完整切换要写三处（只写 misc 不是"默认"，只是"试启动一次"）：
 *   misc @2048 的 32 字节 bootloader_control —— LK 下次启动哪个槽；
 *   /data/e5linux/boot-os = part|android     —— initramfs 选哪个系统；
 *   e5root 里 /etc/e5linux/default-boot      —— e5-boot-ok 只在它是 linux 时
 *                                               每次成功启动续期 Linux 槽，
 *                                               这才是"永久默认"。
 *
 * v3：补上 boot-os 与 default-boot（后者尽力而为并回读校验，失败会明说
 *     "只生效一次"），并加回 Android 方向；槽位仍然运行时检测，不硬编码。
 */
(() => {
    const MISC_PATH = '/dev/block/by-name/misc';
    const E5ROOT_PATH = '/dev/block/by-name/e5root';
    const BC_OFFSET = 2048;
    const E5ROOT_DIR = '/data/e5linux';
    const MOUNT_DIR = '/data/local/tmp/mu300-os-mnt';

    // slot_info 字节：priority:4 | tries_remaining:3 | successful_boot:1
    const ARMED_META = 0x2f;   // prio 15, tries 2, 未成功：Linux 只试一次
    const STOCK_TARGET = 0x9f; // prio 15, tries 1, 成功：Android 作为正常目标
    const STOCK_OTHER = 0x1e;  // prio 14, tries 1, 未成功：另一个槽退回不可用

    const run = async (command, timeout = 15000) => {
        try {
            const res = await runShellWithRoot(command, timeout);
            return { ok: Boolean(res && res.success), text: String((res && res.content) || '').trim() };
        } catch (e) {
            return { ok: false, text: '' };
        }
    };

    const readMisc = async () => {
        const r = await run(
            `dd if=${MISC_PATH} bs=1 skip=${BC_OFFSET} count=32 2>/dev/null | od -An -tx1 -v | tr -d ' \\n'`
        );
        return r.ok ? r.text.replace(/[\r\n ]/g, '') : '';
    };

    const getAndroidSlot = async () => {
        const r = await run('getprop ro.boot.slot_suffix');
        const s = r.text.trim().replace(/_/g, '');
        if (s === 'a' || s === 'b') return s;
        // 兜底：从 misc 的 slot_suffix 字节推
        const misc = await readMisc();
        if (misc.length >= 4) {
            const suffix = misc.substring(0, 4);
            if (suffix === '5f61') return 'a';
            if (suffix === '5f62') return 'b';
        }
        return null;
    };

    // CRC-32 (IEEE 802.3, same as gzip) over a byte array
    const crc32 = (bytes) => {
        let c = 0xFFFFFFFF;
        for (let i = 0; i < bytes.length; i++) {
            c ^= bytes[i];
            for (let k = 0; k < 8; k++) {
                c = (c & 1) ? ((c >>> 1) ^ 0xEDB88320) : (c >>> 1);
            }
        }
        return (c ^ 0xFFFFFFFF) >>> 0;
    };

    // 在现有 32 字节块上改出"目标槽 armed、另一槽 idle"的块并重算 CRC32
    const buildBlock = (liveHex, targetSlot, targetMeta, otherMeta) => {
        const bytes = [];
        for (let i = 0; i < 64; i += 2) {
            bytes.push(parseInt(liveHex.substring(i, i + 2), 16));
        }
        bytes[0] = 0x5f;                                  // 与厂商 set_active 一致的头
        bytes[1] = targetSlot === 'a' ? 0x61 : 0x62;      // slot_suffix "_a"/"_b"
        const targetByte = targetSlot === 'a' ? 12 : 14;  // slot_info[0]/[1]
        const otherByte = targetSlot === 'a' ? 14 : 12;
        bytes[targetByte] = targetMeta;
        bytes[otherByte] = otherMeta;
        const crc = crc32(bytes.slice(0, 28));
        bytes[28] = crc & 0xff;
        bytes[29] = (crc >> 8) & 0xff;
        bytes[30] = (crc >> 16) & 0xff;
        bytes[31] = (crc >> 24) & 0xff;
        return bytes.map(b => b.toString(16).padStart(2, '0')).join('');
    };

    const writeBlock = async (newBlock) => {
        const printfArg = newBlock.match(/../g).map(b => '\\x' + b).join('');
        const r = await run(
            `printf '${printfArg}' | dd of=${MISC_PATH} bs=1 seek=${BC_OFFSET} conv=notrunc && sync`
        );
        if (!r.ok) return 'write-failed';
        const back = await readMisc();
        return back === newBlock ? 'ok' : 'mismatch';
    };

    /**
     * boot-os 与 e5root 里的 default-boot。
     * default-boot 要挂载 e5root 才能写，所以尽力而为：
     * 挂载失败或回读不一致都如实返回，交给调用方提示。
     */
    const writeMarkers = async (os) => {
        const bootos = os === 'linux' ? 'part' : 'android';
        await run(`mkdir -p ${E5ROOT_DIR}; echo ${bootos} > ${E5ROOT_DIR}/boot-os; sync`);
        const r = await run(
            `if mkdir -p ${MOUNT_DIR} && mount -t ext4 ${E5ROOT_PATH} ${MOUNT_DIR} 2>/dev/null; then ` +
            `mkdir -p ${MOUNT_DIR}/etc/e5linux; echo ${os} > ${MOUNT_DIR}/etc/e5linux/default-boot; sync; ` +
            `echo DEFAULT=$(cat ${MOUNT_DIR}/etc/e5linux/default-boot 2>/dev/null); ` +
            `umount ${MOUNT_DIR} 2>/dev/null; else echo DEFAULT=skip; fi`,
            20000
        );
        return {
            bootos: bootos,
            default: r.text.includes(`DEFAULT=${os}`) ? 'ok' : (r.text.includes('DEFAULT=skip') ? 'skip' : 'failed'),
        };
    };

    const switchOs = async (os, toast, lockUI, done) => {
        const androidSlot = await getAndroidSlot();
        if (!androidSlot) {
            createToast('无法确定当前槽位，已取消', 'red');
            lockUI(false);
            return;
        }
        const targetSlot = os === 'linux'
            ? (androidSlot === 'a' ? 'b' : 'a')
            : androidSlot;
        toast(`Android 在 slot ${androidSlot}，目标 ${os} 在 slot ${targetSlot}，正在构建引导块…`);

        const live = await readMisc();
        if (live.length !== 64) {
            createToast('读取 misc 失败，未做任何更改', 'red');
            lockUI(false);
            return;
        }
        const newBlock = os === 'linux'
            ? buildBlock(live, targetSlot, ARMED_META, STOCK_OTHER)
            : buildBlock(live, targetSlot, STOCK_TARGET, STOCK_OTHER);
        const written = await writeBlock(newBlock);
        if (written !== 'ok') {
            createToast(written === 'mismatch' ? '校验不一致，已放弃（设备未重启）' : '引导块写入失败，未重启', 'red');
            lockUI(false);
            return;
        }

        const markers = await writeMarkers(os);
        if (os === 'linux' && markers.default !== 'ok') {
            createToast('引导块已就绪，但 e5root 里的 default-boot 没写成（'
                + (markers.default === 'skip' ? '挂载失败' : '回读不一致')
                + '）：这次只生效一次，需要用新版 reinstall.cmd 重装一次', 'red', 6000);
        } else {
            createToast(`已切换：${os === 'linux' ? 'Linux' : 'Android'}（默认，slot ${targetSlot}）`,
                'green', 3000);
        }
        done();
    };

    const btns = document.createElement('button');
    btns.textContent = '系统切换器';
    btns.onclick = () => {
        const { el, close } = createFixedToast('mu300_os_switch', `
            <div style="pointer-events:all;width:80vw;max-width:320px">
                <div class="title" style="margin:0">系统切换器</div>
                <div style="margin:6px 0;font-size:.65rem;color:var(--dark-text-sub-color,#999)">
                    切换后设备重启；再点一次可以换回来
                </div>
                <div style="margin:6px 0;font-size:.65rem">
                    <span id="mu300_os_slot" style="font-family:monospace">检测中…</span>
                </div>
                <div style="margin:10px 0;display:flex;justify-content:space-around" class="mu300_os_content"></div>
                <div style="text-align:right">
                    <button style="font-size:.64rem" id="mu300_os_close">${t('close_btn')}</button>
                </div>
            </div>
        `);

        const linuxBtn = document.createElement('button');
        const androidBtn = document.createElement('button');
        const rebootBtn = document.createElement('button');
        const content = el.querySelector('.mu300_os_content');
        const slotEl = el.querySelector('#mu300_os_slot');
        const closeBtn = el.querySelector('#mu300_os_close');
        if (!closeBtn) { close(); return; }
        closeBtn.onclick = () => close();

        const lockUI = (lock) => {
            [linuxBtn, androidBtn, rebootBtn].forEach((b) => {
                b.disabled = lock;
                b.style.background = lock ? 'var(--dark-btn-disabled-color)' : '';
            });
        };

        linuxBtn.textContent = '切换到 Linux';
        linuxBtn.onclick = () => {
            lockUI(true);
            switchOs('linux', (m, c) => createToast(m, c), lockUI, () => {
                createToast('即将重启进入 Linux…', 'green');
                setTimeout(() => run('reboot', 3000), 1500);
            });
        };

        androidBtn.textContent = '回到 Android';
        androidBtn.onclick = () => {
            lockUI(true);
            switchOs('android', (m, c) => createToast(m, c), lockUI, () => {
                createToast('即将重启进入 Android…', 'green');
                setTimeout(() => run('reboot', 3000), 1500);
            });
        };

        rebootBtn.textContent = '仅重启';
        rebootBtn.onclick = async () => {
            lockUI(true);
            createToast('重启中…');
            await run('reboot', 3000);
        };

        content.appendChild(linuxBtn);
        content.appendChild(androidBtn);
        content.appendChild(rebootBtn);

        (async () => {
            const s = await getAndroidSlot();
            slotEl.textContent = s
                ? `Android: slot ${s} · Linux: slot ${s === 'a' ? 'b' : 'a'}`
                : '槽位检测失败';
            if (!s) {
                lockUI(true);
                slotEl.style.color = 'var(--red-color,#E25555)';
            }
        })();
    };

    const collapseBtn_menu = document.querySelector('#collapseBtn_menu');
    collapseBtn_menu.nextElementSibling.querySelector('.collapse_box').appendChild(btns);
})();
//</script>
