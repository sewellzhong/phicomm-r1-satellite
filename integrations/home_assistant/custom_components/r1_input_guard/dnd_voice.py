"""Anchored Chinese controls for the R1-owned do-not-disturb policy."""
from dataclasses import dataclass
import re

from homeassistant.exceptions import HomeAssistantError

from .alarm_voice import _normalize, _parse_time


@dataclass(frozen=True)
class DndVoiceCommand:
    operation: str
    value: bool | None = None
    start_hour: int | None = None
    start_minute: int | None = None
    end_hour: int | None = None
    end_minute: int | None = None
    issue: str | None = None


def parse_dnd_voice(text):
    text = _normalize(text)
    if re.fullmatch(r"(?:查询|查看)?免打扰(?:状态|设置|开着吗|开启了吗|是否开启)?", text):
        return DndVoiceCommand("query")
    if re.fullmatch(r"(?:打开|开启|启用)免打扰", text):
        return DndVoiceCommand("manual", True)
    if re.fullmatch(r"(?:关闭|停用|取消)免打扰", text):
        return DndVoiceCommand("manual", False)
    if re.fullmatch(r"(?:启用|打开|开启)免打扰时段", text):
        return DndVoiceCommand("schedule_enabled", True)
    if re.fullmatch(r"(?:停用|关闭|取消)免打扰时段", text):
        return DndVoiceCommand("schedule_enabled", False)
    if re.fullmatch(r"免打扰时(?:允许|保留)闹钟(?:响铃|提醒)?", text):
        return DndVoiceCommand("alarms_allowed", True)
    if re.fullmatch(r"免打扰时(?:不允许|禁止|关闭|屏蔽)闹钟(?:响铃|提醒)?", text):
        return DndVoiceCommand("alarms_allowed", False)
    match = re.fullmatch(r"(?:设置|设定|修改)?免打扰时段(?:为|是|设置为|设为)(.+?)(?:到|至)(.+)", text)
    if match:
        start_hour, start_minute, start_issue = _parse_time(match[1])
        end_hour, end_minute, end_issue = _parse_time(match[2])
        issue = start_issue or end_issue
        if issue == "meridiem_required": issue = "period_required"
        if issue: return DndVoiceCommand("schedule", issue=issue)
        if start_hour == end_hour and start_minute == end_minute:
            return DndVoiceCommand("schedule", issue="same_time")
        return DndVoiceCommand("schedule", True, start_hour, start_minute, end_hour, end_minute)
    return None


def _configuration(state):
    return {key: state[key] for key in (
        'manual', 'schedule_enabled', 'start_hour', 'start_minute',
        'end_hour', 'end_minute', 'alarms_allowed')}


async def execute_dnd_voice(owner, command, context=None):
    if command.issue:
        return {
            'period_required': '请说明上午或下午，也可以使用二十四小时时间。',
            'time_invalid': '免打扰时段无效，没有修改。',
            'same_time': '免打扰开始和结束时间不能相同，没有修改。',
        }.get(command.issue, '免打扰时段无效，没有修改。')
    state = getattr(owner, 'dnd_state', None)
    if state is None:
        return '暂时没有可用的R1免打扰状态，没有修改。'
    if command.operation == 'query':
        active = '正在生效' if state['active'] else '当前未生效'
        manual = '手动开启' if state['manual'] else '手动关闭'
        schedule = (f"每天{state['start_hour']:02d}:{state['start_minute']:02d}到"
                    f"{state['end_hour']:02d}:{state['end_minute']:02d}"
                    if state['schedule_enabled'] else '时段未启用')
        alarm = '允许闹钟响铃' if state['alarms_allowed'] else '屏蔽闹钟响铃'
        sync = '设备状态已确认' if owner.dnd_sync_status == 'synced' else '设备状态可能已过期'
        return f'免打扰{active}，{manual}，{schedule}，{alarm}，{sync}。'
    values = _configuration(state)
    if command.operation == 'manual': values['manual'] = command.value
    elif command.operation == 'schedule_enabled': values['schedule_enabled'] = command.value
    elif command.operation == 'alarms_allowed': values['alarms_allowed'] = command.value
    elif command.operation == 'schedule':
        values.update(schedule_enabled=True, start_hour=command.start_hour,
                      start_minute=command.start_minute, end_hour=command.end_hour,
                      end_minute=command.end_minute)
    else: return '免打扰指令无效，没有修改。'
    values['expected_version'] = state['version']
    try:
        confirmed = await owner.dnd_request('set', context=context, **values)
    except HomeAssistantError:
        return '未能在R1确认免打扰设置，没有反馈为成功。'
    return '免打扰设置已在R1确认，' + ('当前正在生效。' if confirmed['active'] else '当前未生效。')
