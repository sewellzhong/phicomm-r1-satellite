"""Device-bound Chinese friendly-name and Area management."""
from dataclasses import dataclass
import re
import unicodedata

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import area_registry as ar, device_registry as dr


@dataclass(frozen=True)
class DeviceVoiceCommand:
    operation: str
    value: str | None = None
    issue: str | None = None


def _clean_value(value):
    value = unicodedata.normalize("NFKC", value).strip().strip("，。！？!?；;")
    if not value or len(value) > 64 or any(unicodedata.category(char).startswith("C") for char in value):
        return None
    return value


def parse_device_voice(text):
    """Match only explicit commands about the R1 that received the utterance."""
    text = unicodedata.normalize("NFKC", text).strip().strip("，。！？!?；;")
    if re.fullmatch(r"(?:查询|查看|告诉我)?(?:这台|当前)?(?:R1|音箱|语音音箱)(?:的)?(?:名称|名字|叫什么名字)", text, re.I):
        return DeviceVoiceCommand("query_name")
    if re.fullmatch(r"(?:查询|查看|告诉我)?(?:这台|当前)?(?:R1|音箱|语音音箱)(?:在|属于|的)?(?:哪个|什么)?(?:房间|区域|Area)", text, re.I):
        return DeviceVoiceCommand("query_area")
    if re.fullmatch(r"(?:清除|取消|移除)(?:这台|当前)?(?:R1|音箱|语音音箱)(?:的)?(?:房间|区域|Area)", text, re.I):
        return DeviceVoiceCommand("set_area", "")
    match = re.fullmatch(r"(?:把|将)?(?:这台|当前)?(?:R1|音箱|语音音箱)(?:(?:的)?(?:名称|名字)(?:改成|改为|设为|设置为)|命名为|改名为|叫)(.*)", text, re.I)
    if match:
        value = _clean_value(match[1])
        return DeviceVoiceCommand("set_name", value, None if value else "name_invalid")
    match = re.fullmatch(r"(?:把|将)?(?:这台|当前)?(?:R1|音箱|语音音箱)(?:(?:放到|放在|移到|移至|归入)(.*?)(?:房间|区域|Area)?|(?:的)?(?:房间|区域|Area)(?:改成|改为|设为|设置为)(.*))", text, re.I)
    if match:
        value = _clean_value(match[1] if match[1] is not None else match[2])
        return DeviceVoiceCommand("set_area", value, None if value else "area_invalid")
    return None


def _device(owner):
    if not getattr(owner, "device_id", None):
        return None
    return dr.async_get(owner.hass).async_get(owner.device_id)


def _area(owner, area_id):
    return ar.async_get(owner.hass).async_get_area(area_id) if area_id else None


async def execute_device_voice(owner, command, context=None):
    """Use HA registries as the only source and confirm every registry write."""
    del context  # Registry writes execute in HA's event loop and have no service context.
    if command.issue == "name_invalid":
        return "音箱名称必须是一到六十四个可显示字符，没有修改。"
    if command.issue == "area_invalid":
        return "区域名称无效，没有修改。"
    device = _device(owner)
    if device is None:
        return "暂时找不到这台R1的设备注册信息，没有修改。"
    areas = ar.async_get(owner.hass)
    if command.operation == "query_name":
        name = device.name_by_user or device.name
        return f"这台R1在HA中的名称是{name}。" if name else "这台R1在HA中还没有可用名称。"
    if command.operation == "query_area":
        area = _area(owner, device.area_id)
        return f"这台R1位于{area.name}区域。" if area else "这台R1在HA中尚未分配区域。"
    if command.operation == "set_name":
        before_id = device.id
        try:
            dr.async_get(owner.hass).async_update_device(device.id, name_by_user=command.value)
        except (KeyError, ValueError, HomeAssistantError):
            return "未能确认音箱名称修改，没有反馈为成功。"
        confirmed = _device(owner)
        if confirmed is None or confirmed.id != before_id or confirmed.name_by_user != command.value:
            return "未能确认音箱名称修改，没有反馈为成功。"
        return f"这台R1在HA中的名称已改为{command.value}。"
    if command.operation == "set_area":
        area_id = None
        if command.value:
            matches = [item for item in areas.async_list_areas()
                       if unicodedata.normalize("NFKC", item.name).casefold() == command.value.casefold()]
            if not matches:
                return f"HA中没有名为{command.value}的区域，没有修改。"
            if len(matches) != 1:
                return f"HA中有多个名为{command.value}的区域，没有修改。"
            area_id = matches[0].id
        before_id = device.id
        try:
            dr.async_get(owner.hass).async_update_device(device.id, area_id=area_id)
        except (KeyError, ValueError, HomeAssistantError):
            return "未能确认音箱区域修改，没有反馈为成功。"
        confirmed = _device(owner)
        if confirmed is None or confirmed.id != before_id or confirmed.area_id != area_id:
            return "未能确认音箱区域修改，没有反馈为成功。"
        return (f"这台R1已分配到{command.value}区域。" if area_id
                else "这台R1的HA区域已清除。")
    return "设备管理指令无效，没有修改。"
