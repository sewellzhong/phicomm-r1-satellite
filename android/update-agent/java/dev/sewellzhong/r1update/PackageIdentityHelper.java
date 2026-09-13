package dev.sewellzhong.r1update;

import android.content.pm.ApplicationInfo;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.content.pm.Signature;
import android.os.IBinder;

import java.io.File;
import java.io.FileInputStream;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.security.MessageDigest;

/** Fixed app_process helper used only by the independent root supervisor. */
public final class PackageIdentityHelper {
    private static final String PACKAGE = "dev.sewellzhong.r1probe";
    private static final long MIN_APK = 4096L;
    private static final long MAX_APK = 64L * 1024L * 1024L;

    private PackageIdentityHelper() {}

    private static PackageInfo installedPackage() throws Exception {
        Class<?> serviceManager = Class.forName("android.os.ServiceManager");
        Method getService = serviceManager.getDeclaredMethod("getService", String.class);
        getService.setAccessible(true);
        IBinder binder = (IBinder) getService.invoke(null, "package");
        if (binder == null) throw new IllegalStateException("package_service_missing");
        Class<?> stub = Class.forName("android.content.pm.IPackageManager$Stub");
        Method asInterface = stub.getDeclaredMethod("asInterface", IBinder.class);
        asInterface.setAccessible(true);
        Object manager = asInterface.invoke(null, binder);
        Method getPackageInfo = manager.getClass().getMethod(
                "getPackageInfo", String.class, int.class, int.class);
        getPackageInfo.setAccessible(true);
        return (PackageInfo) getPackageInfo.invoke(
                manager, PACKAGE, PackageManager.GET_SIGNATURES, 0);
    }

    private static PackageInfo archivePackage(File file) throws Exception {
        Class<?> parserClass = Class.forName("android.content.pm.PackageParser");
        Object parser = parserClass.getConstructor().newInstance();
        Method parsePackage = parserClass.getDeclaredMethod(
                "parsePackage", File.class, int.class);
        parsePackage.setAccessible(true);
        Object parsed = parsePackage.invoke(parser, file, 0);
        if (parsed == null) throw new IllegalArgumentException("archive_parse_failed");
        Method collectCertificates = parserClass.getDeclaredMethod(
                "collectCertificates", parsed.getClass(), int.class);
        collectCertificates.setAccessible(true);
        collectCertificates.invoke(parser, parsed, 0);

        Field packageName = parsed.getClass().getField("packageName");
        Field versionCode = parsed.getClass().getField("mVersionCode");
        Field signatures = parsed.getClass().getField("mSignatures");
        PackageInfo result = new PackageInfo();
        result.packageName = (String) packageName.get(parsed);
        result.versionCode = versionCode.getInt(parsed);
        result.signatures = (Signature[]) signatures.get(parsed);
        result.applicationInfo = new ApplicationInfo();
        result.applicationInfo.sourceDir = file.getPath();
        return result;
    }

    private static String hex(byte[] value) {
        char[] digits = "0123456789abcdef".toCharArray();
        char[] output = new char[value.length * 2];
        for (int i = 0; i < value.length; ++i) {
            output[i * 2] = digits[(value[i] >>> 4) & 15];
            output[i * 2 + 1] = digits[value[i] & 15];
        }
        return new String(output);
    }

    private static String digestFile(File file) throws Exception {
        long size = file.length();
        if (!file.isFile() || size < MIN_APK || size > MAX_APK) {
            throw new IllegalArgumentException("archive_size_invalid");
        }
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        FileInputStream input = new FileInputStream(file);
        try {
            byte[] buffer = new byte[16384];
            int count;
            while ((count = input.read(buffer)) != -1) {
                digest.update(buffer, 0, count);
            }
        } finally {
            input.close();
        }
        return hex(digest.digest());
    }

    private static void emit(PackageInfo info, String path) throws Exception {
        if (info == null || !PACKAGE.equals(info.packageName) || info.versionCode <= 0) {
            throw new IllegalArgumentException("package_identity_invalid");
        }
        Signature[] signatures = info.signatures;
        if (signatures == null || signatures.length != 1) {
            throw new IllegalArgumentException("package_signer_count_invalid");
        }
        File file = new File(path);
        if (!file.getCanonicalPath().equals(path)) {
            throw new IllegalArgumentException("package_path_not_canonical");
        }
        MessageDigest signer = MessageDigest.getInstance("SHA-256");
        System.out.println("R1_PACKAGE_IDENTITY_V1");
        System.out.println("package_name=" + info.packageName);
        System.out.println("version=" + info.versionCode);
        System.out.println("apk_path=" + path);
        System.out.println("apk_sha256=" + digestFile(file));
        System.out.println("signer_sha256=" + hex(signer.digest(signatures[0].toByteArray())));
    }

    public static void main(String[] args) {
        try {
            if (args.length != 2) throw new IllegalArgumentException("arguments_invalid");
            PackageInfo info;
            String path;
            if ("installed".equals(args[0]) && PACKAGE.equals(args[1])) {
                info = installedPackage();
                path = info.applicationInfo.sourceDir;
            } else if ("archive".equals(args[0])) {
                path = new File(args[1]).getCanonicalPath();
                if (!path.equals(args[1])) {
                    throw new IllegalArgumentException("archive_path_not_canonical");
                }
                info = archivePackage(new File(path));
            } else {
                throw new IllegalArgumentException("mode_invalid");
            }
            emit(info, path);
        } catch (Throwable error) {
            System.err.println("R1_PACKAGE_IDENTITY_FAILED:" + error.getClass().getSimpleName());
            System.exit(2);
        }
    }
}
