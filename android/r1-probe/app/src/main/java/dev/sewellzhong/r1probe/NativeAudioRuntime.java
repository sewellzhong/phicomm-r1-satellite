package dev.sewellzhong.r1probe;

import android.content.Context;
import android.media.AudioFormat;
import android.media.AudioRecord;
import dev.sewellzhong.r1probe.assist.AcknowledgementSelector;
import dev.sewellzhong.r1probe.assist.BargeInCapture;
import dev.sewellzhong.r1probe.assist.CommandWindow;
import dev.sewellzhong.r1probe.assist.DiagnosticWindowRequest;
import dev.sewellzhong.r1probe.assist.PcmPrebuffer;
import dev.sewellzhong.r1probe.assist.PlaybackBargeInGate;
import dev.sewellzhong.r1probe.assist.TtsRuntimeStats;
import dev.sewellzhong.r1probe.esphome.NativeApiConnection;
import dev.sewellzhong.r1probe.esphome.NativeAnnouncementController;
import dev.sewellzhong.r1probe.esphome.NativeAlarmController;
import dev.sewellzhong.r1probe.esphome.NativeAlarmProtocol;
import dev.sewellzhong.r1probe.esphome.NativeAlertAudioProtocol;
import dev.sewellzhong.r1probe.esphome.NativeAudioCoordinator;
import dev.sewellzhong.r1probe.esphome.NativeDndController;
import dev.sewellzhong.r1probe.esphome.NativeDndProtocol;
import dev.sewellzhong.r1probe.esphome.NativeMediaController;
import dev.sewellzhong.r1probe.esphome.NativePcmPlayback;
import dev.sewellzhong.r1probe.esphome.NativeSystemManager;
import dev.sewellzhong.r1probe.esphome.NativeSystemProtocol;
import dev.sewellzhong.r1probe.esphome.NativeTimerController;
import dev.sewellzhong.r1probe.esphome.NativeVoiceSession;
import java.io.IOException;
import java.util.Arrays;
import java.util.Random;
import java.util.concurrent.atomic.AtomicBoolean;

/** Per-connection audio handler owned by NativeSatelliteService, separate from the WS runtime.
 * The service owns authentication, wake locks, connection recovery and stalled-backend protection. */
