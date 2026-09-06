"""Deterministic commands for this satellite only; no LLM tool permissions expanded."""
import re
import unicodedata


def percentage(text):
    if text.isdecimal(): return int(text)
    digits = dict(zip('零一二三四五六七八九', range(10)))
    if text in ('一百', '百'): return 100
    if '十' in text:
        a, b = text.split('十', 1)
        if (not a or a in digits) and (not b or b in digits):
            return (digits[a] if a else 1) * 10 + (digits[b] if b else 0)
    return digits.get(text)


def parse_volume(text):
    text = unicodedata.normalize('NFKC', text).lower()
    text = ''.join(c for c in text if not c.isspace() and c not in '，。！？!?')
    prefix = r'(?:请|帮我|麻烦)?(?:把|将)?(?:r1(?:音箱)?|你的|本机|这个音箱|音箱)?(?:的)?'
    m = re.fullmatch(prefix + r'(?:音量|声音)(?:设置为|设为|调到|调成|设置到)(?:百分之)?([0-9零一二三四五六七八九十百]+)(?:%|百分比)?', text)
    if m:
        value = percentage(m[1])
        return ('absolute', value) if value is not None and 0 <= value <= 100 else None
    m = re.fullmatch(prefix + r'(?:音量|声音)?(?:调)?(大|高|小|低)(?:声)?(?:一点|点|一些)(?:儿)?', text)
    if m: return ('relative', 10 if m[1] in ('大', '高') else -10)
    return None
