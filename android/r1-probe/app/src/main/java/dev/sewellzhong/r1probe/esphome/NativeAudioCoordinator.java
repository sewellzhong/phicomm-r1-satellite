package dev.sewellzhong.r1probe.esphome;

import java.io.IOException;
import java.util.ArrayDeque;
import java.util.Arrays;

/** Audio producer -> bounded mailbox -> single network owner. No concurrent Noise calls. */
public final class NativeAudioCoordinator implements NativeApiConnection.Handler {
    public enum CancelReason { USER_STOP, NEW_WAKE, DIRECT_SPEECH, TIMER_ALARM, CONNECTION_CLOSED, PLAYBACK_FAILURE, SERVICE_STOP }
    public enum RestartReason { NONE, NEW_WAKE, DIRECT_SPEECH }
    private enum CancelPhase { NONE, REQUESTED, DISPATCHED, COMPLETE }
    public interface Observer { void event(String detail); }
    private static final Observer NO_EVENTS = detail -> { };
    private final NativeVoiceSession.Playback playback;
    private final NativeVoiceSession.Clock clock;
    private final Observer observer;
    private final ArrayDeque<byte[]> pending = new ArrayDeque<>();
    private NativeVoiceSession session;
    private int pendingBytes;
    private boolean startPending, eof, accepting;
    private CancelPhase cancelPhase = CancelPhase.NONE;
    private CancelReason cancelReason;
    private RestartReason restartPending = RestartReason.NONE;
    private long runSequence, activeRun;
    private NativeVoiceSession.State reportedState;
    private volatile boolean ready;
    private volatile boolean closed;
    private volatile boolean followup;
    public boolean shouldContinue() { return ready() && followup; }
    private volatile String failure;
    private volatile NativeVoiceSession.Outcome outcome = NativeVoiceSession.Outcome.NONE;

    public NativeAudioCoordinator(NativeVoiceSession.Playback playback, NativeVoiceSession.Clock clock) {
        this(playback, clock, NO_EVENTS);
    }
    public NativeAudioCoordinator(NativeVoiceSession.Playback playback, NativeVoiceSession.Clock clock,
            Observer observer) {
        this.playback = playback; this.clock = clock; this.observer = observer == null ? NO_EVENTS : observer;
    }
    @Override public void connected(NativeVoiceSession.Sender sender) {
        session = new NativeVoiceSession(sender, clock, playback);
        reportedState = session.state();
        event("voice_connected,state=" + reportedState);
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
        cancelPhase = CancelPhase.NONE; cancelReason = null;
        restartPending = RestartReason.NONE;
        activeRun = ++runSequence;
        event("voice_run=" + activeRun + ",event=input_accepted");
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

    /** May be called by capture, key, or service threads. Local audio is stopped immediately;
     * the authenticated protocol cancellation is dispatched later by the single owner thread. */
    public boolean requestCancel(CancelReason reason) {
        if (reason == null) throw new IllegalArgumentException("cancel_reason_required");
        long run;
        synchronized (this) {
            if (closed || session == null || cancelPhase != CancelPhase.NONE || !active()) return false;
            cancelPhase = CancelPhase.REQUESTED; cancelReason = reason;
            restartPending = reason == CancelReason.NEW_WAKE ? RestartReason.NEW_WAKE
                    : reason == CancelReason.DIRECT_SPEECH ? RestartReason.DIRECT_SPEECH
                    : RestartReason.NONE;
            startPending = false; accepting = false; eof = true; clear(); ready = false;
            run = activeRun;
        }
        event("voice_run=" + run + ",event=cancel_requested,reason=" + lower(reason));
        playback.stop();
        event("voice_run=" + run + ",event=local_playback_stop_requested");
        return true;
    }

    /** Consumes an interruption intent only after the cancelled run and old player are fully idle. */
    public synchronized RestartReason takeRestart() {
        if (!ready || outcome != NativeVoiceSession.Outcome.CANCELLED) return RestartReason.NONE;
        RestartReason restart = restartPending;
        restartPending = RestartReason.NONE;
        return restart;
    }

    private boolean active() {
        // activeRun and ready are maintained by the owner thread and published through the
        // coordinator lock/volatile ready flag; callers never inspect session internals cross-thread.
        return activeRun != 0 && !ready;
    }

    @Override public void message(int type, byte[] payload) throws IOException {
        try { session.handle(type, payload); reportState(); tick(); }
        catch (IOException e) { failure = "native_session_failed"; throw e; }
    }
    @Override public void tick() throws IOException {
        if (session == null || closed) return;
        if (failure != null) { session.close(); throw new IOException(failure); }
        boolean cancel;
        CancelReason reason;
        synchronized (this) {
            cancel = cancelPhase == CancelPhase.REQUESTED;
            reason = cancelReason;
            if (cancel) cancelPhase = CancelPhase.DISPATCHED;
        }
        if (cancel) {
            boolean sent = session.cancelAfterLocalStop();
            event("voice_run=" + activeRun + ",event="
                    + (sent ? "remote_cancel_sent" : "remote_cancel_not_needed") + ",reason="
                    + lower(reason));
            reportState();
        }
        session.tick();
        reportState();
        boolean start;
        synchronized (this) { start = startPending && cancelPhase == CancelPhase.NONE; startPending = false; }
        if (start) session.startCommand();
        for (int count = 0; count < 50 && session.state() == NativeVoiceSession.State.STREAMING; count++) {
            byte[] frame;
            synchronized (this) { frame = pending.poll(); if (frame != null) pendingBytes -= frame.length; }
            if (frame == null) break;
            boolean cancelled;
            synchronized (this) { cancelled = cancelPhase != CancelPhase.NONE; }
            try { if (!cancelled) session.sendPcmFrame(frame); }
            finally { Arrays.fill(frame, (byte) 0); }
            if (cancelled) break;
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
            NativeVoiceSession.Outcome sessionOutcome = session.outcome();
            boolean cancelling = cancelPhase != CancelPhase.NONE;
            outcome = cancelling && sessionOutcome != NativeVoiceSession.Outcome.FAILED
                    ? NativeVoiceSession.Outcome.CANCELLED : sessionOutcome;
            followup = !cancelling && session.shouldContinue();
            ready = session.state() == NativeVoiceSession.State.IDLE && !startPending && playback.terminated();
            if (ready && cancelPhase == CancelPhase.DISPATCHED) {
                cancelPhase = CancelPhase.COMPLETE;
                event("voice_run=" + activeRun + ",event=cancel_complete,outcome=" + lower(outcome));
            }
        }
    }
    private void reportState() {
        NativeVoiceSession.State state = session.state();
        if (state != reportedState) {
            reportedState = state;
            event("voice_run=" + activeRun + ",event=state,state=" + lower(state));
        }
    }
    private static String lower(Enum<?> value) { return value.name().toLowerCase(java.util.Locale.ROOT); }
    private void event(String detail) {
        try { observer.event(detail); } catch (RuntimeException ignored) { /* Diagnostics never own audio. */ }
    }
    private void clear() {
        for (byte[] frame : pending) Arrays.fill(frame, (byte) 0);
        pending.clear(); pendingBytes = 0;
    }
    @Override public synchronized void closed() {
        closed = true; ready = false; accepting = false; startPending = false;
        restartPending = RestartReason.NONE; clear();
        event("voice_run=" + activeRun + ",event=connection_closed");
        if (session != null) { session.close(); outcome = session.outcome(); }
        playback.stop();
    }
}
