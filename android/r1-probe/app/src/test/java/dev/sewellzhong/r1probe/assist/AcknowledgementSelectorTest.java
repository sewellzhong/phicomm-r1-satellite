package dev.sewellzhong.r1probe.assist;
import org.junit.Test;
import java.util.Random;
import java.util.HashSet;
import static org.junit.Assert.*;
public final class AcknowledgementSelectorTest {
    @Test public void coversAllPhrasesWithoutImmediateRepeats() {
        AcknowledgementSelector selector = new AcknowledgementSelector(new Random(42));
        int previous = -1;
        int occasional = 0;
        HashSet<Integer> seen = new HashSet<>();
        for (int i = 0; i < 10000; i++) {
            int value = selector.next();
            assertTrue(value >= 0 && value < 10);
            assertNotEquals(previous, value);
            assertFalse(previous >= 6 && value >= 6);
            if (value >= 6) { occasional++; }
            seen.add(value); previous = value;
        }
        assertEquals(10, seen.size());
        assertTrue(occasional > 1300 && occasional < 1700);
    }
}
