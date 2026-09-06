package dev.sewellzhong.r1probe.assist;

import org.junit.Test;
import static org.junit.Assert.*;

public class EmptyInputResumeTest {
    @Test public void rejectedRunConsumesOriginalBudget() {
        CommandWindow w = new CommandWindow(10,1.8f,30);
        for(int i=0;i<6;i++) w.acceptQualified(true,true);
        w.resumeAfterEmpty(6000);
        for(int i=0;i<199;i++) assertEquals(CommandWindow.Decision.WAIT,w.acceptQualified(false,false));
        assertEquals(CommandWindow.Decision.TIMEOUT,w.acceptQualified(false,false));
    }
    @Test public void expiredBudgetCannotStartAgain() {
        CommandWindow w = new CommandWindow(15,1.8f,30);
        w.resumeAfterEmpty(16000);
        assertEquals(CommandWindow.Decision.TIMEOUT,w.acceptQualified(true,true));
    }
    @Test public void newSpeechUsesQuietEndpointBeyondWaitingDeadline() {
        CommandWindow w = new CommandWindow(10,1.8f,30); w.resumeAfterEmpty(9800);
        for(int i=0;i<5;i++) assertEquals(CommandWindow.Decision.WAIT,w.acceptQualified(true,true));
        assertEquals(CommandWindow.Decision.START,w.acceptQualified(true,true));
        for(int i=0;i<100;i++) assertEquals(CommandWindow.Decision.CONTINUE,w.acceptQualified(true,true));
        for(int i=0;i<89;i++) assertEquals(CommandWindow.Decision.CONTINUE,w.acceptQualified(false,false));
        assertEquals(CommandWindow.Decision.END,w.acceptQualified(false,false));
    }
}
