import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from homeassistant.core import Context
from custom_components.r1_input_guard.conversation import NativeConversation
from custom_components.r1_input_guard.media_voice import is_stop_media, parse_explicit_target_stop


class MediaVoiceTest(unittest.TestCase):
    def test_exact_stop_media_phrases(self):
        for text in ('停止播放', '取消播放。', '停止音乐', '停止媒体', '停止 播放'):
            with self.subTest(text=text):
                self.assertTrue(is_stop_media(text))

    def test_unrelated_or_targeted_text_does_not_take_fast_path(self):
        for text in ('停止', '停止绘画', '播放音乐', '停止客厅的播放'):
            with self.subTest(text=text):
                self.assertFalse(is_stop_media(text))
        self.assertEqual(parse_explicit_target_stop('停止客厅音箱的闹钟'),
                         {'operation': 'stop', 'target': '客厅音箱的闹钟'})
        self.assertIsNone(parse_explicit_target_stop('取消明天的闹钟'))

    def test_native_conversation_binds_stop_to_originating_r1(self):
        async def run():
            agent = NativeConversation(SimpleNamespace(
                entry_id='entry', data={'conversation_registry_id': 'router'}))
            agent.hass = SimpleNamespace(data={}, services=SimpleNamespace())
            owner = SimpleNamespace(device_id='device-r1', stop_media=AsyncMock())
            user = SimpleNamespace(text='停止播放', conversation_id='outer',
                context=Context(user_id='user'), language='zh-CN', device_id='device-r1',
                satellite_id='satellite-r1')
            with patch('custom_components.r1_input_guard.interaction.bridge', return_value=owner):
                result = await agent.async_process(user)
            owner.stop_media.assert_awaited_once_with(user.context)
            self.assertEqual('已停止播放。', result.response.speech['plain']['speech'])
        import asyncio
        asyncio.run(run())

    def test_current_device_stop_aggregates_active_results(self):
        async def run():
            agent = NativeConversation(SimpleNamespace(
                entry_id='entry', data={'conversation_registry_id': 'router'}))
            agent.hass = SimpleNamespace(data={}, services=SimpleNamespace())
            owner = SimpleNamespace(device_id='device-r1',
                stop_current_device=AsyncMock(return_value=[('音乐播放', True), ('正在响的闹钟', None)]))
            user = SimpleNamespace(text='停止当前设备', conversation_id='outer',
                context=Context(user_id='user'), language='zh-CN', device_id='device-r1',
                satellite_id='satellite-r1')
            with patch('custom_components.r1_input_guard.interaction.bridge', return_value=owner):
                result = await agent.async_process(user)
            owner.stop_current_device.assert_awaited_once_with(user.context)
            self.assertIn('音乐播放', result.response.speech['plain']['speech'])
        import asyncio
        asyncio.run(run())

    def test_stop_uses_native_playback_entity_not_volume_wrapper(self):
        from custom_components.r1_input_guard.interaction import Interaction
        native = SimpleNamespace(entity_id='media_player.r1_native', domain='media_player',
            device_id='device-r1', platform='esphome', unique_id='mac/0/media_player/R1 媒体播放器',
            disabled_by=None)
        wrapper = SimpleNamespace(entity_id='media_player.yin_xiang', domain='media_player',
            device_id='device-r1', platform='r1_input_guard', unique_id='entry-speaker',
            disabled_by=None)
        registry = SimpleNamespace(entities={native.entity_id: native, wrapper.entity_id: wrapper})
        owner = SimpleNamespace(hass=SimpleNamespace(), device_id='device-r1', entry=SimpleNamespace(entry_id='entry'),
                                resolve=lambda: registry)
        self.assertEqual(['media_player.r1_native'], Interaction.media_player_entities(owner))
