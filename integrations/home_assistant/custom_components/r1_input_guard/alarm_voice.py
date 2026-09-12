"""Anchored Chinese voice commands for the R1-owned local alarm store."""
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import re
import unicodedata
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from homeassistant.exceptions import HomeAssistantError

from .alarm_pending import editable


_NUMBER = r"[0-9零一二两三四五六七八九十]+"
_PERIOD = r"(?:凌晨|早上|早晨|上午|中午|下午|晚上|晚间)?"
_TIME = rf"{_PERIOD}(?:{_NUMBER}(?:点|时)(?:半|{_NUMBER}(?:分)?)?|[0-2]?\d[:：][0-5]\d)"
_DAY_NAMES = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}


@dataclass(frozen=True)
class AlarmVoiceCommand:
    operation: str
    name: str = ""
    hour: int | None = None
    minute: int | None = None
    date_value: str | None = None
    weekdays: int | None = None
    enabled: bool | None = None
    issue: str | None = None


def alarm_local_date(owner, now=None):
    """Resolve relative dates in the device-reported zone, not the HA host zone."""
    state = getattr(owner, 'alarm_state', None) or {}
    zone_name = state.get('time_zone', 'UTC')
    try:
        zone = alarm_time_zone(zone_name)
    except (TypeError, ValueError, ZoneInfoNotFoundError):
        zone = timezone.utc
    instant = now or datetime.now(timezone.utc)
    return instant.astimezone(zone).date()


def alarm_time_zone(zone_name):
    """Accept IANA zones and the fixed GMT offsets Android may report."""
    match = re.fullmatch(r"GMT([+-])(\d{1,2}):?(\d{2})", zone_name or "")
    if match:
        hours, minutes = int(match[2]), int(match[3])
        if hours > 18 or minutes > 59 or hours == 18 and minutes:
            raise ValueError("alarm_time_zone_invalid")
        offset = timedelta(hours=hours, minutes=minutes)
        return timezone(offset if match[1] == '+' else -offset, zone_name)
    return ZoneInfo(zone_name)


def _normalize(text):
    value = unicodedata.normalize("NFKC", text).lower()
    value = "".join(char for char in value if not char.isspace() and char not in "，。！？!?")
    return re.sub(r"^(?:(?:请|帮我|麻烦)(?:你)?)+", "", value)


def _integer(value):
    if value.isdecimal():
        return int(value)
    digits = {char: index for index, char in enumerate("零一二三四五六七八九")}
    value = value.replace("两", "二")
    if all(char in digits for char in value):
        return int("".join(str(digits[char]) for char in value))
    if "十" in value and value.count("十") == 1:
        head, tail = value.split("十")
        if (not head or head in digits) and (not tail or tail in digits):
            return (digits[head] if head else 1) * 10 + (digits[tail] if tail else 0)
    return None


def _parse_time(value):
    match = re.fullmatch(rf"({_PERIOD})([0-2]?\d)[:：]([0-5]\d)", value)
    if match:
        period, hour, minute = match[1], int(match[2]), int(match[3])
    else:
        match = re.fullmatch(rf"({_PERIOD})({_NUMBER})(?:点|时)(半|{_NUMBER})?(?:分)?", value)
        if not match:
            return None, None, "time_invalid"
        period, hour = match[1], _integer(match[2])
        minute = 30 if match[3] == "半" else _integer(match[3]) if match[3] else 0
    if hour is None or minute is None or hour > 23 or minute > 59:
        return None, None, "time_invalid"
    if period:
        if hour > 12:
            return None, None, "time_invalid"
        if period == "凌晨":
            hour = 0 if hour == 12 else hour
        elif period in ("中午", "下午", "晚上", "晚间"):
            hour = hour if hour == 12 else hour + 12
    elif hour <= 12:
        return None, None, "meridiem_required"
    return hour, minute, None


def _parse_schedule(body, today):
    schedules = []
    for token, delta in (("今天", 0), ("明天", 1), ("后天", 2)):
        if token in body:
            schedules.append((token, (today + timedelta(days=delta)).isoformat(), 0))
    explicit = re.search(rf"(?:(?P<year>{_NUMBER})年)?(?P<month>{_NUMBER})月(?P<day>{_NUMBER})日", body)
    if explicit:
        year = _integer(explicit['year']) if explicit['year'] else today.year
        month, day = _integer(explicit['month']), _integer(explicit['day'])
        try:
            resolved = date(year, month, day)
            if not explicit['year'] and resolved < today:
                resolved = date(year + 1, month, day)
            schedules.append((explicit.group(0), resolved.isoformat(), 0))
        except (TypeError, ValueError):
            return None, None, None, "date_invalid"
    fixed = (("每天", 127), ("每日", 127), ("工作日", 31), ("周一至周五", 31),
             ("星期一至星期五", 31), ("周末", 96))
    for token, mask in fixed:
        if token in body:
            schedules.append((token, "", mask))
    weekly = re.search(r"(?:每(?:周|星期))((?:[一二三四五六日天](?:、|和|,)?)+)", body)
    if weekly:
        mask = 0
        for day_name in re.findall(r"[一二三四五六日天]", weekly[1]):
            mask |= 1 << _DAY_NAMES[day_name]
        schedules.append((weekly.group(0), "", mask))
    unique = {(item[1], item[2]) for item in schedules}
    if len(unique) > 1:
        return None, None, None, "schedule_ambiguous"
    if not schedules:
        return body, None, None, None
    token, date_value, weekdays = schedules[0]
    return body.replace(token, "", 1), date_value, weekdays, None


