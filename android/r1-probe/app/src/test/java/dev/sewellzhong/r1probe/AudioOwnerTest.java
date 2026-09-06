package dev.sewellzhong.r1probe;
import org.junit.Test;
import static org.junit.Assert.*;
public final class AudioOwnerTest {
    @Test public void preventsOverlapAndIgnoresStaleRelease() {
        Object first = new Object(), second = new Object();
        try {
            assertTrue(AudioOwner.acquire(first));
            assertTrue(AudioOwner.acquire(first));
            assertFalse(AudioOwner.acquire(second));
            AudioOwner.release(second);
            assertFalse(AudioOwner.acquire(second));
            AudioOwner.release(first);
            assertTrue(AudioOwner.acquire(second));
            AudioOwner.release(first);
            assertFalse(AudioOwner.acquire(first));
        } finally { AudioOwner.release(first); AudioOwner.release(second); }
    }
}
