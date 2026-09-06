package dev.sewellzhong.r1probe.esphome;

import dev.sewellzhong.r1probe.esphome.proto.MessageIds;
import java.io.IOException;

/** Explicit protocol fixture: two synthetic frames, no Android audio APIs or voice advertising. */
final class NativeVoiceProbeHandler implements NativeApiConnection.Handler {
    private NativeVoiceSession session;
    private final boolean duplex;
    private final boolean dialogue;
    private int rounds;
    NativeVoiceProbeHandler() { this(false, false); }
    NativeVoiceProbeHandler(boolean duplex) { this(duplex, false); }
    NativeVoiceProbeHandler(boolean duplex, boolean dialogue) { this.duplex = duplex; this.dialogue = dialogue; }
    private NativeVoiceSession.Playback fixturePlayer() {
        return new NativePcmPlayback(() -> new NativePcmPlayback.Sink() {
            private int bytes;
            private long readyAt;
            public void start() { }
            public int write(byte[] data, int offset, int length) throws IOException {
                for (int i = offset; i < offset + length; i++) {
                    if (data[i] != (byte) (bytes % 127)) throw new IOException("synthetic_downlink_mismatch");
                    bytes++;
                }
                readyAt = System.nanoTime() + 400_000_000L;
                return length;
            }
            public long playedFrames() throws IOException {
                if (bytes != 1886) throw new IOException("synthetic_downlink_length");
                return System.nanoTime() >= readyAt ? bytes / 2 : 0;
            }
            public void stop() { }
            public void close() { }
        }, new NativePcmPlayback.Gate() {
            public void request() { }
            public boolean microphoneReleased() { return true; }
            public void release() { }
        });
    }
    private boolean started;
    public void connected(NativeVoiceSession.Sender sender) {
        session = new NativeVoiceSession(sender, () -> System.nanoTime() / 1_000_000L, duplex ? fixturePlayer() : null);
    }
    public void message(int type, byte[] payload) throws IOException {
        session.handle(type, payload);
        if (!started && type == MessageIds.SubscribeVoiceAssistantRequest
                && session.state() == NativeVoiceSession.State.IDLE) {
            started = true;
            rounds = 1;
            session.startCommand();
        } else if (type == MessageIds.VoiceAssistantResponse
                && session.state() == NativeVoiceSession.State.STREAMING) {
            byte[] frame = new byte[640];
            for (int i = 0; i < frame.length; i++) frame[i] = (byte) (i % 127);
            session.sendPcmFrame(frame);
            session.sendPcmFrame(frame);
            session.finishInput();
        }
    }
    public void tick() throws IOException {
        session.tick();
        if (dialogue && rounds == 1 && session.shouldContinue()) {
            rounds = 2;
            session.startCommand();
        }
    }
    public void closed() { if (session != null) session.close(); }
}
