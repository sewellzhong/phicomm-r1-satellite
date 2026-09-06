package dev.sewellzhong.r1probe.esphome;

import com.google.protobuf.ByteString;
import com.google.protobuf.MessageLite;
import dev.sewellzhong.r1probe.esphome.proto.EsphomeApi;
import dev.sewellzhong.r1probe.esphome.proto.MessageIds;
import java.io.IOException;

/** Single connection/owner thread. Transport only: callers provide post-ack, VAD-gated PCM.
 * No microphone, playback, transcript retention, or production capability advertisement. */
public final class NativeVoiceSession {
    // aioesphomeapi v45.6.1 model.py uses bit 2; pinned api.proto declares bit 0.
    // Accept both subscription encodings; message IDs still come solely from generated schema.
    private static final int API_AUDIO_SUBSCRIPTION_MASK = (1 << 2)
            | EsphomeApi.VoiceAssistantSubscribeFlag.VOICE_ASSISTANT_SUBSCRIBE_API_AUDIO_VALUE;
    public enum State { UNSUBSCRIBED, IDLE, STARTING, STREAMING, PROCESSING, PLAYING, CANCELLING, CLOSED }
    public enum Outcome { NONE, COMPLETE, CANCELLED, NO_INPUT, FAILED }
    public interface Playback {
        void start() throws IOException;
        void audio(byte[] data) throws IOException;
        void end();
        boolean complete();
        String failure();
        void stop();
    }
    public interface Sender { void send(int type, MessageLite message) throws IOException; }
    public interface Clock { long millis(); }
    private final Playback playback;
    private boolean ttsExpected, streamStarted, streamEnded, runEnded, playbackReported;
    private long replyDeadline;
    private String conversationId;
    private long conversationExpires;
    private boolean continueConversation;
    public boolean shouldContinue() {
        return state == State.IDLE && outcome == Outcome.COMPLETE && (continueConversation || playbackReported);
    }
    public String conversationId() { return conversationId; }
    private final Sender sender;
    private final Clock clock;
    private State state = State.UNSUBSCRIBED;
    private Outcome outcome = Outcome.NONE;
    private long deadline;
    private int frames;

    public NativeVoiceSession(Sender sender, Clock clock) {
        this(sender, clock, null);
    }
    public NativeVoiceSession(Sender sender, Clock clock, Playback playback) {
        this.playback = playback;
        this.sender = sender;
        this.clock = clock;
    }
    public State state() { return state; }
    public Outcome outcome() { return outcome; }

