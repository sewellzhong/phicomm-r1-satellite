import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock
from homeassistant.core import Context
from homeassistant.components import conversation
from homeassistant.exceptions import HomeAssistantError
from custom_components.r1_input_guard.controls import parse_control, Control
from custom_components.r1_input_guard.conversation import NativeConversation

class GrammarTest(unittest.TestCase):
    def test_anchored_natural_commands(self):
        cases={'音量小一点':Control('volume','relative',-10),'小声一点':Control('volume','relative',-10),
          '请帮我':None,'请把R1音量调到百分之三十五。':Control('volume','percent',35),
          '调高音量':Control('volume','relative',10),'语速慢一点':Control('speech_speed','relative',-.05),
          '说慢一点':Control('speech_speed','relative',-.05),'慢点说':Control('speech_speed','relative',-.05),
          '说话快一点':Control('speech_speed','relative',.05),'语速调到80%':Control('speech_speed','percent',80),
          '语速设为零点八倍':Control('speech_speed','absolute',.8),'恢复正常语速':Control('speech_speed','absolute',1),
          '当前语数是多少':Control('speech_speed','query'),
          '语数调到百分之八十':Control('speech_speed','percent',80),'语数慢一点':Control('speech_speed','relative',-.05),
          '语数成绩是多少':None,'语数是什么意思':None,'数学的语数是多少':None,
          '现在语速多少':Control('speech_speed','query'),'当前语速是多少':Control('speech_speed','query'),
          '现在雨速多少':None,'现在音量是多少':Control('volume','query'),'再慢一点':Control('speech_speed','repeat',-.05),
          '调到80%':Control(None,'percent',80),'电视音量调到30%':None,'为什么语速慢一点更清楚':None,
          '语速调到百分之一百五十':Control('speech_speed','percent',150)}
        cases.update({'计时器铃声设为柔和':Control('timer_ringtone','choice','gentle'),
          '当前计时器铃声是什么':Control('timer_ringtone','query'),
          '计时器铃声音量调到百分之四十五':Control('timer_volume','percent',45),
          '计时器音量是多少':Control('timer_volume','query')})
        for text, expected in cases.items():
            with self.subTest(text=text): self.assertEqual(expected,parse_control(text))

class ControlTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.values={'volume':35,'speech_speed':.85,'wait_seconds':10,'followup_wait_seconds':15,
                     'timer_volume':100,'timer_ringtone':'classic'}
        async def write(key, value, context): self.values[key]=value;return value
        self.owner=SimpleNamespace(device_id='r1',number=self.values.get,select=self.values.get,
            set_volume=AsyncMock(side_effect=lambda v,c: None),set_speed=AsyncMock())
        async def volume(v,c):return await write('volume',v,c)
        async def speed(v,c):return await write('speech_speed',v,c)
        async def timer_volume(v,c):return await write('timer_volume',v,c)
        async def timer_ringtone(v,c):return await write('timer_ringtone',v,c)
        self.owner.set_volume.side_effect=volume;self.owner.set_speed.side_effect=speed
        self.owner.set_wait=AsyncMock(side_effect=write)
        self.owner.set_timer_volume=AsyncMock(side_effect=timer_volume)
        self.owner.set_timer_ringtone=AsyncMock(side_effect=timer_ringtone)
        self.agent=NativeConversation(SimpleNamespace(entry_id='test',data={'conversation_registry_id':'router'}))
        self.agent.hass=SimpleNamespace(data={'r1_input_guard_interaction':{'test':self.owner}})
    async def ask(self,text,device='r1',session='same'):
        user=conversation.ConversationInput(agent_id='conversation.r1',text=text,context=Context(),
            conversation_id=session,language='zh-CN',device_id=device,satellite_id='assist_satellite.r1')
        return (await self.agent.async_process(user)).response.speech['plain']['speech']
    async def test_exact_percent_speed_and_relative(self):
        self.assertIn('35',await self.ask('音量调到35%'))
        self.assertIn('25',await self.ask('再小一点'))
        self.assertIn('80',await self.ask('语速调到80%'))
        self.assertIn('75',await self.ask('再慢一点'))
        self.assertIn('75',await self.ask('现在语速是多少'))
        self.assertIn('100',await self.ask('恢复正常语速'))
    async def test_ambiguity_identity_bounds_failure_and_context(self):
        self.assertIn('请说明',await self.ask('调到80%'))
        self.assertIn('无法确定',await self.ask('音量调到35%',device='other'))
        self.owner.set_volume.assert_not_awaited()
        self.assertIn('范围',await self.ask('音量调到150%'))
        self.assertIn('范围',await self.ask('语速调到200%'))
        await self.ask('音量调到100%')
        self.assertIn('上限',await self.ask('音量大一点'))
        self.assertIn('请说明',await self.ask('再小一点',session='new'))
        await self.ask('结束对话')
        self.assertIn('请说明',await self.ask('再小一点'))
        self.owner.set_volume.side_effect=HomeAssistantError('offline')
        self.assertIn('未能确认',await self.ask('音量调到35%'))
    async def test_timer_sound_has_confirmed_number_and_select_paths(self):
        self.assertIn('柔和铃声',await self.ask('计时器铃声设为柔和'))
        self.assertEqual('gentle',self.values['timer_ringtone'])
        self.assertIn('45',await self.ask('计时器铃声音量调到百分之四十五'))
        self.assertEqual(45,self.values['timer_volume'])
        self.assertIn('范围',await self.ask('计时器铃声音量调到0%'))

