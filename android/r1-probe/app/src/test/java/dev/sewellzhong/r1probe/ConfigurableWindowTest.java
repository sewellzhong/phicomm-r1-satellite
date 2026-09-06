package dev.sewellzhong.r1probe;
import dev.sewellzhong.r1probe.assist.CommandWindow;
import org.junit.Test;
import static org.junit.Assert.*;
public final class ConfigurableWindowTest {
    @Test public void defaultsAllowLateSpeechAndUseIndependentQuietTimer() {
        CommandWindow w = new CommandWindow(20, 1.8f, 30);
        for (int i=0; i<995; i++) assertEquals(CommandWindow.Decision.WAIT,w.accept(false));
        for (int i=0;i<3;i++) assertEquals(CommandWindow.Decision.WAIT,w.accept(true));
        assertEquals(CommandWindow.Decision.START,w.accept(true));
        for (int i=0;i<89;i++) assertEquals(CommandWindow.Decision.CONTINUE,w.accept(false));
        assertEquals(CommandWindow.Decision.END,w.accept(false));
    }
    @Test public void continuousSpeechCanExceedOldTwentySecondLimit() {
        CommandWindow w = new CommandWindow(20, 1.8f, 30);
        for(int i=0;i<4;i++) w.accept(true);
        for(int i=4;i<1499;i++) assertEquals(CommandWindow.Decision.CONTINUE,w.accept(true));
        assertEquals(CommandWindow.Decision.END,w.accept(true));
    }
    @Test public void totalLimitWinsEvenWhenQuietSettingIsLonger() {
        CommandWindow w = new CommandWindow(1, 10, 5);
        for(int i=0;i<4;i++)w.accept(true);
        for(int i=4;i<249;i++)assertEquals(CommandWindow.Decision.CONTINUE,w.accept(false));
        assertEquals(CommandWindow.Decision.END,w.accept(false));
    }
    @Test public void maximumWaitDoesNotUploadOrStart() {
        CommandWindow w = new CommandWindow(120,.2f,120);
        for(int i=0;i<5999;i++)assertEquals(CommandWindow.Decision.WAIT,w.accept(false));
        assertEquals(CommandWindow.Decision.TIMEOUT,w.accept(false));
    }
    @Test(expected=IllegalArgumentException.class) public void rejectNan() { new CommandWindow(Float.NaN,1,30); }
}
