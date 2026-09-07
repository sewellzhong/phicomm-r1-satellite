package dev.sewellzhong.r1probe;

import static org.junit.Assert.assertEquals;
import java.util.ArrayList;
import java.util.List;
import org.junit.Test;

public class HardwareInputInterpreterTest {
    private static final class Events implements HardwareInputInterpreter.Listener {
        final List<String> values = new ArrayList<>();
        @Override public void central(boolean longer, long duration) { values.add((longer ? "long:" : "short:") + duration); }
        @Override public void ringStep(int direction) { values.add(direction > 0 ? "cw" : "ccw"); }
    }

    @Test public void separatesShortAndLongCentrePresses() {
        Events events = new Events(); HardwareInputInterpreter input = new HardwareInputInterpreter(events);
        input.central(1, 195, 1, 1000); input.central(1, 195, 0, 1160);
        input.central(1, 195, 1, 2000); input.central(1, 195, 0, 5110);
        assertEquals(java.util.Arrays.asList("short:160", "long:3110"), events.values);
    }

    @Test public void ignoresUnpairedReleaseAndOtherKeys() {
        Events events = new Events(); HardwareInputInterpreter input = new HardwareInputInterpreter(events);
        input.central(1, 195, 0, 10); input.central(1, 194, 1, 20); input.central(1, 194, 0, 30);
        assertEquals(0, events.values.size());
    }

    @Test public void emitsClockwiseStepsAndHandlesForwardWrap() {
        Events events = new Events(); HardwareInputInterpreter input = new HardwareInputInterpreter(events);
        input.ring(1, 330, 1, 0); input.ring(3, 0, 240, 1);
        input.ring(3, 0, 250, 2); input.ring(3, 0, 5, 3); input.ring(3, 0, 20, 4);
        input.ring(1, 330, 0, 5);
        assertEquals(java.util.Arrays.asList("cw", "cw"), events.values);
    }

    @Test public void emitsCounterclockwiseStepsAndHandlesReverseWrap() {
        Events events = new Events(); HardwareInputInterpreter input = new HardwareInputInterpreter(events);
        input.ring(1, 330, 1, 0); input.ring(3, 0, 12, 1);
        input.ring(3, 0, 2, 2); input.ring(3, 0, 248, 3); input.ring(3, 0, 230, 4);
        assertEquals(java.util.Arrays.asList("ccw", "ccw"), events.values);
    }

    @Test public void stationaryTapDoesNotChangeVolume() {
        Events events = new Events(); HardwareInputInterpreter input = new HardwareInputInterpreter(events);
        input.ring(1, 330, 1, 0); input.ring(3, 0, 80, 1); input.ring(1, 330, 0, 2);
        assertEquals(0, events.values.size());
    }
}