class TtsCacheTest(unittest.TestCase):
    def test_speed_changes_default_options_used_by_ha_cache_key(self):
        from custom_components.r1_input_guard.tts import R1Speech
        value=[.8]
        owner=SimpleNamespace(number=lambda key:value[0],entry=SimpleNamespace(entry_id='test'))
        provider=R1Speech(owner)
        slow=provider.default_options
        value[0]=1.2
        self.assertNotEqual(slow,provider.default_options)
        self.assertEqual(.8,slow['r1_speed'])
        self.assertIn('r1_speed',provider.supported_options)
        self.assertIs(provider.async_supports_streaming_input(),True)


class PendingTtsTest(unittest.TestCase):
    def test_speed_confirmation_updates_only_source_bound_pending_stream(self):
        from custom_components.r1_input_guard.interaction import update_reply_speed
        from homeassistant.components.assist_pipeline.pipeline import KEY_ASSIST_PIPELINE
        user=SimpleNamespace(context=Context(),device_id='r1',satellite_id='satellite.r1',agent_id='conversation.r1')
        def run(device):
            return SimpleNamespace(context=user.context,_device_id=device,_satellite_id=user.satellite_id,
                pipeline=SimpleNamespace(conversation_engine=user.agent_id),tts_stream=SimpleNamespace(options={'r1_speed':.9}))
        mine,other=run('r1'),run('other')
        hass=SimpleNamespace(data={KEY_ASSIST_PIPELINE:SimpleNamespace(pipeline_runs=SimpleNamespace(_pipeline_runs={'pipeline':{'one':mine,'two':other}}))})
        update_reply_speed(hass,user,.8)
        self.assertEqual(.8,mine.tts_stream.options['r1_speed'])
        self.assertEqual(.9,other.tts_stream.options['r1_speed'])


class WaitGrammarTest(unittest.TestCase):
    def test_wait_semantics_are_explicit_and_device_scoped(self):
        for text in ('唤醒后等我二十秒','把首次唤醒等待开口时间设为20秒','第一次唤醒后等待时间改成二十秒',
                     '请帮我把R1的首次等待时间调到20秒','叫醒后等待开口二十秒'):
            with self.subTest(text=text):self.assertEqual(Control('wait_seconds','seconds',20),parse_control(text))
        for text in ('持续对话时等我三十秒','把续听等待时间改成30秒','连续对话等待开口时间调到三十秒','继续对话的时候等我30秒'):
            with self.subTest(text=text):self.assertEqual(Control('followup_wait_seconds','seconds',30),parse_control(text))
        self.assertEqual(Control('wait_seconds','query'),parse_control('唤醒后会等我多久'))
        self.assertEqual(Control('followup_wait_seconds','query'),parse_control('持续对话的等待时间是多少秒'))
        self.assertEqual(Control('wait_seconds','relative',5),parse_control('首次等待时间长一点'))
        self.assertEqual(Control('wait_seconds','relative',5),parse_control('唤醒后多等我五秒'))
        self.assertEqual(Control('followup_wait_seconds','relative',-5),parse_control('续听等待时间缩短5秒'))
        self.assertEqual(Control('wait_seconds','default'),parse_control('恢复首次等待时间默认值'))
        self.assertEqual(Control('followup_wait_seconds','default'),parse_control('续听等待时间恢复默认'))
        self.assertEqual('wait_choice',parse_control('等待时间调到二十秒').target)
        for text in ('设置一个20秒的计时器','电视唤醒后等我二十秒','为什么要等待二十秒'):
            self.assertIsNone(parse_control(text))

class WaitControlTest(ControlTest):
    async def test_independent_values_defaults_query_and_bounds(self):
        self.assertIn('20秒',await self.ask('唤醒后等我二十秒'))
        self.assertEqual(15,self.values['followup_wait_seconds'])
        self.assertIn('30秒',await self.ask('持续对话时等我三十秒'))
        self.assertEqual(20,self.values['wait_seconds'])
        self.assertIn('35秒',await self.ask('再长一点'))
        self.assertIn('20秒',await self.ask('首次等待时间是多少'))
        self.assertIn('请说明',await self.ask('等待时间调到二十秒'))
        self.assertIn('范围',await self.ask('首次等待时间调到0秒'))
        self.assertIn('范围',await self.ask('续听等待时间调到121秒'))
        self.assertIn('10秒',await self.ask('恢复首次等待时间默认值'))
        self.assertIn('15秒',await self.ask('恢复续听等待时间默认值'))
        self.assertEqual({'volume':35,'speech_speed':.85,'wait_seconds':10,'followup_wait_seconds':15,
                          'timer_volume':100,'timer_ringtone':'classic'},self.values)
