package dev.sewellzhong.r1probe.assist;
import org.junit.Test;
import static org.junit.Assert.*;

public class SpeechEvidenceTest {
    short[] tone(int level) {
        short[] result = new short[320];
        for (int i=0;i<320;i++) result[i]=(short)(level*Math.sin(2*Math.PI*440*i/16000));
        return result;
    }
    @Test public void silenceDcAndWeakVadDoNotStartWindow() {
        SpeechEvidence gate = new SpeechEvidence();
        CommandWindow window = new CommandWindow(20,1.8f,30,6);
        short[] dc = new short[320]; java.util.Arrays.fill(dc,(short)5000);
        for (int i=0;i<999;i++) assertEquals(CommandWindow.Decision.WAIT,window.accept(gate.accept(dc,true,false)));
        assertEquals(CommandWindow.Decision.TIMEOUT,window.accept(gate.accept(tone(30),true,false)));
    }
    @Test public void isolatedBurstRejectedButShortSpeechRetained() {
        SpeechEvidence gate = new SpeechEvidence();
        CommandWindow window = new CommandWindow(20,1.8f,30,6);
        for(int i=0;i<4;i++) assertEquals(CommandWindow.Decision.WAIT,window.accept(gate.accept(tone(1000),true,false)));
        assertEquals(CommandWindow.Decision.WAIT,window.accept(false));
        for(int i=0;i<5;i++) assertEquals(CommandWindow.Decision.WAIT,window.accept(gate.accept(tone(1000),true,false)));
        assertEquals(CommandWindow.Decision.START,window.accept(gate.accept(tone(1000),true,false)));
        for(int i=0;i<89;i++) assertEquals(CommandWindow.Decision.CONTINUE,window.accept(false));
        assertEquals(CommandWindow.Decision.END,window.accept(false));
        assertEquals(120,window.voicedMillis());
    }
    @Test public void waitingAndTrailingSilenceAreIndependentOnTheDevice() {
        CommandWindow window = new CommandWindow(20,1.8f,30,6);
        for(int i=0;i<500;i++) assertEquals(CommandWindow.Decision.WAIT,window.accept(false));
        for(int i=0;i<5;i++) assertEquals(CommandWindow.Decision.WAIT,window.accept(true));
        assertEquals(CommandWindow.Decision.START,window.accept(true));
        for(int i=0;i<80;i++) assertEquals(CommandWindow.Decision.CONTINUE,window.accept(false));
        assertEquals(CommandWindow.Decision.CONTINUE,window.accept(true)); // More speech resets only the tail timer.
        for(int i=0;i<89;i++) assertEquals(CommandWindow.Decision.CONTINUE,window.accept(false));
        assertEquals(CommandWindow.Decision.END,window.accept(false));
        assertEquals("trailing_silence",window.endReason());
        assertEquals(10120,window.waitingMillis()); // Waiting stopped at confirmed onset.
    }
    @Test public void briefWeakBurstDoesNotSwitchFromWaitingToTailTimer() {
        CommandWindow window = new CommandWindow(20,1.8f,30,6);
        for(int i=0;i<450;i++) assertEquals(CommandWindow.Decision.WAIT,window.acceptQualified(false,false));
        for(int i=0;i<7;i++) assertEquals(CommandWindow.Decision.WAIT,window.acceptQualified(true,false));
        for(int i=457;i<999;i++) assertEquals(CommandWindow.Decision.WAIT,window.acceptQualified(false,false));
        assertEquals(CommandWindow.Decision.TIMEOUT,window.acceptQualified(false,false));
        assertEquals(20000,window.waitingMillis());
    }
    @Test public void sustainedQuietSpeechAllowsSmallGapsAndShortStrongReplyIsProtected() {
        CommandWindow window = new CommandWindow(20,1.8f,30,6);
        for(int i=0;i<5;i++) assertEquals(CommandWindow.Decision.WAIT,window.acceptQualified(true,false));
        for(int i=0;i<2;i++) assertEquals(CommandWindow.Decision.WAIT,window.acceptQualified(false,false));
        for(int i=0;i<4;i++) assertEquals(CommandWindow.Decision.WAIT,window.acceptQualified(true,false));
        assertEquals(CommandWindow.Decision.START,window.acceptQualified(true,false));
        assertEquals("sustained_voice",window.onsetReason());
        assertEquals(200,window.voicedMillis());
        CommandWindow shortReply = new CommandWindow(20,1.8f,30,6);
        for(int i=0;i<5;i++) assertEquals(CommandWindow.Decision.WAIT,shortReply.acceptQualified(true,true));
        assertEquals(CommandWindow.Decision.START,shortReply.acceptQualified(true,true));
        assertEquals("strong_voice",shortReply.onsetReason());
    }
    @Test public void qualifiedOnsetThenOnlyTailSilenceDeterminesEnd() {
        CommandWindow window = new CommandWindow(20,1.8f,30,6);
        for(int i=0;i<500;i++) assertEquals(CommandWindow.Decision.WAIT,window.acceptQualified(false,false));
        for(int i=0;i<9;i++) assertEquals(CommandWindow.Decision.WAIT,window.acceptQualified(true,false));
        assertEquals(CommandWindow.Decision.START,window.acceptQualified(true,false));
        for(int i=0;i<80;i++) assertEquals(CommandWindow.Decision.CONTINUE,window.acceptQualified(false,false));
        assertEquals(CommandWindow.Decision.CONTINUE,window.acceptQualified(true,false));
        for(int i=0;i<89;i++) assertEquals(CommandWindow.Decision.CONTINUE,window.acceptQualified(false,false));
        assertEquals(CommandWindow.Decision.END,window.acceptQualified(false,false));
        assertEquals(10200,window.waitingMillis());
    }
    @Test public void vadScalingDoesNotChangeUploadedPcmAndSaturatesSafely() {
        short[] input=new short[320],output=new short[320];
        input[0]=54;input[1]=20000;input[2]=-20000;
        SpeechEvidence.scaleForVad(input,output);
        assertEquals(216,output[0]);assertEquals(32767,output[1]);assertEquals(-32768,output[2]);
        assertEquals(54,input[0]);assertEquals(20000,input[1]);
    }
    @Test public void quietR1SpeechMustSurviveTheEnergyGuard() {
        SpeechEvidence gate = new SpeechEvidence();
        gate.accept(tone(20),false,true); // ~14 RMS: accepted device's measured ambient.
        CommandWindow window = new CommandWindow(20,1.8f,30,6);
        for(int i=0;i<5;i++) assertEquals(CommandWindow.Decision.WAIT,window.accept(gate.accept(tone(76),true,false)));
        assertEquals(CommandWindow.Decision.START,window.accept(gate.accept(tone(76),true,false)));
    }
    @Test public void learnedAmbientRequiresEnergyRiseAndVad() {
        SpeechEvidence gate = new SpeechEvidence();
        gate.accept(tone(400),false,true);
        assertFalse(gate.accept(tone(400),true,false));
        assertFalse(gate.accept(tone(1500),false,false));
        assertTrue(gate.accept(tone(1500),true,false));
    }
}
