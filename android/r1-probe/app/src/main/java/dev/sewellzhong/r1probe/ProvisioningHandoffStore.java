package dev.sewellzhong.r1probe;

import android.content.Context;
import android.content.SharedPreferences;
import android.security.KeyPairGeneratorSpec;
import android.util.Base64;
import java.math.BigInteger;
import java.nio.charset.StandardCharsets;
import java.security.KeyPairGenerator;
import java.security.KeyStore;
import java.security.cert.Certificate;
import java.util.Arrays;
import java.util.Calendar;
import javax.crypto.Cipher;
import javax.security.auth.x500.X500Principal;
import org.json.JSONObject;

/** Device-bound, short-lived credential handoff across the AP-to-station transition. */
final class ProvisioningHandoffStore {
    private static final String KEYSTORE = "AndroidKeyStore";
    private static final String ALIAS = "r1-provisioning-handoff";
    private static final String VALUE = "encrypted_wifi_request";
    private final Context context;
    private final SharedPreferences prefs;

    ProvisioningHandoffStore(Context context) {
        this.context = context.getApplicationContext();
        prefs = this.context.getSharedPreferences("provisioning-handoff", Context.MODE_PRIVATE);
    }

    synchronized void save(JSONObject request) throws Exception {
        byte[] plain = request.toString().getBytes(StandardCharsets.UTF_8);
        try {
            if (plain.length > 220) throw new IllegalArgumentException("wifi_request_too_large");
            KeyStore store = store();
            ensureKey(store);
            Certificate certificate = store.getCertificate(ALIAS);
            if (certificate == null) throw new IllegalStateException("handoff_key_unavailable");
            Cipher cipher = Cipher.getInstance("RSA/ECB/PKCS1Padding");
            cipher.init(Cipher.ENCRYPT_MODE, certificate.getPublicKey());
            String encoded = Base64.encodeToString(cipher.doFinal(plain), Base64.NO_WRAP);
            if (!prefs.edit().putString(VALUE, encoded).commit())
                throw new IllegalStateException("handoff_write_failed");
        } finally {
            Arrays.fill(plain, (byte) 0);
        }
    }

    synchronized JSONObject load() throws Exception {
        String encoded = prefs.getString(VALUE, null);
        if (encoded == null) throw new IllegalStateException("handoff_missing");
        java.security.Key key = store().getKey(ALIAS, null);
        if (key == null) throw new IllegalStateException("handoff_key_unavailable");
        byte[] plain = null;
        try {
            Cipher cipher = Cipher.getInstance("RSA/ECB/PKCS1Padding");
            cipher.init(Cipher.DECRYPT_MODE, key);
            plain = cipher.doFinal(Base64.decode(encoded, Base64.NO_WRAP));
            return new JSONObject(new String(plain, StandardCharsets.UTF_8));
        } finally {
            if (plain != null) Arrays.fill(plain, (byte) 0);
        }
    }

    synchronized boolean present() { return prefs.contains(VALUE); }

    synchronized void clear() {
        if (!prefs.edit().remove(VALUE).commit())
            throw new IllegalStateException("handoff_clear_failed");
    }

    private KeyStore store() throws Exception {
        KeyStore store = KeyStore.getInstance(KEYSTORE);
        store.load(null);
        return store;
    }

    @SuppressWarnings("deprecation")
    private void ensureKey(KeyStore store) throws Exception {
        if (store.containsAlias(ALIAS)) return;
        Calendar start = Calendar.getInstance();
        Calendar end = Calendar.getInstance();
        end.add(Calendar.YEAR, 20);
        KeyPairGeneratorSpec spec = new KeyPairGeneratorSpec.Builder(context)
                .setAlias(ALIAS)
                .setSubject(new X500Principal("CN=R1 provisioning handoff"))
                .setSerialNumber(BigInteger.ONE)
                .setStartDate(start.getTime())
                .setEndDate(end.getTime())
                .build();
        KeyPairGenerator generator = KeyPairGenerator.getInstance("RSA", KEYSTORE);
        generator.initialize(spec);
        generator.generateKeyPair();
    }
}
