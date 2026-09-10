package dev.sewellzhong.r1probe.factoryaudio;

import dev.sewellzhong.r1probe.factoryaudio.proto.FactoryAudio;

import java.io.IOException;

/** Rejects a factory backend until the R1 has proved the complete vendor processing chain. */
public final class FactoryAudioAttestation {
    public static final String PROVEN_BACKEND = "unisound_uni4mic_3448";

    private FactoryAudioAttestation() {}

    /** Minimum identity check for a bounded validation capture; never grants production use. */
    static void requireValidationChain(FactoryAudio.Health health) throws IOException {
        if (health == null
                || !PROVEN_BACKEND.equals(health.getBackendName())
                || health.getRawMicChannels() != 4
                || !health.getArrayProcessingActive()
                || health.getVendorBoardVersion().isEmpty()) {
            throw new IOException("factory_audio_validation_chain_not_identified");
        }
    }

    public static void requireProductionChain(FactoryAudio.Health health) throws IOException {
        if (health == null
                || !PROVEN_BACKEND.equals(health.getBackendName())
                || health.getRawMicChannels() != 4
                || health.getAecReferenceChannels() != 2
                || !health.getArrayProcessingActive()
                || !health.getAecActive()
                || health.getVendorBoardVersion().isEmpty()) {
            throw new IOException("factory_audio_chain_not_attested");
        }
    }
}
