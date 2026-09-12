"""Opt-in STT wrapper; no Core patches or automatic pipeline changes."""
from homeassistant.const import Platform

DOMAIN = "r1_input_guard"

def platforms(entry):
    result = [Platform.STT, Platform.CONVERSATION] if entry.data.get("mode") == "r1_native" else [Platform.STT]
    if entry.data.get("interaction_mac"): result += [Platform.MEDIA_PLAYER, Platform.TTS, Platform.SENSOR]
    return result

async def async_setup(hass, config):
    from .commissioning import register
    register(hass)
    return True

async def async_setup_entry(hass, entry):
    if entry.data.get("interaction_mac"):
        from .interaction import Interaction
        hass.data.setdefault('r1_input_guard_interaction', {})[entry.entry_id] = Interaction(hass, entry)
    loaded = platforms(entry)
    await hass.config_entries.async_forward_entry_setups(entry, loaded)
    hass.data.setdefault('r1_input_guard_platforms', {})[entry.entry_id] = loaded
    return True

async def async_unload_entry(hass, entry):
    loaded = hass.data.get('r1_input_guard_platforms', {}).get(entry.entry_id, [Platform.STT, Platform.CONVERSATION] if entry.data.get('mode') == 'r1_native' else [Platform.STT])
    result = await hass.config_entries.async_unload_platforms(entry, loaded)
    if result:
        hass.data.get('r1_input_guard_platforms', {}).pop(entry.entry_id, None)
        owner = hass.data.get('r1_input_guard_interaction', {}).pop(entry.entry_id, None)
        if owner: await owner.close()
    return result