public final class NativeAudioRuntime implements NativeApiConnection.Handler {
    // r1-sample01 v129 reproduced speaker echo as DIRECT_SPEECH at 10% volume.
    // v133 also proved that using the same candidate for stop-only truncates TTS;
    // PlaybackBargeInGate now requires an AEC-clean, stable speech candidate.
    // Direct speech is still gated by PlaybackBargeInGate below. The flag only
    // enables the guarded state-machine branch; it does not bypass AEC checks.
    private static final boolean DIRECT_BARGE_IN_ENABLED = true;
    // Experimental playback-only path. Normal idle Alexa remains at 229/255;
    // only the vendor-AEC reply model may cancel a reply, after VAD confirms speech.
    private static final boolean REPLY_WAKE_CANCEL_ENABLED = true;
    // Controlled playback-only experiment. The normal idle threshold remains 229.
    // One-round A/B experiment: use the normal Alexa cutoff during playback. This is
    // deliberately not a production conclusion; the previous run only proved a peak
    // of 246, not five consecutive outputs at or above 229.
    private static final int PLAYBACK_REPLY_KWS_CUTOFF = 229;
    private static final boolean AUTOMATIC_FOLLOWUP_ENABLED = true;
    private static final long FOLLOWUP_SETTLE_NANOS = 1_200_000_000L;
    private static final int REPLY_REPLAY_DELAY_FRAMES = 40;
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
    private void recordWake(String source, long sampleIndex, float score) {
        lastWakeSource = source;
        lastWakeSampleIndex = sampleIndex;
        lastWakeMonotonicMs = System.nanoTime() / 1_000_000L;
        lastWakeWallMs = System.currentTimeMillis();
        lastWakeScore = score;
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
    private volatile boolean followupArming;
    private volatile long followupSettleEvents, followupDiscardedFrames;
    private volatile long playbackReferenceSuppressedFrames, playbackTailSuppressedFrames;
    private volatile long replyKwsFrames, replyKwsInferences;
    private volatile int replyKwsPeakRaw;
    private volatile long fixedPcmRuns, fixedPcmCancels;
    private volatile long ttsStreamStartMillis, haRunEndMillis;
    private volatile boolean fixedPcmRun;
    private volatile Thread promptPlayer;
    private final short[] promptHandoff = new short[320];
    private int promptHandoffCount;
    private volatile boolean microphoneWarmAtPromptEnd;
    private volatile String lastPromptKind = "none";
    private volatile long promptDrainedAt;
    private volatile int lastPromptIndex;
    private volatile String lastWakeSource = "none";
    private volatile long lastWakeSampleIndex = -1;
    private volatile long lastWakeMonotonicMs;
    private volatile long lastWakeWallMs;
    private volatile float lastWakeScore;
    private final dev.sewellzhong.r1probe.assist.PromptReference promptReference = new dev.sewellzhong.r1probe.assist.PromptReference();
    private final dev.sewellzhong.r1probe.assist.ContinuousDialogueGuard dialogueGuard =
            new dev.sewellzhong.r1probe.assist.ContinuousDialogueGuard();
    private final TtsRuntimeStats ttsStats = new TtsRuntimeStats();
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
    @Override public void listEntities(NativeVoiceSession.Sender sender) throws IOException {
        controls.list(sender);
        if (alarmProtocol != null) alarmProtocol.list(sender);
        alertAudioProtocol.list(sender);
        if (dndProtocol != null) dndProtocol.list(sender);
        if (systemProtocol != null) systemProtocol.list(sender);
        media.list(sender);
    }

    private final NativePcmPlayback playback;
    private final NativeAnnouncementController announcements;
    private final NativeAlarmProtocol alarmProtocol;
    private final NativeAlertAudioProtocol alertAudioProtocol;
    private final NativeAlarmController alarms;
    private final NativeDndController dnd;
    private final NativeDndProtocol dndProtocol;
    private final NativeSystemProtocol systemProtocol;
    private final NativeMediaController media;
    private volatile boolean wakeEnabled;
    private volatile boolean everOpened;
    private volatile boolean authenticated;
    public boolean authenticated() { return authenticated; }
    public String failureCode() { return failure; }
    private volatile long frames, wakes, replyWakeInterruptions, announcementWakeInterruptions,
            directBargeInterruptions,
            directBargeRejections, commands, transcripts, completed, noInputs;
    private volatile String directBargeBlockReason = "awaiting_aec";
    private volatile long replyContinuousObservedDetections, replyReplayAttempts,
            replyReplayDetections, replyReplayMaxMicros;
    private volatile int replyReplayPeakRaw;
    private volatile long replyRawReplayAttempts, replyRawReplayDetections,
            replyRawReplayMaxMicros;
    private volatile int replyRawReplayPeakRaw;
    private volatile long replyRawContinuousFrames, replyRawContinuousInferences,
            replyRawContinuousDetections, replyRawContinuousMaxMicros;
    private volatile int replyRawContinuousPeakRaw;
    private volatile long vendorAecKwsFrames, vendorAecKwsDetections, vendorAecKwsFailures,
            vendorAecKwsCancelled, vendorAecKwsScoreFramesAt8, vendorAecKwsScoreFramesAt12,
            vendorAecKwsScoreFramesAt16, vendorAecKwsScoreFramesAt32;
    private volatile int vendorAecKwsPeakRaw;
    private volatile int vendorAecKwsOutputPeak;
    private volatile double vendorAecKwsOutputRms;
    private volatile long vendorAecKwsOutputNonzeroFrames;
    private volatile int vendorAecInputPeak, vendorAecReferencePeak;
    private volatile int vendorAecOutputMin = 32767, vendorAecOutputMax = -32768;
    private volatile long vendorAecOutputSamples, vendorAecOutputSaturatedSamples;
    private volatile long vendorAecInputSamples, vendorAecAdapterOutputSamples,
            vendorAecInputSaturatedSamples, vendorAecAdapterOutputSaturatedSamples,
            vendorAecChunks;
    private volatile int vendorAecAdapterInputPeak, vendorAecAdapterOutputPeak;
    private volatile int vendorAecAdapterOutputMin = 32767, vendorAecAdapterOutputMax = -32768;
    private volatile int captureInputPeak;
    private volatile long captureInputFrames, captureInputSamples, captureInputSaturatedSamples;
    private volatile boolean vendorAecKwsAvailable;
    private volatile String vendorAecKwsLastFailure = "none";
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
                .put("commands", commands).put("stt_results", transcripts).put("tts_streams", ttsStats.streams())
                .put("tts_responses", ttsStats.responses())
                .put("tts_playback_completed", ttsStats.playbackCompleted())
                .put("tts_playback_failed", ttsStats.playbackFailed())
                .put("reply_wake_interruptions", replyWakeInterruptions)
                .put("announcement_wake_interruptions", announcementWakeInterruptions)
                .put("last_wake_source", lastWakeSource)
                .put("last_wake_sample_index", lastWakeSampleIndex)
                .put("last_wake_monotonic_ms", lastWakeMonotonicMs)
                .put("last_wake_wall_ms", lastWakeWallMs)
                .put("last_wake_score", lastWakeScore)
                .put("reply_wake_cancel_enabled", REPLY_WAKE_CANCEL_ENABLED)
                .put("reply_continuous_observed_detections", replyContinuousObservedDetections)
                .put("reply_replay_attempts", replyReplayAttempts)
                .put("reply_replay_detections", replyReplayDetections)
                .put("reply_replay_peak_raw", replyReplayPeakRaw)
                .put("reply_replay_max_us", replyReplayMaxMicros)
                .put("reply_raw_replay_attempts", replyRawReplayAttempts)
                .put("reply_raw_replay_detections", replyRawReplayDetections)
                .put("reply_raw_replay_peak_raw", replyRawReplayPeakRaw)
                .put("reply_raw_replay_max_us", replyRawReplayMaxMicros)
                .put("reply_raw_continuous_frames", replyRawContinuousFrames)
                .put("reply_raw_continuous_inferences", replyRawContinuousInferences)
                .put("reply_raw_continuous_detections", replyRawContinuousDetections)
                .put("reply_raw_continuous_peak_raw", replyRawContinuousPeakRaw)
                .put("reply_raw_continuous_max_us", replyRawContinuousMaxMicros)
                .put("vendor_aec_kws_frames", vendorAecKwsFrames)
                .put("vendor_aec_kws_detections", vendorAecKwsDetections)
                .put("vendor_aec_kws_cancelled", vendorAecKwsCancelled)
                .put("vendor_aec_kws_cutoff_raw", PLAYBACK_REPLY_KWS_CUTOFF)
                .put("vendor_aec_kws_score_frames_at_8", vendorAecKwsScoreFramesAt8)
                .put("vendor_aec_kws_score_frames_at_12", vendorAecKwsScoreFramesAt12)
                .put("vendor_aec_kws_score_frames_at_16", vendorAecKwsScoreFramesAt16)
                .put("vendor_aec_kws_score_frames_at_32", vendorAecKwsScoreFramesAt32)
                .put("playback_kws_detections", vendorAecKwsDetections)
                .put("playback_kws_cancelled", vendorAecKwsCancelled)
                .put("vendor_aec_kws_peak_raw", vendorAecKwsPeakRaw)
                .put("vendor_aec_kws_output_peak", vendorAecKwsOutputPeak)
                .put("vendor_aec_kws_output_rms", vendorAecKwsOutputRms)
                .put("vendor_aec_kws_output_nonzero_frames", vendorAecKwsOutputNonzeroFrames)
                .put("vendor_aec_input_peak", vendorAecInputPeak)
                .put("vendor_aec_reference_peak", vendorAecReferencePeak)
                .put("vendor_aec_reference_source", "pre_volume_playback_pcm")
                .put("vendor_aec_output_min", vendorAecOutputSamples == 0 ? 0 : vendorAecOutputMin)
                .put("vendor_aec_output_max", vendorAecOutputSamples == 0 ? 0 : vendorAecOutputMax)
                .put("vendor_aec_output_samples", vendorAecOutputSamples)
                .put("vendor_aec_output_saturated_samples", vendorAecOutputSaturatedSamples)
                .put("vendor_aec_adapter_input_samples", vendorAecInputSamples)
                .put("vendor_aec_adapter_output_samples", vendorAecAdapterOutputSamples)
                .put("vendor_aec_adapter_input_saturated_samples", vendorAecInputSaturatedSamples)
                .put("vendor_aec_adapter_output_saturated_samples", vendorAecAdapterOutputSaturatedSamples)
                .put("vendor_aec_adapter_chunks", vendorAecChunks)
                .put("vendor_aec_adapter_input_peak", vendorAecAdapterInputPeak)
                .put("vendor_aec_adapter_output_peak", vendorAecAdapterOutputPeak)
                .put("vendor_aec_adapter_output_min", vendorAecAdapterOutputSamples == 0 ? 0 : vendorAecAdapterOutputMin)
                .put("vendor_aec_adapter_output_max", vendorAecAdapterOutputSamples == 0 ? 0 : vendorAecAdapterOutputMax)
                .put("capture_input_peak", captureInputPeak)
                .put("capture_input_frames", captureInputFrames)
                .put("capture_input_samples", captureInputSamples)
                .put("capture_input_saturated_samples", captureInputSaturatedSamples)
                .put("vendor_aec_kws_failures", vendorAecKwsFailures)
                .put("vendor_aec_kws_last_failure", vendorAecKwsLastFailure)
                .put("vendor_aec_kws_enabled", vendorAecKwsAvailable)
                .put("vendor_aec_kws_purpose", "playback_cancel_candidate")
                .put("vendor_aec_kws_cancel_authorized", REPLY_WAKE_CANCEL_ENABLED)
                .put("direct_barge_interruptions", directBargeInterruptions)
                .put("direct_barge_in_enabled", DIRECT_BARGE_IN_ENABLED)
                .put("direct_barge_rejections", directBargeRejections)
                .put("direct_barge_block_reason", DIRECT_BARGE_IN_ENABLED
                        ? directBargeBlockReason : "disabled")
                .put("automatic_followup_enabled", AUTOMATIC_FOLLOWUP_ENABLED)
                .put("automatic_followup_block_reason", AUTOMATIC_FOLLOWUP_ENABLED
                        ? "none" : "playback_tail_echo_unverified")
                .put("followup_settle_ms", FOLLOWUP_SETTLE_NANOS / 1_000_000L)
                .put("followup_arming", followupArming)
                .put("followup_settle_events", followupSettleEvents)
                .put("followup_discarded_frames", followupDiscardedFrames)
                .put("followup_onset_voiced_frames", 15)
                .put("followup_onset_strong_frames", 10)
                .put("fixed_pcm_runs", fixedPcmRuns).put("fixed_pcm_cancels", fixedPcmCancels)
                .put("playback_requested_ms", playback.requestedMillis())
                .put("playback_first_write_ms", playback.firstWriteMillis())
                .put("playback_drained_ms", playback.drainedMillis())
                .put("playback_released_ms", playback.releasedMillis())
                .put("playback_buffer_high_water_bytes", playback.highWaterBytes())
                .put("playback_underruns", playback.underruns())
                .put("playback_startup_buffer_bytes", playback.startupBufferedBytes())
                .put("playback_startup_wait_ms", playback.startupWaitMillis())
                .put("playback_prebuffer_target_ms", 200)
                .put("playback_http_error", playback.httpFailure())
                .put("announcement_active", announcements.active())
                .put("announcement_requests", announcements.requests())
                .put("announcement_completed", announcements.completed())
                .put("announcement_failures", announcements.failures())
                .put("announcement_segments_started", announcements.segmentsStarted())
                .put("announcement_segments_completed", announcements.segmentsCompleted())
                .put("announcement_suppressed", announcements.suppressed())
                .put("media_state", media.state().name().toLowerCase(java.util.Locale.ROOT))
                .put("media_requests", media.requests()).put("media_rejected", media.rejected())
                .put("media_failures", media.failures()).put("media_last_failure", media.lastFailure())
                .put("do_not_disturb", dnd == null ? org.json.JSONObject.NULL : dnd.snapshot())
                .put("timers", timers == null ? org.json.JSONObject.NULL : timers.snapshot())
                .put("tts_stream_start_ms", ttsStreamStartMillis)
                .put("ha_run_end_ms", haRunEndMillis)
                .put("prompt_index", lastPromptIndex).put("reference_correlation", promptReference.correlation)
                .put("reference_delay_samples", promptReference.delaySamples).put("reference_before_rms", promptReference.beforeRms)
                .put("reference_after_rms", promptReference.afterRms).put("reference_matched_frames", promptReference.matchedFrames)
                .put("playback_reference_suppressed_frames", playbackReferenceSuppressedFrames)
                .put("playback_tail_suppressed_frames", playbackTailSuppressedFrames)
                .put("reference_held_suppressed_frames", promptReference.heldMatchedFrames)
                .put("reply_kws_frames", replyKwsFrames)
                .put("reply_kws_inferences", replyKwsInferences)
                .put("reply_kws_peak_raw", replyKwsPeakRaw)
                .put("reply_kws_cutoff_raw", AlexaDecision.CUTOFF)
                .put("reference_processed_frames", promptReference.processedFrames).put("reference_max_us", promptReference.maxProcessNanos/1000)
                .put("reference_over_budget_frames", promptReference.overBudgetFrames)
                .put("continuous_round", dialogueGuard.rounds())
                .put("continuous_round_limit", dev.sewellzhong.r1probe.assist.ContinuousDialogueGuard.ROUND_LIMIT)
                .put("continuous_round_limit_stops", dialogueGuard.limitStops())
                .put("last_prompt_kind", lastPromptKind).put("prompt_drained_monotonic_ms", promptDrainedAt / 1_000_000L).put("empty_resumes", emptyResumes).put("ending_prompts", endingPrompts).put("completed", completed).put("no_input_windows", noInputs).put("last_event", event);
    }
    private final AtomicBoolean stopping = new AtomicBoolean();
    private final NativeAudioCoordinator coordinator;
    private final NativeTimerController timers;
    private final TrustedWallClock civilClock;
    private volatile boolean playbackRequested;
    private volatile AudioRecord recorder;
    private volatile long lastRead;
    private volatile String failure;
    private volatile String status = "waiting_subscription";
    private final boolean ownsMedia;
    private Thread capture;
    private volatile Thread recorderStopper;
    private AudioRecord stopTarget;