def _schedule_and_time(body, today, require_schedule):
    body, date_value, weekdays, issue = _parse_schedule(body, today)
    if issue:
        return "", None, None, None, None, issue
    matches = list(re.finditer(_TIME, body))
    if len(matches) != 1:
        return "", None, None, None, None, "time_required" if not matches else "time_ambiguous"
    hour, minute, issue = _parse_time(matches[0].group(0))
    remainder = body[:matches[0].start()] + body[matches[0].end():]
    if issue:
        return "", None, None, None, None, issue
    if require_schedule and date_value is None and weekdays is None:
        issue = "schedule_required"
    remainder = re.sub(r"^(?:一个|个|的)+|(?:的)+$", "", remainder)
    return remainder, hour, minute, date_value, weekdays, issue


def parse_alarm_voice(text, today=None):
    """Return only fully anchored local-alarm commands; unrelated language stays delegated."""
    text = _normalize(text)
    today = today or date.today()
    match = re.fullmatch(r"(?:取消|删除)(.+?)闹钟", text)
    if match:
        name = match[1].removeprefix("我的")
        return AlarmVoiceCommand("delete", name=name,
                                 issue="batch_unsupported" if name in ("所有", "全部") else None)
    match = re.fullmatch(r"(?:启用|开启|打开)(.+?)闹钟", text)
    if match:
        return AlarmVoiceCommand("enable", name=match[1].removeprefix("我的"), enabled=True)
    match = re.fullmatch(r"(?:停用|禁用|关闭)(.+?)闹钟", text)
    if match:
        return AlarmVoiceCommand("enable", name=match[1].removeprefix("我的"), enabled=False)
    match = re.fullmatch(r"(?:把|将)(.+?)闹钟(?:的时间)?(?:改到|改成|设为|设置为|调到)(.+)", text)
    if match:
        remainder, hour, minute, date_value, weekdays, issue = _schedule_and_time(match[2], today, False)
        if remainder:
            issue = issue or "schedule_invalid"
        return AlarmVoiceCommand("update", name=match[1].removeprefix("我的"), hour=hour,
                                 minute=minute, date_value=date_value, weekdays=weekdays, issue=issue)
    match = re.fullmatch(r"(?:设置|设|创建|添加|加)(?:一个|个)?(.+?)闹钟", text)
    if match:
        remainder, hour, minute, date_value, weekdays, issue = _schedule_and_time(match[1], today, True)
        name = remainder or "闹钟"
        name = name.removesuffix("的")
        return AlarmVoiceCommand("create", name=name, hour=hour, minute=minute,
                                 date_value=date_value, weekdays=weekdays, issue=issue)
    match = re.fullmatch(r"(?:查询|查看|告诉我)?(?:我)?(?:现在)?(?:有)?(?:哪些|几个|多少)?闹钟", text)
    if match:
        return AlarmVoiceCommand("query")
    match = re.fullmatch(r"(?:查询|查看|告诉我)(.+?)闹钟", text)
    if not match:
        match = re.fullmatch(r"(.+?)闹钟(?:是|设在)?(?:几点|什么时候|的时间)", text)
    if match:
        return AlarmVoiceCommand("query", name=match[1].removeprefix("我的"))
    return None


def _effective_alarms(owner):
    alarms = {item['id']: dict(item) for item in (owner.alarm_state or {}).get('alarms', [])}
    pending_states = {}
    for item in owner.alarm_pending.items():
        pending_id = item['id']
        pending_states[pending_id] = item
        if item['desired'] is None:
            alarms.pop(pending_id, None)
        else:
            alarms[pending_id] = dict(item['desired'])
    return list(alarms.values()), pending_states


def _schedule_text(alarm):
    if alarm.get('date'):
        schedule = alarm['date']
    else:
        mask = alarm.get('weekdays', 0)
        schedule = {127: "每天", 31: "工作日", 96: "周末"}.get(mask)
        if schedule is None:
            names = "一二三四五六日"
            schedule = "每周" + "、".join(names[index] for index in range(7) if mask & (1 << index))
    return f"{schedule}{alarm['hour']:02d}:{alarm['minute']:02d}"


