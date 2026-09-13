package dev.sewellzhong.r1probe;

import java.io.IOException;

/** Fixed JNI boundary to the dedicated boot-ramdisk system-control agent. */
final class SystemControlNative {
    static { System.loadLibrary("r1_system_control_client"); }
    private SystemControlNative() {}
    static native int[] setLed(int first, int second) throws IOException;
    static native void reboot() throws IOException;
}
