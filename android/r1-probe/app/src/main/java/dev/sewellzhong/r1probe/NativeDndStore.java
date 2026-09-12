package dev.sewellzhong.r1probe;

import android.content.Context;
import android.content.SharedPreferences;
import dev.sewellzhong.r1probe.esphome.NativeDndController;
import java.io.IOException;

final class NativeDndStore implements NativeDndController.Store {
    private final SharedPreferences preferences;
    NativeDndStore(Context context) {
        preferences = context.getSharedPreferences("native-dnd", Context.MODE_PRIVATE);
    }
    @Override public String load() { return preferences.getString("state", ""); }
    @Override public void save(String value) throws IOException {
        if (!preferences.edit().putString("state", value).commit())
            throw new IOException("dnd_persistence_failed");
    }
}
