package dev.sewellzhong.r1probe;

import android.app.ActivityManager;
import android.content.Context;
import android.content.pm.ApplicationInfo;
import android.content.pm.PackageManager;
import java.util.List;

/** Conservative API22 admission check; never changes another package's state. */
final class FactoryAudioIsolation {
    static final String[] PACKAGES = {"com.phicomm.speaker.device", "com.phicomm.speaker.player"};
    static String inspect(Context context) {
        try {
            PackageManager pm = context.getPackageManager();
            ActivityManager am = (ActivityManager) context.getSystemService(Context.ACTIVITY_SERVICE);
            List<ActivityManager.RunningAppProcessInfo> processes = am.getRunningAppProcesses();
            if (processes == null || processes.isEmpty()) return "unknown";
            boolean ownProcessVisible = false;
            for (ActivityManager.RunningAppProcessInfo process : processes) {
                if (process.pid == android.os.Process.myPid()) ownProcessVisible = true;
                for (String name : PACKAGES) {
                    if (name.equals(process.processName) || (process.processName != null && process.processName.startsWith(name + ":")))
                        return "factory_process_running";
                    if (process.pkgList != null) for (String owner : process.pkgList)
                        if (name.equals(owner)) return "factory_process_running";
                }
            }
            if (!ownProcessVisible) return "unknown";
            boolean permanent = true;
            int hiddenCount = 0;
            for (String name : PACKAGES) {
                // API22 represents the user-hidden bit in ApplicationInfo.flags.
                // Resolve the platform field rather than guessing a message/flag number.
                ApplicationInfo info;
                if (android.os.Build.VERSION.SDK_INT == 22) {
                    info = pm.getApplicationInfo(name, PackageManager.GET_UNINSTALLED_PACKAGES);
                    if ((info.flags & ApplicationInfo.FLAG_INSTALLED) == 0) return "unknown";
                    int hiddenFlag = ApplicationInfo.class.getField("FLAG_HIDDEN").getInt(null);
                    if ((info.flags & hiddenFlag) != 0) { hiddenCount++; continue; }
                } else {
                    info = pm.getApplicationInfo(name, 0);
                }
                if (info.enabled) {
                    permanent = false;
                    if ((info.flags & ApplicationInfo.FLAG_STOPPED) == 0) return "factory_package_startable";
                }
            }
            if (!permanent) return "temporary_force_stop";
            return hiddenCount == PACKAGES.length ? "packages_hidden"
                    : hiddenCount == 0 ? "packages_disabled" : "packages_disabled_or_hidden";
        } catch (PackageManager.NameNotFoundException | ReflectiveOperationException | RuntimeException e) {
            return "unknown";
        }
    }
    static boolean permitsAudio(String state) {
        return "packages_disabled".equals(state) || "packages_hidden".equals(state)
                || "packages_disabled_or_hidden".equals(state) || "temporary_force_stop".equals(state);
    }
    private FactoryAudioIsolation() { }
}
