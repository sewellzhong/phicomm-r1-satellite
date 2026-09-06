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
}
