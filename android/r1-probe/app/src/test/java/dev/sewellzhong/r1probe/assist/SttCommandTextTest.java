package dev.sewellzhong.r1probe.assist;

import org.junit.Test;
import static org.junit.Assert.*;

public final class SttCommandTextTest {
    @Test public void discardsReportedPeriodAndMixedPunctuation() {
        for (String text : new String[]{"。", ".", "……", " ，。！？；： ", "...?!", "「」—"}) {
            assertEquals("", SttCommandText.command(text));
        }
    }
    @Test public void discardsWhitespaceFormatMarksAndSymbolsOnly() {
        for (String text : new String[]{"", " \t\n", "\u3000\u00a0", "\u200b\ufeff", "♪♫", "😀"}) {
            assertEquals("", SttCommandText.command(text));
        }
    }
    @Test public void preservesShortCommandsAndDigits() {
        assertEquals("停", SttCommandText.command("停"));
        assertEquals("好。", SttCommandText.command("好。"));
        assertEquals("5", SttCommandText.command("5"));
        assertEquals("５", SttCommandText.command("５"));
    }
    @Test public void preservesWordsNamesAndInternalPunctuation() {
        assertEquals("现在几点？", SttCommandText.command(" 现在几点？ "));
        assertEquals("Alexa-2，打开。", SttCommandText.command("Alexa-2，打开。"));
        assertEquals("é", SttCommandText.command("é"));
        assertEquals("𠀀", SttCommandText.command("𠀀"));
    }
}
