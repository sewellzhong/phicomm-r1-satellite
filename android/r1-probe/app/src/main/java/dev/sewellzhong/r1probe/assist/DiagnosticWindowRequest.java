package dev.sewellzhong.r1probe.assist;

/** An explicit local-admin fixture. Normal Alexa selection never uses this override. */
public final class DiagnosticWindowRequest {
    public final boolean followup;
    public final int promptIndex;
    public DiagnosticWindowRequest(boolean followup, int promptIndex) {
        if(promptIndex < -1 || promptIndex >= AcknowledgementSelector.COUNT || (followup && promptIndex != -1))
            throw new IllegalArgumentException("invalid_diagnostic_prompt");
        this.followup=followup; this.promptIndex=promptIndex;
    }
    public int select(AcknowledgementSelector selector) {
        if(followup) throw new IllegalStateException("followup_has_no_prompt");
        return promptIndex<0 ? selector.next() : promptIndex;
    }
}
