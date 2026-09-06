package dev.sewellzhong.r1probe;

/** Firmware-3448 shell recovery helper for DEFAULT, which its pm CLI cannot select.
 * Invoked only by the administrator tool as shell, never by the satellite service.
 */
public final class FactoryPackageState {
    public static void main(String[] args) throws Exception {
        if (android.os.Process.myUid() != 2000 && android.os.Process.myUid() != 0)
            throw new SecurityException("shell_required");
        if (android.os.Build.VERSION.SDK_INT != 22 || args.length != 1
                || !("com.phicomm.speaker.device".equals(args[0]) || "com.phicomm.speaker.player".equals(args[0])))
            throw new IllegalArgumentException("unsupported_recovery_target");
        Class<?> globals = Class.forName("android.app.AppGlobals");
        Object manager = globals.getMethod("getPackageManager").invoke(null);
        Class<?> contract = Class.forName("android.content.pm.IPackageManager");
        contract.getMethod("setApplicationEnabledSetting", String.class, int.class, int.class, int.class, String.class)
                .invoke(manager, args[0], 0, 0, 0, "com.android.shell");
        int state = (Integer) contract.getMethod("getApplicationEnabledSetting", String.class, int.class)
                .invoke(manager, args[0], 0);
        if (state != 0) throw new IllegalStateException("restore_not_confirmed");
        System.out.println("R1_PACKAGE_DEFAULT_RESTORED");
    }
    private FactoryPackageState() { }
}
