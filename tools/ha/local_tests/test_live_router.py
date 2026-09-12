"""Unmodified live router control flow with in-memory HA/model/device dependencies."""
import ast
import hashlib
import importlib.util
from pathlib import Path
from collections import OrderedDict
from types import SimpleNamespace, ModuleType, MethodType
from time import monotonic
from uuid import uuid4
from unittest.mock import AsyncMock,patch
import sys
import unittest
from homeassistant.core import Context
from homeassistant.components import conversation
from homeassistant.helpers import intent
from custom_components.r1_input_guard.conversation import NativeConversation

ROOT=Path(__file__).resolve().parents[3] / 'local-deps/ha-live-routing-2026-09-06'

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec)
    sys.modules[name]=module;spec.loader.exec_module(module);return module

class LiveRouterTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.original={k:v for k,v in sys.modules.items() if k.startswith(('custom_components.domestic_ai','custom_components.conversation_router'))}
        for name in ['domestic_ai','conversation_router']:
            package=ModuleType('custom_components.'+name);package.__path__=[str(ROOT/name)]
            sys.modules[package.__name__]=package
        def speech(user,outer,text,follow=False):
            response=intent.IntentResponse(language=user.language);response.async_set_speech(text)
            return conversation.ConversationResult(response=response,conversation_id=outer,continue_conversation=follow)
        helper=ModuleType('custom_components.domestic_ai.conversation');helper.speech_result=speech;helper.action_speech=lambda result:'fixture action result'
        sys.modules[helper.__name__]=helper
        self.module=load('custom_components.conversation_router.conversation',ROOT/'conversation_router/conversation.py')
        # Execute the real hub session method without loading external model/network clients.
        tree=ast.parse((ROOT/'domestic_ai/hub.py').read_text())
        method=next(n for cls in tree.body if isinstance(cls,ast.ClassDef) for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='session')
        scope={'hashlib':hashlib,'monotonic':monotonic,'uuid4':uuid4}
        exec(compile(ast.Module(body=[method],type_ignores=[]),'live_hub_session','exec'),scope)
        self.hub=SimpleNamespace(sessions=OrderedDict(),check=AsyncMock(side_effect=ValueError('control_disabled')),execute=AsyncMock(),entities=AsyncMock(return_value=[{'entity_id':'light.fixture','name':'测试灯','aliases':[],'area_id':'room'}]))
        self.hub.session=MethodType(scope['session'],self.hub)
        self.hass=SimpleNamespace(data={'domestic_ai':{'one':SimpleNamespace(hub=self.hub)}})
        self.router=self.module.HomeAIConversationRouter(SimpleNamespace(entry_id='router',options={'cloud_agent':'conversation.cloud','cloud_timeout':45}))
        self.router.hass=self.hass;self.router.async_write_ha_state=lambda:None
        self.adapter=NativeConversation(SimpleNamespace(entry_id='native',data={'conversation_registry_id':'router-uuid'}));self.adapter.hass=self.hass
        self.registry=patch('custom_components.r1_input_guard.conversation.er.async_get').start()
        self.registry.return_value.async_get.side_effect=lambda value:SimpleNamespace(entity_id='conversation.router' if value=='router-uuid' else 'conversation.cloud',platform='conversation_router' if value=='router-uuid' else 'domestic_ai',disabled=False)
        self.calls=[]
        async def dispatch(**kw):
            self.calls.append(kw)
            user=conversation.ConversationInput(agent_id=kw['agent_id'],text=kw['text'],context=kw['context'],conversation_id=kw['conversation_id'],language=kw['language'],device_id=kw['device_id'],satellite_id=kw['satellite_id'])
            if kw['agent_id']=='conversation.router':return await self.router.async_process(user)
            return speech(user,user.conversation_id,'模型测试回复',True)
        patch('custom_components.r1_input_guard.conversation.conversation.async_converse',new=dispatch).start()
        self.addCleanup(self.cleanup)

    def cleanup(self):
        patch.stopall()
        for name in list(sys.modules):
            if name.startswith(('custom_components.domestic_ai','custom_components.conversation_router')):sys.modules.pop(name)
        sys.modules.update(self.original)

    def user(self,text):
        return conversation.ConversationInput(agent_id='conversation.native',text=text,context=Context(user_id='fixture-user'),conversation_id='outer',language='zh-CN',device_id='r1',satellite_id='assist_satellite.r1')

    async def test_actual_router_delegates_and_uses_same_source_bound_hub_session(self):
        # Bind the capability decision to the retained, unmodified household
        # router source. This snapshot must stay on the public non-streaming
        # path until that external component exposes a real incremental API.
        self.assertFalse(self.router.supports_streaming)
        with patch('custom_components.r1_input_guard.conversation.conversation.async_get_agent',
                   return_value=self.router):
            self.assertFalse(self.adapter.supports_streaming)
        await self.adapter.async_process(self.user('解释一下月亮为什么发光'))
        await self.adapter.async_process(self.user('再解释一下'))
        self.assertEqual(1,len(self.hub.sessions))
        self.assertEqual(4,len(self.calls))
        self.assertEqual(self.calls[0]['conversation_id'],self.calls[2]['conversation_id'])
        self.assertEqual(self.calls[0]['context'],self.calls[1]['context'])
        self.assertEqual('assist_satellite.r1',self.calls[1]['satellite_id'])
        self.hub.execute.assert_not_awaited()

    async def test_control_denial_is_preserved_and_never_falls_back_to_model(self):
        match=SimpleNamespace(intent=SimpleNamespace(name='HassTurnOn'),entities_list=[SimpleNamespace(name='name',value='测试灯')],unmatched_entities=[])
        with patch.object(self.module,'async_get_agent',return_value=SimpleNamespace(async_recognize_intent=AsyncMock(return_value=match))):
            result=await self.adapter.async_process(self.user('打开测试灯'))
        self.assertIn('未执行',result.response.speech['plain']['speech'])
        self.hub.check.assert_awaited_once();self.hub.execute.assert_not_awaited()
        self.assertEqual(1,len(self.calls))

if __name__=='__main__':unittest.main()
