"""Small, anchored Chinese grammar for source-bound speaker settings."""
from dataclasses import dataclass
import re
import unicodedata
from .volume import percentage

@dataclass(frozen=True)
class Control:
    target: str | None
    operation: str
    value: float | str = 0


def normalize(text):
    text = unicodedata.normalize('NFKC', text).lower()
    text = ''.join(c for c in text if not c.isspace() and c not in '，。！？!?')
    return re.sub(r'^(?:(?:请|帮我|麻烦)(?:你)?)+', '', text)


def numeric(value):
    if re.fullmatch(r'\d+(?:\.\d+)?', value): return float(value)
    if '点' in value:
        a, b = value.split('点', 1)
        digits = '零一二三四五六七八九'
        head = percentage(a)
        if head is not None and b and all(c in digits for c in b):
            return float(str(head) + '.' + ''.join(str(digits.index(c)) for c in b))
        return None
    if value.startswith('一百') and len(value) > 2:
        rest = value[2:].removeprefix('零')
        tail = percentage(rest)
        return 100 + tail if tail is not None else None
    return percentage(value)



_WAIT_INITIAL = r'(?:首次唤醒|第一次唤醒|唤醒|叫醒你|叫醒|首次|第一次)'
_WAIT_FOLLOWUP = r'(?:持续对话|连续对话|多轮对话|继续对话|续听)'
_WAIT_LABEL = r'(?:等待开口时间|开口等待时间|等待时间|等待时长|等待开口|开口等待|等待|时间|等我|等)'
_NUMBER = r'[0-9.零一二三四五六七八九十百点]+'


def parse_wait(text):
    restore = text.startswith('恢复')
    if restore: text = text[2:]
    m = re.match('^(' + _WAIT_INITIAL + '|' + _WAIT_FOLLOWUP + r')(?:的时候|之后|以后|后|时|中)?(?:的)?(?:会)?', text)
    if m:
        target = 'wait_seconds' if re.fullmatch(_WAIT_INITIAL,m[1]) else 'followup_wait_seconds'
        rest = text[m.end():]
        rest = re.sub('^' + _WAIT_LABEL, '', rest)
    else:
        m = re.match('^' + _WAIT_LABEL, text)
        if not m: return None
        target='wait_choice';rest=text[m.end():]
    if restore and rest in ('默认','默认值','默认设置','的默认值','的默认设置'):
        return Control(target,'default')
    if rest in ('恢复默认','恢复默认值','恢复默认设置'):
        return Control(target,'default')
    if re.fullmatch(r'(?:是)?(?:多少(?:秒)?|多久|多长(?:时间)?)',rest):
        return Control(target,'query')
    m=re.fullmatch(r'(?:设置为|设为|调到|调成|设置到|调节到|调整到|改成|改为|设置成)?('+_NUMBER+r')(?:秒钟|秒|s)',rest)
    if m and (value:=numeric(m[1])) is not None: return Control(target,'seconds',value)
    m=re.fullmatch(r'(增加|延长|缩短|减少|多等我|少等我|多等|少等)('+_NUMBER+r')(?:秒钟|秒|s)',rest)
    if m and (value:=numeric(m[2])) is not None:
        return Control(target,'relative',value if m[1] in ('增加','延长','多等我','多等') else -value)
    m=re.fullmatch(r'(长|短|延长|缩短|多等我|少等我|多等|少等)(?:一点|点|一些)',rest)
    if m: return Control(target,'relative',5 if m[1] in ('长','延长','多等我','多等') else -5)
    return None

def parse_control(text):
    text = normalize(text)
    text = re.sub(r'^(?:把|将)?(?:r1(?:音箱)?|你的|本机|这个音箱|音箱)(?:的)?', '', text)
    text = re.sub(r'^(?:把|将)', '', text)
    wait = parse_wait(text)
    if wait: return wait
    match = re.fullmatch(r'计时器(?:的)?铃声(?:设置为|设为|调成|改成)(经典|柔和|紧急)(?:铃声)?', text)
    if match:
        return Control('timer_ringtone', 'choice', {'经典':'classic','柔和':'gentle','紧急':'urgent'}[match[1]])
    if re.fullmatch(r'(?:现在|当前)?计时器(?:的)?铃声(?:是)?(?:什么|哪种)', text):
        return Control('timer_ringtone', 'query')
    match = re.fullmatch(r'计时器(?:铃声)?音量(?:设置为|设为|调到|调成)(?:百分之)?([0-9零一二三四五六七八九十百]+)(?:%|百分比)?', text)
    if match and (value := numeric(match[1])) is not None:
        return Control('timer_volume', 'percent', value)
    if re.fullmatch(r'(?:现在|当前)?计时器(?:铃声)?音量(?:是)?多少', text):
        return Control('timer_volume', 'query')
    if text in ('再长一点','再多等一点'): return Control(None,'repeat_seconds',5)
    if text in ('再短一点','再少等一点'): return Control(None,'repeat_seconds',-5)
    # Only accept the alias when the entire normalized sentence is a speed control.
    if '语数' in text:
        candidate = parse_control(text.replace('语数', '语速'))
        if candidate is not None and candidate.target == 'speech_speed':
            return candidate
    labels = {'音量': 'volume', '声音': 'volume', '语速': 'speech_speed'}
    if text in ('正常语速', '恢复正常语速'): return Control('speech_speed', 'absolute', 1)
    match = re.fullmatch(r'(?:现在|当前)?(音量|声音|语速)(?:是)?多少', text)
    if match: return Control(labels[match[1]], 'query')
    match = re.fullmatch(r'(音量|声音|语速)?(?:设置为|设为|调到|调成|设置到|调节到)(百分之)?([0-9.零一二三四五六七八九十百点]+)(%|百分比|倍)?', text)
    if match:
        value = numeric(match[3])
        if value is None: return None
        target = labels.get(match[1])
        if match[4] == '倍':
            if target == 'volume' or match[2]: return None
            return Control('speech_speed', 'absolute', value)
        # Unbound percentages are resolved only from the conversation setting context.
        return Control(target, 'percent', value)
    match = re.fullmatch(r'(音量|声音)?(?:调)?(大|高|小|低)(?:声)?(?:一点|点|一些)(?:儿)?', text)
    if match: return Control('volume', 'relative', 10 if match[2] in ('大', '高') else -10)
    match = re.fullmatch(r'调(低|高)(?:音量|声音)', text)
    if match: return Control('volume', 'relative', -10 if match[1] == '低' else 10)
    match = re.fullmatch(r'(?:语速|说|说话)(快|慢)(?:一点|点|一些)(?:儿)?', text)
    if not match: match = re.fullmatch(r'(快|慢)点说', text)
    if match: return Control('speech_speed', 'relative', .05 if match[1] == '快' else -.05)
    match = re.fullmatch(r'再(大|小|快|慢)(?:一点|点|一些)', text)
    if match:
        target = 'volume' if match[1] in ('大', '小') else 'speech_speed'
        return Control(target, 'repeat', (10 if target == 'volume' else .05) * (1 if match[1] in ('大','快') else -1))
    return None
