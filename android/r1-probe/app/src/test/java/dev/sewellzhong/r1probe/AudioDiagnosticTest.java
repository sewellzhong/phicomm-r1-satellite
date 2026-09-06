package dev.sewellzhong.r1probe;

import java.io.*;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import org.junit.Test;
import org.junit.Rule;
import org.junit.rules.TemporaryFolder;
import static org.junit.Assert.*;

public class AudioDiagnosticTest {
    @Rule public TemporaryFolder temporary = new TemporaryFolder();
    private void awaitReady(AudioDiagnostic capture) throws Exception {
        long deadline=System.nanoTime()+3_000_000_000L;
        while(!capture.ready() && System.nanoTime()<deadline) Thread.sleep(10);
        assertTrue(capture.ready());
    }
    @Test public void disabledAndRoundTripPreservesPcmAndRequiresHashForDeletion() throws Exception {
        File directory=temporary.newFolder();
        AudioDiagnostic capture=new AudioDiagnostic(directory);
        capture.pcm("raw",123,new short[]{1},1,"disabled");
        assertEquals(0,directory.list().length);
        capture.start(30);
        short[] samples={-32768,0,32767};
        long timestamp=System.nanoTime();
        capture.pcm("raw",timestamp,samples,3,"frame=0"); samples[0]=42;
        capture.stop("requested"); awaitReady(capture);
        try(DataInputStream input=new DataInputStream(new ByteArrayInputStream(capture.read(0)))) {
            assertEquals(0x52314431,input.readInt()); assertEquals(0,input.readLong());
            assertEquals(timestamp,input.readLong()); assertEquals("raw",input.readUTF());
            assertEquals("frame=0",input.readUTF()); assertEquals(6,input.readInt());
            assertEquals(0,input.readUnsignedByte()); assertEquals(128,input.readUnsignedByte());
        }
        assertEquals(64,capture.hash().length());
        try { capture.clear("wrong"); fail(); } catch(IllegalStateException expected) { }
        assertTrue(capture.ready());
        try { capture.start(30); fail(); } catch(IllegalStateException expected) { }
        capture.clear(capture.hash()); assertFalse(capture.ready());
    }
    @Test public void timeoutWithoutFramesAndDuplicateStart() throws Exception {
        AudioDiagnostic capture=new AudioDiagnostic(temporary.newFolder());
        capture.start(1);
        try { capture.start(1); fail(); } catch(IllegalStateException expected) { }
        awaitReady(capture); assertEquals("timeout",capture.reason()); assertEquals(4,capture.bytes());
        for(int seconds:new int[]{0,31}) {
            try { capture.start(seconds); fail(); } catch(IllegalArgumentException expected) { }
        }
    }
    @Test public void blockedDiskCausesBoundedOverflowWithoutBlockingProducer() throws Exception {
        CountDownLatch blocked=new CountDownLatch(1), release=new CountDownLatch(1);
        AudioDiagnostic capture=new AudioDiagnostic(temporary.newFolder(),file -> new FilterOutputStream(new FileOutputStream(file)) {
            @Override public void write(byte[] bytes,int offset,int length) throws IOException {
                blocked.countDown();
                try { if(!release.await(3,TimeUnit.SECONDS)) throw new IOException("test_timeout"); }
                catch(InterruptedException error) { throw new IOException(error); }
                out.write(bytes,offset,length);
            }
        });
        capture.start(30);
        short[] frame=new short[320];
        for(int i=0;i<20;i++) capture.pcm("raw",System.nanoTime(),frame,320,"frame="+i);
        assertTrue(blocked.await(1,TimeUnit.SECONDS));
        long begin=System.nanoTime();
        for(int i=0;i<1000;i++) capture.pcm("raw",System.nanoTime(),frame,320,"overflow");
        assertTrue(System.nanoTime()-begin<1_000_000_000L);
        assertFalse(capture.active()); assertEquals("queue_overflow",capture.reason());
        release.countDown(); awaitReady(capture);
    }
    @Test public void interruptedCaptureCanBeExportedButNotOverwritten() throws Exception {
        File directory=temporary.newFolder();
        AudioDiagnostic first=new AudioDiagnostic(directory); first.start(30); first.stop("requested"); awaitReady(first);
        AudioDiagnostic restarted=new AudioDiagnostic(directory);
        assertEquals("interrupted_previous_process",restarted.reason());
        assertEquals(first.hash(),restarted.hash());
        try { restarted.read(-1); fail(); } catch(IllegalStateException expected) { }
        try { restarted.read(5); fail(); } catch(IllegalStateException expected) { }
        assertEquals(0,restarted.read(4).length);
    }
    @Test public void producerBudgetFailureStopsAndPreservesEvidence() throws Exception {
        AudioDiagnostic capture=new AudioDiagnostic(temporary.newFolder(),FileOutputStream::new,0);
        capture.start(30); capture.event(System.nanoTime(),"budget_test"); awaitReady(capture);
        assertEquals("producer_over_budget",capture.reason()); assertEquals(1,capture.producerOverBudget());
        assertTrue(capture.maxProducerNanos()>0); assertTrue(capture.bytes()>4);
    }
    @Test public void concurrentProducersDrainAndOldSessionFramesAreRejected() throws Exception {
        AudioDiagnostic capture=new AudioDiagnostic(temporary.newFolder()); capture.start(30);
        capture.event(1,"stale");
        Thread first=new Thread(() -> { for(int i=0;i<20;i++) capture.event(System.nanoTime(),"first"); });
        Thread second=new Thread(() -> { for(int i=0;i<20;i++) capture.event(System.nanoTime(),"second"); });
        first.start(); second.start(); first.join(); second.join(); capture.stop("requested"); awaitReady(capture);
        assertEquals("requested",capture.reason()); assertEquals(40,capture.records());
    }

    @Test public void armedWaitDoesNotRecordAndWakeActivatesOnlyOnce() throws Exception {
        AudioDiagnostic capture=new AudioDiagnostic(temporary.newFolder());
        capture.arm(1); assertTrue(capture.armed()); assertFalse(capture.active()); assertFalse(capture.ready());
        capture.pcm("raw",System.nanoTime(),new short[320],320,"before_wake");
        capture.event(System.nanoTime(),"ignored_before_wake");
        assertEquals(0,capture.records());
        assertTrue(capture.activateOnWake()); assertFalse(capture.armed()); assertTrue(capture.active());
        assertFalse(capture.activateOnWake());
        capture.pcm("raw",System.nanoTime(),new short[320],320,"after_wake");
        awaitReady(capture); assertEquals("timeout",capture.reason()); assertEquals(1,capture.records());
    }
    @Test public void armedTimeoutAndCancellationCannotActivateLater() throws Exception {
        AudioDiagnostic capture=new AudioDiagnostic(temporary.newFolder());
        capture.arm(30,20_000_000L); awaitReady(capture);
        assertEquals("arm_timeout",capture.reason()); assertEquals(4,capture.bytes());
        assertFalse(capture.activateOnWake()); capture.clear(capture.hash());
        capture.arm(30); capture.stop("requested"); awaitReady(capture);
        assertEquals("requested",capture.reason()); assertEquals(4,capture.bytes());
        assertFalse(capture.activateOnWake());
    }

}
