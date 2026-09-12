package dev.sewellzhong.r1probe;

import android.content.Context;
import android.content.SharedPreferences;
import dev.sewellzhong.r1probe.esphome.NativeAlarmController;
import java.io.IOException;

/** Atomic app-private persistence for locally owned alarm schedules. */
final class NativeAlarmStore implements NativeAlarmController.Store {
    private final SharedPreferences preferences;
    NativeAlarmStore(Context context) {
        preferences = context.getSharedPreferences("native-alarms", Context.MODE_PRIVATE);
    }
    @Override public String load() { return preferences.getString("state", ""); }
    @Override public void save(String value) throws IOException {
        if (!preferences.edit().putString("state", value).commit())
            throw new IOException("alarm_persistence_failed");
    }
}
