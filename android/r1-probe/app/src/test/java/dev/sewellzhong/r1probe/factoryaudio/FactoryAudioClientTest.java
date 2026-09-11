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
    private static FactoryAudio.Health.Builder provenStreamingHealth() {
        return FactoryAudio.Health.newBuilder()
                .setCaptureState(FactoryAudio.CaptureState.CAPTURE_STATE_STREAMING)
                .setBackendName(FactoryAudioAttestation.PROVEN_BACKEND)
                .setVendorBoardVersion("UNI_4MIC_HAL_ANDROID_V1.1")
                .setRawMicChannels(4).setAecReferenceChannels(2)
                .setArrayProcessingActive(true).setAecActive(true);
    }

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
                .setHealth(provenStreamingHealth()).build());
        ByteArrayOutputStream requests = new ByteArrayOutputStream();
        FactoryAudioClient client = new FactoryAudioClient(null,
                new ByteArrayInputStream(replies.toByteArray()), requests);
        client.negotiate();
        client.startCapture();
        assertEquals(1, client.readFrame().getSequence());
        assertTrue(requests.size() > 0);
    }

    @Test public void unattestedStartIsRejectedAndClientIsClosed() throws Exception {
        ByteArrayOutputStream replies = new ByteArrayOutputStream();
        FactoryAudioFraming.write(replies, FactoryAudio.Envelope.newBuilder()
                .setProtocolVersion(1).setRequestId(1)
                .setHelloReply(FactoryAudio.HelloReply.newBuilder().setSelectedVersion(1)).build());
        FactoryAudioFraming.write(replies, FactoryAudio.Envelope.newBuilder()
                .setProtocolVersion(1).setRequestId(2)
                .setHealth(FactoryAudio.Health.newBuilder()
                        .setCaptureState(FactoryAudio.CaptureState.CAPTURE_STATE_STREAMING)
                        .setBackendName("synthetic-fake")).build());
        FactoryAudioClient client = new FactoryAudioClient(null,
                new ByteArrayInputStream(replies.toByteArray()), new ByteArrayOutputStream());
        client.negotiate();
        try {
            client.startCapture();
        } catch (IOException expected) {
            assertEquals("factory_audio_chain_not_attested", expected.getMessage());
            try {
                client.health();
            } catch (IOException closed) {
                assertEquals("factory_audio_client_closed", closed.getMessage());
                return;
            }
        }
        throw new AssertionError("unattested capture remained usable");
    }

    @Test public void validationCaptureAcceptsIdentifiedVendorWithoutClaimingProduction()
            throws Exception {
        ByteArrayOutputStream replies = new ByteArrayOutputStream();
        FactoryAudioFraming.write(replies, FactoryAudio.Envelope.newBuilder()
                .setProtocolVersion(1).setRequestId(1)
                .setHelloReply(FactoryAudio.HelloReply.newBuilder().setSelectedVersion(1)).build());
        FactoryAudio.Health partial = FactoryAudio.Health.newBuilder()
                .setCaptureState(FactoryAudio.CaptureState.CAPTURE_STATE_STREAMING)
                .setBackendName(FactoryAudioAttestation.PROVEN_BACKEND)
                .setVendorBoardVersion("UNI_4MIC_HAL_ANDROID_V1.1")
                .setRawMicChannels(4).setArrayProcessingActive(true)
                .setAecReferenceChannels(0).setAecActive(false).build();
        FactoryAudioFraming.write(replies, FactoryAudio.Envelope.newBuilder()
                .setProtocolVersion(1).setRequestId(2).setHealth(partial).build());
        FactoryAudioClient client = new FactoryAudioClient(null,
                new ByteArrayInputStream(replies.toByteArray()), new ByteArrayOutputStream());
        client.negotiate();
        assertEquals(partial, client.startUnattestedValidationCapture());
        try {
            FactoryAudioAttestation.requireProductionChain(partial);
        } catch (IOException expected) {
            assertEquals("factory_audio_chain_not_attested", expected.getMessage());
            return;
        }
        throw new AssertionError("validation-only health granted production capture");
    }

    @Test public void vendorDebugValidationRequiresActiveHealthAndSetsBothFlags()
            throws Exception {
        ByteArrayOutputStream replies = new ByteArrayOutputStream();
        FactoryAudioFraming.write(replies, FactoryAudio.Envelope.newBuilder()
                .setProtocolVersion(1).setRequestId(1)
                .setHelloReply(FactoryAudio.HelloReply.newBuilder().setSelectedVersion(1)).build());
        FactoryAudio.Health health = FactoryAudio.Health.newBuilder()
                .setCaptureState(FactoryAudio.CaptureState.CAPTURE_STATE_STREAMING)
                .setBackendName(FactoryAudioAttestation.PROVEN_BACKEND)
                .setVendorBoardVersion("UNI_4MIC_HAL_ANDROID_V1.1")
                .setRawMicChannels(4).setArrayProcessingActive(true)
                .setVendorDebugFilesActive(true).build();
        FactoryAudioFraming.write(replies, FactoryAudio.Envelope.newBuilder()
                .setProtocolVersion(1).setRequestId(2).setHealth(health).build());
        ByteArrayOutputStream requests = new ByteArrayOutputStream();
        FactoryAudioClient client = new FactoryAudioClient(null,
                new ByteArrayInputStream(replies.toByteArray()), requests);
        client.negotiate();
        assertEquals(health, client.startVendorDebugValidationCapture());

        ByteArrayInputStream encoded = new ByteArrayInputStream(requests.toByteArray());
        FactoryAudioFraming.read(encoded);
        FactoryAudio.StartCapture start = FactoryAudioFraming.read(encoded).getStartCapture();
        assertTrue(start.getIncludeDiagnosticOutput());
        assertTrue(start.getVendorDebugFiles());
    }

    @Test public void micArrayValidationRequiresActiveHealthAndSetsOnlyTapFlags()
            throws Exception {
        ByteArrayOutputStream replies = new ByteArrayOutputStream();
        FactoryAudioFraming.write(replies, FactoryAudio.Envelope.newBuilder()
                .setProtocolVersion(1).setRequestId(1)
                .setHelloReply(FactoryAudio.HelloReply.newBuilder().setSelectedVersion(1)).build());
        FactoryAudio.Health health = FactoryAudio.Health.newBuilder()
                .setCaptureState(FactoryAudio.CaptureState.CAPTURE_STATE_STREAMING)
                .setBackendName(FactoryAudioAttestation.PROVEN_BACKEND)
                .setVendorBoardVersion("UNI_4MIC_HAL_ANDROID_V1.1")
                .setRawMicChannels(4).setArrayProcessingActive(true)
                .setMicarrayDiagnosticTapActive(true).build();
        FactoryAudioFraming.write(replies, FactoryAudio.Envelope.newBuilder()
                .setProtocolVersion(1).setRequestId(2).setHealth(health).build());
        ByteArrayOutputStream requests = new ByteArrayOutputStream();
        FactoryAudioClient client = new FactoryAudioClient(null,
                new ByteArrayInputStream(replies.toByteArray()), requests);
        client.negotiate();
        assertEquals(health, client.startMicArrayDiagnosticValidationCapture());

        ByteArrayInputStream encoded = new ByteArrayInputStream(requests.toByteArray());
        FactoryAudioFraming.read(encoded);
        FactoryAudio.StartCapture start = FactoryAudioFraming.read(encoded).getStartCapture();
        assertTrue(start.getIncludeDiagnosticOutput());
        assertTrue(start.getMicarrayDiagnosticTap());
        assertTrue(!start.getVendorDebugFiles());
    }

    @Test public void micArrayValidationRejectsInactiveTap() throws Exception {
        ByteArrayOutputStream replies = new ByteArrayOutputStream();
        FactoryAudioFraming.write(replies, FactoryAudio.Envelope.newBuilder()
                .setProtocolVersion(1).setRequestId(1)
                .setHelloReply(FactoryAudio.HelloReply.newBuilder().setSelectedVersion(1)).build());
        FactoryAudioFraming.write(replies, FactoryAudio.Envelope.newBuilder()
                .setProtocolVersion(1).setRequestId(2)
                .setHealth(provenStreamingHealth()).build());
        FactoryAudioClient client = new FactoryAudioClient(null,
                new ByteArrayInputStream(replies.toByteArray()), new ByteArrayOutputStream());
        client.negotiate();
        try {
            client.startMicArrayDiagnosticValidationCapture();
        } catch (IOException expected) {
            assertEquals("factory_audio_micarray_tap_not_active", expected.getMessage());
            return;
        }
        throw new AssertionError("inactive MicArray tap entered validation capture");
    }

    @Test public void malformedMicArrayTapPayloadIsRejected() throws Exception {
        ByteArrayOutputStream replies = new ByteArrayOutputStream();
        FactoryAudioFraming.write(replies, FactoryAudio.Envelope.newBuilder()
                .setProtocolVersion(1).setRequestId(1)
                .setHelloReply(FactoryAudio.HelloReply.newBuilder().setSelectedVersion(1)).build());
        FactoryAudio.MicArrayDiagnosticCall malformed =
                FactoryAudio.MicArrayDiagnosticCall.newBuilder()
                        .setSequence(1).setSamplesPerChannel(256)
                        .setRawMicChannels(4).setEchoReferenceChannels(2)
                        .setRawMicPcmS16Le(ByteString.copyFrom(new byte[2048]))
                        .setEchoReferencePcmS16Le(ByteString.copyFrom(new byte[1022]))
                        .build();
        FactoryAudioFraming.write(replies, FactoryAudio.Envelope.newBuilder()
                .setProtocolVersion(1).setAudioFrame(FactoryAudio.AudioFrame.newBuilder()
                        .setSequence(1).setPcmS16Le(ByteString.copyFrom(new byte[640]))
                        .addMicarrayDiagnosticCalls(malformed)).build());
        FactoryAudioFraming.write(replies, FactoryAudio.Envelope.newBuilder()
                .setProtocolVersion(1).setRequestId(2)
                .setHealth(provenStreamingHealth().setMicarrayDiagnosticTapActive(true)).build());
        FactoryAudioClient client = new FactoryAudioClient(null,
                new ByteArrayInputStream(replies.toByteArray()), new ByteArrayOutputStream());
        client.negotiate();
        try {
            client.startMicArrayDiagnosticValidationCapture();
        } catch (IOException expected) {
            assertEquals("factory_audio_micarray_tap_shape_mismatch", expected.getMessage());
            return;
        }
        throw new AssertionError("malformed MicArray tap payload was buffered");
    }

    @Test public void validationCaptureRejectsSyntheticBackend() throws Exception {
        ByteArrayOutputStream replies = new ByteArrayOutputStream();
        FactoryAudioFraming.write(replies, FactoryAudio.Envelope.newBuilder()
                .setProtocolVersion(1).setRequestId(1)
                .setHelloReply(FactoryAudio.HelloReply.newBuilder().setSelectedVersion(1)).build());
        FactoryAudioFraming.write(replies, FactoryAudio.Envelope.newBuilder()
                .setProtocolVersion(1).setRequestId(2)
                .setHealth(FactoryAudio.Health.newBuilder()
                        .setCaptureState(FactoryAudio.CaptureState.CAPTURE_STATE_STREAMING)
                        .setBackendName("synthetic-fake").setRawMicChannels(4)
                        .setArrayProcessingActive(true).setVendorBoardVersion("fake")).build());
        FactoryAudioClient client = new FactoryAudioClient(null,
                new ByteArrayInputStream(replies.toByteArray()), new ByteArrayOutputStream());
        client.negotiate();
        try {
            client.startUnattestedValidationCapture();
        } catch (IOException expected) {
            assertEquals("factory_audio_validation_chain_not_identified", expected.getMessage());
            return;
        }
        throw new AssertionError("synthetic backend entered validation capture");
    }

    @Test public void malformedDiagnosticShapeIsRejected() throws Exception {
        ByteArrayOutputStream replies = new ByteArrayOutputStream();
        FactoryAudioFraming.write(replies, FactoryAudio.Envelope.newBuilder()
                .setProtocolVersion(1).setRequestId(1)
                .setHelloReply(FactoryAudio.HelloReply.newBuilder().setSelectedVersion(1)).build());
        FactoryAudioFraming.write(replies, FactoryAudio.Envelope.newBuilder()
                .setProtocolVersion(1).setAudioFrame(FactoryAudio.AudioFrame.newBuilder()
                        .setSequence(1).setPcmS16Le(ByteString.copyFrom(new byte[640]))
                        .setDiagnosticOutputChannels(2)
                        .setDiagnosticInterleavedPcmS16Le(
                                ByteString.copyFrom(new byte[640]))).build());
        FactoryAudioFraming.write(replies, FactoryAudio.Envelope.newBuilder()
                .setProtocolVersion(1).setRequestId(2)
                .setHealth(provenStreamingHealth()).build());
        FactoryAudioClient client = new FactoryAudioClient(null,
                new ByteArrayInputStream(replies.toByteArray()), new ByteArrayOutputStream());
        client.negotiate();
        try {
            client.startCapture();
        } catch (IOException expected) {
            assertTrue(expected.getMessage().startsWith(
                    "factory_audio_diagnostic_frame_format_mismatch_"));
            return;
        }
        throw new AssertionError("malformed diagnostic frame accepted");
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

    @Test public void brokenStopStillClosesClientAndSecondCloseIsSafe() throws Exception {
        ByteArrayOutputStream replies = new ByteArrayOutputStream();
        FactoryAudioFraming.write(replies, FactoryAudio.Envelope.newBuilder()
                .setProtocolVersion(1).setRequestId(1)
                .setHelloReply(FactoryAudio.HelloReply.newBuilder().setSelectedVersion(1)).build());
        FactoryAudioFraming.write(replies, FactoryAudio.Envelope.newBuilder()
                .setProtocolVersion(1).setRequestId(2)
                .setHealth(provenStreamingHealth()).build());
        FactoryAudioClient client = new FactoryAudioClient(null,
                new ByteArrayInputStream(replies.toByteArray()), new ByteArrayOutputStream());
        client.negotiate();
        client.startCapture();
        try {
            client.close();
        } catch (IOException expected) {
            // The peer disappeared before acknowledging stop, but local state must still close.
        }
        client.close();
        try {
            client.health();
        } catch (IOException expected) {
            assertEquals("factory_audio_client_closed", expected.getMessage());
            return;
        }
        throw new AssertionError("closed client remained usable");
    }
}
