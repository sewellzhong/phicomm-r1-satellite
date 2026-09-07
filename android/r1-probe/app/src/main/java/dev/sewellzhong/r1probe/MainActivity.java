package dev.sewellzhong.r1probe;

import android.app.Activity;
import android.content.Intent;
import android.os.Build;
import android.os.Bundle;
import android.util.Log;
import android.view.Gravity;
import android.view.InputDevice;
import android.view.KeyEvent;
import android.view.MotionEvent;
import android.widget.TextView;

import java.io.File;
import java.util.concurrent.atomic.AtomicBoolean;

public final class MainActivity extends Activity {
    private static final String TAG = "R1Probe";
    private static final String AUDIO_TAG = "R1Audio";
    private static final String NONCE_EXTRA = "probe_nonce";
    private static final String ACTION_EXTRA = "probe_action";
    private static final AtomicBoolean AUDIO_BUSY = new AtomicBoolean(false);

    private TextView statusView;
    private String deviceInfo;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        String nonce = getIntent().getStringExtra(NONCE_EXTRA);
        if (nonce == null) {
            nonce = "manual";
        }

        String info = ProbeInfo.format(
                Build.MODEL,
                Build.VERSION.SDK_INT,
                Build.SUPPORTED_ABIS[0],
                Build.FINGERPRINT);
        deviceInfo = info;

        statusView = new TextView(this);
        statusView.setGravity(Gravity.CENTER);
        statusView.setPadding(24, 24, 24, 24);
        statusView.setText(info);
        setContentView(statusView);

        Log.i(TAG, "R1_PROBE_READY nonce=" + nonce + " " + info.replace('\n', ' '));

