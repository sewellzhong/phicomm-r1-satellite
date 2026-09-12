"""Confirmed full-list view and entity actions for R1-owned local alarms."""
import voluptuous as vol
from homeassistant.components.sensor import SensorEntity
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv, entity_platform
from .interaction import bridge


async def async_setup_entry(hass, entry, async_add_entities):
    owner = bridge(hass, entry.entry_id)
    if not owner: return
    async_add_entities([R1Alarms(owner), R1DoNotDisturb(owner), R1SystemStatus(owner)])
    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service('alarm_refresh', None, 'async_alarm_refresh')
    platform.async_register_entity_service('alarm_put', {
        vol.Required('id'): cv.string, vol.Optional('name', default=''): cv.string,
        vol.Optional('date', default=''): cv.string, vol.Required('hour'): vol.All(vol.Coerce(int), vol.Range(min=0, max=23)),
        vol.Required('minute'): vol.All(vol.Coerce(int), vol.Range(min=0, max=59)),
        vol.Optional('weekdays', default=0): vol.All(vol.Coerce(int), vol.Range(min=0, max=127)),
        vol.Optional('enabled', default=True): cv.boolean,
        vol.Optional('snooze_minutes', default=10): vol.All(vol.Coerce(int), vol.Range(min=1, max=60)),
        vol.Optional('ringtone', default='classic'): vol.In(('classic', 'gentle', 'urgent')),
        vol.Optional('volume_percent', default=100): vol.All(vol.Coerce(int), vol.Range(min=1, max=100)),
        vol.Optional('expected_version'): vol.All(vol.Coerce(int), vol.Range(min=0)),
    }, 'async_alarm_put')
    platform.async_register_entity_service('alarm_delete', {
        vol.Required('id'): cv.string, vol.Optional('expected_version'): vol.All(vol.Coerce(int), vol.Range(min=0)),
    }, 'async_alarm_delete')
    platform.async_register_entity_service('alarm_enable', {
        vol.Required('id'): cv.string, vol.Required('enabled'): cv.boolean,
        vol.Optional('expected_version'): vol.All(vol.Coerce(int), vol.Range(min=0)),
    }, 'async_alarm_enable')
    platform.async_register_entity_service('alarm_stop', {vol.Optional('id', default=''): cv.string}, 'async_alarm_stop')
    platform.async_register_entity_service('alarm_snooze', {
        vol.Optional('id', default=''): cv.string,
        vol.Optional('minutes'): vol.All(vol.Coerce(int), vol.Range(min=1, max=60)),
    }, 'async_alarm_snooze')
    platform.async_register_entity_service('alarm_pending_discard', {
        vol.Optional('id', default=''): cv.string,
    }, 'async_alarm_pending_discard')
    platform.async_register_entity_service('dnd_refresh', None, 'async_dnd_refresh')
    platform.async_register_entity_service('dnd_set', {
        vol.Required('manual'): cv.boolean,
        vol.Required('schedule_enabled'): cv.boolean,
        vol.Required('start_hour'): vol.All(vol.Coerce(int), vol.Range(min=0, max=23)),
        vol.Required('start_minute'): vol.All(vol.Coerce(int), vol.Range(min=0, max=59)),
        vol.Required('end_hour'): vol.All(vol.Coerce(int), vol.Range(min=0, max=23)),
        vol.Required('end_minute'): vol.All(vol.Coerce(int), vol.Range(min=0, max=59)),
        vol.Required('alarms_allowed'): cv.boolean,
        vol.Optional('expected_version'): vol.All(vol.Coerce(int), vol.Range(min=0)),
    }, 'async_dnd_set')


class R1Alarms(SensorEntity):
    _attr_name = '本地闹钟'
    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_icon = 'mdi:alarm-multiple'

    def __init__(self, owner):
        self.owner = owner
        self._attr_unique_id = owner.entry.entry_id + '-alarms'
        self._attr_device_info = owner.device_info

    @property
    def available(self): return self.owner.alarm_sync_status == 'synced'

    @property
    def native_value(self):
        state = self.owner.alarm_state
        return state.get('alarm_count') if state else None

    @property
    def extra_state_attributes(self):
        state = dict(self.owner.alarm_state or {})
        state.pop('request_id', None); state.pop('operation', None)
        state['sync_status'] = self.owner.alarm_sync_status
        state['last_error'] = self.owner.alarm_last_error
        state['pending_changes'] = self.owner.alarm_pending.public()
        return state

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.owner.listeners.add(self.async_write_ha_state)
        self.async_on_remove(lambda: self.owner.listeners.discard(self.async_write_ha_state))

    def _versioned(self, values):
        if 'expected_version' not in values:
            state = self.owner.alarm_state
            if state is None: return values
            values['expected_version'] = state['version']
        return values

    async def async_alarm_refresh(self):
        await self.owner.alarm_request('status')
        await self.owner.replay_alarm_pending()
    async def async_alarm_put(self, **values): await self.owner.alarm_write('put', **self._versioned(values))
    async def async_alarm_delete(self, **values): await self.owner.alarm_write('delete', **self._versioned(values))
    async def async_alarm_enable(self, **values): await self.owner.alarm_write('enable', **self._versioned(values))
    async def async_alarm_stop(self, **values): await self.owner.alarm_request('stop', **values)
    async def async_alarm_snooze(self, **values): await self.owner.alarm_request('snooze', **values)
    async def async_alarm_pending_discard(self, **values): await self.owner.discard_alarm_pending(**values)


class R1DoNotDisturb(SensorEntity):
    _attr_name = '免打扰'
    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_icon = 'mdi:minus-circle-off-outline'

    def __init__(self, owner):
        self.owner = owner
        self._attr_unique_id = owner.entry.entry_id + '-do-not-disturb'
        self._attr_device_info = owner.device_info

    @property
    def available(self): return self.owner.dnd_sync_status == 'synced'

    @property
    def native_value(self):
        state = self.owner.dnd_state
        return 'on' if state and state['active'] else 'off' if state else None

    @property
    def extra_state_attributes(self):
        state = dict(self.owner.dnd_state or {})
        state.pop('request_id', None); state.pop('operation', None)
        state['sync_status'] = self.owner.dnd_sync_status
        state['last_error'] = self.owner.dnd_last_error
        return state

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.owner.listeners.add(self.async_write_ha_state)
        self.async_on_remove(lambda: self.owner.listeners.discard(self.async_write_ha_state))

    async def async_dnd_refresh(self): await self.owner.dnd_request('status')

    async def async_dnd_set(self, **values):
        if 'expected_version' not in values:
            if self.owner.dnd_state is None: raise HomeAssistantError('r1_dnd_state_unavailable')
            values['expected_version'] = self.owner.dnd_state['version']
        await self.owner.dnd_request('set', **values)


class R1SystemStatus(SensorEntity):
    _attr_name = '系统状态'
    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_icon = 'mdi:information-outline'

    def __init__(self, owner):
        self.owner = owner
        self._attr_unique_id = owner.entry.entry_id + '-system-status'
        self._attr_device_info = owner.device_info

    @property
    def available(self): return self.owner.system_sync_status == 'synced'

    @property
    def native_value(self):
        return self.owner.system_state.get('service_status') if self.owner.system_state else None

    @property
    def extra_state_attributes(self):
        state = dict(self.owner.system_state or {})
        state.pop('request_id', None); state.pop('operation', None)
        state['sync_status'] = self.owner.system_sync_status
        state['management_error'] = self.owner.system_last_error
        return state

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.owner.listeners.add(self.async_write_ha_state)
        self.async_on_remove(lambda: self.owner.listeners.discard(self.async_write_ha_state))
