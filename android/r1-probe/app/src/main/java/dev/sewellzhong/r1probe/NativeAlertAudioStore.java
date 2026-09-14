package dev.sewellzhong.r1probe;

import android.content.Context;
import android.system.ErrnoException;
import android.system.Os;
import android.util.Base64;
import dev.sewellzhong.r1probe.esphome.NativeAlarmController;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.RandomAccessFile;
import java.security.MessageDigest;
import java.util.Arrays;
import org.json.JSONArray;
import org.json.JSONObject;

/** App-private, hash-bound alert audio. Uploads arrive only through authenticated Native API. */
public final class NativeAlertAudioStore {
    static final int MAX_BYTES = 16 * 1024 * 1024;
    static final int MAX_TOTAL_BYTES = 64 * 1024 * 1024;
    static final int MAX_ITEMS = 64;
    static final int MAX_CHUNK_BYTES = 24 * 1024;
    private final File root;
    private Upload upload;

    static final class Audio {
        final File file;
        final long dataOffset;
        final int dataBytes;
        Audio(File file, long dataOffset, int dataBytes) {
            this.file = file; this.dataOffset = dataOffset; this.dataBytes = dataBytes;
        }
    }
    private static final class Upload {
        final String id;
        final int size;
        final String sha256;
        final File part;
        int received;
        Upload(String id, int size, String sha256, File part) {
            this.id = id; this.size = size; this.sha256 = sha256; this.part = part;
        }
    }

    public NativeAlertAudioStore(Context context) {
        this(new File(context.getFilesDir(), "alert-audio"));
    }
    NativeAlertAudioStore(File root) {
        this.root = root;
        if ((!root.isDirectory() && !root.mkdirs()) || !root.isDirectory())
            throw new IllegalStateException("alert_audio_directory_failed");
        File[] files = root.listFiles();
        if (files != null) for (File item : files) {
            if (item.isFile() && item.getName().endsWith(".part") && !item.delete())
                throw new IllegalStateException("alert_audio_stale_upload");
        }
    }

    public synchronized JSONObject operation(JSONObject request, NativeSettings settings,
            NativeAlarmController alarms) throws Exception {
        String operation = request.getString("operation");
        if ("status".equals(operation)) return status(settings);
        if ("begin".equals(operation)) {
            begin(request.getString("id"), request.getInt("size"), request.getString("sha256"));
        } else if ("chunk".equals(operation)) {
            chunk(request.getString("id"), request.getInt("offset"), request.getString("data"));
        } else if ("commit".equals(operation)) {
            commit(request.getString("id"));
        } else if ("abort".equals(operation)) {
            abort(request.optString("id", ""));
        } else if ("delete".equals(operation)) {
            delete(request.getString("id"), settings, alarms);
        } else if ("timer_bind".equals(operation)) {
            bindTimer(request.optString("id", ""), settings);
        } else throw new IOException("alert_audio_operation_invalid");
        return status(settings).put("operation", operation);
    }

    private void begin(String id, int size, String sha256) throws IOException {
        id = checkedId(id);
        if (upload != null) throw new IOException("alert_audio_upload_busy");
        if (size < 44 || size > MAX_BYTES || !sha256.matches("[a-f0-9]{64}"))
            throw new IOException("alert_audio_manifest_invalid");
        File[] existing = root.listFiles(); long total = 0; int items = 0;
        if (existing != null) for (File item : existing) if (item.isFile() && item.getName().endsWith(".wav")) {
            if (!item.getName().equals(id + ".wav")) total += item.length();
            items++;
        }
        if (total + size > MAX_TOTAL_BYTES || items >= MAX_ITEMS && !file(id + ".wav").isFile())
            throw new IOException("alert_audio_capacity_exceeded");
        File part = file(id + ".part");
        if (part.exists() && !part.delete()) throw new IOException("alert_audio_stale_upload");
        if (!part.createNewFile()) throw new IOException("alert_audio_upload_create_failed");
        upload = new Upload(id, size, sha256, part);
    }

    private void chunk(String id, int offset, String encoded) throws IOException {
        Upload current = upload;
        if (current == null || !current.id.equals(checkedId(id)) || offset != current.received)
            throw new IOException("alert_audio_chunk_order_invalid");
        byte[] bytes;
        try { bytes = Base64.decode(encoded, Base64.NO_WRAP); }
        catch (IllegalArgumentException error) { throw new IOException("alert_audio_chunk_invalid"); }
        if (bytes.length == 0 || bytes.length > MAX_CHUNK_BYTES
                || current.received + bytes.length > current.size)
            throw new IOException("alert_audio_chunk_invalid");
        try (FileOutputStream output = new FileOutputStream(current.part, true)) {
            output.write(bytes); output.getFD().sync();
        } finally { Arrays.fill(bytes, (byte) 0); }
        current.received += bytes.length;
    }

    private void commit(String id) throws Exception {
        Upload current = upload;
        if (current == null || !current.id.equals(checkedId(id)) || current.received != current.size)
            throw new IOException("alert_audio_upload_incomplete");
        if (!current.sha256.equals(sha256(current.part)))
            throw new IOException("alert_audio_hash_mismatch");
        parse(current.part);
        File target = file(current.id + ".wav");
        try { Os.rename(current.part.getAbsolutePath(), target.getAbsolutePath()); }
        catch (ErrnoException error) { throw new IOException("alert_audio_commit_failed", error); }
        upload = null;
    }

