package dev.sewellzhong.r1probe.assist;

import dev.sewellzhong.r1probe.esphome.NativePcmPlayback;
import java.io.DataInputStream;
import java.io.InputStream;
import java.io.IOException;
import java.util.Arrays;
import java.util.concurrent.atomic.AtomicBoolean;

/** Bounded packaged WAV playback; notify only when AudioTrack consumed every sample. */
public final class PromptPcmPlayer {
    private static int le32(DataInputStream in) throws IOException { return Integer.reverseBytes(in.readInt()); }
    public static void play(InputStream input, NativePcmPlayback.Sink sink,
            AtomicBoolean stopping, Runnable drained) throws Exception {
        byte[] frame = new byte[640];
        try (DataInputStream in = new DataInputStream(input)) {
            if (in.readInt()!=0x52494646) throw new IOException("prompt_not_riff");
            int size=le32(in);
            if(size<36 || size>640000 || in.readInt()!=0x57415645) throw new IOException("prompt_invalid_wave");
            int left=size-4, data=-1; boolean format=false;
            while(left>=8) {
                int kind=in.readInt(), n=le32(in); left-=8;
                if(n<0 || n>left) throw new IOException("prompt_invalid_chunk");
                if(kind==0x666d7420) {
                    if(n<16) throw new IOException("prompt_invalid_format");
                    int pcm=Short.reverseBytes(in.readShort())&0xffff;
                    int channels=Short.reverseBytes(in.readShort())&0xffff;
                    int rate=le32(in), bytes=le32(in);
                    int align=Short.reverseBytes(in.readShort())&0xffff;
                    int bits=Short.reverseBytes(in.readShort())&0xffff;
                    if(pcm!=1 || channels!=1 || rate!=16000 || bytes!=32000 || align!=2 || bits!=16)
                        throw new IOException("prompt_unsupported_format");
                    n-=16; left-=16; format=true;
                } else if(kind==0x64617461) {
                    if(!format || n==0 || (n&1)!=0) throw new IOException("prompt_invalid_data");
                    data=n; break;
                }
                for(int i=0;i<n+(n&1);i++) in.readByte();
                left-=n+(n&1);
            }
            if(data<0) throw new IOException("prompt_missing_data");
            if(stopping.get()) return;
            sink.start(); long written=0, deadline=System.nanoTime()+20_000_000_000L;
            while(data>0 && !stopping.get()) {
                int count=Math.min(frame.length,data); in.readFully(frame,0,count); data-=count;
                for(int offset=0;offset<count && !stopping.get();) {
                    if(System.nanoTime()>deadline) throw new IOException("prompt_write_timeout");
                    int accepted=sink.write(frame,offset,count-offset);
                    if(accepted<=0 || accepted>count-offset || (accepted&1)!=0) throw new IOException("prompt_write_failed");
                    offset+=accepted; written+=accepted/2;
                }
                Arrays.fill(frame,(byte)0);
            }
            while(!stopping.get() && sink.playedFrames()<written) {
                if(System.nanoTime()>deadline) throw new IOException("prompt_drain_timeout");
                Thread.sleep(1);
            }
            if(!stopping.get()) drained.run();
        } finally {
            Arrays.fill(frame,(byte)0);
            try { sink.stop(); } finally { sink.close(); }
        }
    }
    private PromptPcmPlayer() { }
}
