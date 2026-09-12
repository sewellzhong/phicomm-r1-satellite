import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from homeassistant.components import conversation
from homeassistant.core import Context
from homeassistant.exceptions import HomeAssistantError

from custom_components.r1_input_guard.conversation import NativeConversation
from custom_components.r1_input_guard.dnd_voice import (
    DndVoiceCommand, execute_dnd_voice, parse_dnd_voice,
)
from custom_components.r1_input_guard.interaction import Interaction
from custom_components.r1_input_guard.sensor import R1DoNotDisturb


def state(request, **changes):
    value = {'schema': 1, 'request_id': request['request_id'], 'operation': request['operation'],
             'version': 4, 'manual': False, 'schedule_enabled': True,
             'start_hour': 22, 'start_minute': 30, 'end_hour': 7, 'end_minute': 0,
             'alarms_allowed': True, 'active': False, 'source': 'none',
             'clock_trusted': True, 'time_zone': 'Asia/Hong_Kong',
             'dim_light_requested': False, 'suppressed_announcements': 2,
             'suppressed_alarms': 0, 'persistence_failures': 0, 'restore_failed': False}
    value.update(changes); return value


class Services:
    def __init__(self): self.calls = []; self.fail = False
    def has_service(self, domain, service):
        return (domain, service) == ('esphome', 'r1_sample01_do_not_disturb')
    async def async_call(self, domain, service, data, **kwargs):
        self.calls.append((domain, service, data, kwargs))
        if self.fail: raise TimeoutError()
        request = json.loads(data['request'])
        return state(request, manual=request.get('manual', False),
                     active=request.get('manual', False),
                     dim_light_requested=request.get('manual', False),
                     source='manual' if request.get('manual') else 'none',
                     version=5 if request['operation'] == 'set' else 4)


class DndGrammarTest(unittest.TestCase):
    def test_manual_query_schedule_and_alarm_exception_are_anchored(self):
        self.assertEqual(DndVoiceCommand('manual', True), parse_dnd_voice('打开免打扰'))
        self.assertEqual(DndVoiceCommand('manual', False), parse_dnd_voice('关闭免打扰'))
        self.assertEqual(DndVoiceCommand('query'), parse_dnd_voice('查询免打扰状态'))
        self.assertEqual(DndVoiceCommand('schedule', True, 22, 30, 7, 0),
                         parse_dnd_voice('设置免打扰时段为晚上十点半到早上七点'))
        self.assertEqual(DndVoiceCommand('alarms_allowed', False),
                         parse_dnd_voice('免打扰时屏蔽闹钟响铃'))
        self.assertIsNone(parse_dnd_voice('为什么需要免打扰模式'))

    def test_ambiguous_or_degenerate_time_is_rejected(self):
        self.assertEqual('period_required', parse_dnd_voice('免打扰时段为七点到八点').issue)
        self.assertEqual('same_time', parse_dnd_voice('免打扰时段为晚上十点到晚上十点').issue)


class DndInteractionTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.services = Services()
        esphome = SimpleNamespace(unique_id='5a:ab:ea:2d:d4:c3',
            runtime_data=SimpleNamespace(device_info=SimpleNamespace(name='r1-sample01')))
        self.owner = Interaction.__new__(Interaction)
        self.owner.hass = SimpleNamespace(services=self.services,
            config_entries=SimpleNamespace(async_entries=lambda domain: [esphome]))
        self.owner.entry = SimpleNamespace(entry_id='native')
        self.owner.mac = '5a:ab:ea:2d:d4:c3'; self.owner.listeners = set()
        self.owner._dnd_lock = asyncio.Lock(); self.owner.dnd_state = None
        self.owner.dnd_sync_status = 'connecting'; self.owner.dnd_last_error = None

    async def test_status_and_set_are_correlated_and_confirmed(self):
        current = await self.owner.dnd_request('status')
        self.assertEqual('synced', self.owner.dnd_sync_status)
        result = await self.owner.dnd_request('set', manual=True, schedule_enabled=True,
            start_hour=22, start_minute=30, end_hour=7, end_minute=0,
            alarms_allowed=True, expected_version=current['version'])
        self.assertTrue(result['active']); self.assertEqual(5, result['version'])
        domain, service, data, options = self.services.calls[-1]
        self.assertEqual(('esphome', 'r1_sample01_do_not_disturb'), (domain, service))
        self.assertTrue(options['blocking']); self.assertTrue(options['return_response'])
        self.assertRegex(json.loads(data['request'])['request_id'], r'^[a-f0-9]{32}$')

    async def test_failure_keeps_last_confirmed_state_and_never_claims_success(self):
        before = await self.owner.dnd_request('status')
        self.services.fail = True
        with self.assertRaisesRegex(HomeAssistantError, 'r1_dnd_not_confirmed'):
            await self.owner.dnd_request('set', manual=True)
        self.assertIs(before, self.owner.dnd_state)
        self.assertEqual('offline', self.owner.dnd_sync_status)
        self.assertEqual('transport_failed', self.owner.dnd_last_error)

    async def test_entity_exposes_confirmed_state_and_uses_version(self):
        await self.owner.dnd_request('status')
        wrapper = SimpleNamespace(entry=self.owner.entry, device_info=None,
            dnd_state=self.owner.dnd_state, dnd_sync_status=self.owner.dnd_sync_status,
            dnd_last_error=self.owner.dnd_last_error, listeners=set(), dnd_request=self.owner.dnd_request)
        entity = R1DoNotDisturb(wrapper)
        self.assertEqual('off', entity.native_value)
        await entity.async_dnd_set(manual=True, schedule_enabled=True, start_hour=22,
            start_minute=30, end_hour=7, end_minute=0, alarms_allowed=True)
        request = json.loads(self.services.calls[-1][2]['request'])
        self.assertEqual(4, request['expected_version'])
        self.assertNotIn('request_id', entity.extra_state_attributes)

    def test_invalid_state_shape_is_rejected(self):
        request = {'request_id': 'a' * 32, 'operation': 'status'}
        bad = state(request, active='yes')
        with self.assertRaises(HomeAssistantError):
            Interaction._validated_dnd_state(bad, request['request_id'], 'status')
        bad = state(request, time_zone='Not/AZone')
        with self.assertRaises(HomeAssistantError):
            Interaction._validated_dnd_state(bad, request['request_id'], 'status')


class DndVoiceExecutionTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.current = state({'request_id': 'a' * 32, 'operation': 'status'})
        self.owner = SimpleNamespace(dnd_state=self.current, dnd_sync_status='synced',
                                     dnd_request=AsyncMock())
        self.owner.dnd_request.return_value = dict(self.current, manual=True, active=True)

    async def test_voice_write_uses_full_versioned_configuration(self):
        response = await execute_dnd_voice(self.owner, DndVoiceCommand('manual', True), Context())
        self.assertIn('R1确认', response)
        values = self.owner.dnd_request.await_args.kwargs
        self.assertEqual(4, values['expected_version']); self.assertTrue(values['manual'])
        self.assertEqual(22, values['start_hour']); self.assertTrue(values['alarms_allowed'])

    async def test_offline_failure_is_not_success(self):
        self.owner.dnd_request.side_effect = HomeAssistantError('r1_dnd_not_confirmed')
        response = await execute_dnd_voice(self.owner, DndVoiceCommand('manual', True))
        self.assertIn('未能', response); self.assertIn('没有反馈为成功', response)

    async def test_conversation_is_device_bound(self):
        self.owner.device_id = 'r1'
        agent = NativeConversation(SimpleNamespace(entry_id='test', data={'conversation_registry_id':'router'}))
        agent.hass = SimpleNamespace(data={'r1_input_guard_interaction': {'test': self.owner}})
        async def ask(device):
            value = conversation.ConversationInput(agent_id='conversation.r1', text='打开免打扰',
                context=Context(user_id='u'), conversation_id='outer', language='zh-CN',
                device_id=device, satellite_id='assist_satellite.r1')
            return (await agent.async_process(value)).response.speech['plain']['speech']
        self.assertIn('R1确认', await ask('r1'))
        self.owner.dnd_request.reset_mock()
        self.assertIn('无法确定', await ask('other'))
        self.owner.dnd_request.assert_not_awaited()
