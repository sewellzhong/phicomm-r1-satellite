"""Context-free pre-intent rules. Never infer missing VAD or conversation context."""
import re
import unicodedata

_MARKERS = re.compile(
    r"(?:\[(?:blank_audio|no speech|silence|music|noise|applause|inaudible|静音|无语音|音乐|噪音|掌声)\]"
    r"|【(?:静音|无语音|音乐|噪音|掌声)】|\((?:silence|music|noise|静音|音乐|噪音)\)"
    r"|<\|(?:nospeech|silence)\|>)", re.IGNORECASE
)

def _lexical(text):
    # Match Java Character.isLetterOrDigit: Unicode letters + decimal digits,
    # not all numeric symbols accepted by Python str.isalnum().
    return any(unicodedata.category(c).startswith("L") or unicodedata.category(c) == "Nd" for c in text)

def classify(text, *, native=False):
    """Return a reason only, without storing or logging the transcript."""
    normalized = unicodedata.normalize("NFKC", text or "")
    normalized = "".join(c for c in normalized if unicodedata.category(c) not in ("Cf", "Cc")).strip()
    if not _lexical(normalized):
        return "empty"
    remainder, count = _MARKERS.subn("", normalized)
    if count and all(c.isspace() or unicodedata.category(c).startswith("P") for c in remainder):
        return "non_speech_marker"
    key = "".join(c for c in normalized.casefold() if c.isalnum())
    if native and key in {"alexa", "奥ex斯", "欧ex萨"}:
        return "wake_only"
    return "accepted"