    private void abort(String id) throws IOException {
        if (upload == null) return;
        if (!id.isEmpty() && !upload.id.equals(checkedId(id)))
            throw new IOException("alert_audio_upload_mismatch");
        if (upload.part.exists() && !upload.part.delete()) throw new IOException("alert_audio_abort_failed");
        upload = null;
    }

    private void delete(String id, NativeSettings settings, NativeAlarmController alarms) throws IOException {
        id = checkedId(id);
        if (id.equals(settings.timerSoundId()) || alarms != null && alarms.usesSoundId(id))
            throw new IOException("alert_audio_in_use");
        File target = file(id + ".wav");
        if (!target.isFile()) throw new IOException("alert_audio_not_found");
        if (!target.delete()) throw new IOException("alert_audio_delete_failed");
    }

    private void bindTimer(String id, NativeSettings settings) throws IOException {
        if (!id.isEmpty() && resolve(checkedId(id)) == null) throw new IOException("alert_audio_not_found");
        settings.setting("timer_sound_id", id);
    }

    public synchronized Audio resolve(String id) {
        if (id == null || id.isEmpty()) return null;
        try {
            File target = file(checkedId(id) + ".wav");
            return target.isFile() ? parse(target) : null;
        } catch (Exception ignored) { return null; }
    }

    private JSONObject status(NativeSettings settings) throws Exception {
        JSONArray values = new JSONArray();
        File[] files = root.listFiles();
        if (files != null) for (File item : files) {
            String name = item.getName();
            if (!name.endsWith(".wav") || !item.isFile()) continue;
            String id = name.substring(0, name.length() - 4);
            try { checkedId(id); parse(item); }
            catch (Exception ignored) { continue; }
            values.put(new JSONObject().put("id", id).put("size", item.length())
                    .put("sha256", sha256(item)));
        }
        return new JSONObject().put("schema", 1).put("items", values)
                .put("timer_sound_id", settings.timerSoundId())
                .put("upload_active", upload != null)
                .put("upload_id", upload == null ? "" : upload.id)
                .put("upload_received", upload == null ? 0 : upload.received);
    }

    private File file(String name) throws IOException {
        File result = new File(root, name);
        if (!root.getCanonicalFile().equals(result.getCanonicalFile().getParentFile()))
            throw new IOException("alert_audio_path_invalid");
        return result;
    }

    static Audio parse(File file) throws IOException {
        if (!file.isFile() || file.length() < 44 || file.length() > MAX_BYTES)
            throw new IOException("alert_audio_file_invalid");
        try (RandomAccessFile input = new RandomAccessFile(file, "r")) {
            if (input.readInt() != 0x52494646) throw new IOException("alert_audio_not_riff");
            long riffSize = readLe32(input);
            if (riffSize + 8 != input.length() || input.readInt() != 0x57415645)
                throw new IOException("alert_audio_wave_invalid");
            boolean format = false;
            while (input.getFilePointer() + 8 <= input.length()) {
                int kind = input.readInt(); long size = readLe32(input);
                long start = input.getFilePointer();
                if (size < 0 || start + size > input.length()) throw new IOException("alert_audio_chunk_invalid");
                if (kind == 0x666d7420) {
                    if (size < 16 || readLe16(input) != 1 || readLe16(input) != 1
                            || readLe32(input) != 16000 || readLe32(input) != 32000
                            || readLe16(input) != 2 || readLe16(input) != 16)
                        throw new IOException("alert_audio_format_invalid");
                    format = true;
                } else if (kind == 0x64617461) {
                    if (!format || size <= 0 || (size & 1) != 0 || size > Integer.MAX_VALUE)
                        throw new IOException("alert_audio_data_invalid");
                    return new Audio(file, start, (int) size);
                }
                input.seek(start + size + (size & 1));
            }
        }
        throw new IOException("alert_audio_data_missing");
    }

    private static int readLe16(RandomAccessFile input) throws IOException {
        return Short.reverseBytes(input.readShort()) & 0xffff;
    }
    private static long readLe32(RandomAccessFile input) throws IOException {
        return Integer.reverseBytes(input.readInt()) & 0xffffffffL;
    }
    private static String checkedId(String id) throws IOException {
        if (id == null || !id.matches("[a-z0-9][a-z0-9_-]{0,63}"))
            throw new IOException("alert_audio_id_invalid");
        return id;
    }
    private static String sha256(File file) throws Exception {
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        byte[] buffer = new byte[8192];
        try (FileInputStream input = new FileInputStream(file)) {
            for (int count; (count = input.read(buffer)) >= 0;) if (count > 0) digest.update(buffer, 0, count);
        } finally { Arrays.fill(buffer, (byte) 0); }
        StringBuilder value = new StringBuilder();
        for (byte item : digest.digest()) value.append(String.format(java.util.Locale.ROOT, "%02x", item & 255));
        return value.toString();
    }
}
