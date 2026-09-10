package dev.sewellzhong.r1probe.factoryaudio;

import static org.junit.Assert.assertEquals;

import dev.sewellzhong.r1probe.factoryaudio.proto.FactoryAudio;

import java.io.IOException;

import org.junit.Test;

public class FactoryAudioAttestationTest {
    private static FactoryAudio.Health.Builder proven() {
        return FactoryAudio.Health.newBuilder()
                .setBackendName(FactoryAudioAttestation.PROVEN_BACKEND)
                .setVendorBoardVersion("UNI_4MIC_HAL_ANDROID_V1.1")
                .setRawMicChannels(4)
                .setAecReferenceChannels(2)
                .setArrayProcessingActive(true)
                .setAecActive(true);
    }

    @Test public void completeVendorEvidenceIsAccepted() throws Exception {
        FactoryAudioAttestation.requireProductionChain(proven().build());
    }

    @Test public void missingAecEvidenceIsRejected() throws Exception {
        assertRejected(proven().setAecActive(false).build());
    }

    @Test public void syntheticBackendIsRejected() throws Exception {
        assertRejected(proven().setBackendName("synthetic-fake").build());
    }

    @Test public void missingChannelsAreRejected() throws Exception {
        assertRejected(proven().setRawMicChannels(0).build());
        assertRejected(proven().setAecReferenceChannels(0).build());
    }

    private static void assertRejected(FactoryAudio.Health health) throws Exception {
        try {
            FactoryAudioAttestation.requireProductionChain(health);
        } catch (IOException expected) {
            assertEquals("factory_audio_chain_not_attested", expected.getMessage());
            return;
        }
        throw new AssertionError("unattested factory chain accepted");
    }
}
