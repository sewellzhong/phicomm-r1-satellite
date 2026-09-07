package dev.sewellzhong.r1probe;

import static org.junit.Assert.assertEquals;
import org.junit.Test;

public class R1SystemKeyMonitorTest {
    @Test public void mapsOnlyFirmwareSingleAndLongPressMessages() {
        assertEquals(R1SystemKeyMonitor.SHORT, R1SystemKeyMonitor.eventFor(256, 1));
        assertEquals(R1SystemKeyMonitor.LONG, R1SystemKeyMonitor.eventFor(256, 5));
        assertEquals(R1SystemKeyMonitor.NONE, R1SystemKeyMonitor.eventFor(256, 6));
        assertEquals(R1SystemKeyMonitor.NONE, R1SystemKeyMonitor.eventFor(4, 1));
    }
}
