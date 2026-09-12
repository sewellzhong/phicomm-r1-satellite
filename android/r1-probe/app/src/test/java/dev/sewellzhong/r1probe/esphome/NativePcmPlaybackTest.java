package dev.sewellzhong.r1probe.esphome;

import org.junit.Test;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import static org.junit.Assert.*;

public class NativePcmPlaybackTest {
    private static class Gate implements NativePcmPlayback.Gate {
        volatile boolean ready, requested, released, drainNotified;
        public void request() { requested=true; }
        public boolean microphoneReleased() { return ready; }
        public void release() { released=true; }
        public void drained() { assertFalse(released); drainNotified=true; }
    }
    private static class Sink implements NativePcmPlayback.Sink {
        final ByteArrayOutputStream data = new ByteArrayOutputStream();
        final CountDownLatch written = new CountDownLatch(1);
        volatile boolean drained, closed;
        public void start() { }
        public synchronized int write(byte[] bytes, int offset, int length) {
            int n=Math.min(length,126); data.write(bytes,offset,n);
            if(data.size()==1500) written.countDown();
            return n;
        }
        public synchronized long playedFrames() { return drained ? data.size()/2 : 0; }
        public void stop() { }
        public void close() { closed=true; }
    }
    private static void completed(NativePcmPlayback player) throws Exception {
        long deadline=System.nanoTime()+3_000_000_000L;
        while (!player.complete() && player.failure()==null && System.nanoTime()<deadline) Thread.sleep(5);
        assertNull(player.failure()); assertTrue(player.complete());
    }
    @Test public void waitsForMicrophoneAndHardwareDrainAndPreservesPartialFrames() throws Exception {
        Gate gate=new Gate(); Sink sink=new Sink();
        java.util.List<String> events=java.util.Collections.synchronizedList(new java.util.ArrayList<>());
        NativePcmPlayback player=new NativePcmPlayback(()->sink,gate,events::add);
        try {
            player.start(); byte[] expected=new byte[1500];
            for(int i=0;i<expected.length;i++)expected[i]=(byte)(i%127);
            player.audio(java.util.Arrays.copyOfRange(expected,0,126));
            player.audio(java.util.Arrays.copyOfRange(expected,126,1150));
            player.audio(java.util.Arrays.copyOfRange(expected,1150,1500)); player.end();
            assertTrue(gate.requested); assertEquals(0,sink.data.size()); assertFalse(player.complete());
            gate.ready=true;
            assertTrue(sink.written.await(3,TimeUnit.SECONDS));
            assertFalse(player.complete()); assertFalse(gate.drainNotified);
            sink.drained=true; completed(player);
            assertArrayEquals(expected,sink.data.toByteArray()); assertTrue(sink.closed); assertTrue(gate.released); assertTrue(gate.drainNotified);
            assertTrue(events.stream().anyMatch(value -> value.contains("playback_first_write")));
            assertTrue(events.stream().anyMatch(value -> value.contains("playback_drained")));
            assertTrue(events.stream().anyMatch(value -> value.contains("buffer_high_water_bytes=1500")));
            assertTrue(player.requestedMillis() > 0);
            assertTrue(player.firstWriteMillis() >= player.requestedMillis());
            assertTrue(player.drainedMillis() >= player.firstWriteMillis());
            assertTrue(player.releasedMillis() >= player.drainedMillis());
            assertEquals(1500, player.highWaterBytes());
            assertTrue(player.underruns() >= 0);
        } finally { player.stop(); }
    }
    @Test public void overflowAndOddSamplesAreRejectedWithoutUnboundedAllocation() throws Exception {
        Gate gate=new Gate(); NativePcmPlayback player=new NativePcmPlayback(Sink::new,gate);
        try {
            player.start();
            try { player.audio(new byte[1]); fail(); } catch(IOException expected) { }
            player.audio(new byte[32768]);
            try { player.audio(new byte[2]); fail(); } catch(IOException expected) { }
        } finally { player.stop(); }
    }
    @Test public void stopUnblocksWriterAndNeverReportsCompletion() throws Exception {
        Gate gate=new Gate();gate.ready=true;
        CountDownLatch entered=new CountDownLatch(1), unblock=new CountDownLatch(1), closed=new CountDownLatch(1);
        NativePcmPlayback player=new NativePcmPlayback(()->new NativePcmPlayback.Sink() {
            public void start() { }
            public int write(byte[] b,int o,int n) throws Exception { entered.countDown();unblock.await();return n; }
            public long playedFrames() { return 0; }
            public void stop() { unblock.countDown(); }
            public void close() { closed.countDown(); }
        },gate);
        player.start();player.audio(new byte[640]);
        assertTrue(entered.await(3,TimeUnit.SECONDS));player.stop();
        assertTrue(closed.await(3,TimeUnit.SECONDS));assertFalse(player.complete());
    }
    @Test public void blockedNativeStopDoesNotBlockProtocolOwnerOrPretendTerminated() throws Exception {
        Gate gate = new Gate(); gate.ready = true;
        CountDownLatch started = new CountDownLatch(1), stopping = new CountDownLatch(1), release = new CountDownLatch(1);
        AtomicInteger stopCalls = new AtomicInteger(), closeCalls = new AtomicInteger();
        NativePcmPlayback player = new NativePcmPlayback(() -> new NativePcmPlayback.Sink() {
            public void start() { started.countDown(); }
            public int write(byte[] b, int o, int n) { return n; }
            public long playedFrames() { return 0; }
            public void stop() {
                stopCalls.incrementAndGet();
                stopping.countDown();
                boolean done = false;
                while (!done) try { release.await(); done = true; } catch (InterruptedException ignored) { }
            }
            public void close() { closeCalls.incrementAndGet(); }
        }, gate);
        java.util.concurrent.ExecutorService caller = java.util.concurrent.Executors.newSingleThreadExecutor();
        try {
            player.start(); assertTrue(started.await(2, TimeUnit.SECONDS));
            caller.submit(player::stop).get(1, TimeUnit.SECONDS);
            assertTrue(stopping.await(2, TimeUnit.SECONDS));
            assertFalse(player.terminated()); assertFalse(player.complete());
        } finally {
            release.countDown(); caller.shutdownNow(); player.stop();
        }
        long until = System.nanoTime() + 2_000_000_000L;
        while (!player.terminated() && System.nanoTime() < until) Thread.sleep(5);
        assertTrue(player.terminated());
        assertEquals(1, stopCalls.get()); assertEquals(1, closeCalls.get());
    }
    @Test public void emptyStreamFailsRatherThanAcknowledgingPlayback() throws Exception {
        Gate gate=new Gate();gate.ready=true;
        NativePcmPlayback player=new NativePcmPlayback(Sink::new,gate);
        try {
            player.start();player.end();
            long until=System.nanoTime()+3_000_000_000L;
            while(player.failure()==null && System.nanoTime()<until)Thread.sleep(5);
            assertNotNull(player.failure());assertFalse(player.complete());
        } finally { player.stop(); }
    }
}
