#!/usr/bin/env python3
"""Pre-pair R1 native runtime lifecycle/key check; does not open audio or contact HA."""
import argparse
import asyncio
import importlib.util
import json
from pathlib import Path
import sys
import time
from aioesphomeapi import APIClient
from aioesphomeapi.model import APIVersion

spec=importlib.util.spec_from_file_location('native_admin',Path(__file__).with_name('manage-r1-native.py'))
admin=importlib.util.module_from_spec(spec);spec.loader.exec_module(admin)

async def main():
    parser=argparse.ArgumentParser();parser.add_argument('serial');args=parser.parse_args()
    device=admin.Device(args.serial);device.verify();device.start_control()
    initial=device.control({'action':'pairing'})
    if initial['listen']:raise RuntimeError('pre_pair_no_audio_mode_required')
    device.control({'action':'initialize','name':initial['name']})
    assert device.control({'action':'pairing'})['noise_psk']==initial['noise_psk']
    host=args.serial.split(':')[0]
    async def connect(key):
        client=APIClient(host,6053,noise_psk=key,expected_name=initial['name'],keepalive=1)
        try:
            await asyncio.wait_for(client.connect(login=True,log_errors=False),8)
            return client
        except BaseException:
            await client.disconnect();raise
    async def start():
        device.start_control();device.control({'action':'start','listen':False})
        await asyncio.sleep(2)
    await start()
    client=await connect(initial['noise_psk'])
    try:
        info=await client.device_info()
        assert info.mac_address==initial['protocol_mac']
        assert info.voice_assistant_feature_flags_compat(APIVersion(1,15))==7
        await client.set_voice_assistant_configuration([])
        assert not (await client.get_voice_assistant_configuration(timeout=5)).active_wake_words
        await asyncio.sleep(2)
        assert not device.control({'action':'status'})['audio_opened']
    finally:await client.disconnect()
    device.control({'action':'stop'});device.adb('shell','am','stopservice','-n',admin.SERVICE)
    await asyncio.sleep(1)
    await start()
    same=device.control({'action':'pairing'})
    assert same['device_id']==initial['device_id'] and same['noise_psk']==initial['noise_psk']
    client=await connect(initial['noise_psk'])
    try:
        assert not (await client.get_voice_assistant_configuration(timeout=5)).active_wake_words
        await client.set_voice_assistant_configuration(['alexa'])
        assert (await client.get_voice_assistant_configuration(timeout=5)).active_wake_words==['alexa']
    finally:await client.disconnect()
    device.control({'action':'stop'});await asyncio.sleep(2)
    device.control({'action':'rotate'})
    rotated=device.control({'action':'pairing'})
    assert rotated['noise_psk']!=initial['noise_psk'] and rotated['device_id']==initial['device_id']
    await start()
    try:wrong=await connect(initial['noise_psk'])
    except Exception as error:
        if isinstance(error,TimeoutError):raise AssertionError('old_key_must_be_rejected_promptly')
    else:await wrong.disconnect();raise AssertionError('old_key_accepted')
    await asyncio.sleep(.5)
    client=await connect(rotated['noise_psk'])
    try:
        await client.device_info()
        assert not device.control({'action':'status'})['audio_opened']
    finally:await client.disconnect()
    print(json.dumps({'surface':'R1_API22_installed_service','initialize_idempotent':True,
        'identity_key_persist_after_service_restart':True,'wake_setting_persistent':True,
        'key_rotation_old_rejected_new_accepted':True,'native_capabilities':7,
        'audio_opened':False,'psk_logged':False}))
    initial.clear();rotated.clear();same.clear()

if __name__=='__main__':
    try:asyncio.run(main())
    except Exception as error:
        print('Runtime check failed: '+type(error).__name__,file=sys.stderr);sys.exit(1)
