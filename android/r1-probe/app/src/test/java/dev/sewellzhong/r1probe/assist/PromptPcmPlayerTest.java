package dev.sewellzhong.r1probe.assist;

import dev.sewellzhong.r1probe.esphome.NativePcmPlayback;
import java.io.*;
import java.nio.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;
import org.junit.Test;
import static org.junit.Assert.*;

public class PromptPcmPlayerTest {
    private byte[] wav() {
        ByteBuffer b=ByteBuffer.allocate(684).order(ByteOrder.LITTLE_ENDIAN);
        b.put(new byte[]{82,73,70,70}).putInt(676).put(new byte[]{87,65,86,69,102,109,116,32});
        b.putInt(16).putShort((short)1).putShort((short)1).putInt(16000).putInt(32000).putShort((short)2).putShort((short)16);
        b.put(new byte[]{100,97,116,97}).putInt(640);return b.array();
    }
    static class Sink implements NativePcmPlayback.Sink {
        volatile boolean consumed, closed; int bytes;
        CountDownLatch written=new CountDownLatch(1);
        public void start() { }
        public int write(byte[] b,int off,int n) { int count=Math.min(n,126);bytes+=count;if(bytes==640)written.countDown();return count; }
        public long playedFrames(){return consumed ? bytes/2 : 0;}
        public void stop(){ }
        public void close(){closed=true;}
    }
    @Test public void callbackWaitsForPlaybackHeadNotLastWrite() throws Exception {
        Sink sink=new Sink();AtomicBoolean callback=new AtomicBoolean(), stop=new AtomicBoolean();
        AtomicReference<Throwable> error=new AtomicReference<>();
        Thread worker=new Thread(()->{try {PromptPcmPlayer.play(new ByteArrayInputStream(wav()),sink,stop,()->{assertFalse(sink.closed);callback.set(true);});}catch(Throwable e){error.set(e);}});
        worker.start();
        try {assertTrue(sink.written.await(3,TimeUnit.SECONDS));assertFalse(callback.get());sink.consumed=true;worker.join(3000);assertFalse(worker.isAlive());assertNull(error.get());assertTrue(callback.get());assertTrue(sink.closed);}
        finally {stop.set(true);worker.join(3000);}
    }
    @Test public void cancellationNeverSignalsReady() throws Exception {
        Sink sink=new Sink();AtomicBoolean called=new AtomicBoolean();
        PromptPcmPlayer.play(new ByteArrayInputStream(wav()),sink,new AtomicBoolean(true),()->called.set(true));
        assertFalse(called.get());assertTrue(sink.closed);assertEquals(0,sink.bytes);
    }
    @Test public void truncatedAndWrongFormatFailClosed() throws Exception {
        byte[] wrong=wav();wrong[24]=1;
        for(byte[] data:new byte[][]{new byte[4],wrong,java.util.Arrays.copyOf(wav(),80)}) {
            Sink sink=new Sink();sink.consumed=true;AtomicBoolean called=new AtomicBoolean();
            try {PromptPcmPlayer.play(new ByteArrayInputStream(data),sink,new AtomicBoolean(),()->called.set(true));fail();}
            catch(IOException expected){assertFalse(called.get());assertTrue(sink.closed);}
        }
    }
}
