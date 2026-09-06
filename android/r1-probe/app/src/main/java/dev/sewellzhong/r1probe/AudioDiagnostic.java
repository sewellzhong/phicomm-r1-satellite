package dev.sewellzhong.r1probe;

import java.io.*;
import java.security.MessageDigest;
import java.util.Arrays;
import java.util.concurrent.ConcurrentLinkedQueue;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;

/** Explicit, bounded local recording. No microphone ownership and no audio-thread disk I/O. */
public final class AudioDiagnostic {
    private static final long LIMIT = 8 * 1024 * 1024;
    interface OutputFactory { OutputStream open(File file) throws IOException; }
    private final OutputFactory outputFactory;
    private final File file;
    private final ConcurrentLinkedQueue<Record> queue = new ConcurrentLinkedQueue<>();
    private final AtomicInteger queued = new AtomicInteger(), inFlight = new AtomicInteger();
    private final AtomicLong maxOffer = new AtomicLong(), maxProducer = new AtomicLong();
    private final AtomicLong maxCaptureProducer = new AtomicLong(), maxPlaybackProducer = new AtomicLong();
    private final AtomicInteger overBudget = new AtomicInteger();
    private final long producerBudgetNanos;
    private volatile boolean active, armed;
    private long captureDurationNanos;
    private volatile String reason = "disabled", sha256 = "";
    private volatile long deadline, startedAt, records, bytes;
    private Thread writer;
    private static final class Record {
        final long time; final String kind, detail; final byte[] pcm;
        Record(long time, String kind, String detail, byte[] pcm) {
            this.time=time; this.kind=kind; this.detail=detail; this.pcm=pcm;
        }
    }
    public AudioDiagnostic(File directory) { this(directory, FileOutputStream::new); }
    AudioDiagnostic(File directory, OutputFactory factory) { this(directory,factory,20_000_000L); }
    AudioDiagnostic(File directory, OutputFactory factory, long budgetNanos) {
        producerBudgetNanos=budgetNanos;
        outputFactory=factory;
        file = new File(directory, "audio-diagnostic.r1diag");
        if(file.exists()) reason="interrupted_previous_process";
    }
    public boolean active() { return active; }
    public boolean armed() { return armed; }
    public synchronized void start(int seconds) throws IOException { prepare(seconds,0); }
    public synchronized void arm(int seconds) throws IOException { arm(seconds,90_000_000_000L); }
    synchronized void arm(int seconds,long waitNanos) throws IOException {
        if(waitNanos<=0 || waitNanos>90_000_000_000L) throw new IllegalArgumentException("arm_duration");
        prepare(seconds,waitNanos);
    }
    private void prepare(int seconds,long waitNanos) throws IOException {
        if(seconds<1 || seconds>30) throw new IllegalArgumentException("duration");
        if(active || armed || inFlight.get()!=0 || (writer!=null && writer.isAlive()) || file.exists())
            throw new IllegalStateException("export_or_clear_previous_capture");
        queue.clear(); queued.set(0); records=bytes=0;
        maxOffer.set(0); maxProducer.set(0); maxCaptureProducer.set(0); maxPlaybackProducer.set(0); overBudget.set(0);
        sha256=""; reason=waitNanos>0 ? "armed" : "recording";
        captureDurationNanos=seconds*1_000_000_000L;
        startedAt=System.nanoTime(); deadline=startedAt+(waitNanos>0 ? waitNanos : captureDurationNanos);
        // Creation failures are returned before recording is armed.
        OutputStream output = outputFactory.open(file);
        armed=waitNanos>0; active=!armed;
        writer=new Thread(() -> write(output), "audio-diagnostic-writer");
        writer.setDaemon(true); writer.start();
    }
    public synchronized boolean activateOnWake() {
        if(!armed) return false;
        long now=System.nanoTime();
        if(now>=deadline) { stop("arm_timeout"); return false; }
        startedAt=now; deadline=now+captureDurationNanos; reason="recording";
        active=true; armed=false; // Never expose a false/false transition to the writer.
        return true;
    }
    private synchronized void expire(long now) {
        if((active || armed) && now>=deadline) stop(armed ? "arm_timeout" : "timeout");
    }
    public synchronized void stop(String why) {
        if(active || armed) { reason=why; active=false; armed=false; }
    }
    public void pcm(String kind, long time, short[] samples, int count, String detail) {
        inFlight.incrementAndGet();
        try {
            if(!active || time<startedAt) return;
            long begin=System.nanoTime();
            byte[] data=new byte[count*2];
            for(int i=0;i<count;i++) { data[2*i]=(byte)samples[i]; data[2*i+1]=(byte)(samples[i]>>>8); }
            offer(new Record(time,kind,detail,data));
            producerFinished(begin);
        } finally { inFlight.decrementAndGet(); }
    }
    public void playback(long time, byte[] samples, int offset, int count, String detail) {
        inFlight.incrementAndGet();
        try {
            if(!active || time<startedAt) return;
            long begin=System.nanoTime();
            for(int position=0;position<count && active;position+=2048) {
                int length=Math.min(2048,count-position);
                offer(new Record(time,"playback",detail+",chunk_byte_offset="+position,
                        Arrays.copyOfRange(samples,offset+position,offset+position+length)));
            }
            producerFinished(begin);
        } finally { inFlight.decrementAndGet(); }
    }
    public void event(long time, String detail) {
        inFlight.incrementAndGet();
        try {
            if(!active || time<startedAt) return;
            long begin=System.nanoTime();
            offer(new Record(time,"event",detail,new byte[0]));
            producerFinished(begin);
        } finally { inFlight.decrementAndGet(); }
    }
    private static void maximum(AtomicLong value,long sample) {
        long old;
        do { old=value.get(); if(sample<=old) return; } while(!value.compareAndSet(old,sample));
    }
    private void producerFinished(long begin) {
        long elapsed=System.nanoTime()-begin;
        maximum(maxProducer,elapsed);
        String thread=Thread.currentThread().getName();
        if("native-command-capture".equals(thread)) maximum(maxCaptureProducer,elapsed);
        if("native-local-prompt".equals(thread)) maximum(maxPlaybackProducer,elapsed);
        if(elapsed>producerBudgetNanos) { overBudget.incrementAndGet(); stop("producer_over_budget"); }
    }
    private void offer(Record record) {
        long begin=System.nanoTime();
        try {
            if(!active) return;
            if(begin>=deadline) { stop("timeout"); return; }
            int count;
            do {
                count=queued.get();
                if(count>=64) { stop("queue_overflow"); return; }
            } while(!queued.compareAndSet(count,count+1));
            queue.offer(record);
        } finally {
            maximum(maxOffer,System.nanoTime()-begin);
        }
    }
    private void write(OutputStream output) {
        try (DataOutputStream stream=new DataOutputStream(new BufferedOutputStream(output))) {
            stream.writeInt(0x52314431); // R1D1, subsequent integers are big endian; PCM is S16LE.
            while(armed || active || inFlight.get()!=0 || !queue.isEmpty()) {
                expire(System.nanoTime());
                Record record=queue.poll();
                if(record==null) { Thread.sleep(armed ? 50 : 5); continue; }
                queued.decrementAndGet();
                long size=32L+record.kind.length()*3L+record.detail.length()*3L+record.pcm.length;
                if(bytes+size>LIMIT) { stop("size_limit"); queue.clear(); break; }
                stream.writeLong(records++); stream.writeLong(record.time);
                stream.writeUTF(record.kind); stream.writeUTF(record.detail);
                stream.writeInt(record.pcm.length); stream.write(record.pcm);
                bytes+=size;
                Arrays.fill(record.pcm,(byte)0);
            }
        } catch(IOException | InterruptedException error) { reason="writer_failed"; active=false; armed=false; }
        finally { active=false; armed=false; queue.clear(); }
        try { sha256=digest(file); bytes=file.length(); }
        catch(Exception error) { reason="digest_failed"; }
    }
    public synchronized boolean ready() { return file.exists() && !active && !armed && inFlight.get()==0 && (writer==null || !writer.isAlive()); }
    public String reason() { return reason; }
    public long records() { return records; }
    public long bytes() { return ready()?file.length():bytes; }
    public long maxOfferNanos() { return maxOffer.get(); }
    public long maxProducerNanos() { return maxProducer.get(); }
    public long maxCaptureProducerNanos() { return maxCaptureProducer.get(); }
    public long maxPlaybackProducerNanos() { return maxPlaybackProducer.get(); }
    public int producerOverBudget() { return overBudget.get(); }
    public synchronized String hash() throws IOException {
        if(!ready()) throw new IllegalStateException("capture_not_ready");
        if(sha256.isEmpty()) sha256=digest(file);
        return sha256;
    }
    public synchronized byte[] read(long offset) throws IOException {
        if(!ready() || offset<0 || offset>file.length()) throw new IllegalStateException("invalid_export");
        byte[] chunk=new byte[(int)Math.min(2048,file.length()-offset)];
        try(RandomAccessFile input=new RandomAccessFile(file,"r")) { input.seek(offset); input.readFully(chunk); }
        return chunk;
    }
    public synchronized void clear(String expectedHash) throws IOException {
        if(!ready() || !hash().equals(expectedHash)) throw new IllegalStateException("capture_hash_mismatch");
        if(!file.delete()) throw new IOException("capture_delete_failed");
        sha256=""; reason="disabled"; records=bytes=0;
    }
    private static String digest(File file) throws IOException {
        try {
            MessageDigest digest=MessageDigest.getInstance("SHA-256");
            try(InputStream input=new FileInputStream(file)) {
                byte[] buffer=new byte[8192]; int count;
                while((count=input.read(buffer))!=-1) digest.update(buffer,0,count);
            }
            StringBuilder hex=new StringBuilder();
            for(byte value:digest.digest()) hex.append(String.format(java.util.Locale.ROOT,"%02x",value&255));
            return hex.toString();
        } catch(java.security.NoSuchAlgorithmException error) { throw new IOException(error); }
    }
}
