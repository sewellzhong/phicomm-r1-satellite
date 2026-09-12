"""Device-bound HA 2026.8.2 compatibility bridge."""
import asyncio
from datetime import timedelta
import json
import math
import re
from uuid import uuid4
from aioesphomeapi import APIConnectionError
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er, device_registry as dr
from homeassistant.helpers.event import async_track_time_interval, async_track_state_change_event
from homeassistant.helpers.entity import DeviceInfo
from .alarm_pending import AlarmPending, editable, valid_editable


def bridge(hass, entry_id):
    return hass.data.get('r1_input_guard_interaction', {}).get(entry_id)


class Interaction:
    def __init__(self, hass, entry):
        self.hass = hass
        self.entry = entry
        self.mac = entry.data['interaction_mac'].lower()
        self.listeners = set()
        self.device_id = None
        self._busy = False
        self._closed = False
        self._wake_cancel = None
        self._adapted_satellite = None
        self._original_vad_resolver = None
        self._vad_resolver = None
        self.alarm_state = None
        self.alarm_sync_status = 'connecting'
        self.alarm_last_error = None
        self._alarm_lock = asyncio.Lock()
        self.alarm_pending = AlarmPending(hass, entry.entry_id)
        self.resolve()
        self.cancel = async_track_time_interval(hass, self.refresh, timedelta(seconds=5))
        self.task = entry.async_create_background_task(hass, self._initialize(), 'r1-interaction-config')

    async def _initialize(self):
        try:
            await self.alarm_pending.load()
        except HomeAssistantError:
            self.alarm_sync_status = 'conflict'
            self.alarm_last_error = 'pending_store_invalid'
            for listener in tuple(self.listeners): listener()
            return
        await self.refresh(None)

    def resolve(self):
        registry = er.async_get(self.hass)
        item = next((e for e in registry.entities.values() if e.platform == 'esphome'
                     and e.unique_id.lower() == self.mac + '-pipeline'), None)
        self.device_id = item.device_id if item else None
        return registry

    def entity(self, suffix, domain='number'):
        registry = self.resolve()
        if not self.device_id: return None
        label = {'wait_seconds':'等待开口时间', 'quiet_seconds':'讲话结束停顿时间',
                 'command_seconds':'单条命令总时长', 'followup_wait_seconds':'持续对话等待开口时间', 'volume':'音量', 'speech_speed':'语速', 'wake_generation':'唤醒会话序号'}.get(suffix)
        matches = [e.entity_id for e in registry.entities.values() if e.platform == 'esphome'
                   and e.device_id == self.device_id and e.domain == domain
                   and (e.unique_id.lower().endswith('-' + suffix) or (label is not None and e.unique_id == self.mac.upper() + '/0/' + domain + '/' + label))]
        return matches[0] if len(matches) == 1 else None

    @property
    def device_info(self):
        self.resolve()
        device = dr.async_get(self.hass).async_get(self.device_id) if self.device_id else None
        return None  # HA 2026.8: a DeviceInfo would register another integration-owned device.

    def number(self, suffix):
        entity_id = self.entity(suffix)
        state = self.hass.states.get(entity_id) if entity_id else None
        if state is None or state.state in ('unknown', 'unavailable'): return None
        try: value = float(state.state)
        except ValueError: return None
        return value if math.isfinite(value) else None

    async def set_volume(self, percent, context=None):
        target = self.entity('volume')
        if target is None or self.number('volume') is None: raise HomeAssistantError('r1_volume_unavailable')
        if not math.isfinite(percent): raise HomeAssistantError('r1_volume_invalid')
        percent = max(0, min(100, percent))
        await self.hass.services.async_call('number', 'set_value', {'entity_id': target, 'value': percent},
                                             blocking=True, context=context)
        expected = math.floor(percent + .5)
        for _ in range(30):
            actual = self.number('volume')
            if actual is not None and abs(actual - expected) < .05: return actual
            await asyncio.sleep(.1)
        raise HomeAssistantError('r1_volume_not_confirmed')

    async def set_speed(self, value, context=None):
        target = self.entity('speech_speed')
        if target is None or self.number('speech_speed') is None:
            raise HomeAssistantError('r1_speed_unavailable')
        if not math.isfinite(value) or not .5 <= value <= 1.5:
            raise HomeAssistantError('r1_speed_invalid')
        expected = math.floor(value * 20 + .5) / 20
        await self.hass.services.async_call('number', 'set_value',
            {'entity_id': target, 'value': expected}, blocking=True, context=context)
        for _ in range(30):
            actual = self.number('speech_speed')
            if actual is not None and abs(actual - expected) < .002: return actual
            await asyncio.sleep(.1)
        raise HomeAssistantError('r1_speed_not_confirmed')

    async def set_wait(self, target_key, value, context=None):
        if target_key not in ('wait_seconds', 'followup_wait_seconds'):
            raise HomeAssistantError('r1_wait_target_invalid')
        target = self.entity(target_key)
        if target is None or self.number(target_key) is None: raise HomeAssistantError('r1_wait_unavailable')
        if not math.isfinite(value) or not 1 <= value <= 120: raise HomeAssistantError('r1_wait_invalid')
        expected = math.floor(value + .5)
        await self.hass.services.async_call('number','set_value',{'entity_id':target,'value':expected},blocking=True,context=context)
        for _ in range(30):
            actual = self.number(target_key)
            if actual is not None and abs(actual-expected)<.002: return actual
            await asyncio.sleep(.1)
        raise HomeAssistantError('r1_wait_not_confirmed')

    def alarm_service(self):
        """Resolve the generated ESPHome service through the bound MAC, never by display name."""
        entries = [item for item in self.hass.config_entries.async_entries('esphome')
                   if (item.unique_id or '').lower() == self.mac]
        if len(entries) != 1: return None
        info = getattr(getattr(entries[0], 'runtime_data', None), 'device_info', None)
        name = getattr(info, 'name', None)
        if not name or not re.fullmatch(r'[a-z][a-z0-9-]{0,30}', name): return None
        service = name.replace('-', '_') + '_alarm_sync'
        return service if self.hass.services.has_service('esphome', service) else None

    async def alarm_request(self, operation, **values):
        if operation not in ('status', 'put', 'delete', 'enable', 'stop', 'snooze'):
            raise HomeAssistantError('r1_alarm_operation_invalid')
        async with self._alarm_lock:
            try:
                state = await self._alarm_page(operation, values)
                alarms = list(state['alarms'])
                while not state['page_complete']:
                    page = await self._alarm_page('status', {
                        'expected_version': state['version'], 'page_offset': len(alarms)})
                    if page['version'] != state['version'] or page['page_offset'] != len(alarms):
                        raise HomeAssistantError('r1_alarm_response_stale')
                    alarms.extend(page['alarms'])
                    state['page_complete'] = page['page_complete']
                if len(alarms) != state['alarm_count']:
                    raise HomeAssistantError('r1_alarm_response_invalid')
                if len({alarm['id'] for alarm in alarms}) != len(alarms):
                    raise HomeAssistantError('r1_alarm_response_invalid')
                state['alarms'] = alarms
                state['page_offset'] = 0
            except (TimeoutError, HomeAssistantError, ConnectionError, APIConnectionError) as error:
                cause = error
                transport = False
                while cause is not None:
                    if isinstance(cause, (TimeoutError, ConnectionError, APIConnectionError)):
                        transport = True
                        break
                    cause = cause.__cause__
                self.alarm_sync_status = 'offline'
                self.alarm_last_error = 'transport_failed' if transport else 'request_failed'
                for listener in tuple(self.listeners): listener()
                raise HomeAssistantError('r1_alarm_not_confirmed')
            self.alarm_state = state
            self.alarm_sync_status = 'synced'
            self.alarm_last_error = None
            for listener in tuple(self.listeners): listener()
            return state

    async def alarm_write(self, operation, **values):
        """Write immediately only from a confirmed baseline; otherwise persist desired state."""
        if operation not in ('put', 'delete', 'enable'):
            return await self.alarm_request(operation, **values)
        pending = self.alarm_pending.items()
        if pending or self.alarm_sync_status != 'synced' or self.alarm_service() is None:
            await self.alarm_pending.queue(operation, values, self.alarm_state)
            self.alarm_sync_status = 'pending'
            self.alarm_last_error = 'not_delivered'
            for listener in tuple(self.listeners): listener()
            raise HomeAssistantError('r1_alarm_pending')
        try:
            return await self.alarm_request(operation, **values)
        except HomeAssistantError:
            if self.alarm_last_error != 'transport_failed':
                raise
            await self.alarm_pending.queue(operation, values, self.alarm_state)
            self.alarm_sync_status = 'pending'
            self.alarm_last_error = 'not_delivered'
            for listener in tuple(self.listeners): listener()
            raise HomeAssistantError('r1_alarm_pending')

    async def discard_alarm_pending(self, id=''):
        await self.alarm_pending.discard(id)
        self.alarm_sync_status = 'connecting' if self.alarm_pending.items() else 'offline'
        self.alarm_last_error = None if not self.alarm_pending.items() else 'not_delivered'
        for listener in tuple(self.listeners): listener()

    async def replay_alarm_pending(self):
        """Apply pending desired state only when every remote item still matches its baseline."""
        items = self.alarm_pending.items()
        if not items:
            return self.alarm_state
        remote = {item['id']: editable(item) for item in self.alarm_state['alarms']}
        for item in items:
            if item['blocked']:
                self.alarm_sync_status = 'conflict'
                self.alarm_last_error = 'pending_blocked'
                for listener in tuple(self.listeners): listener()
                raise HomeAssistantError('r1_alarm_pending_conflict')
            actual = remote.get(item['id'])
            if actual != item['base'] and actual != item['desired']:
                await self.alarm_pending.block(item['id'])
                self.alarm_sync_status = 'conflict'
                self.alarm_last_error = 'remote_changed'
                for listener in tuple(self.listeners): listener()
                raise HomeAssistantError('r1_alarm_pending_conflict')
        for item in items:
            actual = next((editable(value) for value in self.alarm_state['alarms']
                           if value['id'] == item['id']), None)
            desired = item['desired']
            if actual != desired:
                version = self.alarm_state['version']
                if desired is None:
                    operation = ('delete', {'id': item['id'], 'expected_version': version})
                else:
                    operation = ('put', {**desired, 'expected_version': version})
                try:
                    await self.alarm_request(operation[0], **operation[1])
                except HomeAssistantError:
                    if self.alarm_last_error != 'transport_failed':
                        await self.alarm_pending.block(item['id'])
                        self.alarm_sync_status = 'conflict'
                        self.alarm_last_error = 'device_rejected'
                        for listener in tuple(self.listeners): listener()
                        raise HomeAssistantError('r1_alarm_pending_conflict')
                    raise
            await self.alarm_pending.discard(item['id'])
        self.alarm_sync_status = 'synced'
        self.alarm_last_error = None
        for listener in tuple(self.listeners): listener()
        return self.alarm_state

    async def _alarm_page(self, operation, values):
        service = self.alarm_service()
        if service is None: raise HomeAssistantError('r1_alarm_unavailable')
        request_id = uuid4().hex
        request = {'request_id': request_id, 'operation': operation, **values}
        encoded = json.dumps(request, ensure_ascii=False, separators=(',', ':'))
        if len(encoded.encode()) > 4096: raise HomeAssistantError('r1_alarm_request_too_large')
        response = await self.hass.services.async_call('esphome', service,
            {'request': encoded}, blocking=True, return_response=True)
        return self._validated_alarm_state(response, request_id, operation)

    @staticmethod
    def _validated_alarm_state(value, request_id, operation):
        if not isinstance(value, dict) or value.get('request_id') != request_id \
                or value.get('operation') != operation or value.get('schema') != 1:
            raise HomeAssistantError('r1_alarm_response_invalid')
        version, alarms = value.get('version'), value.get('alarms')
        offset, complete = value.get('page_offset'), value.get('page_complete')
        if not isinstance(version, int) or version < 0 or not isinstance(alarms, list) or len(alarms) > 4 \
                or not isinstance(offset, int) or offset < 0 or not isinstance(complete, bool):
            raise HomeAssistantError('r1_alarm_response_invalid')
        count = value.get('alarm_count')
        if not isinstance(count, int) or count < offset + len(alarms) or count > 32 \
                or complete != (offset + len(alarms) == count):
            raise HomeAssistantError('r1_alarm_response_invalid')
        seen = set()
        for alarm in alarms:
            if not isinstance(alarm, dict) or not isinstance(alarm.get('id'), str) \
                    or not alarm['id'] or alarm['id'] in seen:
                raise HomeAssistantError('r1_alarm_response_invalid')
            seen.add(alarm['id'])
            try: alarm_fields = editable(alarm)
            except KeyError: raise HomeAssistantError('r1_alarm_response_invalid')
            if not valid_editable(alarm_fields) or type(alarm.get('revision')) is not int \
                    or alarm['revision'] < 0 or alarm['revision'] > version:
                raise HomeAssistantError('r1_alarm_response_invalid')
        return value

    def reconcile_device(self):
        if not self.device_id: return
        registry = er.async_get(self.hass)
        devices = dr.async_get(self.hass)
        # Never remove a named device, a child, an entity owner, or an unrelated entry.
        for old in list(devices.devices.values()):
            if (old.id != self.device_id and old.primary_config_entry == self.entry.entry_id
                    and not old.name and not old.name_by_user
                    and old.identifiers == {('r1_input_guard', self.mac)}
                    and not old.connections
                    and not any(e.device_id == old.id for e in registry.entities.values())
                    and not any(d.via_device_id == old.id for d in devices.devices.values())
                    and old.config_entries <= {self.entry.entry_id}):
                devices.async_remove_device(old.id)
        for item in registry.entities.values():
            if item.config_entry_id == self.entry.entry_id and item.domain == 'media_player' and item.device_id != self.device_id:
                registry.async_update_entity(item.entity_id, device_id=self.device_id)

    def adapt_satellite(self, satellite):
        if satellite is self._adapted_satellite: return
        self.restore_satellite()
        if satellite is None: return
        # Fixed HA 2026.8.2: the standard resolver raises for a disabled VAD select.
        # Native STT does not use HA segmentation. A fallback pipeline still gets
        # this device's real trailing-silence setting, never a missing UI entity.
        self._adapted_satellite = satellite
        self._original_vad_resolver = satellite._resolve_vad_sensitivity
        self._vad_resolver = lambda: self.number('quiet_seconds') or 1.8
        satellite._resolve_vad_sensitivity = self._vad_resolver

    def restore_satellite(self):
        if (self._adapted_satellite is not None
                and self._adapted_satellite._resolve_vad_sensitivity is self._vad_resolver):
            self._adapted_satellite._resolve_vad_sensitivity = self._original_vad_resolver
        self._adapted_satellite = None
        self._original_vad_resolver = None
        self._vad_resolver = None

    async def refresh(self, _now):
        if self._busy or self._closed: return
        self._busy = True
        try:
            registry = self.resolve()
            self.reconcile_device()
            satellite_id = self.entity('assist_satellite', 'assist_satellite')
            component = self.hass.data.get('assist_satellite')
            satellite = component.get_entity(satellite_id) if component and satellite_id else None
            self.adapt_satellite(satellite)
            wake_id = self.entity('wake_generation', 'sensor')
            if wake_id and self._wake_cancel is None:
                @callback
                def new_wake(event):
                    old, new = event.data.get('old_state'), event.data.get('new_state')
                    if old and new and old.state == new.state: return
                    from homeassistant.components import conversation
                    component = self.hass.data.get(conversation.DATA_COMPONENT)
                    if component:
                        for agent in component.entities:
                            if getattr(agent, '_entry_id', None) == self.entry.entry_id:
                                agent._controls.clear()
                self._wake_cancel = async_track_state_change_event(self.hass, wake_id, new_wake)
            for suffix in ('pipeline_2', 'wake_word_2', 'vad_sensitivity'):
                entity_id = self.entity(suffix, 'select')
                item = registry.async_get(entity_id) if entity_id else None
                if item and item.disabled_by is None and (suffix != 'vad_sensitivity' or satellite is not None):
                    registry.async_update_entity(entity_id, disabled_by=er.RegistryEntryDisabler.INTEGRATION)
            initial_wait_id = self.entity('wait_seconds')
            if initial_wait_id:
                item = registry.async_get(initial_wait_id)
                if item.name in (None, '等待开口时间'):
                    registry.async_update_entity(initial_wait_id, name='首次唤醒等待开口时间')
            volume_id = self.entity('volume')
            if volume_id:
                item = registry.async_get(volume_id)
                if item.options.get('number', {}).get('display_precision') != 0:
                    registry.async_update_entity_options(volume_id, 'number',
                        {**item.options.get('number', {}), 'display_precision': 0})
            satellite_id = self.entity('assist_satellite', 'assist_satellite')
            component = self.hass.data.get('assist_satellite')
            satellite = component.get_entity(satellite_id) if component and satellite_id else None
            # Fixed-version adapter: ANNOUNCE devices expose wake configuration here.
            if satellite is not None and satellite.available:
                async with asyncio.timeout(12): await satellite._update_satellite_config()
            try:
                await self.alarm_request('status')
                await self.replay_alarm_pending()
            except HomeAssistantError: pass
            for listener in tuple(self.listeners): listener()
        except (TimeoutError, HomeAssistantError, ConnectionError, APIConnectionError):
            pass
        finally:
            self._busy = False

    async def close(self):
        self._closed = True
        self.restore_satellite()
        self.cancel()
        if self._wake_cancel: self._wake_cancel()
        self.task.cancel()
        await asyncio.gather(self.task, return_exceptions=True)
        self.listeners.clear()


def update_reply_speed(hass, user_input, speed):
    """HA 2026.8.2 prepares TTS before STT; update only this run before its reply is cached."""
    from homeassistant.components.assist_pipeline import pipeline as pipelines
    data = hass.data.get(pipelines.KEY_ASSIST_PIPELINE)
    if data is None: return
    for runs in data.pipeline_runs._pipeline_runs.values():
        for run in runs.values():
            if (run.context.id == user_input.context.id
                    and run._device_id == user_input.device_id
                    and run._satellite_id == user_input.satellite_id
                    and run.pipeline.conversation_engine == user_input.agent_id
                    and run.tts_stream is not None):
                run.tts_stream.options['r1_speed'] = round(speed, 2)
