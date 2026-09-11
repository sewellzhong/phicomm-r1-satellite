package dev.sewellzhong.r1probe;

import android.content.Context;
import android.media.AudioFormat;
import android.media.AudioRecord;
import dev.sewellzhong.r1probe.assist.AcknowledgementSelector;
import dev.sewellzhong.r1probe.assist.BargeInCapture;
import dev.sewellzhong.r1probe.assist.CommandWindow;
import dev.sewellzhong.r1probe.assist.DiagnosticWindowRequest;
import dev.sewellzhong.r1probe.assist.PcmPrebuffer;
import dev.sewellzhong.r1probe.esphome.NativeApiConnection;
import dev.sewellzhong.r1probe.esphome.NativeAudioCoordinator;
import dev.sewellzhong.r1probe.esphome.NativePcmPlayback;
import dev.sewellzhong.r1probe.esphome.NativeVoiceSession;
import java.io.IOException;
import java.util.Arrays;
import java.util.Random;
import java.util.concurrent.atomic.AtomicBoolean;

/** Per-connection audio handler owned by NativeSatelliteService, separate from the WS runtime.
 * The service owns authentication, wake locks, connection recovery and stalled-backend protection. */
public final class NativeAudioRuntime implements NativeApiConnection.Handler {
    private final Context context;
    private AudioDiagnostic diagnostic;
    void diagnostic(AudioDiagnostic value) { diagnostic=value; }
    private void diagnosticPcm(String kind, short[] frame, int count, long time, String extra) {
        if(diagnostic!=null && diagnostic.active()) diagnostic.pcm(kind,time,frame,count,
                "frame="+frames+",status="+status+",prompt="+lastPromptKind+":"+lastPromptIndex
                +",window="+windowId+","+extra);
    }
    private void diagnosticEvent(String detail) {
        if(diagnostic!=null) diagnostic.event(System.nanoTime(),detail);
    }
    private final boolean listen;
    interface AudioPermission { boolean allowed(); }
    private final AudioPermission permission;
    private long lastIsolationCheck;
    private void requireAudioPermission() throws IOException {
        if (!permission.allowed()) throw new IOException("factory_audio_not_isolated");
    }
    private final NativeSettings settings;
    private final NativeControls controls;
    private NativeVoiceSession.Sender sender;
    private final Random promptRandom = new Random();
    private int lastEndingPrompt = -1;
    private final dev.sewellzhong.r1probe.assist.PlaybackInputBoundary playbackInput = new dev.sewellzhong.r1probe.assist.PlaybackInputBoundary();
    private volatile long emptyResumes, endingPrompts;
    private volatile Thread promptPlayer;
    private final short[] promptHandoff = new short[320];
    private int promptHandoffCount;
    private volatile boolean microphoneWarmAtPromptEnd;
    private volatile String lastPromptKind = "none";
    private volatile long promptDrainedAt;
    private volatile int lastPromptIndex;
    private final dev.sewellzhong.r1probe.assist.PromptReference promptReference = new dev.sewellzhong.r1probe.assist.PromptReference();
    private dev.sewellzhong.r1probe.esphome.NativePcmPlayback.Sink referenceSink() {
        NativeVolume volume = new NativeVolume(context, settings);
        NativeAudioTrackSink sink = new NativeAudioTrackSink(volume);
        return new dev.sewellzhong.r1probe.esphome.NativePcmPlayback.Sink() {
            private long diagnosticHeadTime;
            public void start() { sink.start(); }
            public int write(byte[] bytes,int offset,int length) {
                float gain=volume.gain(); int count=sink.write(bytes,offset,length);
                if(count>0) {
                    promptReference.append(bytes,offset,count,gain);
                    if(diagnostic!=null && diagnostic.active()) diagnostic.playback(System.nanoTime(),bytes,offset,count,
                            "gain="+gain+",head="+sink.playedFrames()+",prompt="+lastPromptKind+":"+lastPromptIndex);
                }
                promptReference.position(sink.playedFrames(),System.nanoTime());return count;
            }
            public long playedFrames() {
                long frames=sink.playedFrames(), now=System.nanoTime(); promptReference.position(frames,now);
                if(diagnostic!=null && diagnostic.active() && now-diagnosticHeadTime>=20_000_000L) {
                    diagnosticHeadTime=now; diagnosticEvent("playback_head="+frames);
                }
                return frames;
            }
            public void stop() {sink.stop();}
            public void close() {sink.close();}
        };
    }
    private void prompt(String group, int index) throws Exception {
        requireAudioPermission();
        Thread previous = promptPlayer;
        if (previous != null && previous.isAlive()) {
            previous.join(1500);
            if (previous.isAlive()) throw new IOException("prompt_player_stalled");
        }
        // Open and drain BEFORE playing the cue. There is no post-cue sleep/open gap.
        long deadline = System.nanoTime()+2_000_000_000L;
        while(playbackRequested && !stopping.get() && System.nanoTime()<deadline) Thread.sleep(1);
        if (stopping.get()) return;
        if(playbackRequested) throw new IOException("prompt_playback_gate_busy");
        if(recorder==null) startRecorder();
        AudioRecord input=recorder;
        if(input==null) throw new IOException("prompt_microphone_missing");
        short[] discard=new short[320];
        int warmCount=input.read(discard,0,320);
        if(warmCount<=0) throw new IOException("prompt_microphone_not_ready");
        lastRead=System.nanoTime(); frames++;
        diagnosticPcm("raw",discard,warmCount,lastRead,"phase=prompt_warmup");
        dev.sewellzhong.r1probe.assist.PromptAudioBoundary boundary = new dev.sewellzhong.r1probe.assist.PromptAudioBoundary();
        java.util.concurrent.atomic.AtomicReference<Throwable> problem = new java.util.concurrent.atomic.AtomicReference<>();
        int rate = Math.round(settings.speechSpeed() * 100);
        String path="interaction/"+rate+"/"+group+"-"+index+".wav";
        promptReference.start(); lastPromptIndex=index;
        microphoneWarmAtPromptEnd=false; lastPromptKind=group; promptDrainedAt=0;
        Thread worker=new Thread(() -> {
            try (java.io.InputStream asset = context.getAssets().open(path)) {
                dev.sewellzhong.r1probe.assist.PromptPcmPlayer.play(asset,
                    referenceSink(), stopping, () -> {
                        promptDrainedAt=System.nanoTime();
                        promptReference.finish(promptDrainedAt);
                        microphoneWarmAtPromptEnd=recorder==input;
                        diagnosticEvent("prompt_drained="+promptDrainedAt);
                        boundary.complete();
                    });
            } catch(Exception | LinkageError error) { problem.set(error); boundary.complete(); }
        }, "native-local-prompt");
        worker.setDaemon(true); promptPlayer=worker; worker.start();
        long promptDeadline=System.nanoTime()+20_000_000_000L;
        try {
            while(!stopping.get()) {
                if(System.nanoTime()>promptDeadline) throw new IOException("local_prompt_timeout");
                long readStarted=System.nanoTime();
                int count=input.read(discard,0,320);
                lastRead=System.nanoTime();
                if(count<=0) throw new IOException("prompt_capture_failed");
                frames++;
                diagnosticPcm("raw",discard,count,lastRead,"phase=prompt,read_started_ns="+readStarted);
                if(boundary.accept(discard,count)) {
                    promptHandoffCount=boundary.copyTo(promptHandoff);
                    if(problem.get()!=null) throw new IOException("local_prompt_failed");
                    return; // Keep recording immediately; player resource cleanup may finish in parallel.
                }
                if(count==320) promptReference.process(discard,lastRead);
                else promptReference.resetConfidence();
                diagnosticPcm("processed",discard,count,lastRead,"phase=prompt,vad=not_run");
            }
        } finally {
            Arrays.fill(discard,(short)0);
            if(stopping.get()) worker.join(1500);
        }
    }
    private void endingPrompt() throws Exception {
        int next = promptRandom.nextInt(lastEndingPrompt < 0 ? 4 : 3);
        if (lastEndingPrompt >= 0 && next >= lastEndingPrompt) next++;
        lastEndingPrompt = next;
        status = "ending_conversation";
        prompt("ending", next);
        endingPrompts++;
        // Ending audio is never input to Alexa or a subsequent command.
        promptHandoffCount = 0; Arrays.fill(promptHandoff, (short)0);
        releaseRecorder();
    }
    @Override public void listEntities(NativeVoiceSession.Sender sender) throws IOException { controls.list(sender); }

