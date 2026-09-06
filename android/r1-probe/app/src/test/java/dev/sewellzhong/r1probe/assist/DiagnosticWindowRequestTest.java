package dev.sewellzhong.r1probe.assist;
import java.util.Random;
import org.junit.Test;
import static org.junit.Assert.*;
public class DiagnosticWindowRequestTest {
    @Test public void fixedPromptDoesNotConsumeRandomSequence() {
        AcknowledgementSelector selector=new AcknowledgementSelector(new Random(3));
        AcknowledgementSelector baseline=new AcknowledgementSelector(new Random(3));
        assertEquals(1,new DiagnosticWindowRequest(false,1).select(selector));
        assertEquals(baseline.next(),new DiagnosticWindowRequest(false,-1).select(selector));
    }
    @Test public void rejectsInvalidOrFollowupOverride() {
        for(int value:new int[]{-2,AcknowledgementSelector.COUNT}) {
            try { new DiagnosticWindowRequest(false,value); fail(); } catch(IllegalArgumentException expected) { }
        }
        try { new DiagnosticWindowRequest(true,1); fail(); } catch(IllegalArgumentException expected) { }
        assertTrue(new DiagnosticWindowRequest(true,-1).followup);
    }
}
