package dev.sewellzhong.r1probe.esphome;

import dev.sewellzhong.r1probe.esphome.proto.EsphomeApi;
import dev.sewellzhong.r1probe.esphome.proto.MessageIds;
import java.io.IOException;
import java.net.MalformedURLException;
import java.net.URL;
import java.util.EnumSet;

/** Noise-authenticated URL media control with state sourced from the real playback backend. */
public final class NativeMediaController {
    public static final int KEY = 0x52315454;
    public static final int FEATURE_FLAGS = (1 << 0) | (1 << 2) | (1 << 9)
            | (1 << 10) | (1 << 12) | (1 << 14);

    public enum State { IDLE, PREPARING, PLAYING, PAUSED, FAILED }
    public enum Interruption { VOICE, ANNOUNCEMENT, ALARM }

    public interface Backend {
        void open(String url, float volume) throws IOException;
        void play() throws IOException;
        void pause() throws IOException;
        void stop();
        void volume(float value);
        State state();
        String failure();
    }

    public interface Volume {
        float level();
        void level(float value) throws IOException;
    }

    public interface Policy { boolean canStart(); }

    private final Backend backend;
    private final Volume volume;
    private final Policy policy;
    private NativeVoiceSession.Sender sender;
    private boolean subscribed;
    private State reportedState;
    private float reportedVolume = Float.NaN;
    private boolean reportedMuted;
    private long requests;
    private long rejected;
    private long failures;
    private String lastFailure = "none";
    private final EnumSet<Interruption> interruptions = EnumSet.noneOf(Interruption.class);
    private boolean resumePending;

    public NativeMediaController(Backend backend, Volume volume, Policy policy) {
        if (backend == null || volume == null || policy == null)
            throw new IllegalArgumentException("media_dependencies_required");
        this.backend = backend; this.volume = volume; this.policy = policy;
    }

    public void connected(NativeVoiceSession.Sender sender) { this.sender = sender; }

    public void list(NativeVoiceSession.Sender sender) throws IOException {
        EsphomeApi.MediaPlayerSupportedFormat announcement =
                EsphomeApi.MediaPlayerSupportedFormat.newBuilder()
                        .setFormat("wav").setSampleRate(16000).setNumChannels(1).setSampleBytes(2)
                        .setPurpose(EsphomeApi.MediaPlayerFormatPurpose.MEDIA_PLAYER_FORMAT_PURPOSE_ANNOUNCEMENT)
                        .build();
        sender.send(MessageIds.ListEntitiesMediaPlayerResponse,
                EsphomeApi.ListEntitiesMediaPlayerResponse.newBuilder()
                        .setObjectId("r1_media_player").setKey(KEY).setName("R1 媒体播放器")
                        .setSupportsPause(true).setFeatureFlags(FEATURE_FLAGS)
                        .addSupportedFormats(announcement).build());
    }

    /** SubscribeStates is broadcast state, while command messages are consumed only for our key. */
    public synchronized boolean message(int type, byte[] payload) throws IOException {
        if (type == MessageIds.SubscribeStatesRequest) {
            subscribed = true; publish(true); return false;
        }
        if (type != MessageIds.MediaPlayerCommandRequest) return false;
        EsphomeApi.MediaPlayerCommandRequest command =
                EsphomeApi.MediaPlayerCommandRequest.parseFrom(payload);
        if (command.getKey() != KEY) return false;
        requests++;
        if (command.getDeviceId() != 0) { reject("media_device_id_invalid"); publish(true); return true; }
        try {
            Float requestedVolume = command.getHasVolume() ? checkedVolume(command.getVolume()) : null;
            String requestedUrl = command.getHasMediaUrl() ? checkedUrl(command.getMediaUrl()) : null;
            if (command.getHasAnnouncement() && command.getAnnouncement())
                throw new IOException("media_announcement_wrong_path");
            if (requestedUrl != null && (!interruptions.isEmpty() || !policy.canStart()))
                throw new IOException("media_audio_busy");

            if (requestedVolume != null) {
                volume.level(requestedVolume);
                backend.volume(requestedVolume);
            }
            if (requestedUrl != null) backend.open(requestedUrl, volume.level());
            if (command.getHasCommand()) apply(command.getCommand());
            if (requestedUrl == null && requestedVolume == null && !command.getHasCommand())
                throw new IOException("media_empty_command");
            lastFailure = "none";
        } catch (IOException | RuntimeException error) {
            reject(safeFailure(error));
        }
        publish(true);
        return true;
    }

