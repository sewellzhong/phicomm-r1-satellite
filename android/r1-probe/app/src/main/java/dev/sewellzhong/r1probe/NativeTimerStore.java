package dev.sewellzhong.r1probe;

import android.content.Context;
import android.content.SharedPreferences;
import dev.sewellzhong.r1probe.esphome.NativeTimerController;
import java.io.IOException;

/** Atomic private persistence for locally owned timer deadlines and idempotency records. */
final class NativeTimerStore implements NativeTimerController.Store {
    private final SharedPreferences preferences;
    NativeTimerStore(Context context) {
        preferences = context.getSharedPreferences("native-timers", Context.MODE_PRIVATE);
    }
    @Override public String load() { return preferences.getString("state", ""); }
    @Override public void save(String value) throws IOException {
        if (!preferences.edit().putString("state", value).commit())
            throw new IOException("timer_persistence_failed");
    }
}
