"""Confirmed service and device restart controls for the bound R1."""
from homeassistant.components.button import ButtonEntity
from .interaction import bridge


async def async_setup_entry(hass, entry, async_add_entities):
    owner = bridge(hass, entry.entry_id)
    if owner: async_add_entities([R1RestartService(owner), R1RebootDevice(owner)])


class _R1SystemButton(ButtonEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False
    operation = None

    def __init__(self, owner):
        self.owner = owner
        self._attr_unique_id = owner.entry.entry_id + '-' + self.operation.replace('_', '-')
        self._attr_device_info = owner.device_info

    @property
    def available(self): return self.owner.system_service() is not None

    async def async_press(self):
        await self.owner.system_request(self.operation, context=self._context)


class R1RestartService(_R1SystemButton):
    _attr_name = '重启卫星服务'
    _attr_icon = 'mdi:restart'
    operation = 'restart_service'


class R1RebootDevice(_R1SystemButton):
    _attr_name = '重启整机'
    _attr_icon = 'mdi:power-cycle'
    operation = 'reboot_device'
