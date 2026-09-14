package dev.sewellzhong.r1probe;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;
import static org.junit.Assert.*;

public final class NativeAlertAudioStoreTest {
    @Rule public final TemporaryFolder temporary = new TemporaryFolder();

    private byte[] wav(int pcmBytes) {
        ByteBuffer value = ByteBuffer.allocate(44 + pcmBytes).order(ByteOrder.LITTLE_ENDIAN);
        value.put(new byte[]{82,73,70,70}).putInt(36 + pcmBytes)
                .put(new byte[]{87,65,86,69,102,109,116,32}).putInt(16)
                .putShort((short)1).putShort((short)1).putInt(16000).putInt(32000)
                .putShort((short)2).putShort((short)16)
                .put(new byte[]{100,97,116,97}).putInt(pcmBytes);
        return value.array();
    }
    private File write(String name, byte[] bytes) throws Exception {
        File file = new File(temporary.getRoot(), name);
        try (FileOutputStream output = new FileOutputStream(file)) { output.write(bytes); }
        return file;
    }

    @Test public void exactPcmContractReturnsBoundedDataRegion() throws Exception {
        File file = write("music.wav", wav(640));
        NativeAlertAudioStore.Audio audio = NativeAlertAudioStore.parse(file);
        assertEquals(file, audio.file); assertEquals(44, audio.dataOffset); assertEquals(640, audio.dataBytes);
    }

    @Test public void wrongRateAndTruncationFailClosed() throws Exception {
        byte[] wrong = wav(640); wrong[24] = 0x40; wrong[25] = 0x1f;
        for (File file : new File[]{write("wrong.wav", wrong), write("short.wav", new byte[20])}) {
            try { NativeAlertAudioStore.parse(file); fail(); }
            catch (IOException expected) { assertTrue(expected.getMessage().startsWith("alert_audio_")); }
        }
    }

    @Test public void oversizedFilesAreRejectedBeforeParsing() throws Exception {
        File file = temporary.newFile("large.wav");
        try (java.io.RandomAccessFile output = new java.io.RandomAccessFile(file, "rw")) {
            output.setLength(NativeAlertAudioStore.MAX_BYTES + 1L);
        }
        try { NativeAlertAudioStore.parse(file); fail(); }
        catch (IOException expected) { assertEquals("alert_audio_file_invalid", expected.getMessage()); }
    }

    @Test public void constructionRemovesInterruptedUploadsButPreservesCommittedAudio() throws Exception {
        File root = temporary.newFolder("store");
        File part = new File(root, "music.part");
        File committed = new File(root, "music.wav");
        try (FileOutputStream output = new FileOutputStream(part)) { output.write(1); }
        try (FileOutputStream output = new FileOutputStream(committed)) { output.write(wav(640)); }
        new NativeAlertAudioStore(root);
        assertFalse(part.exists());
        assertTrue(committed.isFile());
    }
}
