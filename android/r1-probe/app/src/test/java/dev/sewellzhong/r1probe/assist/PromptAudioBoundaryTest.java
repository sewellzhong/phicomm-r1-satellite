package dev.sewellzhong.r1probe.assist;
import org.junit.Test;
import static org.junit.Assert.*;

public class PromptAudioBoundaryTest {
    @Test public void promptFramesAreDiscardedButImmediateCommandFrameIsPreserved() {
        PromptAudioBoundary boundary=new PromptAudioBoundary();
        short[] frame=new short[320],output=new short[320];
        java.util.Arrays.fill(frame,(short)500);
        for(int i=0;i<100;i++) assertFalse(boundary.accept(frame,320));
        boundary.complete();
        java.util.Arrays.fill(frame,(short)120);
        assertTrue(boundary.accept(frame,320));
        java.util.Arrays.fill(frame,(short)0);
        assertEquals(320,boundary.copyTo(output));
        assertEquals(120,output[0]);assertEquals(120,output[319]);
        assertEquals(0,boundary.copyTo(output));
    }
    @Test public void partialBoundaryReadIsPreservedWithoutPaddingAFullFrame() {
        PromptAudioBoundary boundary=new PromptAudioBoundary();boundary.complete();
        short[] frame=new short[320],output=new short[320];frame[79]=7;
        assertTrue(boundary.accept(frame,80));assertEquals(80,boundary.copyTo(output));assertEquals(7,output[79]);
    }
}
