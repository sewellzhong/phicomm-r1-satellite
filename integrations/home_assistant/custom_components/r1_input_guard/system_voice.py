"""Source-bound Chinese queries and explicit restart operations."""
from dataclasses import dataclass
import re
import unicodedata
from homeassistant.exceptions import HomeAssistantError


@dataclass(frozen=True)
class SystemVoiceCommand:
    operation: str


def parse_system_voice(text):
    text = unicodedata.normalize('NFKC', text).strip().strip('，。！？!?；;')
    target = r'(?:这台|当前)?(?:R1|音箱|语音音箱)'
    if re.fullmatch(r'(?:查询|查看|告诉我)?' + target + r'(?:的)?(?:系统|软件|应用)?版本(?:信息)?', text, re.I):
        return SystemVoiceCommand('query_version')
    if re.fullmatch(r'(?:查询|查看|告诉我)?' + target + r'(?:的)?(?:网络|连接|联网)(?:状态|情况)?', text, re.I):
        return SystemVoiceCommand('query_connection')
    if re.fullmatch(r'(?:查询|查看|告诉我)?' + target + r'(?:的)?(?:故障|错误|异常)(?:状态|信息)?', text, re.I):
        return SystemVoiceCommand('query_fault')
    if re.fullmatch(r'(?:请)?重启' + target + r'(?:的)?(?:卫星)?服务', text, re.I):
        return SystemVoiceCommand('restart_service')
    if re.fullmatch(r'(?:请)?(?:重启|重新启动)' + target + r'(?:整机|设备)?', text, re.I):
        return SystemVoiceCommand('reboot_device')
    return None


async def execute_system_voice(owner, command, context=None):
    operation = command.operation
    try:
        if operation.startswith('query_'):
            state = await owner.system_request('status', context=context)
        else:
            state = await owner.system_request(operation, context=context)
    except HomeAssistantError:
        return 'R1没有确认系统管理操作，没有反馈为成功。'
    if operation == 'query_version':
        return (f"R1应用版本是{state['app_version']}，Android版本是{state['android_release']}，"
                f"固件标识是{state['firmware']}。")
    if operation == 'query_connection':
        if not state['wifi_connected']: return 'R1当前没有确认Wi-Fi连接。'
        return f"R1当前已连接Wi-Fi，信号强度是{state['wifi_rssi_dbm']}dBm。"
    if operation == 'query_fault':
        error = state['last_error']
        return f'R1当前故障代码是{error}。' if error else 'R1当前没有报告故障代码。'
    return ('R1卫星服务已经重启并重新连接。' if operation == 'restart_service'
            else 'R1整机已经重启并重新连接。')