    private final NativePcmPlayback playback;
    private volatile boolean wakeEnabled;
    private volatile boolean everOpened;
    private volatile boolean authenticated;
    public boolean authenticated() { return authenticated; }
    public String failureCode() { return failure; }
    private volatile long frames, wakes, replyWakeInterruptions, directBargeInterruptions, commands, transcripts, replies, completed, noInputs;
    private final dev.sewellzhong.r1probe.assist.SpeechEvidence evidence = new dev.sewellzhong.r1probe.assist.SpeechEvidence();
    private DiagnosticWindowRequest diagnosticWindow;
    private volatile String windowSource = "none";
    public void diagnosticWindow(boolean followup) { diagnosticWindow(followup,-1); }
    public synchronized void diagnosticWindow(boolean followup,int promptIndex) {
        DiagnosticWindowRequest request=new DiagnosticWindowRequest(followup,promptIndex);
        if (!"listening".equals(status) || !coordinator.ready() || diagnosticWindow != null)
            throw new IllegalStateException("diagnostic_requires_idle");
        diagnosticWindow = request;
    }
    private synchronized DiagnosticWindowRequest takeDiagnosticWindow() {
        DiagnosticWindowRequest value=diagnosticWindow;
        if(value!=null) { diagnosticWindow=null; status="diagnostic_requested"; }
        return value;
    }
    private volatile long windowId, windowOpened, onsetMillis, inputBytes;
    private volatile int voicedMillis, commandMillis;
    private final String[] onsetTrace = new String[80];
    private int traceFrames, traceRaw, traceSpeech, traceStrong, tracePeak;
    private void traceOnset(boolean raw, boolean speech, boolean strong) {
        if (traceFrames >= 400) return;
        traceFrames++; if(raw) traceRaw++; if(speech) traceSpeech++; if(strong) traceStrong++;
        tracePeak = Math.max(tracePeak, (int)Math.round(rms));
        if(traceFrames%5==0) {
            onsetTrace[traceFrames/5-1] = (traceFrames*20)+":"+tracePeak+":"+traceRaw+":"+traceSpeech+":"+traceStrong;
            traceRaw=traceSpeech=traceStrong=tracePeak=0;
        }
    }
    private org.json.JSONArray onsetTraceJson() {
        org.json.JSONArray result = new org.json.JSONArray();
        for(String item:onsetTrace) if(item!=null) result.put(item);
        return result;
    }
    private volatile String onsetReason = "none";
    private volatile String endReason = "none";
    private volatile double rms, noiseFloor;
    private volatile String event = "none";
    public org.json.JSONObject diagnostics() throws org.json.JSONException {
        return new org.json.JSONObject().put("microphone_warm_at_prompt_end", microphoneWarmAtPromptEnd).put("audio_frames", frames).put("wake_detections", wakes)
                .put("window_wait_ms", windowWaitMillis).put("window_kind", windowKind).put("window_source", windowSource).put("window_id", windowId).put("onset_trace_ms_peak_vad_speech_strong", onsetTraceJson()).put("onset_reason", onsetReason).put("onset_ms", onsetMillis).put("voiced_ms", voicedMillis)
                .put("command_ms", commandMillis).put("input_bytes", inputBytes).put("end_reason", endReason)
                .put("rms", Math.round(rms)).put("noise_floor", Math.round(noiseFloor))
                .put("commands", commands).put("stt_results", transcripts).put("tts_streams", replies)
                .put("reply_wake_interruptions", replyWakeInterruptions)
                .put("direct_barge_interruptions", directBargeInterruptions)
                .put("prompt_index", lastPromptIndex).put("reference_correlation", promptReference.correlation)
                .put("reference_delay_samples", promptReference.delaySamples).put("reference_before_rms", promptReference.beforeRms)
                .put("reference_after_rms", promptReference.afterRms).put("reference_matched_frames", promptReference.matchedFrames)
                .put("reference_processed_frames", promptReference.processedFrames).put("reference_max_us", promptReference.maxProcessNanos/1000)
                .put("reference_over_budget_frames", promptReference.overBudgetFrames).put("last_prompt_kind", lastPromptKind).put("prompt_drained_monotonic_ms", promptDrainedAt / 1_000_000L).put("empty_resumes", emptyResumes).put("ending_prompts", endingPrompts).put("completed", completed).put("no_input_windows", noInputs).put("last_event", event);
    }
    private final AtomicBoolean stopping = new AtomicBoolean();
    private final NativeAudioCoordinator coordinator;
    private volatile boolean playbackRequested;
    private volatile AudioRecord recorder;
    private volatile long lastRead;
    private volatile String failure;
    private volatile String status = "waiting_subscription";
    private Thread capture;
    private volatile Thread recorderStopper;
    private AudioRecord stopTarget;

