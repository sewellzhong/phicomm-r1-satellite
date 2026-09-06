package dev.sewellzhong.r1probe.esphome;

import java.io.IOException;
import java.util.ArrayDeque;
import java.util.Arrays;

/** Audio producer -> bounded mailbox -> single network owner. No concurrent Noise calls. */
public final class NativeAudioCoordinator implements NativeApiConnection.Handler {
    private final NativeVoiceSession.Playback playback;
    private final NativeVoiceSession.Clock clock;
    private final ArrayDeque<byte[]> pending = new ArrayDeque<>();
    private NativeVoiceSession session;
    private int pendingBytes;
    private boolean startPending, eof, accepting;
    private volatile boolean ready;
    private volatile boolean closed;
    private volatile boolean followup;
    public boolean shouldContinue() { return ready() && followup; }
    private volatile String failure;
    private volatile NativeVoiceSession.Outcome outcome = NativeVoiceSession.Outcome.NONE;

    public NativeAudioCoordinator(NativeVoiceSession.Playback playback, NativeVoiceSession.Clock clock) {
        this.playback = playback; this.clock = clock;
    }
    @Override public void connected(NativeVoiceSession.Sender sender) {
        session = new NativeVoiceSession(sender, clock, playback);
    }
    public boolean ready() { return ready && !closed && failure == null; }
    public synchronized boolean acceptingInput() { return accepting && !eof; }
    public String failure() { return failure; }
    public NativeVoiceSession.Outcome outcome() { return outcome; }

    public synchronized void begin(byte[] prebuffer) throws IOException {
        if (!ready() || startPending || accepting) throw new IOException("native_not_ready");
        if (prebuffer == null || prebuffer.length % 640 != 0 || prebuffer.length > 160000)
            throw new IOException("invalid_command_prebuffer");
        ready = false; startPending = true; accepting = true; eof = false;
        for (int i = 0; i < prebuffer.length; i += 640) enqueue(Arrays.copyOfRange(prebuffer, i, i + 640));
    }
    public synchronized void audio(byte[] pcm) throws IOException {
        if (!accepting || eof) return;
        if (pcm == null || pcm.length != 640) throw new IOException("invalid_command_frame");
        enqueue(pcm.clone());
    }
    private void enqueue(byte[] frame) throws IOException {
        if (pendingBytes + frame.length > 160000) {
            Arrays.fill(frame, (byte) 0); failure = "command_queue_overflow";
            clear(); accepting = false; throw new IOException(failure);
        }
        pending.add(frame); pendingBytes += frame.length;
    }
    public synchronized void endInput() { eof = true; }

    @Override public void message(int type, byte[] payload) throws IOException {
        try { session.handle(type, payload); tick(); }
        catch (IOException e) { failure = "native_session_failed"; throw e; }
    }
    @Override public void tick() throws IOException {
        if (session == null || closed) return;
        if (failure != null) { session.close(); throw new IOException(failure); }
        session.tick();
        boolean start;
        synchronized (this) { start = startPending; startPending = false; }
        if (start) session.startCommand();
        for (int count = 0; count < 50 && session.state() == NativeVoiceSession.State.STREAMING; count++) {
            byte[] frame;
            synchronized (this) { frame = pending.poll(); if (frame != null) pendingBytes -= frame.length; }
            if (frame == null) break;
            try { session.sendPcmFrame(frame); }
            finally { Arrays.fill(frame, (byte) 0); }
        }
        boolean finish;
        synchronized (this) {
            finish = eof && pending.isEmpty() && session.state() == NativeVoiceSession.State.STREAMING;
        }
        if (finish) session.finishInput();
        synchronized (this) {
            if (!startPending && session.state() != NativeVoiceSession.State.STARTING
                    && session.state() != NativeVoiceSession.State.STREAMING) {
                clear(); accepting = false;
            }
            outcome = session.outcome();
            followup = session.shouldContinue();
            ready = session.state() == NativeVoiceSession.State.IDLE && !startPending;
        }
    }
    private void clear() {
        for (byte[] frame : pending) Arrays.fill(frame, (byte) 0);
        pending.clear(); pendingBytes = 0;
    }
    @Override public synchronized void closed() {
        closed = true; ready = false; accepting = false; startPending = false; clear();
        if (session != null) { session.close(); outcome = session.outcome(); }
        playback.stop();
    }
}
