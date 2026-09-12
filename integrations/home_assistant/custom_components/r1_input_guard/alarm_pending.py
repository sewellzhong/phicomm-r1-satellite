"""Persistent, conflict-safe desired state for HA alarm writes made while R1 is offline."""
from collections import OrderedDict
from datetime import date

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.storage import Store


EDITABLE_FIELDS = ('id', 'name', 'date', 'hour', 'minute', 'weekdays', 'enabled', 'snooze_minutes',
                   'ringtone', 'volume_percent')
MAX_PENDING = 32


def editable(value):
    """Return only fields accepted by the device put operation."""
    if value is None:
        return None
    result = {key: value[key] for key in EDITABLE_FIELDS if key in value}
    result.setdefault('ringtone', 'classic')
    result.setdefault('volume_percent', 100)
    return result


def valid_editable(value):
    if not isinstance(value, dict) or set(value) != set(EDITABLE_FIELDS):
        return False
    if not isinstance(value['id'], str) or not 0 < len(value['id']) <= 128:
        return False
    if not isinstance(value['name'], str) or len(value['name']) > 256:
        return False
    if not isinstance(value['date'], str) or len(value['date']) > 10:
        return False
    if any(any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in value[key])
           for key in ('id', 'name', 'date')):
        return False
    integer_fields = ('hour', 'minute', 'weekdays', 'snooze_minutes', 'volume_percent')
    if any(type(value[key]) is not int for key in integer_fields):
        return False
    if value['date']:
        try:
            if date.fromisoformat(value['date']).isoformat() != value['date']:
                return False
        except ValueError:
            return False
    return (0 <= value['hour'] <= 23 and 0 <= value['minute'] <= 59
            and 0 <= value['weekdays'] <= 127 and 1 <= value['snooze_minutes'] <= 60
            and isinstance(value['enabled'], bool)
            and value['ringtone'] in ('classic', 'gentle', 'urgent')
            and 1 <= value['volume_percent'] <= 100
            and bool(value['date']) != bool(value['weekdays']))


class AlarmPending:
    """Compact multiple offline changes per alarm into one persisted desired state."""

    def __init__(self, hass, entry_id):
        self._store = Store(hass, 1, f'r1_input_guard.alarm_pending.{entry_id}', private=True,
                            atomic_writes=True)
        self._items = OrderedDict()

    async def load(self):
        value = await self._store.async_load()
        if value is None:
            return
        try:
            items = value['items']
            if value.get('schema') not in (1, 2) or not isinstance(items, list) or len(items) > MAX_PENDING:
                raise ValueError
            restored = OrderedDict()
            for item in items:
                alarm_id = item['id']
                base, desired = item['base'], item['desired']
                if value.get('schema') == 1:
                    base = editable(base)
                    desired = editable(desired)
                if not isinstance(alarm_id, str) or not alarm_id or alarm_id in restored:
                    raise ValueError
                if base is not None and not valid_editable(base):
                    raise ValueError
                if desired is not None and not valid_editable(desired):
                    raise ValueError
                if (base is not None and base['id'] != alarm_id) or \
                        (desired is not None and desired['id'] != alarm_id):
                    raise ValueError
                blocked = item.get('blocked', False)
                if not isinstance(blocked, bool):
                    raise ValueError
                restored[alarm_id] = {'id': alarm_id, 'base': base, 'desired': desired,
                                      'blocked': blocked}
            self._items = restored
        except (KeyError, TypeError, ValueError):
            raise HomeAssistantError('r1_alarm_pending_store_invalid')

    async def _save(self):
        await self._store.async_save({'schema': 2, 'items': list(self._items.values())})

    def items(self):
        return list(self._items.values())

    def public(self):
        return [{'id': item['id'], 'operation': 'delete' if item['desired'] is None else 'put',
                 'desired': item['desired'], 'blocked': item['blocked']}
                for item in self._items.values()]

    async def queue(self, operation, values, confirmed_state):
        if operation not in ('put', 'delete', 'enable'):
            raise HomeAssistantError('r1_alarm_pending_operation_invalid')
        if not isinstance(confirmed_state, dict) or not isinstance(confirmed_state.get('alarms'), list):
            raise HomeAssistantError('r1_alarm_pending_without_baseline')
        alarm_id = values.get('id')
        if not isinstance(alarm_id, str) or not alarm_id:
            raise HomeAssistantError('r1_alarm_pending_id_invalid')
        existing = self._items.get(alarm_id)
        confirmed = next((editable(item) for item in confirmed_state['alarms']
                          if item.get('id') == alarm_id), None)
        base = existing['base'] if existing else confirmed
        effective = existing['desired'] if existing else confirmed
        if operation == 'put':
            try:
                desired = editable({
                    'id': alarm_id, 'name': values.get('name', ''), 'date': values.get('date', ''),
                    'hour': values['hour'], 'minute': values['minute'],
                    'weekdays': values.get('weekdays', 0), 'enabled': values.get('enabled', True),
                    'snooze_minutes': values.get('snooze_minutes', 10),
                    'ringtone': values.get('ringtone', 'classic'),
                    'volume_percent': values.get('volume_percent', 100),
                })
            except KeyError:
                raise HomeAssistantError('r1_alarm_pending_request_invalid')
        elif operation == 'delete':
            if effective is None:
                raise HomeAssistantError('r1_alarm_not_found')
            desired = None
        else:
            if effective is None:
                raise HomeAssistantError('r1_alarm_not_found')
            desired = dict(effective)
            desired['enabled'] = values.get('enabled')

        if desired is not None and not valid_editable(desired):
            raise HomeAssistantError('r1_alarm_pending_request_invalid')

        if desired == base:
            self._items.pop(alarm_id, None)
        else:
            if existing is None and len(self._items) >= MAX_PENDING:
                raise HomeAssistantError('r1_alarm_pending_capacity')
            self._items[alarm_id] = {'id': alarm_id, 'base': base, 'desired': desired,
                                     'blocked': False}
        await self._save()

    async def block(self, alarm_id):
        self._items[alarm_id]['blocked'] = True
        await self._save()

    async def discard(self, alarm_id):
        if alarm_id:
            self._items.pop(alarm_id, None)
        else:
            self._items.clear()
        await self._save()