        handleAction(getIntent(), nonce);
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        String nonce = intent.getStringExtra(NONCE_EXTRA);
        if (nonce == null) {
            nonce = "manual";
        }
        Log.i(TAG, "R1_PROBE_NEW_INTENT nonce=" + nonce);
        handleAction(intent, nonce);
    }

    @Override public boolean dispatchKeyEvent(KeyEvent event) {
        if (event.getKeyCode() == HardwareInputInterpreter.CENTRAL_KEY
                && (event.getAction() == KeyEvent.ACTION_DOWN || event.getAction() == KeyEvent.ACTION_UP))
            HardwareInputRelay.central(event.getAction() == KeyEvent.ACTION_DOWN ? 1 : 0, event.getEventTime());
        return super.dispatchKeyEvent(event);
    }

    @Override public boolean dispatchTouchEvent(MotionEvent event) {
        int action = event.getActionMasked();
        if (action == MotionEvent.ACTION_DOWN || action == MotionEvent.ACTION_MOVE
                || action == MotionEvent.ACTION_UP || action == MotionEvent.ACTION_CANCEL) {
            float minimum = 0, maximum = 719;
            InputDevice device = event.getDevice();
            InputDevice.MotionRange range = device == null ? null
                    : device.getMotionRange(MotionEvent.AXIS_X, event.getSource());
            if (range != null && range.getRange() > 0) { minimum = range.getMin(); maximum = range.getMax(); }
            int position = HardwareInputRelay.normalizePosition(event.getX(), minimum, maximum);
            HardwareInputRelay.ring(action, position, event.getEventTime());
        }
        return super.dispatchTouchEvent(event);
    }

    private void handleAction(Intent intent, String nonce) {
        String action = intent.getStringExtra(ACTION_EXTRA);
        if ("alexa_engine_check".equals(action)) {
            try {
                AlexaEngineProbe.run(getAssets());
                Log.i(AUDIO_TAG, "R1_ALEXA_ENGINE_CHECK_COMPLETE nonce=" + nonce);
                statusView.setText("Alexa engine checks passed");
            } catch (Exception | LinkageError e) {
                Log.e(AUDIO_TAG, "R1_ALEXA_ENGINE_CHECK_FAILED nonce=" + nonce, e);
            }
        } else if ("record".equals(action)) {
            startRecording(nonce);
        } else if ("play".equals(action)) {
            startPlayback(nonce);
        } else if ("capabilities".equals(action)) {
            String capabilities = AudioEffectCapabilities.describe();
            statusView.setText(deviceInfo + "\n" + capabilities);
            Log.i(AUDIO_TAG, "R1_AUDIO_CAPABILITIES nonce=" + nonce + " " + capabilities);
        } else if ("four_mic_capabilities".equals(action)) {
            startFourMicCapabilities(nonce);
        } else if ("four_mic_record".equals(action)) {
            startFourMicRecording(nonce);
        } else if ("stereo_record".equals(action)) {
            startStereoRecording(nonce);

        } else if ("microwakeword_load".equals(action)) {
            startMicroWakeWordLoad(nonce);
        } else if ("microwakeword_score_wav".equals(action)) {
            startMicroWakeWordScoreWav(intent, nonce);
        }
    }

    private void startMicroWakeWordScoreWav(Intent intent, String nonce) {
        try {
            File wav = FileNames.restrictedChild(
                    diagnosticsDir(), intent.getStringExtra("file_path"));
            short[] samples = MonoWavIo.read(wav);
            MicroWakeWordLoadProbe.ScoreResult result =
                    MicroWakeWordLoadProbe.score(getAssets(), samples, 25);
            Log.i(AUDIO_TAG, "R1_MICROWAKEWORD_SCORE_COMPLETE nonce=" + nonce
                    + " file=" + FileNames.sanitize(wav.getName())
                    + " samples=" + samples.length
                    + " inference_count=" + result.inferenceCount
                    + " max_score=" + result.maximumScore
                    + " max_inference_us=" + result.maxInferenceMicros);
            statusView.setText("Alexa raw score: " + result.maximumScore);
        } catch (Exception | LinkageError error) {
            Log.e(AUDIO_TAG, "R1_MICROWAKEWORD_SCORE_FAILED nonce=" + nonce
                    + " message=" + safeMessage(error), error);
            statusView.setText("microWakeWord score failed: " + safeMessage(error));
        }
    }

    private void startMicroWakeWordLoad(String nonce) {
        try {
            MicroWakeWordLoadProbe.Result result = MicroWakeWordLoadProbe.loadAndRun(getAssets());
            Log.i(AUDIO_TAG, "R1_MICROWAKEWORD_LOAD_COMPLETE nonce=" + nonce
                    + " model=alexa input=" + result.inputShape
                    + " output=" + result.outputShape
                    + " frontend_frames=" + result.frontendFrames
                    + " inference_count=" + result.inferenceCount
                    + " last_score=" + result.lastScore
                    + " max_inference_us=" + result.maxInferenceMicros);
            statusView.setText("Alexa microWakeWord loaded and streamed");
        } catch (Exception | LinkageError error) {
            Log.e(AUDIO_TAG, "R1_MICROWAKEWORD_LOAD_FAILED nonce=" + nonce
                    + " message=" + safeMessage(error), error);
            statusView.setText("microWakeWord load failed: " + safeMessage(error));
        }
    }

    private void startStereoRecording(final String nonce) {
        if (!AUDIO_BUSY.compareAndSet(false, true)) {
            Log.e(AUDIO_TAG, "R1_STEREO_RECORD_FAILED nonce=" + nonce + " error=audio_busy");
            return;
        }
        final int sourceId = getIntent().getIntExtra("audio_source", AudioSourceSpec.VOICE_COMMUNICATION);
        final int durationSeconds = clamp(getIntent().getIntExtra("duration_seconds", 10), 1, 30);
        final String sampleId = FileNames.sanitize(getIntent().getStringExtra("sample_id"));
        Log.i(AUDIO_TAG, "R1_STEREO_RECORD_START nonce=" + nonce
                + " source=" + AudioSourceSpec.nameOf(sourceId)
                + " duration_seconds=" + durationSeconds);

        new Thread(new Runnable() {
            @Override
            public void run() {
                try {
                    StereoAudioCapture.Result result = StereoAudioCapture.record(
                            diagnosticsDir(), sourceId, durationSeconds, sampleId);
                    Log.i(AUDIO_TAG, "R1_STEREO_RECORD_COMPLETE nonce=" + nonce
                            + " stereo_path=" + result.stereoFile.getAbsolutePath()
                            + " left_path=" + result.leftFile.getAbsolutePath()
                            + " right_path=" + result.rightFile.getAbsolutePath()
                            + " average_path=" + result.averageFile.getAbsolutePath()
                            + " difference_path=" + result.differenceFile.getAbsolutePath()
                            + " metadata_path=" + result.metadataFile.getAbsolutePath()
                            + " stereo_pcm_bytes=" + result.stereoBytes
                            + " elapsed_ms=" + result.elapsedMillis
                            + " partial_reads=" + result.partialReads);
                    setStatus("Stereo channel diagnostic recorded");
                } catch (Exception e) {
                    Log.e(AUDIO_TAG, "R1_STEREO_RECORD_FAILED nonce=" + nonce
                            + " error=" + e.getClass().getSimpleName()
                            + " message=" + safeMessage(e), e);
                    setStatus("Stereo recording failed: " + safeMessage(e));
                } finally {
                    AUDIO_BUSY.set(false);
                }
            }
        }, "r1-stereo-record").start();
    }

    private void startFourMicCapabilities(final String nonce) {
        try {
            String boardVersion = safeValue(SystemFourMicBackend.load().boardVersion());
            Log.i(AUDIO_TAG, "R1_FOUR_MIC_CAPABILITIES nonce=" + nonce
                    + " library_source=system library_bundled=false board_version=" + boardVersion);
            statusView.setText("Four microphone library available: " + boardVersion);
        } catch (RuntimeException | LinkageError e) {
            Log.e(AUDIO_TAG, "R1_FOUR_MIC_CAPABILITIES_FAILED nonce=" + nonce
                    + " error=" + e.getClass().getSimpleName()
                    + " message=" + safeMessage(e), e);
            statusView.setText("Four microphone capability failed: " + safeMessage(e));
        }
    }

    private void startFourMicRecording(final String nonce) {
        if (!AUDIO_BUSY.compareAndSet(false, true)) {
            Log.e(AUDIO_TAG, "R1_FOUR_MIC_RECORD_FAILED nonce=" + nonce + " error=audio_busy");
            return;
        }
        final int durationSeconds = clamp(getIntent().getIntExtra("duration_seconds", 10), 1, 30);
        final String sampleId = FileNames.sanitize(getIntent().getStringExtra("sample_id"));
        Log.i(AUDIO_TAG, "R1_FOUR_MIC_RECORD_START nonce=" + nonce
                + " duration_seconds=" + durationSeconds);
        statusView.setText("Recording vendor four microphone path for " + durationSeconds + " seconds");

        new Thread(new Runnable() {
            @Override
            public void run() {
                try {
                    FourMicCapture.Result result = FourMicCapture.record(
                            diagnosticsDir(), durationSeconds, sampleId, SystemFourMicBackend.load());
                    Log.i(AUDIO_TAG, "R1_FOUR_MIC_RECORD_COMPLETE nonce=" + nonce
                            + " path=" + result.wavFile.getAbsolutePath()
                            + " pcm_bytes=" + result.pcmBytes
                            + " elapsed_ms=" + result.elapsedMillis
                            + " partial_reads=" + result.partialReads
                            + " read_calls=" + result.readCalls
                            + " board_version=" + result.boardVersion);
                    setStatus("Recorded " + result.wavFile.getName());
                } catch (Exception | LinkageError e) {
                    Log.e(AUDIO_TAG, "R1_FOUR_MIC_RECORD_FAILED nonce=" + nonce
                            + " error=" + e.getClass().getSimpleName()
                            + " message=" + safeMessage(e), e);
                    setStatus("Four microphone recording failed: " + safeMessage(e));
                } finally {
                    AUDIO_BUSY.set(false);
                }
            }
        }, "r1-four-mic-record").start();
    }

    private void startRecording(final String nonce) {
        if (!AUDIO_BUSY.compareAndSet(false, true)) {
            Log.e(AUDIO_TAG, "R1_AUDIO_RECORD_FAILED nonce=" + nonce + " error=audio_busy");
            return;
        }

        final int sourceId = getIntent().getIntExtra("audio_source", AudioSourceSpec.VOICE_RECOGNITION);
        final int durationSeconds = clamp(getIntent().getIntExtra("duration_seconds", 10), 1, 30);
        final String sampleId = FileNames.sanitize(getIntent().getStringExtra("sample_id"));

        Log.i(AUDIO_TAG, "R1_AUDIO_RECORD_START nonce=" + nonce
                + " source=" + AudioSourceSpec.nameOf(sourceId)
                + " duration_seconds=" + durationSeconds);
        statusView.setText("Recording " + AudioSourceSpec.nameOf(sourceId) + " for " + durationSeconds + " seconds");

        new Thread(new Runnable() {
            @Override
            public void run() {
                try {
                    File diagnosticsDir = diagnosticsDir();
                    AudioCapture.Result result = AudioCapture.record(
                            diagnosticsDir, sourceId, durationSeconds, sampleId);
                    Log.i(AUDIO_TAG, "R1_AUDIO_RECORD_COMPLETE nonce=" + nonce
                            + " source=" + result.sourceName
                            + " path=" + result.wavFile.getAbsolutePath()
                            + " pcm_bytes=" + result.pcmBytes
                            + " elapsed_ms=" + result.elapsedMillis
                            + " session_id=" + result.audioSessionId
                            + " partial_reads=" + result.partialReads);
                    setStatus("Recorded " + result.wavFile.getName());
                } catch (Exception e) {
                    Log.e(AUDIO_TAG, "R1_AUDIO_RECORD_FAILED nonce=" + nonce
                            + " error=" + e.getClass().getSimpleName()
                            + " message=" + safeMessage(e), e);
                    setStatus("Recording failed: " + safeMessage(e));
                } finally {
                    AUDIO_BUSY.set(false);
                }
            }
        }, "r1-audio-record").start();
    }

    private void startPlayback(final String nonce) {
        if (!AUDIO_BUSY.compareAndSet(false, true)) {
            Log.e(AUDIO_TAG, "R1_AUDIO_PLAYBACK_FAILED nonce=" + nonce + " error=audio_busy");
            return;
        }

        final String requestedPath = getIntent().getStringExtra("file_path");
        Log.i(AUDIO_TAG, "R1_AUDIO_PLAYBACK_START nonce=" + nonce + " path=" + requestedPath);

        new Thread(new Runnable() {
            @Override
            public void run() {
                try {
                    File diagnosticsDir = diagnosticsDir();
                    File wavFile = FileNames.restrictedChild(diagnosticsDir, requestedPath);
                    AudioPlayback.Result result = AudioPlayback.play(wavFile);
                    Log.i(AUDIO_TAG, "R1_AUDIO_PLAYBACK_COMPLETE nonce=" + nonce
                            + " path=" + wavFile.getAbsolutePath()
                            + " pcm_bytes=" + result.pcmBytes
                            + " elapsed_ms=" + result.elapsedMillis);
                    setStatus("Played " + wavFile.getName());
                } catch (Exception e) {
                    Log.e(AUDIO_TAG, "R1_AUDIO_PLAYBACK_FAILED nonce=" + nonce
                            + " error=" + e.getClass().getSimpleName()
                            + " message=" + safeMessage(e), e);
                    setStatus("Playback failed: " + safeMessage(e));
                } finally {
                    AUDIO_BUSY.set(false);
                }
            }
        }, "r1-audio-playback").start();
    }

    private File diagnosticsDir() throws InterruptedException {
        File external = getExternalFilesDir(null);
        if (external == null) {
            throw new IllegalStateException("external_files_unavailable");
        }
        File diagnostics = new File(external, "diagnostics");
        for (int attempt = 0; attempt < 20; attempt++) {
            if (diagnostics.isDirectory()) {
                return diagnostics;
            }
            diagnostics.mkdirs();
            if (diagnostics.isDirectory()) {
                return diagnostics;
            }
            Thread.sleep(50L);
        }
        throw new IllegalStateException("cannot_create_diagnostics_dir_" + external.getAbsolutePath());
    }

    private void setStatus(final String text) {
        runOnUiThread(new Runnable() {
            @Override
            public void run() {
                statusView.setText(text);
            }
        });
    }

    private static int clamp(int value, int minimum, int maximum) {
        return Math.max(minimum, Math.min(maximum, value));
    }

    private static String safeMessage(Throwable exception) {
        String message = exception.getMessage();
        return message == null ? "none" : message.replace(' ', '_');
    }

    private static String safeValue(String value) {
        if (value == null || value.length() == 0) {
            return "unknown";
        }
        return value.replace('\n', '_').replace('\r', '_').replace(' ', '_');
    }
}
