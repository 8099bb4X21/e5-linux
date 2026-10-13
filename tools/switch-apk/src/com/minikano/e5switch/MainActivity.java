package com.minikano.e5switch;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.DialogInterface;
import android.os.Bundle;
import android.view.ContextThemeWrapper;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Nothing but the dialog: tapping the icon puts up "switch to OpenWrt?" at once
 * (the activity itself is translucent, there is no screen behind it), a
 * confirmation runs the switch and reports what it wrote, and the activity
 * finishes.
 */
public class MainActivity extends Activity {

    private static final String TAG = "e5switch";
    private static final String E5ROOT = "/data/e5linux";
    private static final String MOUNT = "/data/local/tmp/e5-switch-mnt";
    private static final Pattern BLOCK = Pattern.compile("BC=([0-9a-f]{64})");

    private boolean busy;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        ask('b');
    }

    /** Every dialog is built with a dialog theme: the activity's own is translucent. */
    private AlertDialog window(String title, String message) {
        return new AlertDialog.Builder(new ContextThemeWrapper(this,
                android.R.style.Theme_DeviceDefault_Dialog_Alert))
                .setTitle(title)
                .setMessage(message)
                .create();
    }

    private void ask(final char slot) {
        final boolean linux = slot == 'b';
        AlertDialog dialog = window(linux ? "切换到 OpenWrt？" : "回到 Android？",
                linux ? "确认后设备下次启动进入 OpenWrt，并保持为默认系统。\n\n"
                        + "Android 用户数据、分区表和 boot 镜像都不动。\n"
                        + "如果 OpenWrt 起不来，设备会自己回到 Android。"
                      : "确认后设备下次启动进入 Android，并保持为默认系统。\n\n"
                        + "OpenWrt 系统本身不会被删除，随时可以再切回来。");
        android.util.Log.i(TAG, "ask slot=" + slot);
        dialog.setButton(DialogInterface.BUTTON_NEUTRAL, linux ? "回到 Android" : "切换到 OpenWrt",
                (d, w) -> ask(linux ? 'a' : 'b'));
        dialog.setButton(DialogInterface.BUTTON_NEGATIVE, "取消", (d, w) -> finish());
        dialog.setButton(DialogInterface.BUTTON_POSITIVE,
                linux ? "确认切换" : "确认回到 Android", (d, w) -> apply(slot));
        dialog.setOnCancelListener(d -> finish());
        dialog.show();
    }

    private void report(String title, String message, boolean offerReboot) {
        busy = false;
        AlertDialog dialog = window(title, message);
        if (offerReboot) {
            dialog.setButton(DialogInterface.BUTTON_NEGATIVE, "稍后", (d, w) -> finish());
            dialog.setButton(DialogInterface.BUTTON_POSITIVE, "现在重启", (d, w) -> {
                new Thread(() -> su("reboot")).start();
                finish();
            });
        } else {
            dialog.setButton(DialogInterface.BUTTON_POSITIVE, "好", (d, w) -> finish());
        }
        dialog.setOnCancelListener(d -> finish());
        dialog.show();
    }

    // ------------------------------------------------------------- the work

    private void apply(final char slot) {
        busy = true;
        final AlertDialog progress = window("E5 启动切换", "正在写入并校验…");
        progress.setCancelable(false);
        progress.show();
        new Thread(() -> {
            try {
                String read = su("BY=/dev/block/by-name; "
                        + "[ -b $BY/misc ] || { echo NO-MISC; exit 4; }; "
                        + "[ -b $BY/e5root ] && echo E5ROOT=1 || echo E5ROOT=0; "
                        + "echo BC=$(dd if=$BY/misc bs=1 skip=2048 count=32 2>/dev/null"
                        + " | od -An -tx1 | tr -d ' \\n')");
                if (read.contains("NO-MISC")) {
                    throw new IllegalStateException("找不到 misc 分区（这台设备不支持？）");
                }
                Matcher found = BLOCK.matcher(read);
                if (!found.find()) {
                    throw new IllegalStateException("读不到 misc 的启动控制块：\n" + read.trim());
                }
                if (slot == 'b' && !read.contains("E5ROOT=1")) {
                    throw new IllegalStateException("这台设备还没有装内置分区的 OpenWrt"
                            + "（没有 e5root 分区），先安装再切。");
                }
                byte[] wanted = ArmedBlock.armed(unhex(found.group(1)), slot);
                // Three things decide what boots and whether it stays:
                //   /data/e5linux/boot-os       which system the initramfs picks
                //   /etc/e5linux/default-boot   e5-boot-ok rearms slot B only while
                //                               this says linux -- the permanence
                //   misc @2048                  the A/B boot control block
                // The second lives inside e5root: written best effort, because a
                // system from an older package still has android there, and an
                // unreadable filesystem must not stop the arm.
                String written = su("BY=/dev/block/by-name; "
                        + "mkdir -p " + E5ROOT + "; echo " + (slot == 'b' ? "part" : "android")
                        + " > " + E5ROOT + "/boot-os; sync; "
                        + "if mkdir -p " + MOUNT + " && mount -t ext4 $BY/e5root " + MOUNT
                        + " 2>/dev/null; then "
                        + "  mkdir -p " + MOUNT + "/etc/e5linux; echo "
                        + (slot == 'b' ? "linux" : "android") + " > "
                        + MOUNT + "/etc/e5linux/default-boot; sync; "
                        + "  umount " + MOUNT + " 2>/dev/null && echo DEFAULT=ok || echo DEFAULT=busy; "
                        + "else echo DEFAULT=skip; fi; "
                        + "printf '%b' '" + ArmedBlock.octalEscapes(wanted)
                        + "' > /data/local/tmp/e5-switch-bc; "
                        + "dd if=/data/local/tmp/e5-switch-bc of=$BY/misc bs=1 seek=2048"
                        + " conv=notrunc 2>/dev/null; sync; rm -f /data/local/tmp/e5-switch-bc; "
                        + "echo BC=$(dd if=$BY/misc bs=1 skip=2048 count=32 2>/dev/null"
                        + " | od -An -tx1 | tr -d ' \\n')");
                Matcher check = BLOCK.matcher(written);
                final String expect = ArmedBlock.hex(wanted);
                if (!check.find() || !expect.equals(check.group(1))) {
                    throw new IllegalStateException("写入后校验不一致，请勿重启并把这行发我：\n"
                            + "期望 " + expect + "\n实际 " + written.trim());
                }
                String note = "";
                if (slot == 'b' && !written.contains("DEFAULT=ok")) {
                    note = "\n\n注意：没能改 e5root 里的 default-boot（"
                            + (written.contains("DEFAULT=busy") ? "卸载失败" : "挂载失败")
                            + "），这次切换可能只生效一次；装老版本包的系统要用新版 reinstall 重装一次。";
                }
                final String text = "已切换（" + (slot == 'b' ? "OpenWrt" : "Android") + "）\n\nmisc: "
                        + expect + "\n" + E5ROOT + "/boot-os = " + (slot == 'b' ? "part" : "android")
                        + note + "\n\n现在重启？";
                runOnUiThread(() -> {
                    progress.dismiss();
                    report("E5 启动切换", text, true);
                });
            } catch (final RuntimeException error) {
                runOnUiThread(() -> {
                    progress.dismiss();
                    report("没有改动任何东西", String.valueOf(error.getMessage()), false);
                });
            }
        }).start();
    }

    // ---------------------------------------------------------------- the su

    /** Run a script as root; never throws, the output carries everything. */
    private String su(String script) {
        StringBuilder out = new StringBuilder();
        try {
            Process process = Runtime.getRuntime().exec(new String[] {"su", "-c", script});
            BufferedReader reader = new BufferedReader(new InputStreamReader(process.getInputStream()));
            String line;
            while ((line = reader.readLine()) != null) {
                out.append(line).append('\n');
            }
            reader.close();
            BufferedReader errors = new BufferedReader(new InputStreamReader(process.getErrorStream()));
            while ((line = errors.readLine()) != null) {
                out.append(line).append('\n');
            }
            errors.close();
            int code = process.waitFor();
            if (code != 0 && out.indexOf("BC=") < 0) {
                out.append("exit ").append(code);
            }
        } catch (Exception error) {
            out.append("su 不可用（Magisk 里给这个 app 授权）：").append(error);
        }
        return out.toString();
    }

    private static byte[] unhex(String hex) {
        byte[] out = new byte[hex.length() / 2];
        for (int i = 0; i < out.length; i++) {
            out[i] = (byte) Integer.parseInt(hex.substring(2 * i, 2 * i + 2), 16);
        }
        return out;
    }
}
