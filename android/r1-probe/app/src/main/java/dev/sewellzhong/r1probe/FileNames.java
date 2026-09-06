package dev.sewellzhong.r1probe;

import java.io.File;
import java.io.IOException;

final class FileNames {
    private FileNames() {
    }

    static String sanitize(String value) {
        if (value == null || value.length() == 0) {
            return "sample";
        }
        String cleaned = value.replaceAll("[^A-Za-z0-9._-]", "_");
        return cleaned.length() > 64 ? cleaned.substring(0, 64) : cleaned;
    }

    static File restrictedChild(File parent, String requestedPath) throws IOException {
        if (requestedPath == null) {
            throw new IllegalArgumentException("missing_file_path");
        }
        File parentCanonical = parent.getCanonicalFile();
        File requestedCanonical = new File(requestedPath).getCanonicalFile();
        String prefix = parentCanonical.getPath() + File.separator;
        if (!requestedCanonical.getPath().startsWith(prefix)) {
            throw new SecurityException("playback_path_outside_diagnostics");
        }
        if (!requestedCanonical.isFile()) {
            throw new IllegalArgumentException("playback_file_missing");
        }
        return requestedCanonical;
    }
}
