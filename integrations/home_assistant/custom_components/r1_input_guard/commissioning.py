"""One-shot local configuration-admin commissioning, consumed at HA startup.

No HTTP endpoint, user impersonation, direct .storage edits, or secret reports.
The private marker can contain a device PSK; it is unlinked before parsing/use.
"""
from __future__ import annotations
import asyncio
import base64
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import stat
import traceback
from homeassistant.core import Context
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.start import async_at_started

MARKER = ".r1_native_commission.json"
REPORT = ".r1_native_commission_result.json"
TITLE = "R1 原生中文助手"

class CommissioningError(ValueError):
    """Only fixed, secret-free application error codes."""


def consume(path: Path):
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return None
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_size > 8192:
            raise ValueError("private_marker_required")
        path.unlink()
        value = json.loads(stream.read(8192))
    if value.get("action") not in {"pair", "inspect", "upgrade_interaction", "verify_interaction"}:
        raise ValueError("invalid_commission_action")
    if value["action"] == "pair":
        import ipaddress
        ipaddress.IPv4Address(value["host"])
        if not re.fullmatch(r"[0-9A-F]{2}(:[0-9A-F]{2}){5}", value["protocol_mac"]):
            raise ValueError("invalid_protocol_identity")
        if not re.fullmatch(r"[a-z][a-z0-9-]{0,30}", value["name"]):
            raise ValueError("invalid_node_name")
        if len(base64.b64decode(value["noise_psk"], validate=True)) != 32:
            raise ValueError("invalid_psk")
    return value


def write_report(path, value):
    # Reports contain only identifiers, state and fixed errors, never flow payloads.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as stream:
        os.fchmod(stream.fileno(), 0o600)
        json.dump(value, stream, ensure_ascii=False, indent=2)


def one(values, reason):
    if len(values) != 1:
        raise CommissioningError(reason)
    return values[0]


async def upgrade_interaction(hass, request, store, registry):
    mac = request.get('protocol_mac', '').lower()
    if not re.fullmatch(r'[0-9a-f]{2}(:[0-9a-f]{2}){5}', mac): raise CommissioningError('invalid_protocol_identity')
    selector = one([e for e in registry.entities.values() if e.platform == 'esphome'
                    and e.unique_id.lower() == mac + '-pipeline'], 'r1_selector_missing')
    entry = one([e for e in hass.config_entries.async_entries('r1_input_guard')
                 if e.data.get('mode') == 'r1_native'], 'native_entry_not_unique')
    pipeline = one([p for p in store.async_items() if p.name == TITLE], 'native_pipeline_missing')
    source = registry.async_get(pipeline.tts_engine)
    if source is None: raise CommissioningError('tts_source_missing')
    previous_tts = pipeline.tts_engine
    previous_data = dict(entry.data)
    source_id = entry.data.get('tts_source_registry_id') if source.platform == 'r1_input_guard' else source.id
    if source_id is None: raise CommissioningError('tts_source_missing')
    hass.config_entries.async_update_entry(entry, data={**entry.data, 'interaction_mac': mac, 'tts_source_registry_id': source_id})
    await hass.config_entries.async_reload(entry.entry_id)
    for _ in range(100):
        entities = er.async_entries_for_config_entry(registry, entry.entry_id)
        target = next((e for e in entities if e.domain == 'tts'), None)
        if target and (state := hass.states.get(target.entity_id)) and state.state != 'unavailable': break
        await asyncio.sleep(.5)
    if not target: raise CommissioningError('r1_tts_missing')
    fields = pipeline.to_json()
    fields.pop('id')
    fields['tts_engine'] = target.entity_id
    await store.async_update_item(pipeline.id, fields)
    from .diagnostics import verify
    verification = await verify(hass, entry)
    return {'verification': verification,'interaction_upgraded': True, 'pipeline_id': pipeline.id, 'tts_entity': target.entity_id,
            'previous_tts_engine': previous_tts, 'native_entry_id': entry.entry_id,
            'previous_native_entry_data': previous_data, 'device_id': selector.device_id}


