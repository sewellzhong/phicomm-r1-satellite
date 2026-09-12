import unittest
from types import SimpleNamespace
from unittest.mock import patch

from homeassistant.components import conversation
from homeassistant.core import Context

from custom_components.r1_input_guard.conversation import NativeConversation
from custom_components.r1_input_guard.device_voice import (
    DeviceVoiceCommand, execute_device_voice, parse_device_voice,
)


class DeviceGrammarTest(unittest.TestCase):
    def test_queries_and_explicit_writes_are_anchored(self):
        self.assertEqual(DeviceVoiceCommand("query_name"), parse_device_voice("这台音箱叫什么名字"))
        self.assertEqual(DeviceVoiceCommand("query_area"), parse_device_voice("R1在哪个区域"))
        self.assertEqual(DeviceVoiceCommand("set_name", "书房音箱"), parse_device_voice("把这台音箱命名为书房音箱"))
        self.assertEqual(DeviceVoiceCommand("set_name", "书房音箱"), parse_device_voice("把R1的名字改为书房音箱"))
        self.assertEqual(DeviceVoiceCommand("set_area", "书房"), parse_device_voice("把R1放到书房"))
        self.assertEqual(DeviceVoiceCommand("set_area", "书房"), parse_device_voice("将这台音箱移至书房区域"))
        self.assertEqual(DeviceVoiceCommand("set_area", "书房"), parse_device_voice("把R1的区域设置为书房"))
        self.assertEqual(DeviceVoiceCommand("set_area", ""), parse_device_voice("清除这台音箱的区域"))

    def test_unrelated_or_invalid_values_do_not_become_writes(self):
        for text in ("客厅音箱叫什么名字", "为什么要给音箱改名", "把电视放到客厅", "把R1设置为书房"):
            self.assertIsNone(parse_device_voice(text))
        self.assertEqual("name_invalid", parse_device_voice("把这台音箱命名为。").issue)
        self.assertEqual("area_invalid", parse_device_voice("把这台音箱放到。区域").issue)


class FakeAreas:
    def __init__(self, values): self.areas = {item.id: item for item in values}
    def async_get_area(self, area_id): return self.areas.get(area_id)
    def async_list_areas(self): return list(self.areas.values())


class FakeDevices:
    def __init__(self, device): self.device = device; self.confirm = True
    def async_get(self, device_id): return self.device if device_id == self.device.id else None
    def async_update_device(self, device_id, **changes):
        if self.confirm:
            for key, value in changes.items(): setattr(self.device, key, value)
        return self.device


class DeviceExecutionTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.device = SimpleNamespace(id="stable-id", name="R1", name_by_user=None, area_id="living")
        self.devices = FakeDevices(self.device)
        self.areas = FakeAreas([SimpleNamespace(id="living", name="客厅"),
                                SimpleNamespace(id="study", name="书房")])
        self.owner = SimpleNamespace(hass=object(), device_id="stable-id")
        self.registry = patch("custom_components.r1_input_guard.device_voice.dr.async_get", return_value=self.devices)
        self.area_registry = patch("custom_components.r1_input_guard.device_voice.ar.async_get", return_value=self.areas)
        self.registry.start(); self.area_registry.start()
        self.addCleanup(self.registry.stop); self.addCleanup(self.area_registry.stop)

    async def test_query_and_updates_use_registry_without_changing_identity(self):
        self.assertIn("R1", await execute_device_voice(self.owner, DeviceVoiceCommand("query_name")))
        self.assertIn("客厅", await execute_device_voice(self.owner, DeviceVoiceCommand("query_area")))
        self.assertIn("已改为书房音箱", await execute_device_voice(self.owner, DeviceVoiceCommand("set_name", "书房音箱")))
        self.assertEqual("stable-id", self.device.id)
        self.assertIn("已分配到书房", await execute_device_voice(self.owner, DeviceVoiceCommand("set_area", "书房")))
        self.assertEqual("study", self.device.area_id)
        self.assertIn("已清除", await execute_device_voice(self.owner, DeviceVoiceCommand("set_area", "")))
        self.assertIsNone(self.device.area_id)

    async def test_unknown_area_and_unconfirmed_write_never_claim_success(self):
        response = await execute_device_voice(self.owner, DeviceVoiceCommand("set_area", "车库"))
        self.assertIn("没有名为车库", response); self.assertIn("没有修改", response)
        self.devices.confirm = False
        response = await execute_device_voice(self.owner, DeviceVoiceCommand("set_name", "新名称"))
        self.assertIn("未能确认", response); self.assertIn("没有反馈为成功", response)

    async def test_ambiguous_area_never_writes(self):
        self.areas.areas["study-duplicate"] = SimpleNamespace(id="study-duplicate", name="书房")
        response = await execute_device_voice(self.owner, DeviceVoiceCommand("set_area", "书房"))
        self.assertIn("多个", response); self.assertIn("没有修改", response)
        self.assertEqual("living", self.device.area_id)


class DeviceConversationTest(unittest.IsolatedAsyncioTestCase):
    async def test_voice_management_is_bound_to_originating_r1(self):
        owner = SimpleNamespace(device_id="r1")
        agent = NativeConversation(SimpleNamespace(entry_id="test", data={"conversation_registry_id": "router"}))
        agent.hass = SimpleNamespace(data={"r1_input_guard_interaction": {"test": owner}})

        async def ask(device):
            value = conversation.ConversationInput(agent_id="conversation.r1", text="这台音箱叫什么名字",
                context=Context(user_id="u"), conversation_id="outer", language="zh-CN",
                device_id=device, satellite_id="assist_satellite.r1")
            return (await agent.async_process(value)).response.speech["plain"]["speech"]

        with patch("custom_components.r1_input_guard.device_voice.execute_device_voice",
                   return_value="这台R1在HA中的名称是书房音箱。") as execute:
            self.assertIn("书房音箱", await ask("r1"))
            execute.assert_awaited_once()
            execute.reset_mock()
            self.assertIn("无法确定", await ask("other"))
            execute.assert_not_awaited()
