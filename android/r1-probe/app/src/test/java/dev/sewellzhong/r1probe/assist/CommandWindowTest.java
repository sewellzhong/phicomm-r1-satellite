package dev.sewellzhong.r1probe.assist;

import org.junit.Test;
import static org.junit.Assert.*;
import static dev.sewellzhong.r1probe.assist.CommandWindow.Decision.*;

public final class CommandWindowTest {
    @Test public void silenceTimesOutWithoutStartingUpload() {
        CommandWindow w = new CommandWindow();
        for (int i = 0; i < 299; i++) { assertEquals(WAIT, w.accept(false)); }
        assertEquals(TIMEOUT, w.accept(false));
        assertEquals(DONE, w.accept(true));
    }
    @Test public void isolatedVoiceFlagsDoNotStartCommand() {
        CommandWindow w = new CommandWindow();
        for (int i = 0; i < 299; i++) { assertEquals(WAIT, w.accept(i % 10 < 3)); }
        assertEquals(TIMEOUT, w.accept(false));
    }
    @Test public void lateStartGetsItsOwnCommandWindow() {
        CommandWindow w = new CommandWindow();
        for (int i = 0; i < 295; i++) { assertEquals(WAIT, w.accept(false)); }
        for (int i = 0; i < 3; i++) { assertEquals(WAIT, w.accept(true)); }
        assertEquals(START, w.accept(true));
        assertEquals(80, w.voicedMillis());
        for (int i = 0; i < 200; i++) { assertEquals(CONTINUE, w.accept(true)); }
        for (int i = 0; i < 59; i++) { assertEquals(CONTINUE, w.accept(false)); }
        assertEquals(END, w.accept(false));
        assertEquals(DONE, w.accept(true));
    }
    @Test public void shortCommandDoesNotWaitEightSeconds() {
        CommandWindow w = new CommandWindow();
        for (int i = 0; i < 3; i++) { assertEquals(WAIT, w.accept(true)); }
        assertEquals(START, w.accept(true));
        assertEquals(80, w.voicedMillis());
        for (int i = 0; i < 30; i++) { assertEquals(CONTINUE, w.accept(true)); }
        for (int i = 0; i < 59; i++) { assertEquals(CONTINUE, w.accept(false)); }
        assertEquals(END, w.accept(false));
    }
    @Test public void continuousSpeechHasTwentySecondCap() {
        CommandWindow w = new CommandWindow();
        for (int i = 0; i < 3; i++) { assertEquals(WAIT, w.accept(true)); }
        assertEquals(START, w.accept(true));
        assertEquals(80, w.voicedMillis());
        for (int i = 0; i < 995; i++) { assertEquals(CONTINUE, w.accept(true)); }
        assertEquals(END, w.accept(true));
    }
    @Test public void followupRejectsShortTailButAcceptsClearShortReply() {
        CommandWindow tail = new CommandWindow(10,1.8f,30,6,15,10);
        for(int i=0;i<9;i++)assertEquals(WAIT,tail.acceptQualified(true,true));
        for(int i=0;i<20;i++)assertEquals(WAIT,tail.acceptQualified(false,false));
        CommandWindow clear = new CommandWindow(10,1.8f,30,6,15,10);
        for(int i=0;i<9;i++)assertEquals(WAIT,clear.acceptQualified(true,true));
        assertEquals(START,clear.acceptQualified(true,true));
        assertEquals("strong_voice",clear.onsetReason());
    }
    @Test public void followupStillAcceptsSustainedQuietReply() {
        CommandWindow quiet = new CommandWindow(10,1.8f,30,6,15,10);
        for(int i=0;i<14;i++)assertEquals(WAIT,quiet.acceptQualified(true,false));
        assertEquals(START,quiet.acceptQualified(true,false));
        assertEquals("sustained_voice",quiet.onsetReason());
    }
}
