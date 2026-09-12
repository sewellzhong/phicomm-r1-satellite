import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock
from homeassistant.exceptions import HomeAssistantError
from custom_components.r1_input_guard.interaction import Interaction
from custom_components.r1_input_guard.sensor import R1Alarms


def state(request, version=3, alarms=None, total=None):
    alarms = alarms if alarms is not None else [{
        'id': 'wake', 'name': '起床', 'date': '', 'hour': 7, 'minute': 30,
        'weekdays': 31, 'enabled': True, 'snooze_minutes': 10,
        'next_wall_ms': 1789171200000, 'snooze_wall_ms': None,
        'ringing': False, 'revision': version,
    }]
    offset=request.get('page_offset',0);total=len(alarms) if total is None else total
    return {'schema': 1, 'request_id': request['request_id'], 'operation': request['operation'],
            'version': version, 'alarm_count': total, 'ringing_count': 0,
            'ringer_active': False, 'clock_pending': False, 'time_zone': 'Asia/Hong_Kong',
            'alarms': alarms, 'page_offset': offset, 'page_complete': offset+len(alarms)==total}


class Services:
    def __init__(self): self.calls=[]; self.fail=False; self.all_alarms=None
    def has_service(self, domain, service): return (domain, service) == ('esphome', 'r1_sample01_alarm_sync')
    async def async_call(self, domain, service, data, **kwargs):
        self.calls.append((domain, service, data, kwargs))
        if self.fail: raise HomeAssistantError('offline')
        request=json.loads(data['request'])
        if self.all_alarms is not None:
            offset=request.get('page_offset',0)
            return state(request,alarms=self.all_alarms[offset:offset+4],total=len(self.all_alarms))
        return state(request)


class AlarmSyncTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.services=Services()
        esphome=SimpleNamespace(unique_id='5a:ab:ea:2d:d4:c3',
            runtime_data=SimpleNamespace(device_info=SimpleNamespace(name='r1-sample01')))
        self.owner=Interaction.__new__(Interaction)
        self.owner.hass=SimpleNamespace(services=self.services,
            config_entries=SimpleNamespace(async_entries=lambda domain:[esphome]))
        self.owner.mac='5a:ab:ea:2d:d4:c3';self.owner.listeners=set()
        self.owner._alarm_lock=__import__('asyncio').Lock()
        self.owner.alarm_state=None;self.owner.alarm_sync_status='connecting';self.owner.alarm_last_error=None

    async def test_status_is_noise_service_bound_and_response_correlated(self):
        result=await self.owner.alarm_request('status')
        self.assertEqual(3,result['version']);self.assertEqual('synced',self.owner.alarm_sync_status)
        domain,service,data,kwargs=self.services.calls[0]
        self.assertEqual(('esphome','r1_sample01_alarm_sync'),(domain,service))
        self.assertTrue(kwargs['blocking']);self.assertTrue(kwargs['return_response'])
        request=json.loads(data['request'])
        self.assertRegex(request['request_id'],r'^[a-f0-9]{32}$')
        self.assertEqual('status',request['operation'])

    async def test_failure_marks_offline_and_preserves_confirmed_cache(self):
        await self.owner.alarm_request('status'); before=self.owner.alarm_state
        self.services.fail=True
        with self.assertRaises(HomeAssistantError): await self.owner.alarm_request('delete',id='wake',expected_version=3)
        self.assertIs(before,self.owner.alarm_state)
        self.assertEqual('offline',self.owner.alarm_sync_status)
        self.assertEqual('request_failed',self.owner.alarm_last_error)

    async def test_mismatched_response_is_never_accepted(self):
        async def wrong(*args,**kwargs): return state({'request_id':'0'*32,'operation':'status'})
        self.services.async_call=wrong
        with self.assertRaises(HomeAssistantError): await self.owner.alarm_request('status')
        self.assertIsNone(self.owner.alarm_state)

    async def test_entity_uses_confirmed_version_and_exposes_full_list(self):
        await self.owner.alarm_request('status')
        wrapper=SimpleNamespace(entry=SimpleNamespace(entry_id='native'),device_info=None,
            alarm_state=self.owner.alarm_state,alarm_sync_status=self.owner.alarm_sync_status,
            alarm_last_error=self.owner.alarm_last_error,listeners=set(),alarm_request=self.owner.alarm_request)
        entity=R1Alarms(wrapper)
        await entity.async_alarm_enable(id='wake',enabled=False)
        request=json.loads(self.services.calls[-1][2]['request'])
        self.assertEqual(3,request['expected_version'])
        self.assertEqual(1,entity.native_value)
        self.assertEqual('wake',entity.extra_state_attributes['alarms'][0]['id'])
        self.assertNotIn('request_id',entity.extra_state_attributes)

    async def test_invalid_shape_rejected(self):
        request={'request_id':'a'*32,'operation':'status'}
        bad=state(request);bad['alarm_count']=2
        with self.assertRaises(HomeAssistantError): Interaction._validated_alarm_state(bad,'a'*32,'status')

    async def test_all_pages_are_version_locked_and_published_together(self):
        self.services.all_alarms=[dict(state({'request_id':'a'*32,'operation':'status'})['alarms'][0],
            id=f'alarm-{index}') for index in range(9)]
        result=await self.owner.alarm_request('status')
        self.assertEqual(9,len(result['alarms']))
        requests=[json.loads(call[2]['request']) for call in self.services.calls]
        self.assertEqual([0,4,8],[item.get('page_offset',0) for item in requests])
        self.assertEqual([None,3,3],[item.get('expected_version') for item in requests])
