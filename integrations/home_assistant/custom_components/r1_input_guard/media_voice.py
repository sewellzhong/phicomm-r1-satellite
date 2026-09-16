"""Source-bound media voice commands that do not require a household target."""
import re
import unicodedata

_STOP_MEDIA = {"停止播放", "取消播放", "停止音乐", "取消音乐", "停止媒体", "取消媒体"}
_STOP_CURRENT = {"停止当前设备", "关闭当前设备", "取消当前设备", "停止这台设备", "关闭这台设备", "取消这台设备"}


def is_stop_media(text):
    value = unicodedata.normalize("NFKC", text or "").casefold()
    value = re.sub(r"[\s，。！？、,.!?]", "", value)
    return value in _STOP_MEDIA


def is_stop_current(text):
    value = unicodedata.normalize("NFKC", text or "").casefold()
    value = re.sub(r"[\s，。！？、,.!?]", "", value)
    return value in _STOP_CURRENT


def parse_explicit_target_stop(text):
    value = unicodedata.normalize("NFKC", text or "").casefold()
    value = re.sub(r"[\s，。！？、,.!?]", "", value)
    match = re.fullmatch(r"(停止|关闭|取消)(.+)", value)
    if not match or match[2] in _STOP_CURRENT or match[2] in _STOP_MEDIA:
        return None
    target = match[2]
    # Bare schedule commands stay with the alarm/timer grammar.  A
    # device-qualified form (for example “取消客厅音箱的闹钟”) is an active
    # action on that device and is handled by the device stop path.
    device_qualifier = ("客厅", "卧室", "厨房", "餐厅", "书房", "阳台", "卫生间",
                        "音箱", "卫星", "电视", "设备", "床帘", "晾衣架", "窗帘")
    schedule_words = ("闹钟", "定时器", "计时器", "定时提示")
    if (target in schedule_words
            or any(token in target for token in ("今天", "明天", "后天", "我的闹钟"))
            or any(token in target for token in schedule_words)
            and not any(token in target for token in device_qualifier)):
        return None
    return {"operation": "close" if match[1] == "关闭" else "stop", "target": target}
