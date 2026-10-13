package com.minikano.e5switch;

import android.app.AlertDialog;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.DialogInterface;
import android.content.Intent;
import android.graphics.PixelFormat;
import android.graphics.drawable.GradientDrawable;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.provider.Settings;
import android.util.TypedValue;
import android.view.ContextThemeWrapper;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.View;
import android.view.WindowManager;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * The whole app: one nearly invisible dot floating over everything.
 *
 * Tap it -> a confirmation window ("switch to OpenWrt?") -> the switch happens
 * and is verified by reading the block back.  Long press -> the menu (switch to
 * OpenWrt, back to Android, hide the dot).
 *
 * There is no activity UI at all, and the dot is the only window that is always
 * there -- which is also why this must be a foreground service: a plain
 * background service is stopped shortly after the app leaves the foreground,
 * and the dot would go with it.
 */
public class OverlayService extends Service {

    private static final String CHANNEL = "switch";
    private static final String E5ROOT = "/data/e5linux";
    private static final String MOUNT = "/data/local/tmp/e5-switch-mnt";
    private static final Pattern BLOCK = Pattern.compile("BC=([0-9a-f]{64})");
    private static final int TAP_SLOP = 24;
    private static final long LONG_PRESS = 450;

    private final Handler main = new Handler(Looper.getMainLooper());
    private WindowManager windows;
    private View dot;
    private WindowManager.LayoutParams dotParams;
    private boolean dragging;

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    @Override
    public void onCreate() {
        super.onCreate();
        windows = (WindowManager) getSystemService(WINDOW_SERVICE);
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        startForeground(1, notification());
        if (dot != null) {
            return START_STICKY;
        }
        new Thread(() -> {
            boolean allowed = Settings.canDrawOverlays(this) || grantOverlayWithRoot();
            main.post(() -> {
                if (allowed) {
                    addDot();
                } else {
                    // No overlay permission means no overlay window either: tell
                    // the user with a toast and open the settings page for it.
                    android.widget.Toast.makeText(this,
                            "需要在设置里允许「显示在其他应用上层」",
                            android.widget.Toast.LENGTH_LONG).show();
                    try {
                        Intent settings = new Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                                android.net.Uri.parse("package:" + getPackageName()));
                        settings.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                        startActivity(settings);
                    } catch (RuntimeException ignored) {
                    }
                    stopSelf();
                }
            });
        }).start();
        return START_STICKY;
    }

    @Override
    public void onDestroy() {
        if (dot != null) {
            try {
                windows.removeView(dot);
            } catch (RuntimeException ignored) {
            }
            dot = null;
        }
        super.onDestroy();
    }

    // -------------------------------------------------------------- the dot

    private int dp(float value) {
        return (int) TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, value,
                getResources().getDisplayMetrics());
    }

    private void addDot() {
        int size = dp(44);
        GradientDrawable shape = new GradientDrawable();
        shape.setShape(GradientDrawable.OVAL);
        shape.setColor(0x2822c55e);                  // green, mostly transparent
        shape.setStroke(dp(2), 0x8822c55e);
        dot = new View(this);
        dot.setBackground(shape);

        dotParams = new WindowManager.LayoutParams(size, size,
                WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
                WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE
                        | WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS,
                PixelFormat.TRANSLUCENT);
        dotParams.gravity = Gravity.TOP | Gravity.START;
        dotParams.x = dp(6);
        dotParams.y = dp(200);
        dot.setOnTouchListener(this::touch);
        windows.addView(dot, dotParams);
    }

    private boolean touch(View view, MotionEvent event) {
        switch (event.getAction()) {
            case MotionEvent.ACTION_DOWN:
                dragging = false;
                down(event);
                return true;
            case MotionEvent.ACTION_MOVE: {
                int dx = (int) (event.getRawX() - downX);
                int dy = (int) (event.getRawY() - downY);
                if (Math.abs(dx) > TAP_SLOP || Math.abs(dy) > TAP_SLOP) {
                    dragging = true;
                }
                if (dragging) {
                    dotParams.x = startX + dx;
                    dotParams.y = startY + dy;
                    windows.updateViewLayout(dot, dotParams);
                }
                return true;
            }
            case MotionEvent.ACTION_UP:
                if (!dragging) {
                    if (event.getEventTime() - downTime > LONG_PRESS) {
                        menu();
                    } else {
                        confirm('b');
                    }
                }
                return true;
            default:
                return false;
        }
    }

    private float downX, downY;
    private int startX, startY;
    private long downTime;

    private void down(MotionEvent event) {
        downX = event.getRawX();
        downY = event.getRawY();
        startX = dotParams.x;
        startY = dotParams.y;
        downTime = event.getEventTime();
    }

    private void menu() {
        String[] labels = {"隐藏悬浮窗", "切换到 OpenWrt（永久）", "回到 Android"};
        Runnable[] actions = {this::stopSelf, () -> confirm('b'), () -> confirm('a')};
        AlertDialog dialog = window("E5 启动切换", "点一下悬浮点 = 切到 OpenWrt；这里可以选别的。");
        DialogInterface.OnClickListener listener = (d, which) -> {
            int index = which == DialogInterface.BUTTON_POSITIVE ? 2
                    : which == DialogInterface.BUTTON_NEGATIVE ? 1 : 0;
            actions[index].run();
        };
        dialog.setButton(DialogInterface.BUTTON_NEUTRAL, labels[0], listener);
        dialog.setButton(DialogInterface.BUTTON_NEGATIVE, labels[1], listener);
        dialog.setButton(DialogInterface.BUTTON_POSITIVE, labels[2], listener);
        dialog.show();
    }

    // ----------------------------------------------------------- the dialogs

    /** A dialog is a window too: from a service it has to be an overlay window. */
    private AlertDialog window(String title, String message) {
        AlertDialog dialog = new AlertDialog.Builder(new ContextThemeWrapper(this,
                android.R.style.Theme_DeviceDefault_Dialog_Alert))
                .setTitle(title)
                .setMessage(message)
                .create();
        dialog.getWindow().setType(WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY);
        return dialog;
    }

    private void dialog(String title, String message) {
        AlertDialog dialog = window(title, message);
        dialog.setButton(DialogInterface.BUTTON_POSITIVE, "好", (d, w) -> { });
        dialog.show();
    }

    private void confirm(final char slot) {
        boolean linux = slot == 'b';
        AlertDialog dialog = window(linux ? "切换到 OpenWrt？" : "回到 Android？",
                linux ? "确认后设备下次启动进入 OpenWrt，并保持为默认系统。\n\n"
                        + "Android 用户数据、分区表和 boot 镜像都不动。\n"
                        + "如果 OpenWrt 起不来，设备会自己回到 Android。"
                      : "确认后设备下次启动进入 Android，并保持为默认系统。\n\n"
                        + "OpenWrt 系统本身不会被删除，随时可以再切回来。");
        dialog.setButton(DialogInterface.BUTTON_NEGATIVE, "取消", (d, w) -> { });
        dialog.setButton(DialogInterface.BUTTON_POSITIVE,
                linux ? "确认切换" : "确认回到 Android", (d, w) -> apply(slot));
        dialog.show();
    }

    // ------------------------------------------------------------- the work

    private void apply(final char slot) {
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
                final String written = su("BY=/dev/block/by-name; "
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
                main.post(() -> {
                    AlertDialog dialog = window("E5 启动切换", text);
                    dialog.setButton(DialogInterface.BUTTON_NEGATIVE, "稍后", (d, w) -> { });
                    dialog.setButton(DialogInterface.BUTTON_POSITIVE, "现在重启",
                            (d, w) -> new Thread(() -> su("reboot")).start());
                    dialog.show();
                });
            } catch (final RuntimeException error) {
                main.post(() -> dialog("没有改动任何东西", String.valueOf(error.getMessage())));
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

    /** The overlay permission can be granted by root, so no settings trip is needed. */
    private boolean grantOverlayWithRoot() {
        su("appops set com.minikano.e5switch SYSTEM_ALERT_WINDOW allow");
        return Settings.canDrawOverlays(this);
    }

    private static byte[] unhex(String hex) {
        byte[] out = new byte[hex.length() / 2];
        for (int i = 0; i < out.length; i++) {
            out[i] = (byte) Integer.parseInt(hex.substring(2 * i, 2 * i + 2), 16);
        }
        return out;
    }

    // ------------------------------------------------------- the notification

    /** Foreground services need one; keep it as quiet as the system allows. */
    private Notification notification() {
        if (Build.VERSION.SDK_INT >= 26) {
            NotificationManager manager = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
            NotificationChannel channel = new NotificationChannel(
                    CHANNEL, "悬浮切换", NotificationManager.IMPORTANCE_MIN);
            channel.setShowBadge(false);
            manager.createNotificationChannel(channel);
        }
        Notification.Builder builder = Build.VERSION.SDK_INT >= 26
                ? new Notification.Builder(this, CHANNEL)
                : new Notification.Builder(this);
        return builder
                .setSmallIcon(android.R.drawable.stat_notify_sync)
                .setContentTitle("E5 启动切换")
                .setContentText("悬浮点已就绪：点一下切到 OpenWrt，长按出菜单")
                .setOngoing(true)
                .build();
    }
}