def _issue_text(issue):
    return {
        "time_required": "请说明闹钟时间。",
        "time_ambiguous": "只能同时设置一个闹钟时间。",
        "time_invalid": "闹钟时间无效，没有修改。",
        "meridiem_required": "请说明上午或下午，也可以使用二十四小时时间。",
        "schedule_required": "请说明哪一天或重复日期，例如明天或每天。",
        "schedule_ambiguous": "日期和重复规则有冲突，没有修改。",
        "schedule_invalid": "闹钟日期或时间无法确定，没有修改。",
        "date_invalid": "闹钟日期无效，没有修改。",
        "batch_unsupported": "为避免误删，请逐个说出要取消的闹钟名称。",
    }[issue]


async def execute_alarm_voice(owner, command, context=None):
    """Execute against confirmed/pending state and report delivery truthfully."""
    if command.issue:
        return _issue_text(command.issue)
    if owner.alarm_state is None:
        return "暂时没有可用的R1闹钟状态，没有修改。"
    alarms, pending_states = _effective_alarms(owner)
    if command.operation == "query":
        matches = alarms if not command.name else [item for item in alarms if item.get('name') == command.name]
        if not matches:
            cancelled = [item for item in pending_states.values() if item['desired'] is None
                         and (item.get('base') or {}).get('name') == command.name]
            if cancelled:
                return f"名为{command.name}的闹钟正在等待取消同步，尚未送达R1。"
            return "没有找到" + (f"名为{command.name}的" if command.name else "") + "闹钟。"
        details = []
        for item in matches:
            pending = pending_states.get(item['id'])
            status = ("同步冲突" if pending and pending.get('blocked') else
                      "待同步" if item['id'] in pending_states else
                      "已启用" if item.get('enabled') else "已停用")
            details.append(f"{item.get('name') or '未命名闹钟'}，{_schedule_text(item)}，{status}")
        summaries = []
        if pending_states:
            conflicts = sum(bool(item.get('blocked')) for item in pending_states.values())
            summaries.append(f"另有{len(pending_states)}项" + (f"待处理，其中{conflicts}项冲突" if conflicts else "待同步变更"))
        if owner.alarm_sync_status == 'offline':
            summaries.append("设备当前离线，其余是上次确认状态")
        elif owner.alarm_sync_status == 'conflict':
            summaries.append("当前存在同步冲突")
        return "共" + str(len(matches)) + "个：" + "；".join(details) \
            + ("。" + "；".join(summaries) if summaries else "") + "。"
    if command.operation == "create":
        if len(alarms) >= 32:
            return "闹钟已达三十二个上限，没有创建。"
        values = {'id': 'voice-' + uuid4().hex, 'name': command.name,
                  'date': command.date_value or '', 'hour': command.hour, 'minute': command.minute,
                  'weekdays': command.weekdays or 0, 'enabled': True, 'snooze_minutes': 10,
                  'expected_version': owner.alarm_state['version']}
        action = "创建"
    else:
        matches = [item for item in alarms if item.get('name') == command.name]
        if not matches:
            return f"没有找到名为{command.name}的闹钟，没有修改。"
        if len(matches) > 1:
            choices = "、".join(_schedule_text(item) for item in matches[:4])
            return f"找到多个名为{command.name}的闹钟：{choices}。请先在HA中使用唯一名称，没有修改。"
        current = matches[0]
        if command.operation == "delete":
            values = {'id': current['id'], 'expected_version': owner.alarm_state['version']}
            action = "取消"
        elif command.operation == "enable":
            if current.get('enabled') is command.enabled:
                return f"名为{command.name}的闹钟已经{'启用' if command.enabled else '停用'}。"
            values = {'id': current['id'], 'enabled': command.enabled,
                      'expected_version': owner.alarm_state['version']}
            action = "启用" if command.enabled else "停用"
        else:
            values = editable(current)
            values.update(hour=command.hour, minute=command.minute)
            if command.date_value is not None or command.weekdays is not None:
                values.update(date=command.date_value or '', weekdays=command.weekdays or 0)
            values['expected_version'] = owner.alarm_state['version']
            action = "修改"
    try:
        operation = 'delete' if command.operation == 'delete' else \
            'enable' if command.operation == 'enable' else 'put'
        await owner.alarm_write(operation, context=context, **values)
    except HomeAssistantError as error:
        if str(error) == 'r1_alarm_pending':
            return f"已记录{action}的待同步变更，但尚未送达R1。"
        return f"未能确认闹钟{action}，没有反馈为成功。"
    return f"闹钟已在R1确认{action}。"
