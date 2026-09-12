import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from homeassistant.components import conversation
from homeassistant.core import Context
from homeassistant.exceptions import HomeAssistantError

from custom_components.r1_input_guard.button import R1RebootDevice, R1RestartService
from custom_components.r1_input_guard.conversation import NativeConversation
from custom_components.r1_input_guard.interaction import Interaction
from custom_components.r1_input_guard.sensor import R1SystemStatus
from custom_components.r1_input_guard.system_voice import (
    SystemVoiceCommand, execute_system_voice, parse_system_voice,
)


def state(request, **changes):
    value = {'schema': 1, 'request_id': request['request_id'], 'operation': request['operation'],
        'app_version': '1.17-system-management', 'app_version_code': 117,
        'android_release': '5.1.1', 'android_sdk': 22, 'firmware': '3448',
        'service_status': 'waiting_ha', 'service_uptime_seconds': 9,
        'device_uptime_seconds': 1000, 'wifi_connected': True, 'wifi_rssi_dbm': -48,
        'ip_address': '192.0.2.10', 'last_error': None, 'connections': 3, 'failures': 0,
        'audio_blocked': False, 'privacy_muted': False, 'factory_isolation': 'isolated',
        'last_operation_id': '', 'last_operation': 'none', 'last_operation_state': 'none',
        'last_operation_error': None}
    value.update(changes)
    return value


class Services:
    def __init__(self): self.calls=[]; self.operation=None; self.polls=0; self.fail=False
    def has_service(self, domain, service):
        return (domain,service)==('esphome','r1_sample01_system_management')
    async def async_call(self, domain, service, data, **kwargs):
        self.calls.append((domain,service,data,kwargs))
        if self.fail: raise TimeoutError()
        request=json.loads(data['request'])
        if request['operation'] in ('restart_service','reboot_device'):
            self.operation=(request['request_id'],request['operation'])
            return state(request,last_operation_id=self.operation[0],last_operation=self.operation[1],
                         last_operation_state='requested')
        if self.operation:
            self.polls += 1
            return state(request,last_operation_id=self.operation[0],last_operation=self.operation[1],
                         last_operation_state='completed' if self.polls >= 2 else 'requested')
        return state(request)


class SystemInteractionTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.services=Services()
        esphome=SimpleNamespace(unique_id='5a:ab:ea:2d:d4:c3',
            runtime_data=SimpleNamespace(device_info=SimpleNamespace(name='r1-sample01')))
        self.owner=Interaction.__new__(Interaction)
        self.owner.hass=SimpleNamespace(services=self.services,
            config_entries=SimpleNamespace(async_entries=lambda domain:[esphome]))
        self.owner.entry=SimpleNamespace(entry_id='native');self.owner.mac='5a:ab:ea:2d:d4:c3'
        self.owner.listeners=set();self.owner._system_lock=asyncio.Lock()
        self.owner.system_state=None;self.owner.system_sync_status='connecting';self.owner.system_last_error=None

    async def test_status_is_correlated_and_strictly_validated(self):
        result=await self.owner.system_request('status')
        self.assertEqual(-48,result['wifi_rssi_dbm']);self.assertEqual('synced',self.owner.system_sync_status)
        request=json.loads(self.services.calls[0][2]['request'])
        self.assertRegex(request['request_id'],r'^[a-f0-9]{32}$')
        bad=state(request,wifi_connected=False,ip_address='192.0.2.10')
        with self.assertRaises(HomeAssistantError):
            Interaction._validated_system_state(bad,request['request_id'],'status')

    async def test_restart_waits_for_reconnected_completion(self):
        real_sleep=asyncio.sleep
        async def immediate(_): await real_sleep(0)
        with unittest.mock.patch('custom_components.r1_input_guard.interaction.asyncio.sleep',immediate):
            result=await self.owner.system_request('restart_service')
        self.assertEqual('completed',result['last_operation_state']);self.assertEqual(2,self.services.polls)

    async def test_failure_never_claims_success(self):
        self.services.fail=True
        with self.assertRaisesRegex(HomeAssistantError,'r1_system_not_confirmed'):
            await self.owner.system_request('status')
        self.assertEqual('offline',self.owner.system_sync_status)

    async def test_sensor_and_buttons_use_same_owner(self):
        await self.owner.system_request('status')
        wrapper=SimpleNamespace(entry=self.owner.entry,device_info=None,system_state=self.owner.system_state,
            system_sync_status=self.owner.system_sync_status,system_last_error=self.owner.system_last_error,
            listeners=set(),system_service=lambda:'r1_sample01_system_management',
            system_request=AsyncMock(return_value={}))
        sensor=R1SystemStatus(wrapper)
        self.assertEqual('waiting_ha',sensor.native_value);self.assertNotIn('request_id',sensor.extra_state_attributes)
        service=R1RestartService(wrapper);reboot=R1RebootDevice(wrapper)
        await service.async_press();await reboot.async_press()
        self.assertEqual('restart_service',wrapper.system_request.await_args_list[0].args[0])
        self.assertEqual('reboot_device',wrapper.system_request.await_args_list[1].args[0])


class SystemVoiceTest(unittest.IsolatedAsyncioTestCase):
    def test_grammar_is_anchored(self):
        self.assertEqual(SystemVoiceCommand('query_version'),parse_system_voice('查询这台R1的系统版本'))
        self.assertEqual(SystemVoiceCommand('query_connection'),parse_system_voice('查看R1网络状态'))
        self.assertEqual(SystemVoiceCommand('query_fault'),parse_system_voice('查询R1故障信息'))
        self.assertEqual(SystemVoiceCommand('restart_service'),parse_system_voice('重启R1卫星服务'))
        self.assertEqual(SystemVoiceCommand('reboot_device'),parse_system_voice('重启这台R1整机'))
        self.assertIsNone(parse_system_voice('为什么重启R1服务'))

    async def test_voice_only_reports_confirmed_completion(self):
        request={'request_id':'a'*32,'operation':'status'}
        owner=SimpleNamespace(system_request=AsyncMock(return_value=state(request)))
        self.assertIn('1.17',await execute_system_voice(owner,SystemVoiceCommand('query_version')))
        owner.system_request.side_effect=HomeAssistantError('failed')
        reply=await execute_system_voice(owner,SystemVoiceCommand('reboot_device'))
        self.assertIn('没有反馈为成功',reply)

    async def test_conversation_is_bound_to_originating_r1(self):
        owner=SimpleNamespace(device_id='r1',system_request=AsyncMock(return_value={}))
        agent=NativeConversation(SimpleNamespace(entry_id='test',data={'conversation_registry_id':'router'}))
        agent.hass=SimpleNamespace(data={'r1_input_guard_interaction':{'test':owner}})
        value=conversation.ConversationInput(agent_id='conversation.r1',text='查询R1故障信息',
            context=Context(user_id='u'),conversation_id='outer',language='zh-CN',device_id='other',
            satellite_id='assist_satellite.r1')
        reply=(await agent.async_process(value)).response.speech['plain']['speech']
        self.assertIn('无法确定',reply);owner.system_request.assert_not_awaited()
