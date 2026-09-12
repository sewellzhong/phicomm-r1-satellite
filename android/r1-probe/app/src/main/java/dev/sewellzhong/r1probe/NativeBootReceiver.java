package dev.sewellzhong.r1probe;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.os.Build;

public final class NativeBootReceiver extends BroadcastReceiver {
    @Override public void onReceive(Context context, Intent intent) {
        if (!(Intent.ACTION_BOOT_COMPLETED.equals(intent.getAction())
                || Intent.ACTION_MY_PACKAGE_REPLACED.equals(intent.getAction()))) return;
        boolean replacement = Intent.ACTION_MY_PACKAGE_REPLACED.equals(intent.getAction());
        if (replacement) {
            new UpdateHealthReporter.PreferencesStore(context)
                    .markReplacement(UpdateHealthReporter.bootIdentity());
        }
        if (!replacement && !new NativeSettings(context).enabled()) return;
        Intent service = new Intent(context, NativeSatelliteService.class);
        if (Build.VERSION.SDK_INT >= 26) context.startForegroundService(service);
        else context.startService(service);
    }
}
