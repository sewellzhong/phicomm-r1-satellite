package dev.sewellzhong.r1probe.esphome;

import dev.sewellzhong.r1probe.esphome.proto.EsphomeApi;
import dev.sewellzhong.r1probe.esphome.proto.MessageIds;
import java.io.IOException;

/** Owns one HA-initiated announcement on the authenticated protocol thread. */
public final class NativeAnnouncementController {
    public interface Policy {
        boolean allowed();
        void suppressed();
    }
    private final NativeVoiceSession.Playback playback;
    private final Policy policy;
    private NativeVoiceSession.Sender sender;
    private String mediaUrl;
    private volatile boolean active;
    private volatile boolean interrupted;
    private volatile long requests;
    private volatile long completed;
    private volatile long failures;
    private volatile long segmentsStarted;
    private volatile long segmentsCompleted;
    private volatile long suppressed;

    public NativeAnnouncementController(NativeVoiceSession.Playback playback) {
        this(playback, new Policy() {
            @Override public boolean allowed() { return true; }
            @Override public void suppressed() { }
        });
    }

    public NativeAnnouncementController(NativeVoiceSession.Playback playback, Policy policy) {
        if (policy == null) throw new IllegalArgumentException("announcement_policy_required");
        this.playback = playback; this.policy = policy;
    }

    public void connected(NativeVoiceSession.Sender sender) {
        this.sender = sender;
    }

    public boolean active() { return active; }
    public long requests() { return requests; }
    public long completed() { return completed; }
    public long failures() { return failures; }
    public long segmentsStarted() { return segmentsStarted; }
    public long segmentsCompleted() { return segmentsCompleted; }
    public long suppressed() { return suppressed; }

    /** Returns true only for the announcement message owned by this controller. */
    public boolean message(int type, byte[] payload, boolean voiceIdle) throws IOException {
        if (type != MessageIds.VoiceAssistantAnnounceRequest) return false;
        requests++;
        EsphomeApi.VoiceAssistantAnnounceRequest request =
                EsphomeApi.VoiceAssistantAnnounceRequest.parseFrom(payload);
        if (!policy.allowed()) {
            suppressed++; policy.suppressed(); reply(false); return true;
        }
        if (active || !voiceIdle || playback == null || !playback.terminated()
                || request.getStartConversation() || request.getMediaId().isEmpty()) {
            reply(false);
            return true;
        }
        mediaUrl = request.getMediaId();
        String first = request.getPreannounceMediaId().isEmpty()
                ? takeMediaUrl() : request.getPreannounceMediaId();
        try {
            if (!playback.startUrl(first)) throw new IOException("announcement_start_rejected");
            segmentsStarted++;
            active = true;
        } catch (IOException | RuntimeException error) {
            mediaUrl = null;
            playback.stop();
            reply(false);
        }
        return true;
    }

    /** Called by the single protocol owner; never sends from a playback worker. */
    public void tick() throws IOException {
        if (!active) return;
        if (interrupted) {
            interrupted = false;
            playback.stop();
            finish(false);
            return;
        }
        if (playback.failure() != null) {
            if (playback.terminated()) finish(false);
            return;
        }
        if (!playback.complete() || !playback.terminated()) return;
        segmentsCompleted++;
        String next = takeMediaUrl();
        if (next == null) {
            finish(true);
            return;
        }
        try {
            if (!playback.startUrl(next)) throw new IOException("announcement_start_rejected");
            segmentsStarted++;
        } catch (IOException | RuntimeException error) {
            playback.stop();
            finish(false);
        }
    }

    public void closed() {
        if (active) failures++;
        active = false;
        mediaUrl = null;
        interrupted = false;
        sender = null;
        if (playback != null) playback.stop();
    }

    /** Thread-safe request; the protocol owner sends the failure response from tick(). */
    public void interrupt() {
        if (!active) return;
        interrupted = true;
        playback.stop();
    }

    private String takeMediaUrl() {
        String value = mediaUrl;
        mediaUrl = null;
        return value;
    }

    private void finish(boolean success) throws IOException {
        active = false;
        mediaUrl = null;
        if (success) completed++;
        reply(success);
    }

    private void reply(boolean success) throws IOException {
        if (!success) failures++;
        if (sender == null) throw new IOException("announcement_not_connected");
        sender.send(MessageIds.VoiceAssistantAnnounceFinished,
                EsphomeApi.VoiceAssistantAnnounceFinished.newBuilder().setSuccess(success).build());
    }
}
