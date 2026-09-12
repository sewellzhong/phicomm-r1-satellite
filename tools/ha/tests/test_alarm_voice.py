import unittest
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from homeassistant.components import conversation
from homeassistant.core import Context
from homeassistant.exceptions import HomeAssistantError

from custom_components.r1_input_guard.alarm_voice import (
    AlarmVoiceCommand, alarm_local_date, execute_alarm_voice, parse_alarm_voice,
)
from custom_components.r1_input_guard.conversation import NativeConversation


def alarm(alarm_id='wake', name='起床', hour=7, minute=30, date_value='', weekdays=31,
          enabled=True):
    return {'id': alarm_id, 'name': name, 'date': date_value, 'hour': hour, 'minute': minute,
            'weekdays': weekdays, 'enabled': enabled, 'snooze_minutes': 10,
            'next_wall_ms': 1, 'snooze_wall_ms': None, 'ringing': False, 'revision': 3}


class AlarmVoiceGrammarTest(unittest.TestCase):
    def test_relative_date_uses_device_reported_zone(self):
        owner=SimpleNamespace(alarm_state={'time_zone':'Asia/Hong_Kong'})
        instant=datetime(2026,9,12,17,0,tzinfo=timezone.utc)
        self.assertEqual(date(2026,9,13),alarm_local_date(owner,instant))
        owner.alarm_state['time_zone']='GMT+08:00'
        self.assertEqual(date(2026,9,13),alarm_local_date(owner,instant))

    def test_create_dates_recurrence_time_and_name_are_explicit(self):
        today=date(2026,9,12)
        cases={
            '设置一个明天早上七点半的起床闹钟':
                AlarmVoiceCommand('create','起床',7,30,'2026-09-13',0),
            '添加工作日早上7:15通勤闹钟':
                AlarmVoiceCommand('create','通勤',7,15,'',31),
            '创建每周一和三晚上八点吃药闹钟':
                AlarmVoiceCommand('create','吃药',20,0,'',5),
            '设九月二十日十九点闹钟':
                AlarmVoiceCommand('create','闹钟',19,0,'2026-09-20',0),
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(expected, parse_alarm_voice(text, today))

    def test_ambiguous_or_invalid_schedules_are_captured_without_guessing(self):
        today=date(2026,9,12)
        issues={
            '设置早上七点闹钟':'schedule_required',
            '设置明天七点闹钟':'meridiem_required',
            '设置明天每天早上七点闹钟':'schedule_ambiguous',
            '设置二月三十日早上七点闹钟':'date_invalid',
            '设置明天闹钟':'time_required',
        }
        for text, issue in issues.items():
            with self.subTest(text=text):
                self.assertEqual(issue, parse_alarm_voice(text,today).issue)
        for text in ('闹钟为什么会响','提醒我明天开会','电视设个闹钟节目'):
            self.assertIsNone(parse_alarm_voice(text,today))

    def test_query_update_delete_are_anchored(self):
        today=date(2026,9,12)
        self.assertEqual(AlarmVoiceCommand('query'),parse_alarm_voice('我有哪些闹钟',today))
        self.assertEqual(AlarmVoiceCommand('query','起床'),parse_alarm_voice('起床闹钟几点',today))
        self.assertEqual(AlarmVoiceCommand('update','起床',8,0),
                         parse_alarm_voice('把起床闹钟改到早上八点',today))
        self.assertEqual(AlarmVoiceCommand('delete','起床'),parse_alarm_voice('取消起床闹钟',today))
        self.assertEqual(AlarmVoiceCommand('enable','起床',enabled=True),
                         parse_alarm_voice('打开起床闹钟',today))
        self.assertEqual(AlarmVoiceCommand('enable','起床',enabled=False),
                         parse_alarm_voice('停用我的起床闹钟',today))
        self.assertEqual('batch_unsupported',parse_alarm_voice('删除所有闹钟',today).issue)


class AlarmVoiceExecutionTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        pending=SimpleNamespace(items=lambda:[])
        self.owner=SimpleNamespace(alarm_state={'version':3,'alarms':[alarm()]},
            alarm_sync_status='synced',alarm_pending=pending,alarm_write=AsyncMock())
        self.context=Context(user_id='user1')

    async def test_success_uses_shared_write_path_and_context(self):
        result=await execute_alarm_voice(self.owner,AlarmVoiceCommand('update','起床',8,0),self.context)
        self.assertIn('R1确认修改',result)
        kwargs=self.owner.alarm_write.await_args.kwargs
        self.assertEqual('wake',kwargs['id']);self.assertEqual(8,kwargs['hour'])
        self.assertEqual(31,kwargs['weekdays']);self.assertEqual(3,kwargs['expected_version'])
        self.assertIs(self.context,kwargs['context'])

    async def test_offline_pending_is_not_reported_as_delivered(self):
        self.owner.alarm_write.side_effect=HomeAssistantError('r1_alarm_pending')
        result=await execute_alarm_voice(self.owner,AlarmVoiceCommand('delete','起床'),self.context)
        self.assertIn('待同步',result);self.assertIn('尚未送达R1',result)
        self.assertNotIn('R1确认',result)

    async def test_enable_disable_uses_versioned_shared_write_and_is_idempotent(self):
        result=await execute_alarm_voice(self.owner,AlarmVoiceCommand('enable','起床',enabled=False),self.context)
        self.assertIn('R1确认停用',result)
        self.owner.alarm_write.assert_awaited_once_with('enable',context=self.context,
            id='wake',enabled=False,expected_version=3)
        self.owner.alarm_write.reset_mock()
        self.owner.alarm_state['alarms'][0]['enabled']=False
        result=await execute_alarm_voice(self.owner,AlarmVoiceCommand('enable','起床',enabled=False),self.context)
        self.assertIn('已经停用',result)
        self.owner.alarm_write.assert_not_awaited()

    async def test_offline_enable_is_pending_not_confirmed(self):
        self.owner.alarm_write.side_effect=HomeAssistantError('r1_alarm_pending')
        result=await execute_alarm_voice(self.owner,AlarmVoiceCommand('enable','起床',enabled=False),self.context)
        self.assertIn('待同步',result);self.assertNotIn('R1确认',result)

    async def test_query_exposes_effective_pending_without_claiming_sync(self):
        desired={key:value for key,value in alarm('later','吃药',20,0,'',127).items()
                 if key in ('id','name','date','hour','minute','weekdays','enabled','snooze_minutes')}
        self.owner.alarm_pending=SimpleNamespace(items=lambda:[
            {'id':'wake','base':{key:value for key,value in alarm().items()
             if key in ('id','name','date','hour','minute','weekdays','enabled','snooze_minutes')},
             'desired':None,'blocked':False},
            {'id':'later','base':None,'desired':desired,'blocked':False}])
        self.owner.alarm_sync_status='pending'
        result=await execute_alarm_voice(self.owner,AlarmVoiceCommand('query'),self.context)
        self.assertIn('吃药，每天20:00，待同步',result)
        self.assertIn('另有2项待同步变更',result);self.assertNotIn('设备当前离线',result)
        self.assertNotIn('起床',result)
        cancelled=await execute_alarm_voice(self.owner,AlarmVoiceCommand('query','起床'),self.context)
        self.assertIn('等待取消同步',cancelled);self.assertIn('尚未送达R1',cancelled)

    async def test_query_reports_multiple_independent_alarms(self):
        self.owner.alarm_state['alarms'].append(alarm('medicine','吃药',20,0,'',127,False))
        result=await execute_alarm_voice(self.owner,AlarmVoiceCommand('query'),self.context)
        self.assertIn('共2个',result)
        self.assertIn('起床，工作日07:30，已启用',result)
        self.assertIn('吃药，每天20:00，已停用',result)

    async def test_missing_or_duplicate_target_never_writes(self):
        result=await execute_alarm_voice(self.owner,AlarmVoiceCommand('delete','不存在'),self.context)
        self.assertIn('没有找到',result)
        self.owner.alarm_state['alarms'].append(alarm('wake2'))
        result=await execute_alarm_voice(self.owner,AlarmVoiceCommand('update','起床',8,0),self.context)
        self.assertIn('多个',result);self.assertIn('没有修改',result)
        self.owner.alarm_write.assert_not_awaited()


class AlarmVoiceConversationTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.owner=SimpleNamespace(device_id='r1',alarm_state={'version':3,'alarms':[alarm()]},
            alarm_sync_status='synced',alarm_pending=SimpleNamespace(items=lambda:[]),
            alarm_write=AsyncMock())
        self.agent=NativeConversation(SimpleNamespace(entry_id='test',data={'conversation_registry_id':'router'}))
        self.agent.hass=SimpleNamespace(data={'r1_input_guard_interaction':{'test':self.owner}})

    async def ask(self,text,device='r1'):
        user=conversation.ConversationInput(agent_id='conversation.r1',text=text,context=Context(user_id='u'),
            conversation_id='outer',language='zh-CN',device_id=device,satellite_id='assist_satellite.r1')
        return (await self.agent.async_process(user)).response.speech['plain']['speech']

    async def test_source_binding_and_confirmed_write(self):
        with patch('custom_components.r1_input_guard.alarm_voice.uuid4',return_value=SimpleNamespace(hex='a'*32)):
            speech=await self.ask('设置一个明天早上七点半的起床闹钟')
        self.assertIn('R1确认创建',speech)
        self.assertEqual('voice-'+'a'*32,self.owner.alarm_write.await_args.kwargs['id'])
        self.owner.alarm_write.reset_mock()
        self.assertIn('无法确定',await self.ask('取消起床闹钟',device='other'))
        self.owner.alarm_write.assert_not_awaited()
