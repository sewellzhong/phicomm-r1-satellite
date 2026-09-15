package dev.sewellzhong.r1probe.assist;

import org.junit.Test;
import static org.junit.Assert.*;

public class ContinuousDialogueGuardTest {
    @Test public void allowsExactlyTenRoundsAndRecordsBoundedStop() {
        ContinuousDialogueGuard guard=new ContinuousDialogueGuard();
        for(int round=1;round<=ContinuousDialogueGuard.ROUND_LIMIT;round++) {
            assertTrue(guard.mayStartAnother());
            guard.commandStarted();
            assertEquals(round,guard.rounds());
        }
        assertFalse(guard.mayStartAnother());
        guard.stoppedAtLimit();
        assertEquals(1,guard.limitStops());
    }

    @Test public void resetStartsAnIndependentWakeConversation() {
        ContinuousDialogueGuard guard=new ContinuousDialogueGuard();
        guard.commandStarted();guard.commandStarted();guard.reset();
        assertEquals(0,guard.rounds());assertTrue(guard.mayStartAnother());
        guard.commandStarted();assertEquals(1,guard.rounds());
    }

    @Test(expected=IllegalStateException.class)
    public void anEleventhRoundFailsClosed() {
        ContinuousDialogueGuard guard=new ContinuousDialogueGuard();
        for(int i=0;i<ContinuousDialogueGuard.ROUND_LIMIT+1;i++) guard.commandStarted();
    }
}
