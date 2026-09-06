package dev.sewellzhong.r1probe;

import android.content.Context;
import android.media.AudioManager;
import dev.sewellzhong.r1probe.esphome.NativeVoiceSession;
import dev.sewellzhong.r1probe.esphome.proto.EsphomeApi;
import dev.sewellzhong.r1probe.esphome.proto.MessageIds;
import java.io.IOException;

/** Six stable number keys and one diagnostic sensor key, not protocol message IDs. Credentials never pass this surface. */
final class NativeControls {
    private static final int BASE = 0x52310001;
    private static final String[] IDS = {"wait_seconds", "quiet_seconds", "command_seconds", "volume", "speech_speed", "followup_wait_seconds"};
    private static final String[] NAMES = {"等待开口时间", "讲话结束停顿时间", "单条命令总时长", "音量", "语速", "持续对话等待开口时间"};
    private static final float[] MIN = {1, .2f, 5, 0, .5f, 1}, MAX = {120, 10, 120, 100, 1.5f, 120}, STEP = {1, .1f, 1, 1, .05f, 1};
    private final NativeSettings settings;
    private final AudioManager audio;
    private final float[] previous = {Float.NaN, Float.NaN, Float.NaN, Float.NaN, Float.NaN, Float.NaN};
    private boolean subscribed;
    private volatile int wakeGeneration;
    private int lastGeneration = -1;
    void wake() { wakeGeneration++; }
    private long nextPoll;
    NativeControls(Context context, NativeSettings settings) {
        this.settings = settings; audio = (AudioManager) context.getSystemService(Context.AUDIO_SERVICE);
        new NativeVolume(context, settings);
    }
    float value(int i) {
        switch(i) {
            case 0: return settings.waitSeconds(); case 1: return settings.quietSeconds();
            case 2: return settings.commandSeconds(); case 4: return settings.speechSpeed();
            case 5: return settings.followupWaitSeconds();
            default: return settings.volumePercent();
        }
    }
    private int key(int index) { return BASE + (index == 5 ? 6 : index); }
    void list(NativeVoiceSession.Sender sender) throws IOException {
        sender.send(MessageIds.ListEntitiesSensorResponse,
            EsphomeApi.ListEntitiesSensorResponse.newBuilder().setKey(BASE+5).setObjectId("wake_generation")
                .setName("唤醒会话序号").setEntityCategoryValue(2).setAccuracyDecimals(0).build());
        for (int i=0; i<IDS.length; i++) sender.send(MessageIds.ListEntitiesNumberResponse,
            EsphomeApi.ListEntitiesNumberResponse.newBuilder().setKey(key(i)).setObjectId(IDS[i]).setName(NAMES[i])
                .setMinValue(MIN[i]).setMaxValue(MAX[i]).setStep(STEP[i])
                .setEntityCategoryValue(1).setModeValue(i == 3 ? 2 : 1)
                .setUnitOfMeasurement((i < 3 || i == 5) ? "s" : i == 3 ? "%" : "倍").build());
    }
    boolean message(int type, byte[] payload, NativeVoiceSession.Sender sender) throws IOException {
        if (type == MessageIds.SubscribeStatesRequest) { subscribed = true; publish(sender, true); return true; }
        if (type != MessageIds.NumberCommandRequest) return false;
        EsphomeApi.NumberCommandRequest command = EsphomeApi.NumberCommandRequest.parseFrom(payload);
        int i = command.getKey() == BASE+6 ? 5 : command.getKey() - BASE; float v = command.getState();
        if (command.getKey() == BASE+5) return true; // Sensor key is never a number command.
        if (command.getDeviceId() != 0 || i < 0 || i >= IDS.length) return true;
        if (Float.isNaN(v) || Float.isInfinite(v) || v < MIN[i] || v > MAX[i]) { publish(sender, true); return true; }
        v = Math.round(v / STEP[i]) * STEP[i];
        settings.setting(IDS[i], v);
        publish(sender, true); return true;
    }
    void tick(NativeVoiceSession.Sender sender) throws IOException {
        if (subscribed && wakeGeneration != lastGeneration) {
            sender.send(MessageIds.SensorStateResponse, EsphomeApi.SensorStateResponse.newBuilder()
                .setKey(BASE+5).setState(wakeGeneration).build());
            lastGeneration = wakeGeneration;
        }
        if (subscribed && System.nanoTime() >= nextPoll) { nextPoll = System.nanoTime()+1_000_000_000L; publish(sender, false); }
    }
    private void publish(NativeVoiceSession.Sender sender, boolean force) throws IOException {
        if (!subscribed) return;
        for (int i=0; i<IDS.length; i++) {
            float v = value(i);
            if (force || Float.compare(previous[i], v) != 0) {
                sender.send(MessageIds.NumberStateResponse, EsphomeApi.NumberStateResponse.newBuilder().setKey(key(i)).setState(v).build());
                previous[i] = v;
            }
        }
    }
}
