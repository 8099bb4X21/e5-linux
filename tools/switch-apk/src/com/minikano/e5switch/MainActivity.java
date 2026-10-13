package com.minikano.e5switch;

import android.app.Activity;
import android.content.Intent;
import android.os.Build;
import android.os.Bundle;

/**
 * Invisible, on purpose: translucent, no layout, finishes immediately.  It is
 * the launcher entry point that (re)starts the floating dot after it was hidden
 * -- everything else happens in {@link OverlayService}.
 */
public class MainActivity extends Activity {

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        Intent service = new Intent(this, OverlayService.class);
        if (Build.VERSION.SDK_INT >= 26) {
            startForegroundService(service);
        } else {
            startService(service);
        }
        finish();
    }
}
