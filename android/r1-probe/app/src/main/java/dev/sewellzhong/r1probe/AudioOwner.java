package dev.sewellzhong.r1probe;

/** Process-wide exclusion for the two satellite runtimes. */
final class AudioOwner {
    private static Object owner;
    static synchronized boolean acquire(Object candidate) {
        if (owner != null && owner != candidate) return false;
        owner = candidate;
        return true;
    }
    static synchronized void release(Object candidate) { if (owner == candidate) owner = null; }
}
