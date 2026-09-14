import hashlib
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from homeassistant.exceptions import HomeAssistantError
from custom_components.r1_input_guard.interaction import Interaction


class AlertAudioTest(unittest.IsolatedAsyncioTestCase):
    async def test_upload_is_chunked_hash_bound_and_optionally_binds_timer(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name) / 'r1-alert-audio'; root.mkdir()
        data = b'RIFF' + b'0' * 60000
        (root / 'tea.wav').write_bytes(data)
        owner = Interaction.__new__(Interaction)
        async def executor(function): return function()
        owner.hass = SimpleNamespace(config=SimpleNamespace(path=lambda value: str(root)),
                                     async_add_executor_job=executor)
        owner._alert_audio_lock = __import__('asyncio').Lock()
        owner.listeners = set(); owner.alert_audio_state = None
        calls = []
        async def call(operation, **values):
            calls.append((operation, values))
            state = {'schema':1,'items':[],'timer_sound_id':'','upload_active':operation != 'commit'}
            if operation in ('commit','timer_bind'):
                state['items']=[{'id':'tea-ready','size':len(data),'sha256':hashlib.sha256(data).hexdigest()}]
                state['upload_active']=False
            if operation == 'timer_bind': state['timer_sound_id']='tea-ready'
            return state
        owner._alert_audio_call = AsyncMock(side_effect=call)
        result = await owner.upload_alert_audio('tea-ready','tea.wav',bind_timer=True)
        self.assertEqual('tea-ready',result['timer_sound_id'])
        self.assertEqual(['begin','chunk','chunk','chunk','commit','timer_bind'],[item[0] for item in calls])
        chunks=[item[1] for item in calls if item[0]=='chunk']
        self.assertEqual([0,24576,49152],[item['offset'] for item in chunks])
        self.assertTrue(all(len(item['data']) <= 32768 for item in chunks))

    def test_response_validation_rejects_duplicate_or_unbounded_items(self):
        request='a'*32
        item={'id':'music','size':100,'sha256':'b'*64}
        good={'schema':1,'request_id':request,'operation':'status','items':[item], 'timer_sound_id':'music',
              'upload_active':False,'upload_id':'','upload_received':0}
        self.assertEqual(good,Interaction._validated_alert_audio_state(good,request,'status'))
        bad={**good,'items':[item,item]}
        with self.assertRaises(HomeAssistantError): Interaction._validated_alert_audio_state(bad,request,'status')
        bad={**good,'items':[{**item,'size':17*1024*1024}]}
        with self.assertRaises(HomeAssistantError): Interaction._validated_alert_audio_state(bad,request,'status')
        for bad in ({**good,'upload_active':True},
                    {**good,'upload_id':'music','upload_received':-1},
                    {**good,'upload_id':'Bad ID','upload_active':True}):
            with self.assertRaises(HomeAssistantError):
                Interaction._validated_alert_audio_state(bad,request,'status')

    async def test_upload_path_is_confined_to_dedicated_directory(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        root=Path(temporary.name)/'r1-alert-audio';root.mkdir()
        owner=Interaction.__new__(Interaction)
        owner.hass=SimpleNamespace(config=SimpleNamespace(path=lambda value:str(root)))
        with self.assertRaises(HomeAssistantError):
            await owner.upload_alert_audio('music','../outside.wav')


if __name__ == '__main__': unittest.main()
