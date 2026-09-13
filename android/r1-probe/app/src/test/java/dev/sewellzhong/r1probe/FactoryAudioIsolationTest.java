package dev.sewellzhong.r1probe;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

public final class FactoryAudioIsolationTest {
    @Test public void onlyObservedUnsafeStatesArePersistentBlockers() {
        assertTrue(FactoryAudioIsolation.definitivelyUnsafe("factory_process_running"));
        assertTrue(FactoryAudioIsolation.definitivelyUnsafe("factory_package_startable"));
        assertFalse(FactoryAudioIsolation.definitivelyUnsafe("unknown"));
        assertFalse(FactoryAudioIsolation.definitivelyUnsafe("packages_hidden"));
    }
}
