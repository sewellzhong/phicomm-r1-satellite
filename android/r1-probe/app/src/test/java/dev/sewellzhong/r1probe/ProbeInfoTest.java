package dev.sewellzhong.r1probe;

import static org.junit.Assert.assertEquals;

import org.junit.Test;

public final class ProbeInfoTest {
    @Test
    public void formatsStableDiagnosticText() {
        assertEquals(
                "R1 install probe\nmodel=rk322x-box\nsdk=22\nabi=armeabi-v7a\nfingerprint=test/fingerprint",
                ProbeInfo.format("rk322x-box", 22, "armeabi-v7a", "test/fingerprint"));
    }
}
