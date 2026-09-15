package dev.sewellzhong.r1probe;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.util.Log;

import java.io.File;
import java.io.PrintWriter;
import java.util.concurrent.atomic.AtomicBoolean;

/** Explicit shell-only offline probe, hosted in a disposable process to contain native failures. */
public final class VendorAecProbeReceiver extends BroadcastReceiver {
    private static final String TAG = "R1VendorAec";
    private static final String ACTION = "vendor_aec_offline";
    private static final AtomicBoolean BUSY = new AtomicBoolean(false);

    @Override public void onReceive(final Context context, final Intent intent) {
        final String nonce = value(intent.getStringExtra("probe_nonce"), "manual");
        if (!ACTION.equals(intent.getStringExtra("probe_action"))) {
            Log.e(TAG, "R1_VENDOR_AEC_REJECTED nonce=" + nonce + " error=unsupported_action");
            return;
        }
        if (!BUSY.compareAndSet(false, true)) {
            Log.e(TAG, "R1_VENDOR_AEC_FAILED nonce=" + nonce + " error=probe_busy");
            return;
        }
        final PendingResult pending = goAsync();
        new Thread(new Runnable() {
            @Override public void run() {
                try {
                    runProbe(context, intent, nonce);
                } catch (Throwable error) {
                    Log.e(TAG, "R1_VENDOR_AEC_FAILED nonce=" + nonce
                            + " error=" + error.getClass().getSimpleName()
                            + " message=" + safe(error), error);
                } finally {
                    BUSY.set(false);
                    pending.finish();
                }
            }
        }, "r1-vendor-aec-offline").start();
    }

    private static void runProbe(Context context, Intent intent, String nonce) throws Exception {
        File diagnostics = diagnosticsDir(context);
        File microphone = FileNames.restrictedChild(diagnostics,
                intent.getStringExtra("microphone_path"));
        File reference = FileNames.restrictedChild(diagnostics,
                intent.getStringExtra("reference_path"));
        int offset = intent.getIntExtra("reference_offset_samples", 0);
        String sampleId = FileNames.sanitize(intent.getStringExtra("sample_id"));
        File output = new File(diagnostics,
                System.currentTimeMillis() + "-vendor-aec-" + sampleId + ".wav");
        File metadata = new File(output.getAbsolutePath() + ".meta.txt");
        Log.i(TAG, "R1_VENDOR_AEC_START nonce=" + nonce
                + " reference_offset_samples=" + offset);
        VendorAecOfflineProcessor.Result result = VendorAecOfflineProcessor.process(
                microphone, reference, output, offset);
        PrintWriter writer = new PrintWriter(metadata, "UTF-8");
        try {
            writer.println("purpose=bounded offline original firmware AEC diagnostic");
            writer.println("production_capture=false");
            writer.println("library_source=/system/lib/libaec.so");
            writer.println("abi=com.unisound.jni.AEC");
            writer.println("format=PCM_S16LE_16000Hz_mono");
            writer.println("constructor=16000,1");
            writer.println("options=0:600,2:1,3:0");
            writer.println("input_layout=interleaved_mic_then_echo");
            writer.println("process_second_argument=null");
            writer.println("option_0_result=" + result.option0Result);
            writer.println("option_2_result=" + result.option2Result);
            writer.println("option_3_result=" + result.option3Result);
            writer.println("chunk_bytes=" + VendorAecOfflineProcessor.CHUNK_BYTES);
            writer.println("microphone_bytes=" + result.microphoneBytes);
            writer.println("reference_bytes=" + result.referenceBytes);
            writer.println("output_bytes=" + result.outputBytes);
            writer.println("chunks=" + result.chunks);
            writer.println("reference_offset_samples=" + result.referenceOffsetSamples);
            writer.println("elapsed_nanos=" + result.elapsedNanos);
        } finally {
            writer.close();
        }
        Log.i(TAG, "R1_VENDOR_AEC_COMPLETE nonce=" + nonce
                + " output_path=" + output.getAbsolutePath()
                + " metadata_path=" + metadata.getAbsolutePath()
                + " microphone_bytes=" + result.microphoneBytes
                + " reference_bytes=" + result.referenceBytes
                + " output_bytes=" + result.outputBytes
                + " chunks=" + result.chunks
                + " option_0_result=" + result.option0Result
                + " option_2_result=" + result.option2Result
                + " option_3_result=" + result.option3Result
                + " elapsed_nanos=" + result.elapsedNanos);
    }

    private static File diagnosticsDir(Context context) {
        File external = context.getExternalFilesDir(null);
        if (external == null) throw new IllegalStateException("external_files_unavailable");
        File diagnostics = new File(external, "diagnostics");
        if (!diagnostics.isDirectory() && !diagnostics.mkdirs() && !diagnostics.isDirectory()) {
            throw new IllegalStateException("cannot_create_diagnostics_dir");
        }
        return diagnostics;
    }

    private static String value(String value, String fallback) {
        return value == null ? fallback : value;
    }

    private static String safe(Throwable error) {
        String message = error.getMessage();
        return message == null ? "none" : message.replace(' ', '_');
    }
}
