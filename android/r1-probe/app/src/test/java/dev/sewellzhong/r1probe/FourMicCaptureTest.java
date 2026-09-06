package dev.sewellzhong.r1probe;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

import java.io.File;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import org.junit.Test;

public final class FourMicCaptureTest {
    @Test
    public void recordsExactPcmAndCleansUpInOrder() throws Exception {
        File directory = Files.createTempDirectory("four-mic-test").toFile();
        FakeBackend backend = new FakeBackend();

        FourMicCapture.Result result = FourMicCapture.record(directory, 1, "test", backend);

        assertEquals(32000, result.pcmBytes);
        assertEquals(32000, WavHeader.validate(result.wavFile));
        assertEquals("board_1", result.boardVersion);
        assertEquals(Arrays.asList("version", "init:1", "debug:1", "algorithm:0", "wakeup:0",
                "open:2", "start", "stop", "close", "release"), backend.lifecycle);
        assertTrue(new File(result.wavFile.getAbsolutePath() + ".meta.txt").isFile());
    }

    @Test
    public void releasesInitializedBackendWhenConfigurationFails() throws Exception {
        File directory = Files.createTempDirectory("four-mic-failure").toFile();
        FakeBackend backend = new FakeBackend();
        backend.debugResult = -7;

        try {
            FourMicCapture.record(directory, 1, "failure", backend);
            fail("Expected configuration failure");
        } catch (IllegalStateException expected) {
            assertEquals("four_mic_set_debug_mode_error_-7", expected.getMessage());
        }

        assertEquals(Arrays.asList("version", "init:1", "debug:1", "release"), backend.lifecycle);
        File[] wavFiles = directory.listFiles();
        assertFalse(wavFiles != null && wavFiles.length > 0);
    }

    @Test
    public void rejectsOddPcmReadAndClosesSession() throws Exception {
        File directory = Files.createTempDirectory("four-mic-odd").toFile();
        FakeBackend backend = new FakeBackend();
        backend.oddRead = true;

        try {
            FourMicCapture.record(directory, 1, "odd", backend);
            fail("Expected odd-byte failure");
        } catch (IllegalStateException expected) {
            assertEquals("four_mic_odd_pcm_bytes_2399", expected.getMessage());
        }

        assertTrue(backend.lifecycle.containsAll(Arrays.asList("stop", "close", "release")));
    }

    @Test
    public void releasesBackendWhenNativeOpenFails() throws Exception {
        File directory = Files.createTempDirectory("four-mic-open-failure").toFile();
        FakeBackend backend = new FakeBackend();
        backend.openHandle = 0L;

        try {
            FourMicCapture.record(directory, 1, "open", backend);
            fail("Expected open failure");
        } catch (IllegalStateException expected) {
            assertEquals("four_mic_open_failed_0", expected.getMessage());
        }

        assertEquals(Arrays.asList("version", "init:1", "debug:1", "algorithm:0", "wakeup:0",
                "open:2", "release"), backend.lifecycle);
    }

    private static final class FakeBackend implements FourMicBackend {
        final List<String> lifecycle = new ArrayList<>();
        int debugResult;
        boolean oddRead;
        long openHandle = 42L;

        @Override public String boardVersion() { lifecycle.add("version"); return "board 1"; }
        @Override public int init(int mode) { lifecycle.add("init:" + mode); return 0; }
        @Override public int setDebugMode(int enabled) { lifecycle.add("debug:" + enabled); return debugResult; }
        @Override public int closeAlgorithm(int closed) { lifecycle.add("algorithm:" + closed); return 0; }
        @Override public int setWakeUpStatus(int status) { lifecycle.add("wakeup:" + status); return 0; }
        @Override public long openAudioIn(int source) { lifecycle.add("open:" + source); return openHandle; }
        @Override public int startRecorder(long handle) { lifecycle.add("start"); return 0; }
        @Override public int readData(long handle, byte[] buffer, int length) {
            int result = oddRead ? Math.min(2399, length) : length;
            Arrays.fill(buffer, 0, result, (byte) 1);
            return result;
        }
        @Override public int stopRecorder(long handle) { lifecycle.add("stop"); return 0; }
        @Override public int closeAudioIn(long handle) { lifecycle.add("close"); return 0; }
        @Override public int release() { lifecycle.add("release"); return 0; }
    }
}
