package dev.sewellzhong.r1probe.assist;
import org.junit.Test;
import static org.junit.Assert.*;
import java.util.*;

public class PromptReferenceTest {
    private short[] source() {short[] x=new short[16000];Random r=new Random(42);for(int i=0;i<x.length;i++)x[i]=(short)(r.nextInt(4000)-2000);return x;}
    private byte[] pcm(short[] x){byte[] b=new byte[x.length*2];for(int i=0;i<x.length;i++){b[i*2]=(byte)x[i];b[i*2+1]=(byte)(x[i]>>8);}return b;}
    private PromptReference prepared(short[] source) {PromptReference p=new PromptReference();p.start();byte[] b=pcm(source);p.append(b,0,b.length,.5f);return p;}
    @Test public void delayedAttenuatedEchoRequiresThreeFramesAndIsSubtracted() {
        short[] ref=source();PromptReference p=prepared(ref);
        for(int n=0;n<5;n++) {
            int end=1600+n*320,offset=end-320-333;
            short[] frame=new short[320];for(int i=0;i<320;i++)frame[i]=(short)Math.round(ref[offset+i]*.25);
            short[] original=frame.clone();long now=1_000_000_000L+n*20_000_000L;
            p.position(end,now);p.process(frame,now);
            if(n<2)assertArrayEquals(original,frame);else assertTrue(p.afterRms<2);
        }
        assertEquals(3,p.matchedFrames);assertEquals(333,p.delaySamples);
    }
    @Test public void unrelatedInputIsNeverErased() {
        short[] ref=source();PromptReference p=prepared(ref);Random r=new Random(91);
        for(int n=0;n<5;n++) {short[] f=new short[320];for(int i=0;i<320;i++)f[i]=(short)(r.nextInt(500)-250);short[] original=f.clone();p.position(3000+n*320,1_000_000_000L);p.process(f,1_000_000_000L);assertArrayEquals(original,f);}
        assertEquals(0,p.matchedFrames);
    }
    @Test public void simultaneousIndependentSpeechRemainsInResidual() {
        short[] ref=source();PromptReference p=prepared(ref);
        for(int n=0;n<4;n++) {short[] f=new short[320];double wanted=0,error=0;
            for(int i=0;i<320;i++){double speech=40*Math.sin(i*.12);wanted+=speech*speech;f[i]=(short)(ref[1280+n*320+i]*.25+speech);}
            p.position(1600+n*320,1_000_000_000L);p.process(f,1_000_000_000L);
            if(n>=2){for(int i=0;i<320;i++){double delta=f[i]-40*Math.sin(i*.12);error+=delta*delta;}assertTrue(error<wanted*.1);}
        }
    }
    @Test public void referenceRingIsBoundedAndExpiredEchoCannotMatch() {
        short[] ref=source();PromptReference p=prepared(ref);byte[] b=pcm(ref);
        for(int i=0;i<5;i++)p.append(b,0,b.length,.5f);
        short[] frame=Arrays.copyOf(ref,320),original=frame.clone();
        p.finish(1_000_000_000L);p.expire(2_000_000_001L);
        p.process(frame,2_000_000_002L);assertArrayEquals(original,frame);
    }
    @Test public void expirationAndNewPromptRemoveOldReference() {
        short[] ref=source();PromptReference p=prepared(ref);p.finish(1_000_000_000L);
        short[] f=Arrays.copyOf(ref,320),copy=f.clone();p.process(f,2_000_000_001L);assertArrayEquals(copy,f);
        p.start();p.position(320,3_000_000_000L);p.process(f,3_000_000_000L);assertArrayEquals(copy,f);assertEquals(0,p.processedFrames);
    }
}
