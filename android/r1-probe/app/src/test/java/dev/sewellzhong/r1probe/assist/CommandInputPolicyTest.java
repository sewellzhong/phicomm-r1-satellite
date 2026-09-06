package dev.sewellzhong.r1probe.assist;

import org.junit.Test;
import static org.junit.Assert.*;
import static dev.sewellzhong.r1probe.assist.CommandInputPolicy.Reason.*;

public final class CommandInputPolicyTest {
    private void ignored(String text, CommandInputPolicy.Reason reason) {
        CommandInputPolicy.Result result = CommandInputPolicy.evaluate(text, false, -1, null);
        assertEquals(reason, result.reason); assertEquals("", result.text);
    }
    @Test public void recognizesWholeNonSpeechMarkersButNotCommandWords() {
        for (String text : new String[]{"[BLANK_AUDIO]", "[no speech]", "(silence)", "[音乐]",
                "【噪音】", "<|nospeech|>", "[music] [applause]。"}) { ignored(text, NON_SPEECH_MARKER); }
        for (String text : new String[]{"音乐", "播放[音乐]", "关闭噪音检测", "播放无声电影"}) {
            assertEquals(ACCEPTED, CommandInputPolicy.evaluate(text, false, -1, null).reason);
        }
    }
    @Test public void wakeOnlyIsIgnoredButPrefixAndFollowupNameArePreserved() {
        for (String text : new String[]{"ＡＬＥＸＡ。", "Alexa!", "欧ex萨", "奥ex斯"}) { ignored(text, WAKE_ONLY); }
        assertEquals(ACCEPTED, CommandInputPolicy.evaluate("Alexa灯打开", false, 100, null).reason);
        assertEquals(ACCEPTED, CommandInputPolicy.evaluate("Alexa", true, 100, null).reason);
    }
    @Test public void fillerRequiresNoPendingFollowup() {
        for (String text : new String[]{"嗯", "呃……", "嗯嗯", "哦", "唔"}) {
            ignored(text, FILLER_ONLY);
            assertEquals(ACCEPTED, CommandInputPolicy.evaluate(text, true, -1, null).reason);
        }
    }
    @Test public void cancellationIsExactAndDoesNotSwallowStopOrTimerCommands() {
        for (String text : new String[]{"算了", "没事了", "不说了", "不用了", "结束对话"}) { ignored(text, CANCELLED); }
        assertEquals(ACCEPTED, CommandInputPolicy.evaluate("不用了", true, -1, null).reason);
        assertEquals(CANCELLED, CommandInputPolicy.evaluate("结束对话", true, -1, null).reason);
        for (String text : new String[]{"停", "停止", "取消", "取消计时器", "把算了这首歌放一下"}) {
            assertEquals(ACCEPTED, CommandInputPolicy.evaluate(text, false, 80, null).reason);
        }
    }
    @Test public void echoRequiresLastActualPromptAndWeakMeasuredSpeech() {
        assertEquals(ACK_ECHO, CommandInputPolicy.evaluate("诶，叫我啦？", false, 120, "诶，叫我啦？").reason);
        assertEquals(ACCEPTED, CommandInputPolicy.evaluate("诶，叫我啦？", false, -1, "诶，叫我啦？").reason);
        assertEquals(ACCEPTED, CommandInputPolicy.evaluate("诶，叫我啦？", false, 800, "诶，叫我啦？").reason);
        assertEquals(ACCEPTED, CommandInputPolicy.evaluate("诶，叫我啦？", true, 120, "诶，叫我啦？").reason);
        assertEquals(ACCEPTED, CommandInputPolicy.evaluate("来了来了", false, 120, "诶，叫我啦？").reason);
    }
    @Test public void repetitiveHallucinationNeedsWeakAcousticsNotJustRepeatedWords() {
        String text = "谢谢观看谢谢观看谢谢观看谢谢观看";
        assertEquals(WEAK_REPETITION, CommandInputPolicy.evaluate(text, false, 100, null).reason);
        assertEquals(ACCEPTED, CommandInputPolicy.evaluate(text, false, 1000, null).reason);
        assertEquals(ACCEPTED, CommandInputPolicy.evaluate(text, false, -1, null).reason);
        assertEquals(ACCEPTED, CommandInputPolicy.evaluate("谢谢观看", false, 100, null).reason);
        assertEquals(ACCEPTED, CommandInputPolicy.evaluate("你好你好", false, 100, null).reason);
    }
    @Test public void noSpeechMustBeMeasuredRatherThanInferredFromMissingData() {
        assertEquals(NO_SPEECH, CommandInputPolicy.evaluate("现在几点", false, 0, null).reason);
        assertEquals(ACCEPTED, CommandInputPolicy.evaluate("现在几点", false, -1, null).reason);
    }
    @Test public void keepsShortRepliesNamesAndUnknownIntents() {
        for (String text : new String[]{"好", "不", "是", "否", "5", "５", "谢谢", "嗯打开灯", "客厅", "蓝色",
                "现在什么时间？", "明天会有外星人吗？", "名为null的灯", "null"}) {
            assertEquals(text, CommandInputPolicy.evaluate(text, false, 80, null).text);
        }
    }
}
