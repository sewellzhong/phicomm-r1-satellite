package dev.sewellzhong.r1probe;

import static org.junit.Assert.assertEquals;
import java.util.ArrayList;
import java.util.List;
import org.junit.Test;

public class HardwareInputRelayTest {
    @Test public void normalizesTheFirmwareDisplayRange() {
        assertEquals(0, HardwareInputRelay.normalizePosition(0, 0, 719));
        assertEquals(128, HardwareInputRelay.normalizePosition(360, 0, 719));
        assertEquals(255, HardwareInputRelay.normalizePosition(719, 0, 719));
        assertEquals(0, HardwareInputRelay.normalizePosition(-10, 0, 719));
        assertEquals(255, HardwareInputRelay.normalizePosition(800, 0, 719));
    }

    @Test public void relaysOnlyWhileAttached() {
        List<String> events = new ArrayList<>();
        HardwareInputRelay.Listener listener = new HardwareInputRelay.Listener() {
            @Override public void central(int action, long eventMs) { events.add("key:" + action); }
            @Override public void ring(int action, int position, long eventMs) { events.add("ring:" + position); }
        };
        HardwareInputRelay.attach(listener);
        HardwareInputRelay.central(1, 1); HardwareInputRelay.ring(2, 42, 2);
        HardwareInputRelay.detach(listener); HardwareInputRelay.central(0, 3);
        assertEquals(java.util.Arrays.asList("key:1", "ring:42"), events);
    }
}
