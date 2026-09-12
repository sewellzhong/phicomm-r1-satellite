package dev.sewellzhong.r1probe.esphome;

import com.google.protobuf.MessageLite;
import dev.sewellzhong.r1probe.esphome.proto.EsphomeApi;
import dev.sewellzhong.r1probe.esphome.proto.MessageIds;
import java.io.IOException;
import java.util.ArrayList;
import java.util.List;
import org.junit.Test;
import static org.junit.Assert.*;

public final class NativeMediaControllerTest {
    static final class Backend implements NativeMediaController.Backend {
        NativeMediaController.State state = NativeMediaController.State.IDLE;
        String url, failure = "none";
        float volume;
        public void open(String value, float level) { url=value;volume=level;state=NativeMediaController.State.PREPARING; }
        public void play() throws IOException { if(state!=NativeMediaController.State.PAUSED)throw new IOException("media_not_resumable");state=NativeMediaController.State.PLAYING; }
        public void pause() throws IOException { if(state!=NativeMediaController.State.PLAYING&&state!=NativeMediaController.State.PREPARING)throw new IOException("media_not_playing");state=NativeMediaController.State.PAUSED; }
        public void stop(){state=NativeMediaController.State.IDLE;failure="none";}
        public void volume(float value){volume=value;}
        public NativeMediaController.State state(){return state;}
        public String failure(){return failure;}
    }
    static final class Volume implements NativeMediaController.Volume {
        float value=.4f;
        public float level(){return value;}
        public void level(float value){this.value=value;}
    }
    private final Backend backend=new Backend();
    private final Volume volume=new Volume();
    private final List<Integer> ids=new ArrayList<>();
    private final List<MessageLite> sent=new ArrayList<>();
    private boolean allowed=true;
    private final NativeMediaController controller=new NativeMediaController(backend,volume,()->allowed);

    private void connect() { controller.connected((id,message)->{ids.add(id);sent.add(message);}); }
    private byte[] request(EsphomeApi.MediaPlayerCommand command) {
        return EsphomeApi.MediaPlayerCommandRequest.newBuilder().setKey(NativeMediaController.KEY)
                .setHasCommand(true).setCommand(command).build().toByteArray();
    }

    @Test public void entityAdvertisesImplementedControlsAndAnnouncementWav() throws Exception {
        connect(); controller.list((id,message)->{ids.add(id);sent.add(message);});
        assertEquals(MessageIds.ListEntitiesMediaPlayerResponse,(int)ids.get(0));
        EsphomeApi.ListEntitiesMediaPlayerResponse entity=(EsphomeApi.ListEntitiesMediaPlayerResponse)sent.get(0);
        assertEquals(NativeMediaController.FEATURE_FLAGS,entity.getFeatureFlags());assertTrue(entity.getSupportsPause());
        assertEquals("r1_media_player",entity.getObjectId());assertEquals(1,entity.getSupportedFormatsCount());
        EsphomeApi.MediaPlayerSupportedFormat format=entity.getSupportedFormats(0);
        assertEquals("wav",format.getFormat());assertEquals(16000,format.getSampleRate());
        assertEquals(EsphomeApi.MediaPlayerFormatPurpose.MEDIA_PLAYER_FORMAT_PURPOSE_ANNOUNCEMENT,format.getPurpose());
    }

