package dev.sewellzhong.r1probe;

final class ProbeInfo {
    private ProbeInfo() {
    }

    static String format(String model, int sdk, String abi, String fingerprint) {
        return "R1 install probe\n"
                + "model=" + model + "\n"
                + "sdk=" + sdk + "\n"
                + "abi=" + abi + "\n"
                + "fingerprint=" + fingerprint;
    }
}