    public boolean handle(int type, byte[] payload) throws IOException {
        if (state == State.CLOSED) throw new IOException("voice_connection_closed");
        tick();
        if (type == MessageIds.SubscribeVoiceAssistantRequest) {
            EsphomeApi.SubscribeVoiceAssistantRequest request = EsphomeApi.SubscribeVoiceAssistantRequest.parseFrom(payload);
            boolean supported = request.getSubscribe() && (request.getFlags() & API_AUDIO_SUBSCRIPTION_MASK) != 0;
            if (!supported) {
                if (active()) abortConnection("voice_unsubscribed_during_run");
                state = State.UNSUBSCRIBED;
            } else if (state == State.UNSUBSCRIBED) state = State.IDLE;
            return true;
        }
        if (type == MessageIds.VoiceAssistantResponse) {
            EsphomeApi.VoiceAssistantResponse response = EsphomeApi.VoiceAssistantResponse.parseFrom(payload);
            if (state != State.STARTING) return true;
            if (response.getError()) { outcome = Outcome.FAILED; state = State.IDLE; return true; }
            if (response.getPort() != 0) abortConnection("voice_udp_not_supported");
            state = State.STREAMING;
            deadline = clock.millis() + 130000;
            return true;
        }
        if (type == MessageIds.VoiceAssistantAudio) {
            EsphomeApi.VoiceAssistantAudio audio = EsphomeApi.VoiceAssistantAudio.parseFrom(payload);
            if (state == State.CANCELLING) return true;
            if (!streamStarted || streamEnded || state != State.PLAYING || playback == null)
                abortConnection("unexpected_tts_audio");
            if (audio.getEnd() || !audio.getData2().isEmpty()) abortConnection("unsupported_tts_audio_shape");
            try { playback.audio(audio.getData().toByteArray()); }
            catch (IOException e) { abortConnection("tts_buffer_or_format_failed"); }
            return true;
        }
        if (type == MessageIds.VoiceAssistantEventResponse) {
            EsphomeApi.VoiceAssistantEventResponse response = EsphomeApi.VoiceAssistantEventResponse.parseFrom(payload);
            EsphomeApi.VoiceAssistantEvent event = response.getEventType();
            if (!active()) return true;
            switch (event) {
                case VOICE_ASSISTANT_INTENT_END:
                    if (state == State.CANCELLING) break;
                    for (EsphomeApi.VoiceAssistantEventData data : response.getDataList()) {
                        if ("conversation_id".equals(data.getName())) {
                            if (data.getValue().length() > 256) abortConnection("conversation_id_too_long");
                            conversationId = data.getValue().isEmpty() ? null : data.getValue();
                        } else if ("continue_conversation".equals(data.getName())) {
                            if (!"0".equals(data.getValue()) && !"1".equals(data.getValue()))
                                abortConnection("invalid_continuation_flag");
                            continueConversation = "1".equals(data.getValue());
                        }
                    }
                    break;
                case VOICE_ASSISTANT_RUN_END:
                    runEnded = true;
                    if (!ttsExpected || state == State.CANCELLING) finishRun();
                    else completePlayback();
                    break;
                case VOICE_ASSISTANT_TTS_START:
                case VOICE_ASSISTANT_TTS_END:
                    if (state == State.CANCELLING) break;
                    expectTts();
                    break;
                case VOICE_ASSISTANT_TTS_STREAM_START:
                    if (state == State.CANCELLING) break;
                    expectTts();
                    if (streamStarted || playback == null) abortConnection("tts_stream_unsupported_or_duplicate");
                    streamStarted = true;
                    state = State.PLAYING;
                    try { playback.start(); }
                    catch (IOException e) { abortConnection("tts_start_failed"); }
                    break;
                case VOICE_ASSISTANT_TTS_STREAM_END:
                    if (state == State.CANCELLING) break;
                    if (!streamStarted) abortConnection("tts_end_before_start");
                    if (!streamEnded) { streamEnded = true; playback.end(); }
                    completePlayback();
                    break;
                case VOICE_ASSISTANT_ERROR:
                    // Retain only a bounded outcome, never HA messages or recognized text.
                    boolean noInput = false;
                    int codeFields = 0;
                    for (EsphomeApi.VoiceAssistantEventData data : response.getDataList()) {
                        if ("code".equals(data.getName())) {
                            codeFields++;
                            noInput = "stt-no-text-recognized".equals(data.getValue());
                        }
                    }
                    if (codeFields != 1 || !noInput) outcome = Outcome.FAILED;
                    else if (outcome == Outcome.NONE) outcome = Outcome.NO_INPUT;
                    if (playback != null) playback.stop();
                    // ERROR can precede RUN_END. Do not let old terminal events end a new run.
                    if (state != State.CANCELLING) {
                        state = State.CANCELLING;
                        deadline = clock.millis() + 5000;
                    }
                    break;
                case VOICE_ASSISTANT_STT_VAD_END:
                case VOICE_ASSISTANT_STT_END:
                    if (state == State.STREAMING) finishInput();
                    break;
                default:
                    break;
            }
            return true;
        }
        return false;
    }

