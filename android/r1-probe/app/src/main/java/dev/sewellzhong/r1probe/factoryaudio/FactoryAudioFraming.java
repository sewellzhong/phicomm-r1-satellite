package dev.sewellzhong.r1probe.factoryaudio;

import dev.sewellzhong.r1probe.factoryaudio.proto.FactoryAudio;

import java.io.DataInputStream;
import java.io.DataOutputStream;
import java.io.EOFException;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;

final class FactoryAudioFraming {
    static final int MAX_ENVELOPE_BYTES = 1024 * 1024;

    private FactoryAudioFraming() {}

    static void write(OutputStream output, FactoryAudio.Envelope envelope) throws IOException {
        byte[] payload = envelope.toByteArray();
        if (payload.length == 0 || payload.length > MAX_ENVELOPE_BYTES) {
            throw new IOException("factory_audio_invalid_outbound_length_" + payload.length);
        }
        DataOutputStream data = new DataOutputStream(output);
        data.writeInt(payload.length);
        data.write(payload);
        data.flush();
    }

    static FactoryAudio.Envelope read(InputStream input) throws IOException {
        DataInputStream data = new DataInputStream(input);
        final int length;
        try {
            length = data.readInt();
        } catch (EOFException error) {
            throw new EOFException("factory_audio_agent_disconnected");
        }
        if (length <= 0 || length > MAX_ENVELOPE_BYTES) {
            throw new IOException("factory_audio_invalid_inbound_length_" + length);
        }
        byte[] payload = new byte[length];
        data.readFully(payload);
        return FactoryAudio.Envelope.parseFrom(payload);
    }
}