    public NativeAudioRuntime(Context context) {
        this(context, true);
    }
    public NativeAudioRuntime(Context context, boolean listen) {
        this(context, listen, () -> FactoryAudioIsolation.permitsAudio(FactoryAudioIsolation.inspect(context)));
    }
    NativeAudioRuntime(Context context, boolean listen, AudioPermission permission) {
        this.context = context.getApplicationContext();
        this.listen = listen;
        this.permission = permission;
        settings = new NativeSettings(context);
        controls = new NativeControls(context, settings);
        wakeEnabled = settings.wakeEnabled();
        playback = new NativePcmPlayback(() -> {
            requireAudioPermission();
            lastPromptKind = "tts"; lastPromptIndex = -1; promptReference.start();
            return referenceSink();
        }, new NativePcmPlayback.Gate() {
            @Override public void request() { playbackInput.start(); playbackRequested = true; }
            @Override public boolean microphoneReleased() { return true; }
            @Override public void drained() {
                promptReference.finish(System.nanoTime()); playbackInput.drained();
            }
            @Override public void release() {
                promptReference.finish(System.nanoTime()); playbackRequested = false;
            }
        }, this::diagnosticEvent);
        coordinator = new NativeAudioCoordinator(playback, () -> System.nanoTime() / 1_000_000L,
                this::diagnosticEvent);
    }
    boolean cancelAudio(NativeAudioCoordinator.CancelReason reason) { return coordinator.requestCancel(reason); }
    public String status() { return status; }
    public boolean audioOpened() { return everOpened; }
    public boolean terminated() { return (capture == null || !capture.isAlive()) && (promptPlayer == null || !promptPlayer.isAlive()) && playback.terminated() && (recorderStopper == null || !recorderStopper.isAlive()); }
    @Override public boolean wakeEnabled() { return wakeEnabled; }
    @Override public void wakeEnabled(boolean enabled) { settings.wakeEnabled(enabled); wakeEnabled = enabled; }
    @Override public void connected(NativeVoiceSession.Sender sender) {
        this.sender = sender;
        authenticated = true;
        coordinator.connected(sender);
        status = listen ? "waiting_subscription" : "authenticated_no_microphone";
        if (!listen) return;
        capture = new Thread(this::captureLoop, "native-command-capture");
        capture.setDaemon(true); capture.start();
    }
    @Override public void message(int type, byte[] payload) throws IOException {
        if (controls.message(type, payload, sender)) return;
        coordinator.message(type, payload);
        if (type == dev.sewellzhong.r1probe.esphome.proto.MessageIds.VoiceAssistantEventResponse) {
            dev.sewellzhong.r1probe.esphome.proto.EsphomeApi.VoiceAssistantEvent kind =
                    dev.sewellzhong.r1probe.esphome.proto.EsphomeApi.VoiceAssistantEventResponse.parseFrom(payload).getEventType();
            event = kind.name();
            diagnosticEvent("ha_event="+event);
            switch (kind) {
                case VOICE_ASSISTANT_STT_END: transcripts++; break;
                case VOICE_ASSISTANT_TTS_STREAM_START: replies++; break;
                default: break;
            }
        }
    }
    @Override public void tick() throws IOException {
        if (sender != null) controls.tick(sender);
        if (failure != null) throw new IOException(failure);
        long now = System.nanoTime();
        if (listen && now - lastIsolationCheck > 1_000_000_000L) {
            lastIsolationCheck = now;
            requireAudioPermission();
        }
        if (recorder != null && System.nanoTime() - lastRead > 10_000_000_000L) {
            failure = "native_capture_timeout"; stopRecorder(); throw new IOException(failure);
        }
        coordinator.tick();
    }
    @Override public void closed() {
        if (!stopping.compareAndSet(false, true)) return;
        if(diagnostic!=null) diagnostic.stop("connection_closed");
        stopRecorder(); coordinator.closed();
        new NativeVolume(context, settings).restoreOutput();
        if (capture != null) capture.interrupt();
        status = "closed";
    }
    private volatile int windowWaitMillis;
    private volatile String windowKind = "none";
    private void openedWindow(CommandWindow window, boolean following) {
        windowWaitMillis = window.waitLimitMillis(); windowKind = following ? "followup" : "initial";
        Arrays.fill(onsetTrace,null); traceFrames=traceRaw=traceSpeech=traceStrong=tracePeak=0;
        windowId++; windowOpened = System.nanoTime(); onsetMillis = -1;
        diagnosticEvent("window_open="+windowId+",kind="+windowKind+",wait_ms="+windowWaitMillis);
        inputBytes = 0; onsetReason = "none"; voicedMillis = 0; commandMillis = 0; endReason = "waiting";
    }
    private void captureLoop() {
        short[] frame = new short[320];
        short[] bargeAnalysis = new short[320];
        byte[] pcm = new byte[640];
        PcmPrebuffer history = new PcmPrebuffer();
        BargeInCapture bargeCapture = new BargeInCapture();
        AcknowledgementSelector selector = new AcknowledgementSelector(new Random());
        try (AlexaKwsEngine engine = new AlexaKwsEngine(context.getAssets()); CommandVad vad = new CommandVad()) {
            long index = 0;
            int fill = 0;
            boolean waiting = false, busy = false, commandActive = false, following = false;
            boolean bargePending = false, bargeEnded = false;
            CommandWindow window = settings.window(following);
            CommandWindow bargeWindow = null;
            while (!stopping.get()) {
                DiagnosticWindowRequest requestedWindow = (!busy && !waiting && coordinator.ready()) ? takeDiagnosticWindow() : null;
                if (requestedWindow != null) {
                    releaseRecorder(); history.clear(); engine.reset(); vad.reset(); index = 0; fill = 0;
                    following = requestedWindow.followup;
                    status = "diagnostic_prompt";
                    if (following) { startRecorder(); }
                    else { controls.wake(); prompt("ack", requestedWindow.select(selector)); }
                    windowSource = "local_admin_diagnostic";
                    window = settings.window(following); openedWindow(window,following); waiting = true;
                    status = following ? "waiting_followup" : "waiting_command";
                }
                if (coordinator.failure() != null) throw new IOException("native_transport_failed");
                if (busy && coordinator.ready()) {
                    NativeVoiceSession.Outcome outcome = coordinator.outcome();
                    NativeAudioCoordinator.RestartReason restart = coordinator.takeRestart();
                    if (outcome == NativeVoiceSession.Outcome.COMPLETE) completed++;
                    busy = false; commandActive = false;
                    if (restart == NativeAudioCoordinator.RestartReason.DIRECT_SPEECH
                            && outcome == NativeVoiceSession.Outcome.CANCELLED && bargePending
                            && bargeWindow != null && bargeCapture.bytes() > 0) {
                        playbackInput.clear();
                        byte[] buffered = bargeCapture.snapshot();
                        inputBytes = buffered.length;
                        try { coordinator.begin(buffered); } finally { Arrays.fill(buffered, (byte) 0); }
                        commands++; busy = true; commandActive = !bargeEnded;
                        window = bargeWindow; following = false; waiting = false;
                        if (bargeEnded) { coordinator.endInput(); status = "processing"; }
                        else status = "uploading_barge_in";
                        diagnosticEvent("direct_barge_restart,window=" + windowId + ",bytes=" + inputBytes
                                + ",ended=" + bargeEnded);
                        bargePending = false; bargeEnded = false; bargeWindow = null;
                        bargeCapture.clear(); history.clear(); engine.reset(); index = 0; fill = 0;
                    } else if (restart == NativeAudioCoordinator.RestartReason.NEW_WAKE
                            && outcome == NativeVoiceSession.Outcome.CANCELLED) {
                        history.clear(); engine.reset(); vad.reset(); index = 0; fill = 0;
                        bargePending = bargeEnded = false; bargeWindow = null; bargeCapture.clear();
                        playbackInput.clear();
                        releaseRecorder(); status = "acknowledging_interrupt";
                        prompt("ack", selector.next());
                        following = false;
                        window = settings.window(false); openedWindow(window, false);
                        waiting = true; status = "waiting_command";
                        diagnosticEvent("reply_wake_restart,window=" + windowId);
                    } else if (outcome == NativeVoiceSession.Outcome.NO_INPUT) {
                        history.clear(); engine.reset(); vad.reset(); index = 0; fill = 0;
                        bargePending = bargeEnded = false; bargeWindow = null; bargeCapture.clear();
                        emptyResumes++;
                        playbackInput.clear();
                        window.resumeAfterEmpty((System.nanoTime() - windowOpened) / 1_000_000L);
                        waiting = true;
                        endReason = "resumed_after_empty";
                        status = following ? "waiting_followup" : "waiting_command";
                    } else {
                        history.clear(); engine.reset(); vad.reset(); index = 0; fill = 0;
                        bargePending = bargeEnded = false; bargeWindow = null; bargeCapture.clear();
                        waiting = coordinator.shouldContinue();
                        following = waiting;
                        if (waiting) {
                            window = settings.window(true);
                            openedWindow(window, true);
                            status = "waiting_followup";
                        } else {
                            playbackInput.clear();
                            if (outcome == NativeVoiceSession.Outcome.COMPLETE) endingPrompt();
                            status = outcome == NativeVoiceSession.Outcome.FAILED ? "run_failed" : "listening";
                        }
                    }
                }
                if (!wakeEnabled && !busy && !waiting) {
                    releaseRecorder(); history.clear(); engine.reset(); index = 0; fill = 0;
                    status = "wake_word_disabled"; Thread.sleep(100); continue;
                }
                // Keep draining AudioRecord during processing and TTS. Capture never restarts
                // at the reply boundary; only post-drain frames can enter the next window.
                if (!busy && !waiting && !coordinator.ready()) {
                    releaseRecorder(); fill = 0; Thread.sleep(20); continue;
                }
                if (recorder == null) {
                    if (!waiting && !busy) status = "opening_microphone";
                    startRecorder();
                }
                AudioRecord current = recorder;
                if (current == null) continue;
                int count;
                boolean replayed=false;
                if((waiting || commandActive) && playbackInput.active() && playbackInput.poll(frame)) {
                    count = frame.length; fill = 0; replayed=true;
                } else if(promptHandoffCount>0) {
                    count=promptHandoffCount; replayed=true;
                    System.arraycopy(promptHandoff,0,frame,fill,count);
                    Arrays.fill(promptHandoff,(short)0); promptHandoffCount=0;
                } else {
                    long readStarted=System.nanoTime();
                    count = current.read(frame, fill, frame.length - fill);
                    if(count>0 && diagnostic!=null && diagnostic.active()) {
                        short[] raw=Arrays.copyOfRange(frame,fill,fill+count);
                        diagnosticPcm("raw",raw,count,System.nanoTime(),"phase=capture,read_started_ns="+readStarted);
                    }
                }
                if (stopping.get()) break;
                if (count <= 0) throw new IOException("native_capture_read_failed");
                lastRead = System.nanoTime(); fill += count;
                if (fill < frame.length) continue;
                fill = 0; frames++; promptReference.expire(lastRead);
                boolean interruptibleReply = busy && !commandActive && !coordinator.acceptingInput();
                if (interruptibleReply) {
                    history.append(frame);
                    if (!bargePending) {
                        KwsDetection replyDetection = engine.acceptFrame(frame, 0, frame.length, index);
                        index += frame.length;
                        if (replyDetection.detected
                                && coordinator.requestCancel(NativeAudioCoordinator.CancelReason.NEW_WAKE)) {
                            replyWakeInterruptions++; wakes++; controls.wake();
                            playbackInput.clear(); history.clear();
                            bargeWindow = null; bargeCapture.clear();
                            status = "interrupting_reply";
                            diagnosticEvent("reply_wake_detected,score=" + replyDetection.score);
                            continue;
                        }
                    }
                    // The original vendor frame is retained for upload. Echo matching may only
                    // alter this analysis copy, so it cannot manufacture a claimed AEC result.
                    System.arraycopy(frame, 0, bargeAnalysis, 0, frame.length);
                    promptReference.process(bargeAnalysis, lastRead);
                    boolean rawBargeSpeech = vad.speechForQuietR1(bargeAnalysis);
                    boolean qualifiedBargeSpeech = evidence.accept(bargeAnalysis, rawBargeSpeech, false);
                    if (bargeWindow == null) {
                        bargeWindow = settings.window(false);
                        windowSource = "direct_barge_in";
                        openedWindow(bargeWindow, false);
                        diagnosticEvent("direct_barge_monitor_started,window=" + windowId);
                    }
                    CommandWindow.Decision bargeDecision = bargeWindow.acceptQualified(
                            qualifiedBargeSpeech, rawBargeSpeech && evidence.strong());
                    if (!bargePending && bargeDecision == CommandWindow.Decision.START) {
                        byte[] onset = history.snapshot(15);
                        try { bargeCapture.start(onset); } finally { Arrays.fill(onset, (byte) 0); }
                        if (coordinator.requestCancel(NativeAudioCoordinator.CancelReason.DIRECT_SPEECH)) {
                            bargePending = true; directBargeInterruptions++;
                            onsetMillis = bargeWindow.waitingMillis(); onsetReason = bargeWindow.onsetReason();
                            voicedMillis = bargeWindow.voicedMillis(); commandMillis = bargeWindow.commandMillis();
                            inputBytes = bargeCapture.bytes(); endReason = "speech";
                            playbackInput.clear(); history.clear(); status = "interrupting_reply_directly";
                            diagnosticEvent("direct_barge_detected,window=" + windowId + ",onset_ms=" + onsetMillis);
                            continue;
                        }
                        bargeCapture.clear();
                    } else if (bargePending && !bargeEnded) {
                        if (!bargeCapture.append(frame)) {
                            bargeEnded = true; endReason = "barge_handoff_limit";
                            diagnosticEvent("direct_barge_buffer_full,window=" + windowId);
                        } else {
                            inputBytes = bargeCapture.bytes();
                            voicedMillis = bargeWindow.voicedMillis(); commandMillis = bargeWindow.commandMillis();
                            if (bargeDecision == CommandWindow.Decision.END) {
                                bargeEnded = true; endReason = bargeWindow.endReason();
                                diagnosticEvent("direct_barge_input_end,window=" + windowId + ",reason=" + endReason);
                            }
                        }
                    } else if (!bargePending && bargeDecision == CommandWindow.Decision.TIMEOUT) {
                        history.clear(); bargeWindow = settings.window(false);
                        openedWindow(bargeWindow, false);
                        diagnosticEvent("direct_barge_monitor_restarted,window=" + windowId);
                    }
                }
                if (playbackRequested || interruptibleReply) {
                    playbackInput.accept(frame);
                    if (playbackRequested && !bargePending) status = "playing";
                    if (!interruptibleReply) history.clear();
                    continue;
                }
                promptReference.process(frame,lastRead);
                history.append(frame);
                if (!waiting && !busy) status = "listening";
                boolean rawSpeech = vad.speechForQuietR1(frame);
                boolean speech = evidence.accept(frame, rawSpeech, !waiting && !busy);
                rms = evidence.rms(); noiseFloor = evidence.floor();
                if(diagnostic!=null && diagnostic.active()) diagnosticPcm("processed",frame,frame.length,lastRead,
                        "vad="+rawSpeech+",speech="+speech+",strong="+evidence.strong()+",replayed="+replayed
                        +",rms="+rms+",floor="+noiseFloor+",correlation="+promptReference.correlation
                        +",delay_samples="+promptReference.delaySamples);

                if(waiting) traceOnset(rawSpeech, speech, rawSpeech && evidence.strong());
                if (waiting || commandActive) {
                    CommandWindow.Decision decision = window.acceptQualified(speech, rawSpeech && evidence.strong());
                    voicedMillis = window.voicedMillis(); commandMillis = window.commandMillis();
                    if (decision == CommandWindow.Decision.START) {
                        onsetMillis = window.waitingMillis(); onsetReason = window.onsetReason(); endReason = "speech";
                        byte[] onset = history.snapshot(15);
                        inputBytes = onset.length;
                        try { coordinator.begin(onset); } finally { Arrays.fill(onset, (byte) 0); }
                        diagnosticEvent("command_start,window="+windowId+",onset_ms="+onsetMillis);
                        commands++;
                        waiting = false; busy = true; commandActive = true; status = "uploading";
                    } else if (decision == CommandWindow.Decision.TIMEOUT) {
                        noInputs++; endReason = "no_input_timeout";
                        diagnosticEvent("window_timeout="+windowId);
                        releaseRecorder();
                        endingPrompt();
                        following = false; waiting = false; history.clear(); engine.reset(); vad.reset(); index = 0;
                        status = "listening"; // Both window kinds end with exactly one local prompt.
                    } else if (commandActive && decision != CommandWindow.Decision.DONE) {
                        for (int i = 0; i < frame.length; i++) {
                            pcm[i * 2] = (byte) frame[i]; pcm[i * 2 + 1] = (byte) (frame[i] >>> 8);
                        }
                        coordinator.audio(pcm); inputBytes += pcm.length;
                        if (decision == CommandWindow.Decision.END) {
                            endReason = window.endReason();
                            coordinator.endInput(); commandActive = false; status = "processing";
                            history.clear();
                        }
                    }
                    continue;
                }
                KwsDetection detection = engine.acceptFrame(frame, 0, frame.length, index);
                index += frame.length;
                if (coordinator.ready() && detection.detected) {
                    if(diagnostic!=null && diagnostic.armed() && diagnostic.activateOnWake())
                        diagnosticEvent("capture_trigger=alexa,format=PCM_S16LE,rate=16000,channels=1,purpose=post_wake_silence,utc_ms="+System.currentTimeMillis());
                    windowSource = "alexa"; wakes++; controls.wake();
                    releaseRecorder(); history.clear(); status = "acknowledging";
                    requireAudioPermission();
                    prompt("ack", selector.next());
                    following = false;
                    vad.reset(); engine.reset(); index = 0; fill = 0;
                    window = settings.window(following); openedWindow(window,following); waiting = true; status = "waiting_command";
                }
            }
        } catch (Exception | LinkageError e) {
            if (!stopping.get()) { failure = "native_audio_failed"; status = failure; }
        } finally {
            releaseRecorder(); history.clear(); bargeCapture.clear(); playbackInput.clear(); promptReference.clear();
            Arrays.fill(frame, (short) 0); Arrays.fill(bargeAnalysis, (short) 0);
            Arrays.fill(pcm, (byte) 0); Arrays.fill(promptHandoff,(short)0);
        }
    }
    private void startRecorder() throws IOException {
        requireAudioPermission();
        int minimum = AudioRecord.getMinBufferSize(16000, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT);
        if (minimum <= 0) throw new IOException("native_capture_buffer_invalid");
        AudioRecord next = new AudioRecord(AudioSourceSpec.VOICE_COMMUNICATION, 16000,
                AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT, Math.max(6400, minimum));
        if (next.getState() != AudioRecord.STATE_INITIALIZED) { next.release(); throw new IOException("native_capture_unavailable"); }
        lastRead = System.nanoTime(); recorder = next;
        if (stopping.get()) { releaseRecorder(); return; }
        next.startRecording();
        everOpened = true; diagnosticEvent("recorder_started");
    }
    private synchronized void stopRecorder() {
        AudioRecord current = recorder;
        if (current == null || current == stopTarget) return;
        stopTarget = current;
        // Firmware 3448 can block forever in native_stop when another audio owner is active.
        // Never make that Binder call on the protocol owner or main thread.
        recorderStopper = new Thread(() -> {
            try { current.stop(); } catch (IllegalStateException ignored) { }
        }, "native-recorder-stop");
        recorderStopper.setDaemon(true); recorderStopper.start();
    }
    private void releaseRecorder() {
        AudioRecord current = recorder;
        if (current != null) {
            try { current.stop(); } catch (IllegalStateException ignored) { }
            current.release();
            diagnosticEvent("recorder_released");
            recorder = null; // Playback gate opens only after release completes.
        }
    }
}