    /** Call only after local acknowledgement completes and real speech has been detected. */
    public void startCommand() throws IOException {
        tick();
        require(State.IDLE);
        state = State.STARTING;
        outcome = Outcome.NONE;
        continueConversation = false;
        if (clock.millis() >= conversationExpires) conversationId = null;
        ttsExpected = false; streamStarted = false; streamEnded = false;
        runEnded = false; playbackReported = false; replyDeadline = 0;
        frames = 0;
        deadline = clock.millis() + 10000;
        // Wake word is handled locally and must not be re-run on command audio in HA.
        send(MessageIds.VoiceAssistantRequest, EsphomeApi.VoiceAssistantRequest.newBuilder()
                .setStart(true).setConversationId(conversationId == null ? "" : conversationId).setAudioSettings(EsphomeApi.VoiceAssistantAudioSettings.newBuilder()
                        .setVolumeMultiplier(1.0f)).build());
    }

    public void sendPcmFrame(byte[] pcm) throws IOException {
        tick();
        require(State.STREAMING);
        if (pcm == null || pcm.length != 640) throw new IllegalArgumentException("pcm_requires_640_bytes");
        if (frames >= 6050) { finishInput(); return; }
        send(MessageIds.VoiceAssistantAudio, EsphomeApi.VoiceAssistantAudio.newBuilder()
                .setData(ByteString.copyFrom(pcm)).build());
        frames++;
    }

    public void finishInput() throws IOException {
        tick();
        require(State.STREAMING);
        if (frames == 0) { cancel(); return; }
        state = State.PROCESSING;
        deadline = clock.millis() + 60000;
        send(MessageIds.VoiceAssistantAudio, EsphomeApi.VoiceAssistantAudio.newBuilder().setEnd(true).build());
    }

    public void cancel() throws IOException {
        if (!active() || state == State.CANCELLING) return;
        if (outcome == Outcome.NONE) outcome = Outcome.CANCELLED;
        if (playback != null) playback.stop();
        if (runEnded) { finishRun(); return; }
        state = State.CANCELLING;
        deadline = clock.millis() + 5000;
        send(MessageIds.VoiceAssistantRequest, EsphomeApi.VoiceAssistantRequest.newBuilder().setStart(false).build());
    }

    /** Owner must call at least once per second, including when the peer is silent. */
    public void tick() throws IOException {
        if (active() && clock.millis() >= deadline) {
            outcome = Outcome.FAILED;
            if (state == State.CANCELLING) abortConnection("voice_terminal_timeout");
            cancel();
            return;
        }
        if (ttsExpected && state != State.CANCELLING && active()) {
            if (playback != null && playback.failure() != null) {
                outcome = Outcome.FAILED; cancel(); return;
            }
            completePlayback();
        }
    }
    public void close() {
        if (active()) outcome = Outcome.FAILED;
        if (playback != null) playback.stop();
        state = State.CLOSED;
        conversationId = null;
        continueConversation = false;
        frames = 0;
    }
    private void expectTts() throws IOException {
        if (playback == null) abortConnection("tts_playback_not_configured");
        if (!ttsExpected) {
            ttsExpected = true;
            replyDeadline = clock.millis() + 300000;
        }
        deadline = replyDeadline;
    }
    private void completePlayback() throws IOException {
        if (!streamEnded || playback == null || !playback.complete()) return;
        if (!playbackReported) {
            playbackReported = true;
            send(MessageIds.VoiceAssistantAnnounceFinished,
                    EsphomeApi.VoiceAssistantAnnounceFinished.newBuilder().setSuccess(true).build());
        }
        if (runEnded) finishRun();
    }
    private void finishRun() {
        if (outcome == Outcome.NONE) outcome = Outcome.COMPLETE;
        if (outcome == Outcome.COMPLETE) conversationExpires = clock.millis() + 900000;
        state = State.IDLE;
    }
    private boolean active() {
        return state == State.STARTING || state == State.STREAMING
                || state == State.PROCESSING || state == State.PLAYING || state == State.CANCELLING;
    }
    private void require(State expected) {
        if (state != expected) throw new IllegalStateException("voice_state_" + state);
    }
    private void send(int type, MessageLite message) throws IOException {
        try { sender.send(type, message); }
        catch (IOException e) { outcome = Outcome.FAILED; close(); throw e; }
    }
    private void abortConnection(String reason) throws IOException {
        outcome = Outcome.FAILED; close(); throw new IOException(reason);
    }
}
