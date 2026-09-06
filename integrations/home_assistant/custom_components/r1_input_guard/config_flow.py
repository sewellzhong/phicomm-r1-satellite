"""Choose a backing STT entity explicitly."""
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components import stt
from homeassistant.helpers import entity_registry as er, selector
from . import DOMAIN

class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            entity_id = user_input["source_entity_id"]
            registered = er.async_get(self.hass).async_get(entity_id)
            source = stt.async_get_speech_to_text_entity(self.hass, entity_id)
            if source is None or registered is None or registered.platform == DOMAIN:
                errors["base"] = "invalid_source"
            else:
                native = user_input.get("mode", "standard") == "r1_native"
                data = {"source_registry_id": registered.id}
                if native:
                    target = er.async_get(self.hass).async_get(user_input.get("conversation_entity_id", ""))
                    if target is None or target.platform != "conversation_router" or target.disabled:
                        errors["base"] = "invalid_conversation"
                    else:
                        data.update(mode="r1_native", conversation_registry_id=target.id)
                if not errors:
                    await self.async_set_unique_id(registered.id + (":r1_native" if native else ""))
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(title="R1 原生语音" if native else "语音识别与无效输入过滤", data=data)
        return self.async_show_form(step_id="user", data_schema=vol.Schema({
            vol.Optional("mode", default="standard"): selector.SelectSelector(
                selector.SelectSelectorConfig(options=[
                    {"value": "standard", "label": "通用无效输入过滤（保留 HA 结束判定）"},
                    {"value": "r1_native", "label": "R1 原生（由 R1 结束收音，支持持续对话）"}])),
            vol.Optional("conversation_entity_id"): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="conversation")),
            vol.Required("source_entity_id"): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="stt"))
        }), errors=errors)
