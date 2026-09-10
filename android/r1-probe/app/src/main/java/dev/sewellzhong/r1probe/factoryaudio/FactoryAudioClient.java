package dev.sewellzhong.r1probe.factoryaudio;

import android.net.LocalSocket;
import android.net.LocalSocketAddress;

import com.google.protobuf.ByteString;

import dev.sewellzhong.r1probe.factoryaudio.proto.FactoryAudio;

import java.io.Closeable;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.util.ArrayDeque;

/** Explicit factory-proxy source. Errors never trigger a silent AudioRecord fallback. */
public final class FactoryAudioClient implements Closeable {
    public static final int PROTOCOL_VERSION = 1;
    public static final int FRAME_BYTES = 640;
    public static final int IO_TIMEOUT_MS = 2000;
    public static final String SOCKET_NAME = "r1_factory_audio";
    private static final int MAX_PENDING_FRAMES = 50;

    private final LocalSocket socket;
    private final InputStream input;
    private final OutputStream output;
    private final ArrayDeque<FactoryAudio.AudioFrame> pendingFrames = new ArrayDeque<>();
    private long nextRequestId = 1;
    private boolean negotiated;
    private boolean capturing;
    private boolean closed;

    public static FactoryAudioClient connect() throws IOException {
        LocalSocket socket = new LocalSocket();
        try {
            socket.connect(new LocalSocketAddress(
                    SOCKET_NAME, LocalSocketAddress.Namespace.RESERVED));
            socket.setSoTimeout(IO_TIMEOUT_MS);
            FactoryAudioClient client = new FactoryAudioClient(
                    socket, socket.getInputStream(), socket.getOutputStream());
            client.negotiate();
            return client;
        } catch (IOException error) {
            try { socket.close(); } catch (IOException ignored) {}
            throw error;
        }
    }

    FactoryAudioClient(LocalSocket socket, InputStream input, OutputStream output) {
        this.socket = socket;
        this.input = input;
        this.output = output;
    }

    public synchronized void negotiate() throws IOException {
        requireOpen();
        require(!negotiated, "factory_audio_already_negotiated");
        long requestId = nextRequestId++;
        send(requestId, FactoryAudio.Envelope.newBuilder().setHello(
                FactoryAudio.Hello.newBuilder()
                        .setMinimumVersion(PROTOCOL_VERSION)
                        .setMaximumVersion(PROTOCOL_VERSION)
                        .setClientName("r1-satellite")));
        FactoryAudio.Envelope reply = readReply(requestId);
        if (!reply.hasHelloReply()
                || reply.getHelloReply().getSelectedVersion() != PROTOCOL_VERSION) {
            throw new IOException("factory_audio_protocol_mismatch");
        }
        negotiated = true;
    }

    public synchronized void startCapture() throws IOException {
        requireOpen();
        require(negotiated, "factory_audio_not_negotiated");
        require(!capturing, "factory_audio_already_capturing");
        long requestId = nextRequestId++;
        FactoryAudio.AudioFormat format = FactoryAudio.AudioFormat.newBuilder()
                .setSampleRateHz(16000).setChannels(1).setSampleWidthBytes(2)
                .setFrameDurationMs(20).build();
        send(requestId, FactoryAudio.Envelope.newBuilder().setStartCapture(
                FactoryAudio.StartCapture.newBuilder().setFormat(format)));
        FactoryAudio.Envelope reply = readReply(requestId);
        if (!reply.hasHealth()
                || reply.getHealth().getCaptureState()
                != FactoryAudio.CaptureState.CAPTURE_STATE_STREAMING) {
            throw new IOException("factory_audio_start_not_streaming");
        }
        try {
            FactoryAudioAttestation.requireProductionChain(reply.getHealth());
        } catch (IOException rejected) {
            // Closing the transport makes the agent release its single capture owner.
            // Do not leave an unattested backend streaming or permit this client to retry it.
            closed = true;
            negotiated = false;
            pendingFrames.clear();
            if (socket != null) {
                try { socket.close(); } catch (IOException ignored) {}
            }
            throw rejected;
        }
        capturing = true;
    }

    public synchronized FactoryAudio.AudioFrame readFrame() throws IOException {
        requireOpen();
        require(capturing, "factory_audio_not_capturing");
        if (!pendingFrames.isEmpty()) {
            return pendingFrames.removeFirst();
        }
        while (true) {
            FactoryAudio.Envelope envelope = FactoryAudioFraming.read(input);
            throwIfError(envelope);
            if (envelope.hasAudioFrame()) {
                validateFrame(envelope.getAudioFrame());
                return envelope.getAudioFrame();
            }
        }
    }