    public NativeAudioRuntime(Context context) {
        this(context, true, () -> FactoryAudioIsolation.permitsAudio(FactoryAudioIsolation.inspect(context)), null, null, null, null, null, null);
    }
    public NativeAudioRuntime(Context context, boolean listen) {
        this(context, listen, () -> FactoryAudioIsolation.permitsAudio(FactoryAudioIsolation.inspect(context)), null, null, null, null, null, null);
    }
    NativeAudioRuntime(Context context, boolean listen, AudioPermission permission) {
        this(context, listen, permission, null, null, null, null, null, null);
    }
    NativeAudioRuntime(Context context, boolean listen, AudioPermission permission,
            NativeTimerController timers) {
        this(context, listen, permission, timers, null, null, null, null, null);
    }
    NativeAudioRuntime(Context context, boolean listen, AudioPermission permission,
            NativeTimerController timers, NativeAlarmController alarms) {
        this(context, listen, permission, timers, alarms, null, null, null, null);
    }
    NativeAudioRuntime(Context context, boolean listen, AudioPermission permission,
            NativeTimerController timers, NativeAlarmController alarms, NativeDndController dnd) {
        this(context, listen, permission, timers, alarms, dnd, null, null, null);
    }
    NativeAudioRuntime(Context context, boolean listen, AudioPermission permission,
            NativeTimerController timers, NativeAlarmController alarms, NativeDndController dnd,
            NativeSystemManager system) {
        this(context, listen, permission, timers, alarms, dnd, system, null, null);
    }
    NativeAudioRuntime(Context context, boolean listen, AudioPermission permission,
            NativeTimerController timers, NativeAlarmController alarms, NativeDndController dnd,
            NativeSystemManager system, TrustedWallClock civilClock) {
        this(context, listen, permission, timers, alarms, dnd, system, civilClock, null);
    }
    NativeAudioRuntime(Context context, boolean listen, AudioPermission permission,
            NativeTimerController timers, NativeAlarmController alarms, NativeDndController dnd,
            NativeSystemManager system, TrustedWallClock civilClock,
            NativeMediaController sharedMedia) {
        this.context = context.getApplicationContext();
        this.listen = listen;
        this.permission = permission;
        this.timers = timers;
        this.civilClock = civilClock;
        this.alarms = alarms;
        alarmProtocol = alarms == null ? null : new NativeAlarmProtocol(alarms);
        this.dnd = dnd;
        dndProtocol = dnd == null ? null : new NativeDndProtocol(dnd);
        systemProtocol = system == null ? null : new NativeSystemProtocol(system);
        settings = new NativeSettings(context);
        alertAudioProtocol = new NativeAlertAudioProtocol(new NativeAlertAudioStore(context), settings, alarms);
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
        announcements = new NativeAnnouncementController(playback, new NativeAnnouncementController.Policy() {
            @Override public boolean allowed() { return NativeAudioRuntime.this.dnd == null
                    || NativeAudioRuntime.this.dnd.announcementsAllowed(); }
            @Override public void suppressed() {
                if (NativeAudioRuntime.this.dnd != null) NativeAudioRuntime.this.dnd.suppressedAnnouncement();
            }
        });
        coordinator = new NativeAudioCoordinator(playback, () -> System.nanoTime() / 1_000_000L,
                this::diagnosticEvent);
        ownsMedia = sharedMedia == null;
        if (sharedMedia != null) media = sharedMedia;
        else {
            NativeUrlMediaPlayer mediaBackend = new NativeUrlMediaPlayer(this.context);
            media = new NativeMediaController(mediaBackend, new NativeMediaController.Volume() {
                @Override public float level() { return settings.volumePercent() / 100f; }
                @Override public void level(float value) {
                    settings.setting("volume", Math.round(value * 100));
                    new NativeVolume(NativeAudioRuntime.this.context, settings).prepareOutput();
                }
            }, this::mediaCanStart);
        }
    }
    boolean mediaCanStart() { return coordinator.ready() && !announcements.active()
            && (timers == null || !timers.ringing()); }
    @Override public void synchronizedTime(long epochSeconds) {
        if (civilClock != null) civilClock.synchronize(epochSeconds);
    }
    boolean cancelAudio(NativeAudioCoordinator.CancelReason reason) {
        boolean cancelled = coordinator.requestCancel(reason);
        if (cancelled && reason != NativeAudioCoordinator.CancelReason.DIRECT_SPEECH) dialogueGuard.reset();
        return cancelled;
    }
    void timerAlarmStarting() {
        media.interrupt(NativeMediaController.Interruption.ALARM);
        announcements.interrupt();
        if (coordinator.requestCancel(NativeAudioCoordinator.CancelReason.TIMER_ALARM)) dialogueGuard.reset();
        playback.stop();
    }
    boolean localPlaybackTerminated() { return playback.terminated(); }
    public synchronized void fixedPcmStart() throws IOException {
        if (!listen || fixedPcmRun || !"listening".equals(status) || !coordinator.ready())
            throw new IOException("fixed_pcm_requires_idle_listener");
        media.interrupt(NativeMediaController.Interruption.VOICE);
        try { coordinator.begin(new byte[0]); }
        catch (IOException error) {
            media.release(NativeMediaController.Interruption.VOICE);
            throw error;
        }
        ttsStats.beginRun();
        fixedPcmRun = true; fixedPcmRuns++; inputBytes = 0;
        ttsStreamStartMillis = haRunEndMillis = 0;
        status = "injecting_fixed_pcm";
    }
    public synchronized void fixedPcmFrame(byte[] pcm) throws IOException {
        if (!fixedPcmRun || pcm == null || pcm.length != 640)
            throw new IOException("fixed_pcm_frame_invalid");
        coordinator.audio(pcm); inputBytes += pcm.length;
    }
    public synchronized void fixedPcmEnd() throws IOException {
        if (!fixedPcmRun) throw new IOException("fixed_pcm_not_active");
        coordinator.endInput(); status = "processing";
    }
    public synchronized void fixedPcmCancel() throws IOException {
        if (!fixedPcmRun || !coordinator.requestCancel(NativeAudioCoordinator.CancelReason.USER_STOP))
            throw new IOException("fixed_pcm_cancel_rejected");
        fixedPcmCancels++; status = "cancelling_fixed_pcm";
        long deadline = System.nanoTime() + 5_000_000_000L;
        while (!playback.terminated()) {
            if (System.nanoTime() >= deadline) throw new IOException("fixed_pcm_release_timeout");
            try { Thread.sleep(10); }
            catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                throw new IOException("fixed_pcm_release_interrupted", e);
            }
        }
    }
    public String status() { return status; }
    String indicatorStatus() {
        NativeMediaController.State mediaState = media.state();
        if (announcements.active() || mediaState == NativeMediaController.State.PLAYING
                || mediaState == NativeMediaController.State.PREPARING || !playback.terminated())
            return "playing";
        return status;
    }
    public boolean audioOpened() { return everOpened; }
    public boolean terminated() { return (capture == null || !capture.isAlive()) && (promptPlayer == null || !promptPlayer.isAlive()) && playback.terminated() && (recorderStopper == null || !recorderStopper.isAlive()); }
    @Override public boolean wakeEnabled() { return wakeEnabled; }
    @Override public void wakeEnabled(boolean enabled) { settings.wakeEnabled(enabled); wakeEnabled = enabled; }
    @Override public void connected(NativeVoiceSession.Sender sender) {
        this.sender = sender;
        authenticated = true;
        coordinator.connected(sender);
        announcements.connected(sender);
        media.connected(sender);
        status = listen ? "waiting_subscription" : "authenticated_no_microphone";
        if (!listen) return;
        capture = new Thread(this::captureLoop, "native-command-capture");
        capture.setDaemon(true); capture.start();
    }
    @Override public void message(int type, byte[] payload) throws IOException {
        if (type == dev.sewellzhong.r1probe.esphome.proto.MessageIds.SubscribeStatesRequest) {
            media.message(type, payload);
            controls.message(type, payload, sender);
            return;
        }
        if (controls.message(type, payload, sender)) return;
        if (alarmProtocol != null && alarmProtocol.message(type, payload, sender)) return;
        if (alertAudioProtocol.message(type, payload, sender)) return;
        if (dndProtocol != null && dndProtocol.message(type, payload, sender)) return;
        if (systemProtocol != null && systemProtocol.message(type, payload, sender)) return;
        if (timers != null && timers.message(type, payload)) return;
        if (type == dev.sewellzhong.r1probe.esphome.proto.MessageIds.VoiceAssistantAnnounceRequest) {
            media.interrupt(NativeMediaController.Interruption.ANNOUNCEMENT);
            if (announcements.message(type, payload, coordinator.ready()
                    && (timers == null || !timers.ringing()))) {
                if (!announcements.active()) media.release(NativeMediaController.Interruption.ANNOUNCEMENT);
                return;
            }
            media.release(NativeMediaController.Interruption.ANNOUNCEMENT);
        }
        if (media.message(type, payload)) return;
        coordinator.message(type, payload);
        if (type == dev.sewellzhong.r1probe.esphome.proto.MessageIds.VoiceAssistantEventResponse) {
            dev.sewellzhong.r1probe.esphome.proto.EsphomeApi.VoiceAssistantEvent kind =
                    dev.sewellzhong.r1probe.esphome.proto.EsphomeApi.VoiceAssistantEventResponse.parseFrom(payload).getEventType();
            event = kind.name();
            diagnosticEvent("ha_event="+event);
            long eventMillis = System.nanoTime() / 1_000_000L;
            switch (kind) {
                case VOICE_ASSISTANT_STT_END: transcripts++; break;
                case VOICE_ASSISTANT_INTENT_PROGRESS:
                    for (dev.sewellzhong.r1probe.esphome.proto.EsphomeApi.VoiceAssistantEventData data :
                            dev.sewellzhong.r1probe.esphome.proto.EsphomeApi.VoiceAssistantEventResponse
                                    .parseFrom(payload).getDataList()) {
                        if ("tts_start_streaming".equals(data.getName()) && "1".equals(data.getValue())) {
                            ttsStats.response(true); ttsStreamStartMillis = eventMillis;
                        }
                    }
                    break;
                case VOICE_ASSISTANT_TTS_START:
                    ttsStats.response(false); break;
                case VOICE_ASSISTANT_TTS_END:
                    if (!ttsStats.responseSeen()) ttsStats.response(false);
                    break;
                case VOICE_ASSISTANT_TTS_STREAM_START:
                    ttsStats.response(true); ttsStreamStartMillis = eventMillis; break;
                case VOICE_ASSISTANT_RUN_END: haRunEndMillis = eventMillis; break;
                default: break;
            }
        }
    }
    @Override public void tick() throws IOException {
        if (sender != null) controls.tick(sender);
        if (timers != null) timers.tick();
        if (alarms != null) alarms.tick();
        if ((timers == null || !timers.ringing()) && (alarms == null || !alarms.ringing()))
            media.release(NativeMediaController.Interruption.ALARM);
        if (dnd != null && dnd.active() && announcements.active()) announcements.interrupt();
        if (failure != null) throw new IOException(failure);
        long now = System.nanoTime();
        if (listen && now - lastIsolationCheck > 1_000_000_000L) {
            lastIsolationCheck = now;
            requireAudioPermission();
        }
        if (recorder != null && System.nanoTime() - lastRead > 10_000_000_000L) {
            failure = "native_capture_timeout"; stopRecorder(); throw new IOException(failure);
        }
        announcements.tick();
        if (!announcements.active()) media.release(NativeMediaController.Interruption.ANNOUNCEMENT);
        media.tick();
        // Recompute voice readiness only after an announcement advances or finishes, so a
        // preannounce -> media handoff never publishes a transient idle window to capture.
        coordinator.tick();
    }
    @Override public void closed() {
        if (!stopping.compareAndSet(false, true)) return;
        dialogueGuard.reset();
        if(diagnostic!=null) diagnostic.stop("connection_closed");
        stopRecorder(); announcements.closed(); coordinator.closed();
        if (ownsMedia) media.closed(); else media.disconnected();
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
    private KwsDetection replayReplyWake(AlexaKwsEngine engine, PcmPrebuffer analysisHistory,
            short[] scratch) throws Exception {
        byte[] recent=analysisHistory.snapshot(100);
        long sample=0;
        KwsDetection found=KwsDetection.NONE;
        try {
            engine.reset(); Arrays.fill(scratch,(short)0);
            int retainedFrames=recent.length/640;
            for(int n=retainedFrames;n<100;n++) {
                KwsDetection detection=engine.acceptFrame(scratch,0,320,sample);
                if(detection.detected)found=detection;sample+=320;
            }
            for(int offset=0;offset<recent.length;offset+=640) {
                for(int i=0;i<320;i++)scratch[i]=(short)((recent[offset+i*2]&255)|(recent[offset+i*2+1]<<8));
                KwsDetection detection=engine.acceptFrame(scratch,0,320,sample);
                if(detection.detected)found=detection;sample+=320;
            }
            return found;
        } finally {
            Arrays.fill(recent,(byte)0);Arrays.fill(scratch,(short)0);
        }
    }
    private void updateVendorAecAdapterMetrics(VendorAecLiveProcessor processor) {
        vendorAecInputSamples = processor.inputSamples();
        vendorAecAdapterOutputSamples = processor.outputSamples();
        vendorAecInputSaturatedSamples = processor.inputSaturatedSamples();
        vendorAecAdapterOutputSaturatedSamples = processor.outputSaturatedSamples();
        vendorAecChunks = processor.chunks();
        vendorAecAdapterInputPeak = processor.inputPeak();
        vendorAecAdapterOutputPeak = processor.outputPeak();
        vendorAecAdapterOutputMin = processor.outputMinimum();
        vendorAecAdapterOutputMax = processor.outputMaximum();
    }
    private void captureLoop() {
        short[] frame = new short[320];
        short[] bargeAnalysis = new short[320];
        short[] vendorAecReference = new short[320];
        short[] vendorAecAnalysis = new short[320];
        byte[] pcm = new byte[640];
        PcmPrebuffer history = new PcmPrebuffer();
        PcmPrebuffer replyAnalysisHistory = new PcmPrebuffer();
        short[] replayScratch = new short[320];
        BargeInCapture bargeCapture = new BargeInCapture();
        AcknowledgementSelector selector = new AcknowledgementSelector(new Random());
                try (AlexaKwsEngine engine = new AlexaKwsEngine(context.getAssets());
                AlexaKwsEngine rawReplyEngine = new AlexaKwsEngine(context.getAssets());
                AlexaKwsEngine vendorAecReplyEngine = new AlexaKwsEngine(context.getAssets(),
                        PLAYBACK_REPLY_KWS_CUTOFF);
                VendorAecLiveProcessor vendorAec = VendorAecLiveProcessor.tryCreate();
                CommandVad vad = new CommandVad()) {
            long index = 0;
            long rawReplyIndex = 0;
            long vendorAecReplyIndex = 0;
            int fill = 0;
            boolean waiting = false, busy = false, commandActive = false, following = false;
            boolean rawReplyActive = false;
            boolean vendorAecReplyActive = false;
            boolean vendorAecHealthy = vendorAec != null;
            boolean vendorAecReferenceActive = false;
            vendorAecKwsAvailable = vendorAecHealthy;
            long followupNotBefore = 0;
            int replyReplayDelayFrames = -1;
            boolean bargePending = false, bargeEnded = false;
            PlaybackBargeInGate directBargeGate = new PlaybackBargeInGate();
            CommandWindow window = settings.window(following);
            CommandWindow bargeWindow = null;
            while (!stopping.get()) {
                if (fixedPcmRun && coordinator.ready()) {
                    NativeVoiceSession.Outcome fixedOutcome = coordinator.outcome();
                    if (fixedOutcome == NativeVoiceSession.Outcome.COMPLETE) completed++;
                    if (fixedOutcome == NativeVoiceSession.Outcome.COMPLETE)
                        ttsStats.finish(true);
                    else if (fixedOutcome == NativeVoiceSession.Outcome.FAILED)
                        ttsStats.finish(false);
                    fixedPcmRun = false;
                    media.release(NativeMediaController.Interruption.VOICE);
                    status = fixedOutcome == NativeVoiceSession.Outcome.FAILED
                            ? "run_failed" : "listening";
                }
                DiagnosticWindowRequest requestedWindow = (!busy && !waiting && coordinator.ready()) ? takeDiagnosticWindow() : null;
                if (requestedWindow != null) {
                    media.interrupt(NativeMediaController.Interruption.VOICE);
                    releaseRecorder(); history.clear(); engine.reset(); vad.reset(); index = 0; fill = 0;
                    following = requestedWindow.followup;
                    if (!following) dialogueGuard.reset();
                    status = "diagnostic_prompt";
                    if (following) { startRecorder(); }
                    else { controls.wake(); prompt("ack", requestedWindow.select(selector)); }
                    windowSource = "local_admin_diagnostic";
                    window = settings.window(following); openedWindow(window,following); waiting = true;
                    status = following ? "waiting_followup" : "waiting_command";
                }
                if (coordinator.failure() != null) {
                    ttsStats.finish(false);
                    throw new IOException("native_transport_failed");
                }
                if (busy && coordinator.ready()) {
                    NativeVoiceSession.Outcome outcome = coordinator.outcome();
                    NativeAudioCoordinator.RestartReason restart = coordinator.takeRestart();
                    if (outcome == NativeVoiceSession.Outcome.COMPLETE) completed++;
                    if (outcome == NativeVoiceSession.Outcome.COMPLETE)
                        ttsStats.finish(true);
                    else if (outcome == NativeVoiceSession.Outcome.FAILED)
                        ttsStats.finish(false);
                    busy = false; commandActive = false;
                    if (restart == NativeAudioCoordinator.RestartReason.DIRECT_SPEECH
                            && outcome == NativeVoiceSession.Outcome.CANCELLED && bargePending
                            && bargeWindow != null && bargeCapture.bytes() > 0) {
                        playbackInput.clear();
                        byte[] buffered = bargeCapture.snapshot();
                        inputBytes = buffered.length;
                        ttsStats.beginRun();
                        try { coordinator.begin(buffered); } finally { Arrays.fill(buffered, (byte) 0); }
                        dialogueGuard.commandStarted();
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
                        dialogueGuard.reset();
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
                        boolean continuationRequested = coordinator.shouldContinue();
                        waiting = continuationRequested && AUTOMATIC_FOLLOWUP_ENABLED
                                && dialogueGuard.mayStartAnother();
                        following = waiting;
                        if (waiting) {
                            followupArming = true; followupSettleEvents++;
                            followupNotBefore = System.nanoTime() + FOLLOWUP_SETTLE_NANOS;
                            status = "settling_followup";
                        } else {
                            if (continuationRequested && !AUTOMATIC_FOLLOWUP_ENABLED) {
                                dialogueGuard.reset();
                                diagnosticEvent("automatic_followup_blocked=playback_tail_echo_unverified");
                            } else if (continuationRequested) {
                                dialogueGuard.stoppedAtLimit();
                                diagnosticEvent("continuous_round_limit=" + dialogueGuard.rounds());
                            } else if (outcome != NativeVoiceSession.Outcome.COMPLETE) {
                                dialogueGuard.reset();
                            }
                            playbackInput.clear();
                            if (outcome == NativeVoiceSession.Outcome.COMPLETE) endingPrompt();
                            media.release(NativeMediaController.Interruption.VOICE);
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
                if (!replayed) {
                    int framePeak = 0;
                    long saturated = 0;
                    for (short sample : frame) {
                        int absolute = Math.abs((int) sample);
                        framePeak = Math.max(framePeak, absolute);
                        if (sample == Short.MIN_VALUE || sample == Short.MAX_VALUE) saturated++;
                    }
                    captureInputPeak = Math.max(captureInputPeak, framePeak);
                    captureInputFrames++;
                    captureInputSamples += frame.length;
                    captureInputSaturatedSamples += saturated;
                }
                fill = 0; frames++; promptReference.expire(lastRead);
                boolean interruptibleReply = busy && !commandActive && !coordinator.acceptingInput();
                // Announcements and TTS share the playback/reference path. Previously an
                // announcement bypassed AEC/KWS because it has no active Assist run.
                boolean playbackWakeMonitor = playbackRequested || interruptibleReply;
                if(!playbackWakeMonitor) {
                    directBargeGate.reset();
                    directBargeBlockReason = directBargeGate.blockReason();
                    replyAnalysisHistory.clear();
                    replyReplayDelayFrames = -1;
                    if (rawReplyActive) {
                        rawReplyEngine.reset();
                        rawReplyIndex = 0;
                        rawReplyActive = false;
                    }
                    if (vendorAecReplyActive || vendorAecReferenceActive) {
                        vendorAec.reset();
                        vendorAecReplyEngine.reset();
                        vendorAecReplyActive = false;
                        vendorAecReplyIndex = 0;
                        vendorAecReferenceActive = false;
                    }
                }
                if (playbackWakeMonitor) {
                    history.append(frame);
                    if (!rawReplyActive) {
                        rawReplyEngine.reset();
                        rawReplyIndex = 0;
                        rawReplyActive = true;
                    }
                    long rawStarted=System.nanoTime();
                    long rawInferencesBefore=rawReplyEngine.inferenceCount();
                    KwsDetection rawContinuousDetection=rawReplyEngine.acceptFrame(
                            frame,0,frame.length,rawReplyIndex);
                    replyRawContinuousMaxMicros=Math.max(replyRawContinuousMaxMicros,
                            (System.nanoTime()-rawStarted)/1000);
                    rawReplyIndex+=frame.length;
                    replyRawContinuousFrames++;
                    long rawNewInferences=rawReplyEngine.inferenceCount()-rawInferencesBefore;
                    if(rawNewInferences>0) {
                        replyRawContinuousInferences+=rawNewInferences;
                        replyRawContinuousPeakRaw=Math.max(replyRawContinuousPeakRaw,
                                rawReplyEngine.lastRawScore());
                    }
                    if(rawContinuousDetection.detected) {
                        replyRawContinuousDetections++;
                        recordWake("reply_raw_continuous", rawReplyIndex,
                                rawContinuousDetection.score);
                        diagnosticEvent("reply_wake_observed,mode=raw_continuous,score="
                                +rawContinuousDetection.score);
                    }
                    // Both reply-wake KWS and direct-speech VAD must inspect the same
                    // echo-reduced analysis copy. The vendor PCM retained above remains
                    // byte-for-byte unchanged for any later upload.
                    System.arraycopy(frame, 0, bargeAnalysis, 0, frame.length);
                    promptReference.process(bargeAnalysis, lastRead);
                    replyAnalysisHistory.append(bargeAnalysis);
                    if (promptReference.lastFrameMatched()) {
                        playbackReferenceSuppressedFrames++;
                        if (!playbackRequested) playbackTailSuppressedFrames++;
                    }
                    boolean vendorReferenceReady = false;
                    boolean vendorAecDetection = false;
                    float vendorAecDetectionScore = 0.0f;
                    boolean vendorAecOutputReady = false;
                    boolean vendorAecOutputSaturated = false;
                    if (vendorAec != null && vendorAecHealthy) {
                        vendorReferenceReady = vendorAecReferenceActive
                                ? promptReference.copyNextContinuousVendorReference(vendorAecReference)
                                : promptReference.lastFrameMatched()
                                && promptReference.beginContinuousVendorReference(vendorAecReference);
                        if (!vendorReferenceReady && vendorAecReferenceActive) {
                            vendorAec.reset();
                            vendorAecReplyEngine.reset();
                            vendorAecReplyActive = false;
                            vendorAecReplyIndex = 0;
                            vendorAecReferenceActive = false;
                        }
                        vendorAecReferenceActive = vendorReferenceReady;
                    }
                    if (vendorReferenceReady) {
                        try {
                            for (short sample : frame) {
                                vendorAecInputPeak = Math.max(vendorAecInputPeak,
                                        Math.abs((int) sample));
                            }
                            for (short sample : vendorAecReference) {
                                vendorAecReferencePeak = Math.max(vendorAecReferencePeak,
                                        Math.abs((int) sample));
                            }
                            boolean aecOutputReady = vendorAec.process(frame, vendorAecReference,
                                    vendorAecAnalysis);
                            updateVendorAecAdapterMetrics(vendorAec);
                            if (aecOutputReady) {
                                vendorAecOutputReady = true;
                                long outputEnergy = 0;
                                int outputPeak = 0;
                                for (short sample : vendorAecAnalysis) {
                                    int absolute = Math.abs((int) sample);
                                    outputPeak = Math.max(outputPeak, absolute);
                                    vendorAecOutputMin = Math.min(vendorAecOutputMin, sample);
                                    vendorAecOutputMax = Math.max(vendorAecOutputMax, sample);
                                    if (sample == Short.MIN_VALUE || sample == Short.MAX_VALUE) {
                                        vendorAecOutputSaturatedSamples++;
                                        vendorAecOutputSaturated = true;
                                    }
                                    outputEnergy += (long) sample * sample;
                                }
                                vendorAecOutputSamples += vendorAecAnalysis.length;
                                vendorAecKwsOutputPeak = Math.max(vendorAecKwsOutputPeak,
                                        outputPeak);
                                vendorAecKwsOutputRms = Math.sqrt(outputEnergy
                                        / (double) vendorAecAnalysis.length);
                                if (outputPeak > 0) vendorAecKwsOutputNonzeroFrames++;
                                if (!vendorAecReplyActive) {
                                    vendorAecReplyEngine.reset();
                                    vendorAecReplyIndex = 0;
                                    vendorAecReplyActive = true;
                                }
                                long vendorInferencesBefore = vendorAecReplyEngine.inferenceCount();
                                KwsDetection vendorDetection = vendorAecReplyEngine.acceptFrame(
                                        vendorAecAnalysis, 0, vendorAecAnalysis.length,
                                        vendorAecReplyIndex);
                                vendorAecReplyIndex += vendorAecAnalysis.length;
                                vendorAecKwsFrames++;
                                int vendorRawScore = vendorAecReplyEngine.lastRawScore();
                                vendorAecKwsPeakRaw = Math.max(vendorAecKwsPeakRaw, vendorRawScore);
                                if (vendorAecReplyEngine.inferenceCount() > vendorInferencesBefore) {
                                    if (vendorRawScore >= 8) vendorAecKwsScoreFramesAt8++;
                                    if (vendorRawScore >= 12) vendorAecKwsScoreFramesAt12++;
                                    if (vendorRawScore >= 16) vendorAecKwsScoreFramesAt16++;
                                    if (vendorRawScore >= 32) vendorAecKwsScoreFramesAt32++;
                                }
                                if (vendorDetection.detected) {
                                    vendorAecKwsDetections++;
                                    vendorAecDetection = true;
                                    vendorAecDetectionScore = vendorDetection.score;
                                    recordWake("reply_vendor_aec", vendorAecReplyIndex,
                                            vendorDetection.score);
                                    diagnosticEvent("reply_wake_observed,mode=vendor_aec,score="
                                            +vendorDetection.score);
                                }
                            }
                        } catch (RuntimeException error) {
                            vendorAecKwsFailures++;
                            vendorAecHealthy = false;
                            vendorAecKwsAvailable = false;
                            vendorAecKwsLastFailure = error.getMessage() == null
                                    ? error.getClass().getSimpleName() : error.getMessage();
                            diagnosticEvent("vendor_aec_kws_failed,reason=" + error.getMessage());
                        }
                    }
                    if (replyReplayDelayFrames > 0) replyReplayDelayFrames--;
                    if (replyReplayDelayFrames == 0) {
                        replyReplayDelayFrames = -1;
                        replyReplayAttempts++;
                        long replayStarted=System.nanoTime();
                        KwsDetection replayDetection=replayReplyWake(
                                engine,replyAnalysisHistory,replayScratch);
                        replyReplayMaxMicros=Math.max(replyReplayMaxMicros,
                                (System.nanoTime()-replayStarted)/1000);
                        replyReplayPeakRaw=Math.max(
                                replyReplayPeakRaw,engine.maximumRawScore());
                        int processedPeak=engine.maximumRawScore();
                        replyRawReplayAttempts++;
                        long rawReplayStarted=System.nanoTime();
                        KwsDetection rawReplayDetection=replayReplyWake(
                                engine,history,replayScratch);
                        replyRawReplayMaxMicros=Math.max(replyRawReplayMaxMicros,
                                (System.nanoTime()-rawReplayStarted)/1000);
                        replyRawReplayPeakRaw=Math.max(
                                replyRawReplayPeakRaw,engine.maximumRawScore());
                        index=32000;
                        if(replayDetection.detected)replyReplayDetections++;
                        if(rawReplayDetection.detected)replyRawReplayDetections++;
                        diagnosticEvent("reply_wake_replay,delay_frames="
                                +REPLY_REPLAY_DELAY_FRAMES
                                +",replay_detected="+replayDetection.detected
                                +",replay_score="+replayDetection.score
                                +",replay_peak_raw="+processedPeak
                                +",raw_replay_detected="+rawReplayDetection.detected
                                +",raw_replay_score="+rawReplayDetection.score
                                +",raw_replay_peak="+engine.maximumRawScore());
                    }
                    if (!bargePending) {
                        long inferencesBefore = engine.inferenceCount();
                        KwsDetection replyDetection = engine.acceptFrame(
                                bargeAnalysis, 0, bargeAnalysis.length, index);
                        index += frame.length;
                        replyKwsFrames++;
                        long newInferences = engine.inferenceCount() - inferencesBefore;
                        if (newInferences > 0) {
                            replyKwsInferences += newInferences;
                            replyKwsPeakRaw = Math.max(replyKwsPeakRaw, engine.lastRawScore());
                        }
                        if (replyDetection.detected) {
                            replyContinuousObservedDetections++;
                            recordWake("reply_continuous_observed", index, replyDetection.score);
                            diagnosticEvent("reply_wake_observed,mode=continuous,score=" + replyDetection.score);
                        }
                    }
                    boolean rawBargeSpeech = vad.speechForQuietR1(bargeAnalysis);
                    boolean qualifiedBargeSpeech = evidence.accept(bargeAnalysis, rawBargeSpeech, false);
                    PlaybackBargeInGate.Decision directBargeGateDecision = directBargeGate.observe(
                            vendorAecOutputReady, promptReference.lastFrameMatched(),
                            qualifiedBargeSpeech, evidence.strong(), vendorAecOutputSaturated);
                    directBargeBlockReason = directBargeGate.blockReason();
                    if (bargeWindow == null) {
                        bargeWindow = settings.window(false);
                        windowSource = "direct_barge_in";
                        openedWindow(bargeWindow, false);
                        diagnosticEvent("direct_barge_monitor_started,window=" + windowId);
                    }
                    CommandWindow.Decision bargeDecision = bargeWindow.acceptQualified(
                            qualifiedBargeSpeech, rawBargeSpeech && evidence.strong());
                    if (vendorAecDetection && REPLY_WAKE_CANCEL_ENABLED && qualifiedBargeSpeech) {
                        if (coordinator.requestCancel(NativeAudioCoordinator.CancelReason.NEW_WAKE)) {
                            vendorAecKwsCancelled++;
                            replyWakeInterruptions++; wakes++; controls.wake();
                            recordWake("reply_vendor_aec_cancel", index, vendorAecDetectionScore);
                            playbackInput.clear(); history.clear();
                            bargeWindow = null; bargeCapture.clear();
                            status = "interrupting_reply";
                            diagnosticEvent("reply_vendor_aec_cancel,score=" + vendorAecDetectionScore);
                            continue;
                        }
                        // HA announcements have no active voice run to cancel. Stop the
                        // local announcement and enter the normal Alexa acknowledgement path.
                        if (playbackRequested && announcements.active()) {
                            announcements.interrupt();
                            media.release(NativeMediaController.Interruption.ANNOUNCEMENT);
                            playbackInput.clear(); history.clear();
                            bargeWindow = null; bargeCapture.clear();
                            announcementWakeInterruptions++; wakes++; controls.wake();
                            recordWake("announcement_vendor_aec_cancel", index,
                                    vendorAecDetectionScore);
                            releaseRecorder(); status = "acknowledging";
                            requireAudioPermission();
                            prompt("ack", selector.next());
                            following = false; vad.reset(); engine.reset(); index = 0; fill = 0;
                            window = settings.window(following); openedWindow(window, following);
                            waiting = true; status = "waiting_command";
                            diagnosticEvent("announcement_vendor_aec_cancel,score="
                                    + vendorAecDetectionScore);
                            continue;
                        }
                    }
                    if (!bargePending && bargeDecision == CommandWindow.Decision.START
                            && (!DIRECT_BARGE_IN_ENABLED
                            || directBargeGateDecision != PlaybackBargeInGate.Decision.ACCEPT)) {
                        directBargeRejections++;
                        replyReplayDelayFrames=REPLY_REPLAY_DELAY_FRAMES;
                        diagnosticEvent("direct_barge_rejected,reason=" + directBargeBlockReason
                                +",replay_after_frames="+REPLY_REPLAY_DELAY_FRAMES);
                    } else if (!bargePending && bargeDecision == CommandWindow.Decision.START
                            && dialogueGuard.mayStartAnother()) {
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
                if (waiting && followupArming) {
                    history.clear(); vad.reset(); followupDiscardedFrames++;
                    if (lastRead < followupNotBefore) continue;
                    followupArming = false; promptReference.clear(); engine.reset(); index = 0;
                    window = settings.window(true); openedWindow(window, true);
                    status = "waiting_followup";
                    continue;
                }
                // Playback-reference suppression is detection-only. Preserve the vendor frame
                // byte-for-byte in history and Assist uploads under the vendor-native policy.
                System.arraycopy(frame, 0, bargeAnalysis, 0, frame.length);
                promptReference.process(bargeAnalysis,lastRead);
                if (promptReference.lastFrameMatched()) {
                    playbackReferenceSuppressedFrames++;
                    if (!playbackRequested) playbackTailSuppressedFrames++;
                }
                history.append(frame);
                if (!waiting && !busy) status = "listening";
                boolean rawSpeech = vad.speechForQuietR1(bargeAnalysis);
                boolean speech = evidence.accept(bargeAnalysis, rawSpeech, !waiting && !busy);
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
                        media.interrupt(NativeMediaController.Interruption.VOICE);
                        onsetMillis = window.waitingMillis(); onsetReason = window.onsetReason(); endReason = "speech";
                        byte[] onset = history.snapshot(15);
                        inputBytes = onset.length;
                        ttsStats.beginRun();
                        try { coordinator.begin(onset); } finally { Arrays.fill(onset, (byte) 0); }
                        dialogueGuard.commandStarted();
                        diagnosticEvent("command_start,window="+windowId+",onset_ms="+onsetMillis);
                        commands++;
                        waiting = false; busy = true; commandActive = true; status = "uploading";
                    } else if (decision == CommandWindow.Decision.TIMEOUT) {
                        noInputs++; endReason = "no_input_timeout";
                        diagnosticEvent("window_timeout="+windowId);
                        releaseRecorder();
                        endingPrompt();
                        media.release(NativeMediaController.Interruption.VOICE);
                        following = false; waiting = false; history.clear(); engine.reset(); vad.reset(); index = 0;
                        dialogueGuard.reset();
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
                    recordWake("normal_listening", index, detection.score);
                    if(diagnostic!=null && diagnostic.armed() && diagnostic.activateOnWake())
                        diagnosticEvent("capture_trigger=alexa,format=PCM_S16LE,rate=16000,channels=1,purpose=post_wake_silence,utc_ms="+System.currentTimeMillis());
                    windowSource = "alexa"; wakes++; controls.wake();
                    dialogueGuard.reset();
                    media.interrupt(NativeMediaController.Interruption.VOICE);
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
            releaseRecorder(); history.clear(); replyAnalysisHistory.clear(); bargeCapture.clear(); playbackInput.clear(); promptReference.clear();
            Arrays.fill(frame, (short) 0); Arrays.fill(bargeAnalysis, (short) 0);
            Arrays.fill(vendorAecReference, (short) 0); Arrays.fill(vendorAecAnalysis, (short) 0);
            Arrays.fill(replayScratch,(short)0);Arrays.fill(pcm, (byte) 0); Arrays.fill(promptHandoff,(short)0);
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
