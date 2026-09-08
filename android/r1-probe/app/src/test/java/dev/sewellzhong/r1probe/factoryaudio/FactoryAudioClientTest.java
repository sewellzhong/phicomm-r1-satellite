package dev.sewellzhong.r1probe.factoryaudio;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

import com.google.protobuf.ByteString;

import dev.sewellzhong.r1probe.factoryaudio.proto.FactoryAudio;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;

import org.junit.Test;

public class FactoryAudioClientTest {
    @Test public void framingRoundTripsEnvelope() throws Exception {
        FactoryAudio.Envelope expected = FactoryAudio.Envelope.newBuilder()
                .setProtocolVersion(1).setRequestId(7)
                .setGetHealth(FactoryAudio.GetHealth.getDefaultInstance()).build();
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        FactoryAudioFraming.write(output, expected);
        assertEquals(expected, FactoryAudioFraming.read(
                new ByteArrayInputStream(output.toByteArray())));
    }

    @Test public void oversizedEnvelopeIsRejectedBeforeAllocation() throws Exception {
        byte[] header = new byte[] {0x00, 0x10, 0x00, 0x01};
        try {
            FactoryAudioFraming.read(new ByteArrayInputStream(header));
        } catch (IOException expected) {
            assertTrue(expected.getMessage().startsWith(
                    "factory_audio_invalid_inbound_length_"));
            return;
        }
        throw new AssertionError("oversized envelope accepted");
    }

    @Test public void clientBuffersAudioWhileWaitingForStartReply() throws Exception {
        ByteArrayOutputStream replies = new ByteArrayOutputStream();
        FactoryAudioFraming.write(replies, FactoryAudio.Envelope.newBuilder()
                .setProtocolVersion(1).setRequestId(1)
                .setHelloReply(FactoryAudio.HelloReply.newBuilder()
                        .setSelectedVersion(1).setBackendName("synthetic-fake")).build());
        FactoryAudioFraming.write(replies, FactoryAudio.Envelope.newBuilder()
                .setProtocolVersion(1).setAudioFrame(FactoryAudio.AudioFrame.newBuilder()
                        .setSequence(1).setPcmS16Le(ByteString.copyFrom(new byte[640]))).build());
        FactoryAudioFraming.write(replies, FactoryAudio.Envelope.newBuilder()
                .setProtocolVersion(1).setRequestId(2)
                .setHealth(FactoryAudio.Health.newBuilder().setCaptureState(
                        FactoryAudio.CaptureState.CAPTURE_STATE_STREAMING)).build());
        ByteArrayOutputStream requests = new ByteArrayOutputStream();
        FactoryAudioClient client = new FactoryAudioClient(null,
                new ByteArrayInputStream(replies.toByteArray()), requests);
        client.negotiate();
        client.startCapture();
        assertEquals(1, client.readFrame().getSequence());
        assertTrue(requests.size() > 0);
    }

    @Test public void explicitAgentErrorIsSurfacedWithoutFallback() throws Exception {
        ByteArrayOutputStream replies = new ByteArrayOutputStream();
        FactoryAudioFraming.write(replies, FactoryAudio.Envelope.newBuilder()
                .setProtocolVersion(1).setRequestId(1)
                .setError(FactoryAudio.Error.newBuilder()
                        .setCode(FactoryAudio.ErrorCode.ERROR_CODE_UNAVAILABLE)
                        .setDetail("factory_backend_unimplemented")).build());
        FactoryAudioClient client = new FactoryAudioClient(null,
                new ByteArrayInputStream(replies.toByteArray()), new ByteArrayOutputStream());
        try {
            client.negotiate();
        } catch (IOException expected) {
            assertTrue(expected.getMessage().contains("ERROR_CODE_UNAVAILABLE"));
            assertTrue(expected.getMessage().contains("factory_backend_unimplemented"));
            return;
        }
        throw new AssertionError("agent error was silently accepted");
    }

    @Test public void pendingAudioQueueIsBounded() throws Exception {
        ByteArrayOutputStream replies = new ByteArrayOutputStream();
        FactoryAudioFraming.write(replies, FactoryAudio.Envelope.newBuilder()
                .setProtocolVersion(1).setRequestId(1)
                .setHelloReply(FactoryAudio.HelloReply.newBuilder().setSelectedVersion(1)).build());
        for (int sequence = 1; sequence <= 51; sequence++) {
            FactoryAudioFraming.write(replies, FactoryAudio.Envelope.newBuilder()
                    .setProtocolVersion(1).setAudioFrame(FactoryAudio.AudioFrame.newBuilder()
                            .setSequence(sequence)
                            .setPcmS16Le(ByteString.copyFrom(new byte[640]))).build());
        }
        FactoryAudioClient client = new FactoryAudioClient(null,
                new ByteArrayInputStream(replies.toByteArray()), new ByteArrayOutputStream());
        client.negotiate();
        try {
            client.startCapture();
        } catch (IOException expected) {
            assertEquals("factory_audio_pending_frame_overflow", expected.getMessage());
            return;
        }
        throw new AssertionError("unbounded pending frames accepted");
    }

    @Test(expected = IOException.class)
    public void referenceMustBeExactlyOneFrame() throws Exception {
        ByteArrayOutputStream replies = new ByteArrayOutputStream();
        FactoryAudioFraming.write(replies, FactoryAudio.Envelope.newBuilder()
                .setProtocolVersion(1).setRequestId(1)
                .setHelloReply(FactoryAudio.HelloReply.newBuilder().setSelectedVersion(1)).build());
        FactoryAudioClient client = new FactoryAudioClient(null,
                new ByteArrayInputStream(replies.toByteArray()), new ByteArrayOutputStream());
        client.negotiate();
        client.submitPlaybackReference(1, 1, new byte[638], "tts");
    }
}