    private void apply(EsphomeApi.MediaPlayerCommand command) throws IOException {
        switch (command) {
            case MEDIA_PLAYER_COMMAND_PLAY:
                if (!interruptions.isEmpty()) throw new IOException("media_audio_busy");
                resumePending = false; backend.play(); break;
            case MEDIA_PLAYER_COMMAND_PAUSE: resumePending = false; backend.pause(); break;
            case MEDIA_PLAYER_COMMAND_STOP: resumePending = false; backend.stop(); break;
            case MEDIA_PLAYER_COMMAND_TOGGLE:
                if (backend.state() == State.PLAYING || backend.state() == State.PREPARING) {
                    resumePending = false; backend.pause();
                } else if (backend.state() == State.PAUSED) {
                    if (!interruptions.isEmpty()) throw new IOException("media_audio_busy");
                    resumePending = false; backend.play();
                }
                else throw new IOException("media_not_resumable");
                break;
            case MEDIA_PLAYER_COMMAND_VOLUME_UP: stepVolume(.1f); break;
            case MEDIA_PLAYER_COMMAND_VOLUME_DOWN: stepVolume(-.1f); break;
            default: throw new IOException("media_command_unsupported");
        }
    }

    private void stepVolume(float delta) throws IOException {
        float value = Math.max(0, Math.min(1, volume.level() + delta));
        volume.level(value); backend.volume(value);
    }

    public synchronized void tick() throws IOException {
        if (resumePending && interruptions.isEmpty() && policy.canStart()) {
            if (backend.state() == State.PAUSED) {
                try { backend.play(); resumePending = false; }
                catch (IOException | RuntimeException error) {
                    failures++; lastFailure = safeFailure(error); resumePending = false; backend.stop();
                }
            } else if (backend.state() != State.PREPARING) resumePending = false;
        }
        String backendFailure = backend.failure();
        if (backend.state() == State.FAILED && backendFailure != null
                && !backendFailure.equals(lastFailure)) {
            failures++; lastFailure = safeFailure(backendFailure);
        }
        publish(false);
    }

    /** Pause once for nested system audio owners and resume only if this controller paused it. */
    public synchronized void interrupt(Interruption reason) {
        if (reason == null || !interruptions.add(reason) || interruptions.size() != 1) return;
        State current = backend.state();
        if (current != State.PLAYING && current != State.PREPARING) return;
        try { backend.pause(); resumePending = true; }
        catch (IOException | RuntimeException error) {
            failures++; lastFailure = safeFailure(error); resumePending = false; backend.stop();
        }
    }

    public synchronized void release(Interruption reason) {
        if (reason != null) interruptions.remove(reason);
    }

    public synchronized void closed() {
        backend.stop(); sender = null; subscribed = false; interruptions.clear(); resumePending = false;
        reportedState = null; reportedVolume = Float.NaN; reportedMuted = false;
    }

    public synchronized State state() { return backend.state(); }
    public synchronized long requests() { return requests; }
    public synchronized long rejected() { return rejected; }
    public synchronized long failures() { return failures; }
    public synchronized String lastFailure() { return lastFailure; }

    private void publish(boolean force) throws IOException {
        if (!subscribed || sender == null) return;
        State current = backend.state();
        float currentVolume = checkedCurrentVolume(volume.level());
        boolean muted = currentVolume == 0;
        if (!force && current == reportedState && Float.compare(currentVolume, reportedVolume) == 0
                && muted == reportedMuted) return;
        sender.send(MessageIds.MediaPlayerStateResponse,
                EsphomeApi.MediaPlayerStateResponse.newBuilder().setKey(KEY)
                        .setState(protocolState(current)).setVolume(currentVolume).setMuted(muted).build());
        reportedState = current; reportedVolume = currentVolume; reportedMuted = muted;
    }

    private void reject(String reason) { rejected++; lastFailure = reason; }

    private static float checkedVolume(float value) throws IOException {
        if (Float.isNaN(value) || Float.isInfinite(value) || value < 0 || value > 1)
            throw new IOException("media_volume_invalid");
        return value;
    }

    private static float checkedCurrentVolume(float value) { return Math.max(0, Math.min(1, value)); }

    static String checkedUrl(String value) throws IOException {
        if (value == null || value.isEmpty() || value.length() > 2048)
            throw new IOException("media_url_invalid");
        try {
            URL url = new URL(value);
            if (!("http".equals(url.getProtocol()) || "https".equals(url.getProtocol()))
                    || url.getHost().isEmpty() || url.getUserInfo() != null || url.getRef() != null)
                throw new IOException("media_url_invalid");
        } catch (MalformedURLException error) { throw new IOException("media_url_invalid"); }
        return value;
    }

    private static EsphomeApi.MediaPlayerState protocolState(State state) {
        if (state == State.PLAYING) return EsphomeApi.MediaPlayerState.MEDIA_PLAYER_STATE_PLAYING;
        if (state == State.PAUSED) return EsphomeApi.MediaPlayerState.MEDIA_PLAYER_STATE_PAUSED;
        return EsphomeApi.MediaPlayerState.MEDIA_PLAYER_STATE_IDLE;
    }

    private static String safeFailure(Object error) {
        String value = error instanceof Throwable ? ((Throwable) error).getMessage() : String.valueOf(error);
        return value != null && value.matches("media_[a-z0-9_]{1,64}")
                ? value : "media_playback_failed";
    }
}
