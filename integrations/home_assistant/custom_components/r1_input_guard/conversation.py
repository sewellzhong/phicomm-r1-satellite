"""Source-bound short-lived conversation IDs around the existing household router."""
import asyncio
from collections import OrderedDict
import time
import unicodedata
from uuid import uuid4
from homeassistant.components import conversation
from homeassistant.helpers import entity_registry as er, intent
from homeassistant.exceptions import HomeAssistantError

_END = {"结束对话", "取消本次对话", "取消这次对话", "不用回答了"}

def is_end(text):
    value = unicodedata.normalize("NFKC", text).casefold()
    value = "".join(c for c in value if unicodedata.category(c).startswith("L") or c.isdecimal())
    return value in _END

async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([NativeConversation(entry)])

class NativeConversation(conversation.ConversationEntity):
    _attr_name = "R1 原生会话"
    _attr_supports_streaming = False
    _attr_supported_features = conversation.ConversationEntityFeature.CONTROL
    TTL = 900
    MAX_SESSIONS = 256

    def __init__(self, entry):
        self._attr_unique_id = entry.entry_id + "-conversation"
        self._target_id = entry.data["conversation_registry_id"]
        self._entry_id = entry.entry_id
        self._sessions = OrderedDict()
        self._busy = set()
        self._controls = {}
        self._last_control_diagnostic = {}
        self._clock = time.monotonic
        self._unloaded = False

    @property
    def supported_languages(self):
        return ["zh", "zh-CN", "zh-HK", "zh-TW"]

    async def async_process(self, user_input):
        if self._unloaded:
            raise HomeAssistantError("r1_conversation_unloaded")
        now = self._clock()
        for old, (_, stamp) in list(self._controls.items()):
            if now - stamp > 60: self._controls.pop(old, None)
        if len(self._controls) >= self.MAX_SESSIONS: self._controls.pop(next(iter(self._controls)))
        outer = user_input.conversation_id or uuid4().hex
        key = (user_input.context.user_id, user_input.device_id, user_input.satellite_id, outer)
        if key in self._busy:
            raise HomeAssistantError("r1_conversation_busy")
        # Bound active and retained sessions; do not evict an in-flight conversation.
        for old in list(self._sessions):
            if old not in self._busy and now - self._sessions[old][1] >= self.TTL:
                del self._sessions[old]
                self._controls.pop(old, None)
        while key not in self._sessions and len(self._sessions) >= self.MAX_SESSIONS:
            victim = next((item for item in self._sessions if item not in self._busy), None)
            if victim is None:
                raise HomeAssistantError("r1_conversation_capacity")
            del self._sessions[victim]
        if is_end(user_input.text):
            self._controls.pop(key, None)
            self._sessions.pop(key, None)
            response = intent.IntentResponse(language=user_input.language)
            response.async_set_speech("")
            return conversation.ConversationResult(response=response, conversation_id=outer, continue_conversation=False)
        from .interaction import bridge
        from .controls import parse_control
        owner = bridge(self.hass, self._entry_id) if hasattr(self.hass, 'data') else None
        command = parse_control(user_input.text)
        self._last_control_diagnostic = {"matched": command is not None, "device_id": user_input.device_id,
            "satellite_id": user_input.satellite_id, "bound_device": owner.device_id if owner else None,
            "target": command.target if command else None}
        previous = self._controls.pop(key, None)
        if previous and now - previous[1] > 60: previous = None
        if command:
            def answer(text):
                response = intent.IntentResponse(language=user_input.language)
                response.async_set_speech(text)
                return conversation.ConversationResult(response=response, conversation_id=outer, continue_conversation=True)
            if not owner or not owner.device_id or user_input.device_id != owner.device_id:
                return answer('无法确定要调节的音箱，请通过R1发出指令。')
            time_targets = ('wait_seconds','followup_wait_seconds')
            if command.target == 'wait_choice':
                return answer('请说明首次唤醒等待时间，还是持续对话等待时间，例如：首次等待时间调到二十秒。')
            target = command.target or (previous[0] if previous else None)
            if command.operation == 'repeat_seconds' and target not in time_targets:
                return answer('请说明要延长或缩短首次唤醒等待时间，还是持续对话等待时间。')
            if target is None or command.operation == 'repeat' and (not previous or previous[0] != target):
                return answer('请说明要调节音量还是语速，以及要调到多少。')
            label = {'volume':'音量','speech_speed':'语速','wait_seconds':'首次唤醒等待开口时间','followup_wait_seconds':'持续对话等待开口时间'}[target]
            current = owner.number(target)
            if current is None: return answer(f'{label}暂时不可用，没有修改设置。')
            self._busy.add(key)
            try:
                if command.operation == 'query':
                    value = current
                else:
                    value = command.value
                    if command.operation in ('relative', 'repeat', 'repeat_seconds'): value += current
                    elif command.operation == 'default': value = 10 if target == 'wait_seconds' else 15
                    elif command.operation == 'percent' and target == 'speech_speed': value /= 100
                    elif command.operation == 'percent' and target in time_targets:
                        return answer('等待时间请用秒设置，并说明首次唤醒还是持续对话。')
                    low, high = (1,120) if target in time_targets else (0, 100) if target == 'volume' else (.5, 1.5)
                    if command.operation in ('relative', 'repeat', 'repeat_seconds'):
                        value = max(low, min(high, value))
                        if abs(value-current) < .002:
                            self._controls[key] = (target, now)
                            return answer(f'{label}已经达到' + ('上限。' if command.value > 0 else '下限。'))
                    elif not low <= value <= high:
                        return answer(f'{label}范围是' + ('一秒到一百二十秒。' if target in time_targets else '百分之零到百分之一百。' if target == 'volume' else '百分之五十到百分之一百五十。'))
                    requested = value
                    value = await (owner.set_wait(target,value,user_input.context) if target in time_targets
                                   else owner.set_volume(value, user_input.context) if target == 'volume'
                                   else owner.set_speed(value, user_input.context))
                    if target == 'speech_speed':
                        from .interaction import update_reply_speed
                        update_reply_speed(self.hass, user_input, value)
                    self._controls[key] = (target, now)
                if target in time_targets:
                    return answer(f'{label}现在是{round(value)}秒。' + ('' if command.operation == 'query' else '下一轮收音生效。'))
                percent = round(value if target == 'volume' else value * 100)
                rounded = command.operation != 'query' and abs(value-requested) > .002
                return answer(f'{label}' + ('采用最接近的档位，已调到' if rounded else '现在是') + f'百分之{percent}。')
            except HomeAssistantError:
                return answer(f'未能确认{label}设置，请稍后重试。')
            finally:
                self._busy.discard(key)
        # An unrelated valid topic invalidates relative setting shorthand.
        registered = er.async_get(self.hass).async_get(self._target_id)
        if registered is None or registered.platform != "conversation_router" or registered.disabled:
            raise HomeAssistantError("r1_conversation_source_unavailable")
        inner, _ = self._sessions.pop(key, (uuid4().hex, now))
        self._sessions[key] = (inner, now)
        self._busy.add(key)
        try:
            async with asyncio.timeout(60):
                result = await conversation.async_converse(
                    hass=self.hass, text=user_input.text, conversation_id=inner,
                    context=user_input.context, language=user_input.language,
                    agent_id=registered.entity_id, device_id=user_input.device_id,
                    satellite_id=user_input.satellite_id,
                )
            if self._unloaded:
                raise HomeAssistantError("r1_conversation_unloaded")
            self._sessions[key] = (result.conversation_id or inner, now)  # Match the hub: TTL since last input.
            return conversation.ConversationResult(response=result.response, conversation_id=outer,
                continue_conversation=result.continue_conversation)
        except BaseException:
            self._sessions.pop(key, None)
            raise
        finally:
            self._busy.discard(key)

    async def async_will_remove_from_hass(self):
        self._unloaded = True
        self._sessions.clear()
        self._controls.clear()
        await super().async_will_remove_from_hass()