async def configure(hass, request):
    from homeassistant.components.assist_pipeline import pipeline as pipelines
    store = hass.data[pipelines.KEY_ASSIST_PIPELINE].pipeline_store
    before = {item.id: item.to_json() for item in store.async_items()}
    preferred = store.async_get_preferred_item()
    registry = er.async_get(hass)
    if request['action'] == 'verify_interaction':
        from .interaction import bridge
        from .diagnostics import verify
        entry = one([e for e in hass.config_entries.async_entries('r1_input_guard')
            if e.data.get('interaction_mac', '').lower() == request.get('protocol_mac', '').lower()], 'native_entry_not_unique')
        for _ in range(120):
            owner = bridge(hass, entry.entry_id)
            if owner and all(owner.number(k) is not None for k in ('volume','speech_speed','wait_seconds','followup_wait_seconds')): break
            await asyncio.sleep(.5)
        result = await verify(hass, entry)
        from .diagnostics import observe
        entry.async_create_background_task(hass, observe(hass, entry), 'r1-bounded-observation')
        return {'verification': result}
    if request['action'] == 'upgrade_interaction':
        result = await upgrade_interaction(hass, request, store, registry)
        after = {item.id: item.to_json() for item in store.async_items()}
        if preferred != store.async_get_preferred_item() or any(after.get(k) != v for k,v in before.items() if k != result['pipeline_id']):
            raise CommissioningError('unrelated_pipeline_changed')
        return result
    if request["action"] == "inspect":
        return {"pipelines": list(before.values()), "preferred": preferred, "entities": [
            {"entity_id": item.entity_id, "unique_id": item.unique_id, "device_id": item.device_id,
             "hidden_by": item.hidden_by, "disabled_by": item.disabled_by, "options": dict(item.options), "state": hass.states.get(item.entity_id).state if hass.states.get(item.entity_id) else None}
            for item in registry.entities.values() if item.platform == "esphome" or item.platform == "r1_input_guard"]}
    source = registry.async_get("stt.faster_whisper")
    if source is None: raise CommissioningError("whisper_source_missing")
    route = one([item for item in registry.entities.values() if item.platform == "conversation_router"
                 and not item.disabled and item.domain == "conversation"], "router_not_unique")
    native = [entry for entry in hass.config_entries.async_entries("r1_input_guard")
              if entry.data.get("mode") == "r1_native" and entry.data["source_registry_id"] == source.id]
    if native:
        native_entry = one(native, "native_entry_not_unique")
        if native_entry.data.get("conversation_registry_id") != route.id:
            raise CommissioningError("existing_native_route_differs")
    else:
        flow = await hass.config_entries.flow.async_init("r1_input_guard", context={"source": "user"},
            data={"mode": "r1_native", "source_entity_id": source.entity_id, "conversation_entity_id": route.entity_id})
        if flow["type"] != "create_entry": raise CommissioningError("native_entry_failed")
        native_entry = flow["result"]
    for _ in range(100):
        entities = er.async_entries_for_config_entry(registry, native_entry.entry_id)
        stt = [item.entity_id for item in entities if item.domain == "stt"]
        conversation = [item.entity_id for item in entities if item.domain == "conversation"]
        if len(stt) == len(conversation) == 1: break
        await asyncio.sleep(.2)
    stt_id = one(stt, "native_stt_missing")
    conversation_id = one(conversation, "native_conversation_missing")
    fields = dict(before[preferred]); fields.pop("id")
    fields.update(name=TITLE, stt_engine=stt_id, conversation_engine=conversation_id,
                  language="zh", stt_language="zh", conversation_language="zh-CN",
                  wake_word_entity=None, wake_word_id=None, prefer_local_intents=False)
    matches = [item for item in store.async_items() if item.name == TITLE]
    if matches:
        pipeline = one(matches, "native_pipeline_not_unique")
        if any(pipeline.to_json().get(k) != v for k, v in fields.items()):
            raise CommissioningError("existing_native_pipeline_differs")
    else:
        pipeline = await store.async_create_item(fields)

    mac = request["protocol_mac"].lower()
    entries = [entry for entry in hass.config_entries.async_entries("esphome")
               if (entry.unique_id or "").lower() == mac]
    if entries:
        entry = one(entries, "device_entry_not_unique")
        if entry.data.get("noise_psk") != request["noise_psk"]:
            flow = await hass.config_entries.flow.async_init("esphome",
                context={"source": "reauth", "entry_id": entry.entry_id}, data=dict(entry.data))
        else:
            flow = None
            if entry.data.get("host") != request["host"]:
                hass.config_entries.async_update_entry(entry, data={**entry.data, "host": request["host"]})
                await hass.config_entries.async_reload(entry.entry_id)
    else:
        flow = await hass.config_entries.flow.async_init("esphome", context={"source": "user"},
                                                       data={"host": request["host"], "port": 6053})
    for _ in range(8):
        if flow is None or flow["type"] in {"create_entry", "abort"}: break
        step = flow.get("step_id")
        if step in {"encryption_key", "reauth_confirm"}: data = {"noise_psk": request["noise_psk"]}
        elif step in {"confirm", "finish"}: data = {}
        else:
            hass.config_entries.flow.async_abort(flow["flow_id"])
            raise CommissioningError("unexpected_pairing_step")
        flow = await hass.config_entries.flow.async_configure(flow["flow_id"], data)
        if flow.get("errors"):
            hass.config_entries.flow.async_abort(flow["flow_id"])
            raise CommissioningError("encrypted_pairing_rejected")
    if flow is not None and (flow["type"] not in {"create_entry", "abort"}
            or flow["type"] == "abort" and flow.get("reason") not in {"already_configured", "reauth_successful"}):
        raise CommissioningError("pairing_incomplete")
    selector = None
    for _ in range(150):
        selector = next((item for item in registry.entities.values() if item.platform == "esphome"
                         and item.domain == "select" and item.unique_id.lower() == mac + "-pipeline"), None)
        if selector and (state := hass.states.get(selector.entity_id)) and TITLE in state.attributes.get("options", []): break
        await asyncio.sleep(.2)
    if not selector: raise CommissioningError("pipeline_selector_missing")
    await hass.services.async_call("select", "select_option", {"entity_id": selector.entity_id, "option": TITLE},
                                   blocking=True, context=Context())
    if hass.states.get(selector.entity_id).state != TITLE: raise CommissioningError("pipeline_selection_failed")
    after = {item.id: item.to_json() for item in store.async_items()}
    if preferred != store.async_get_preferred_item() or any(after.get(key) != value for key, value in before.items()):
        raise CommissioningError("existing_pipeline_changed")
    satellites = [item.entity_id for item in registry.entities.values() if item.platform == "esphome"
                  and item.domain == "assist_satellite" and item.device_id == selector.device_id]
    return {"pipeline_id": pipeline.id, "pipeline_select": selector.entity_id, "satellites": satellites,
            "native_stt": stt_id, "native_conversation": conversation_id,
            "default_preserved": True, "existing_pipelines_preserved": True, "psk_logged": False}


def register(hass):
    async def run(_hass):
        request = None
        report = {"ok": False, "started_at": datetime.now(timezone.utc).isoformat()}
        try:
            request = await hass.async_add_executor_job(consume, Path(hass.config.path(MARKER)))
            if request is None: return
            async with asyncio.timeout(180):
                report.update(await configure(hass, request))
            report["ok"] = True
        except Exception as error:
            # Never include exception strings: a third-party flow could put credentials there.
            report["error_type"] = type(error).__name__
            report["error_location"] = [{"file": Path(frame.filename).name, "line": frame.lineno, "function": frame.name}
                                        for frame in traceback.extract_tb(error.__traceback__)[-5:]]
            if type(error) is CommissioningError: report["error_code"] = str(error)
        finally:
            if request is not None: request.clear()
        await hass.async_add_executor_job(write_report, Path(hass.config.path(REPORT)), report)
    async_at_started(hass, run)
