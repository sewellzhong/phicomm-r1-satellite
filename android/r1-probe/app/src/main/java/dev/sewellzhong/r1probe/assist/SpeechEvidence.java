package dev.sewellzhong.r1probe.assist;

/** AC energy guard around VAD, no audio retained. The noise floor learns only outside commands. */
public final class SpeechEvidence {
    public static void scaleForVad(short[] input, short[] output) {
        if (input.length != 320 || output.length != 320) throw new IllegalArgumentException("vad_frame_size");
        for (int i=0;i<320;i++) output[i]=(short)Math.max(-32768,Math.min(32767,input[i]*4));
    }
    private double floor = 40;
    private double rms;
    private boolean calibrated;
    public double rms() { return rms; }
    public boolean strong() { return rms >= Math.max(48, floor * 4); }
    public double floor() { return floor; }
    public boolean accept(short[] frame, boolean vad, boolean learn) {
        double sum = 0, square = 0;
        for (short value : frame) { sum += value; square += (double) value * value; }
        double mean = sum / frame.length;
        rms = Math.sqrt(Math.max(0, square / frame.length - mean * mean));
        if (learn && !vad) {
            if (!calibrated) { floor = rms; calibrated = true; }
            else floor += (rms < floor ? .15 : .005) * (rms - floor);
        }
        // R1 raw speech is quiet (~54 RMS in the accepted recording); preserve it.
        // 24 PCM RMS minimum and 6 dB above ambient; VAD alone is not proof of speech.
        return vad && rms >= Math.max(24, floor * 2);
    }
}
