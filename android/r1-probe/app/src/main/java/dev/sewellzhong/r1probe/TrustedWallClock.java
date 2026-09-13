package dev.sewellzhong.r1probe;

import android.os.SystemClock;
import dev.sewellzhong.r1probe.esphome.NativeAlarmController;
import dev.sewellzhong.r1probe.esphome.NativeDndController;
import dev.sewellzhong.r1probe.esphome.NativeTimerController;

/** HA-synchronized wall time advanced by Android's monotonic clock without changing system time. */
final class TrustedWallClock implements NativeAlarmController.Clock,
        NativeDndController.Clock, NativeTimerController.Clock {
    interface Source {
        long elapsedMillis();
        long systemWallMillis();
        String timeZoneId();
    }

    private static final long MIN_EPOCH_SECONDS = 1_577_836_800L;
    private static final long MAX_EPOCH_SECONDS = 4_102_444_800L;
    private final Source source;
    private long epochAtSyncMillis;
    private long elapsedAtSyncMillis;
    private boolean synchronizedTime;

    TrustedWallClock() {
        this(new Source() {
            @Override public long elapsedMillis() { return SystemClock.elapsedRealtime(); }
            @Override public long systemWallMillis() { return System.currentTimeMillis(); }
            @Override public String timeZoneId() { return java.util.TimeZone.getDefault().getID(); }
        });
    }

    TrustedWallClock(Source source) {
        if (source == null) throw new IllegalArgumentException("clock_source_required");
        this.source = source;
    }

    synchronized void synchronize(long epochSeconds) {
        if (epochSeconds < MIN_EPOCH_SECONDS || epochSeconds > MAX_EPOCH_SECONDS)
            throw new IllegalArgumentException("clock_epoch_invalid");
        epochAtSyncMillis = epochSeconds * 1000L;
        elapsedAtSyncMillis = source.elapsedMillis();
        synchronizedTime = true;
    }

    @Override public synchronized long wallMillis() {
        if (!synchronizedTime) return source.systemWallMillis();
        long elapsed = source.elapsedMillis() - elapsedAtSyncMillis;
        return epochAtSyncMillis + Math.max(0, elapsed);
    }

    @Override public synchronized boolean wallTrusted() {
        return synchronizedTime || source.systemWallMillis() >= MIN_EPOCH_SECONDS * 1000L;
    }

    @Override public long elapsedMillis() { return source.elapsedMillis(); }
    @Override public String timeZoneId() { return source.timeZoneId(); }
}