    public synchronized FactoryAudio.Health health() throws IOException {
        requireOpen();
        require(negotiated, "factory_audio_not_negotiated");
        long requestId = nextRequestId++;
        send(requestId, FactoryAudio.Envelope.newBuilder().setGetHealth(
                FactoryAudio.GetHealth.getDefaultInstance()));
        FactoryAudio.Envelope reply = readReply(requestId);
        if (!reply.hasHealth()) {
            throw new IOException("factory_audio_missing_health");
        }
        return reply.getHealth();
    }

    public synchronized void submitPlaybackReference(long sequence, long monotonicTimeNs,
            byte[] pcm, String source) throws IOException {
        requireOpen();
        require(negotiated, "factory_audio_not_negotiated");
        if (pcm == null || pcm.length != FRAME_BYTES) {
            throw new IOException("factory_audio_reference_format_mismatch");
        }
        long requestId = nextRequestId++;
        FactoryAudio.PlaybackReference reference = FactoryAudio.PlaybackReference.newBuilder()
                .setSequence(sequence).setMonotonicTimeNs(monotonicTimeNs)
                .setPcmS16Le(ByteString.copyFrom(pcm)).setSource(source == null ? "" : source)
                .build();
        send(requestId, FactoryAudio.Envelope.newBuilder().setPlaybackReference(reference));
        FactoryAudio.Envelope reply = readReply(requestId);
        if (!reply.hasHealth()) {
            throw new IOException("factory_audio_reference_not_acknowledged");
        }
    }

    public synchronized void stopCapture() throws IOException {
        requireOpen();
        if (!capturing) {
            return;
        }
        long requestId = nextRequestId++;
        send(requestId, FactoryAudio.Envelope.newBuilder().setStopCapture(
                FactoryAudio.StopCapture.getDefaultInstance()));
        FactoryAudio.Envelope reply = readReply(requestId);
        if (!reply.hasHealth()
                || reply.getHealth().getCaptureState()
                != FactoryAudio.CaptureState.CAPTURE_STATE_IDLE) {
            throw new IOException("factory_audio_stop_not_idle");
        }
        capturing = false;
        pendingFrames.clear();
    }

    @Override
    public synchronized void close() throws IOException {
        if (closed) return;
        IOException first = null;
        try {
            stopCapture();
        } catch (IOException error) {
            first = error;
        }
        closed = true;
        capturing = false;
        negotiated = false;
        pendingFrames.clear();
        if (socket != null) {
            try { socket.close(); } catch (IOException error) {
                if (first == null) first = error;
            }
        }
        if (first != null) throw first;
    }

    private void requireOpen() throws IOException {
        require(!closed, "factory_audio_client_closed");
    }

    private void send(long requestId, FactoryAudio.Envelope.Builder body) throws IOException {
        body.setProtocolVersion(PROTOCOL_VERSION).setRequestId(requestId);
        FactoryAudioFraming.write(output, body.build());
    }

    private FactoryAudio.Envelope readReply(long requestId) throws IOException {
        while (true) {
            FactoryAudio.Envelope envelope = FactoryAudioFraming.read(input);
            throwIfError(envelope);
            if (envelope.hasAudioFrame()) {
                validateFrame(envelope.getAudioFrame());
                if (pendingFrames.size() >= MAX_PENDING_FRAMES) {
                    throw new IOException("factory_audio_pending_frame_overflow");
                }
                pendingFrames.addLast(envelope.getAudioFrame());
                continue;
            }
            if (envelope.getRequestId() != requestId) {
                throw new IOException("factory_audio_unexpected_request_id_"
                        + envelope.getRequestId());
            }
            return envelope;
        }
    }

    private static void validateFrame(FactoryAudio.AudioFrame frame) throws IOException {
        if (frame.getPcmS16Le().size() != FRAME_BYTES) {
            throw new IOException("factory_audio_frame_format_mismatch_"
                    + frame.getPcmS16Le().size());
        }
    }

    private static void throwIfError(FactoryAudio.Envelope envelope) throws IOException {
        if (envelope.getProtocolVersion() != PROTOCOL_VERSION) {
            throw new IOException("factory_audio_protocol_mismatch");
        }
        if (envelope.hasError()) {
            throw new IOException("factory_audio_agent_error_"
                    + envelope.getError().getCode().name() + "_"
                    + envelope.getError().getDetail());
        }
    }

    private static void require(boolean condition, String message) throws IOException {
        if (!condition) throw new IOException(message);
    }
}
