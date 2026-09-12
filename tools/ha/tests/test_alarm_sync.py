import json
import unittest
from collections import OrderedDict
from types import SimpleNamespace
from unittest.mock import AsyncMock
from homeassistant.exceptions import HomeAssistantError
from custom_components.r1_input_guard.alarm_pending import AlarmPending
from custom_components.r1_input_guard.interaction import Interaction
from custom_components.r1_input_guard.sensor import R1Alarms


def state(request, version=3, alarms=None, total=None):
    alarms = alarms if alarms is not None else [{
        'id': 'wake', 'name': '起床', 'date': '', 'hour': 7, 'minute': 30,
        'weekdays': 31, 'enabled': True, 'snooze_minutes': 10,
        'ringtone': 'classic', 'volume_percent': 100,
        'next_wall_ms': 1789171200000, 'snooze_wall_ms': None,
        'ringing': False, 'revision': version, 'prompt_text': '起床时间到了', 'prompt_mode': 'tone_only',
    }]
    offset=request.get('page_offset',0);total=len(alarms) if total is None else total
    return {'schema': 2, 'request_id': request['request_id'], 'operation': request['operation'],
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
        self.owner.alarm_pending=AlarmPending.__new__(AlarmPending)
        self.owner.alarm_pending._items=OrderedDict()
        self.owner.alarm_pending._store=SimpleNamespace(async_save=AsyncMock())

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
            alarm_last_error=self.owner.alarm_last_error,alarm_pending=self.owner.alarm_pending,
            listeners=set(),alarm_request=self.owner.alarm_request,alarm_write=self.owner.alarm_write)
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
        bad=state(request);bad['time_zone']='Not/AZone'
        with self.assertRaises(HomeAssistantError): Interaction._validated_alarm_state(bad,'a'*32,'status')
        bad=state(request);bad['alarms'][0]['prompt_mode']='spoken'
        with self.assertRaises(HomeAssistantError): Interaction._validated_alarm_state(bad,'a'*32,'status')

    async def test_all_pages_are_version_locked_and_published_together(self):
        self.services.all_alarms=[dict(state({'request_id':'a'*32,'operation':'status'})['alarms'][0],
            id=f'alarm-{index}') for index in range(9)]
        result=await self.owner.alarm_request('status')
        self.assertEqual(9,len(result['alarms']))
        requests=[json.loads(call[2]['request']) for call in self.services.calls]
        self.assertEqual([0,4,8],[item.get('page_offset',0) for item in requests])
        self.assertEqual([None,3,3],[item.get('expected_version') for item in requests])

    async def test_offline_write_is_persisted_but_never_reported_as_delivered(self):
        await self.owner.alarm_request('status')
        self.owner.alarm_sync_status='offline'
        with self.assertRaisesRegex(HomeAssistantError, 'r1_alarm_pending'):
            await self.owner.alarm_write('enable',id='wake',enabled=False,expected_version=3)
        self.assertEqual('pending',self.owner.alarm_sync_status)
        self.assertEqual('not_delivered',self.owner.alarm_last_error)
        self.assertFalse(self.owner.alarm_pending.public()[0]['desired']['enabled'])
        self.assertTrue(self.owner.alarm_state['alarms'][0]['enabled'])
        self.owner.alarm_pending._store.async_save.assert_awaited_once()

    async def test_first_write_during_transport_loss_is_queued(self):
        await self.owner.alarm_request('status')
        self.services.async_call=AsyncMock(side_effect=TimeoutError())
        with self.assertRaisesRegex(HomeAssistantError, 'r1_alarm_pending'):
            await self.owner.alarm_write('delete',id='wake',expected_version=3)
        self.assertEqual('pending',self.owner.alarm_sync_status)
        self.assertEqual('delete',self.owner.alarm_pending.public()[0]['operation'])

    async def test_reconnect_replays_against_unchanged_item_with_latest_global_version(self):
        await self.owner.alarm_request('status')
        self.owner.alarm_sync_status='offline'
        with self.assertRaises(HomeAssistantError):
            await self.owner.alarm_write('enable',id='wake',enabled=False)
        calls=[]
        async def request(operation, **values):
            calls.append((operation,values))
            current=dict(self.owner.alarm_state['alarms'][0],enabled=False,revision=9)
            self.owner.alarm_state={**self.owner.alarm_state,'version':9,'alarms':[current]}
            return self.owner.alarm_state
        self.owner.alarm_state={**self.owner.alarm_state,'version':8}
        self.owner.alarm_request=request
        await self.owner.replay_alarm_pending()
        self.assertEqual([('put', {'id':'wake','name':'起床','date':'','hour':7,'minute':30,
            'weekdays':31,'enabled':False,'snooze_minutes':10,'ringtone':'classic',
            'volume_percent':100,'expected_version':8})],calls)
        self.assertEqual([],self.owner.alarm_pending.items())
        self.assertEqual('synced',self.owner.alarm_sync_status)

    async def test_reconnect_conflict_does_not_apply_any_pending_item(self):
        await self.owner.alarm_request('status')
        self.owner.alarm_sync_status='offline'
        with self.assertRaises(HomeAssistantError):
            await self.owner.alarm_write('delete',id='wake')
        self.owner.alarm_state['alarms'][0]['name']='远端已修改'
        self.owner.alarm_request=AsyncMock()
        with self.assertRaisesRegex(HomeAssistantError, 'r1_alarm_pending_conflict'):
            await self.owner.replay_alarm_pending()
        self.owner.alarm_request.assert_not_awaited()
        self.assertEqual('conflict',self.owner.alarm_sync_status)
        self.assertEqual('remote_changed',self.owner.alarm_last_error)
        self.assertTrue(self.owner.alarm_pending.public()[0]['blocked'])

    async def test_device_rejection_blocks_automatic_retries_until_discarded(self):
        await self.owner.alarm_request('status')
        self.owner.alarm_sync_status='offline'
        with self.assertRaises(HomeAssistantError):
            await self.owner.alarm_write('delete',id='wake')
        async def reject(*args,**kwargs):
            self.owner.alarm_last_error='request_failed'
            raise HomeAssistantError('r1_alarm_not_confirmed')
        self.owner.alarm_request=AsyncMock(side_effect=reject)
        with self.assertRaisesRegex(HomeAssistantError, 'r1_alarm_pending_conflict'):
            await self.owner.replay_alarm_pending()
        with self.assertRaisesRegex(HomeAssistantError, 'r1_alarm_pending_conflict'):
            await self.owner.replay_alarm_pending()
        self.assertEqual(1,self.owner.alarm_request.await_count)
        await self.owner.discard_alarm_pending(id='wake')
        self.assertEqual([],self.owner.alarm_pending.items())


class PendingAlarmTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.pending=AlarmPending.__new__(AlarmPending)
        self.pending._items=OrderedDict()
        self.pending._store=SimpleNamespace(async_save=AsyncMock(),async_load=AsyncMock(return_value=None))
        self.baseline=state({'request_id':'a'*32,'operation':'status'})

    async def test_changes_compact_to_one_desired_state_and_can_cancel_out(self):
        await self.pending.queue('enable',{'id':'wake','enabled':False},self.baseline)
        await self.pending.queue('enable',{'id':'wake','enabled':True},self.baseline)
        self.assertEqual([],self.pending.items())
        self.assertEqual(2,self.pending._store.async_save.await_count)

    async def test_delete_of_new_offline_alarm_drops_the_pending_creation(self):
        values={'id':'later','name':'稍后','date':'','hour':9,'minute':0,'weekdays':127,
                'enabled':True,'snooze_minutes':5,'ringtone':'gentle','volume_percent':45}
        await self.pending.queue('put',values,self.baseline)
        await self.pending.queue('delete',{'id':'later'},self.baseline)
        self.assertEqual([],self.pending.items())

    async def test_invalid_persisted_data_fails_closed(self):
        self.pending._store.async_load=AsyncMock(return_value={'schema':1,'items':[{
            'id':'wake','base':None,'desired':{'id':'wake'}}]})
        with self.assertRaisesRegex(HomeAssistantError, 'r1_alarm_pending_store_invalid'):
            await self.pending.load()