    @Test public void urlPauseResumeStopAndObservedStateArePublished() throws Exception {
        connect(); controller.message(MessageIds.SubscribeStatesRequest,new byte[0]);sent.clear();ids.clear();
        byte[] start=EsphomeApi.MediaPlayerCommandRequest.newBuilder().setKey(NativeMediaController.KEY)
                .setHasMediaUrl(true).setMediaUrl("https://ha.local/media/song.mp3?token=opaque")
                .setHasVolume(true).setVolume(.65f).build().toByteArray();
        assertTrue(controller.message(MessageIds.MediaPlayerCommandRequest,start));
        assertEquals(NativeMediaController.State.PREPARING,backend.state);assertEquals(.65f,volume.value,0);
        backend.state=NativeMediaController.State.PLAYING;controller.tick();
        controller.message(MessageIds.MediaPlayerCommandRequest,request(EsphomeApi.MediaPlayerCommand.MEDIA_PLAYER_COMMAND_PAUSE));
        assertEquals(NativeMediaController.State.PAUSED,backend.state);
        controller.message(MessageIds.MediaPlayerCommandRequest,request(EsphomeApi.MediaPlayerCommand.MEDIA_PLAYER_COMMAND_PLAY));
        assertEquals(NativeMediaController.State.PLAYING,backend.state);
        controller.message(MessageIds.MediaPlayerCommandRequest,request(EsphomeApi.MediaPlayerCommand.MEDIA_PLAYER_COMMAND_STOP));
        assertEquals(NativeMediaController.State.IDLE,backend.state);
        assertTrue(sent.stream().allMatch(value->value instanceof EsphomeApi.MediaPlayerStateResponse));
        assertEquals(4,controller.requests());assertEquals(0,controller.rejected());
    }

    @Test public void invalidOrBusyStartFailsClosedWithoutChangingPlayback() throws Exception {
        connect(); controller.message(MessageIds.SubscribeStatesRequest,new byte[0]);
        for(String url:new String[]{"file:///private.mp3","https://user:secret@ha/media.mp3","https://ha/media.mp3#fragment",""}) {
            byte[] value=EsphomeApi.MediaPlayerCommandRequest.newBuilder().setKey(NativeMediaController.KEY)
                    .setHasMediaUrl(true).setMediaUrl(url).build().toByteArray();
            controller.message(MessageIds.MediaPlayerCommandRequest,value);
        }
        allowed=false;
        byte[] busy=EsphomeApi.MediaPlayerCommandRequest.newBuilder().setKey(NativeMediaController.KEY)
                .setHasMediaUrl(true).setMediaUrl("https://ha/media.mp3").build().toByteArray();
        controller.message(MessageIds.MediaPlayerCommandRequest,busy);
        assertNull(backend.url);assertEquals(NativeMediaController.State.IDLE,backend.state);
        assertEquals(5,controller.rejected());assertEquals("media_audio_busy",controller.lastFailure());
    }

    @Test public void foreignKeyAndUnsupportedCommandsCannotControlBackend() throws Exception {
        connect();
        byte[] foreign=EsphomeApi.MediaPlayerCommandRequest.newBuilder().setKey(1).setHasCommand(true)
                .setCommand(EsphomeApi.MediaPlayerCommand.MEDIA_PLAYER_COMMAND_STOP).build().toByteArray();
        assertFalse(controller.message(MessageIds.MediaPlayerCommandRequest,foreign));
        controller.message(MessageIds.MediaPlayerCommandRequest,
                request(EsphomeApi.MediaPlayerCommand.MEDIA_PLAYER_COMMAND_MUTE));
        assertEquals(1,controller.rejected());assertEquals(NativeMediaController.State.IDLE,backend.state);
    }

    @Test public void nestedSystemInterruptionsResumeOnlySystemPausedMedia() throws Exception {
        connect(); backend.state=NativeMediaController.State.PLAYING;
        controller.interrupt(NativeMediaController.Interruption.VOICE);
        assertEquals(NativeMediaController.State.PAUSED,backend.state);
        controller.interrupt(NativeMediaController.Interruption.ALARM);
        controller.release(NativeMediaController.Interruption.VOICE);controller.tick();
        assertEquals(NativeMediaController.State.PAUSED,backend.state);
        controller.release(NativeMediaController.Interruption.ALARM);controller.tick();
        assertEquals(NativeMediaController.State.PLAYING,backend.state);

        controller.interrupt(NativeMediaController.Interruption.VOICE);
        controller.message(MessageIds.MediaPlayerCommandRequest,
                request(EsphomeApi.MediaPlayerCommand.MEDIA_PLAYER_COMMAND_STOP));
        controller.release(NativeMediaController.Interruption.VOICE);controller.tick();
        assertEquals(NativeMediaController.State.IDLE,backend.state);
    }
}
