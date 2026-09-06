"""Volume-only speaker surface bound to native Number state/readback."""
from homeassistant.components.media_player import MediaPlayerEntity, MediaPlayerEntityFeature, MediaPlayerState
from homeassistant.core import callback
from .interaction import bridge
from homeassistant.helpers import entity_registry as er, device_registry as dr

async def async_setup_entry(hass, entry, async_add_entities):
    owner = bridge(hass, entry.entry_id)
    if owner: async_add_entities([R1Volume(owner)])

class R1Volume(MediaPlayerEntity):
    _attr_name = '音箱'
    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_supported_features = MediaPlayerEntityFeature.VOLUME_SET | MediaPlayerEntityFeature.VOLUME_STEP
    _attr_state = MediaPlayerState.IDLE
    def __init__(self, owner):
        self.owner = owner
        self._attr_unique_id = owner.entry.entry_id + '-speaker'
        self._attr_device_info = owner.device_info
    @property
    def available(self): return self.owner.number('volume') is not None
    @property
    def volume_level(self):
        value = self.owner.number('volume')
        return value / 100 if value is not None else None
    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        registry = er.async_get(self.hass)
        item = registry.async_get(self.entity_id)
        if item and self.owner.device_id and item.device_id != self.owner.device_id:
            registry.async_update_entity(self.entity_id, device_id=self.owner.device_id)
        self.owner.reconcile_device()
        self.owner.listeners.add(self.async_write_ha_state)
        self.async_on_remove(lambda: self.owner.listeners.discard(self.async_write_ha_state))
    async def async_set_volume_level(self, volume):
        await self.owner.set_volume(volume * 100, self._context)
        self.async_write_ha_state()
    async def async_volume_up(self): await self.async_set_volume_level(min(1, (self.volume_level or 0) + .1))
    async def async_volume_down(self): await self.async_set_volume_level(max(0, (self.volume_level or 0) - .1))
