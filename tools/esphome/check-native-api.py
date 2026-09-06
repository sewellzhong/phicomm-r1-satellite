#!/usr/bin/env python3
"""Official-client interoperability with ephemeral in-memory PSK; no HA registration/audio."""
import argparse,asyncio,base64,json,os,socket,subprocess,time,re
from pathlib import Path
from aioesphomeapi import APIClient
from aioesphomeapi.model import VoiceAssistantEventType
from noise.connection import NoiseConnection

ROOT=Path(__file__).resolve().parents[2]

async def main():
    parser=argparse.ArgumentParser();parser.add_argument('--adb');parser.add_argument('--satellite-metadata',action='store_true');parser.add_argument('--synthetic-voice',action='store_true');parser.add_argument('--synthetic-duplex',action='store_true');parser.add_argument('--synthetic-dialogue',action='store_true');parser.add_argument('--adb-apk',type=Path);args=parser.parse_args()
    if args.synthetic_dialogue:args.synthetic_duplex=True
    if args.synthetic_duplex:args.synthetic_voice=True
    if args.adb_apk and not args.adb:parser.error('--adb-apk requires --adb')
    key=os.urandom(32);encoded=base64.b64encode(key).decode();forward=None;remote_apk=None
    try:
        if args.adb:
            def adb(*cmd):return subprocess.check_output(['adb','-s',args.adb,*cmd],text=True).strip()
            package=adb('shell','CLASSPATH=/system/framework/pm.jar app_process /system/bin com.android.commands.pm.Pm path dev.sewellzhong.r1probe')
            apk=package.split('package:')[-1].strip();directory=apk.rsplit('/',1)[0]
            assert re.fullmatch(r'/data/app/dev\.sewellzhong\.r1probe-[0-9]+',directory) and apk.endswith('/base.apk')
            if args.adb_apk:
                remote_apk='/data/local/tmp/r1-native-'+os.urandom(8).hex()+'.apk'
                assert re.fullmatch(r'/data/local/tmp/r1-native-[A-Za-z0-9]+\.apk',remote_apk)
                adb('push',str(args.adb_apk.resolve()),remote_apk)
                apk=remote_apk
            command=['adb','-s',args.adb,'shell','dalvikvm',f'-Djava.library.path={directory}/lib/arm','-cp',apk,
                     'dev.sewellzhong.r1probe.esphome.NativeApiProbe']
            forward=int(adb('forward','tcp:0','tcp:6053'));port=forward
        else:
            jars=list((Path(os.environ.get('GRADLE_USER_HOME', Path.home() / '.gradle')) / 'caches/modules-2/files-2.1/com.google.protobuf/protobuf-javalite/3.25.5').rglob('*.jar'))
            classes=ROOT/'android/r1-probe/app/build/intermediates/javac/debug/compileDebugJavaWithJavac/classes'
            command=[str(Path(os.environ['JAVA_HOME']) / 'bin/java') if os.environ.get('JAVA_HOME') else 'java',
                     '-Djava.library.path='+str(ROOT/'local-deps/build/r1-noise-host'),'-cp',str(classes)+os.pathsep+str(jars[0]),
                     'dev.sewellzhong.r1probe.esphome.NativeApiProbe'];port=6053
        if args.satellite_metadata:command.append("--satellite-metadata")
        if args.synthetic_voice:command.append('--synthetic-dialogue' if args.synthetic_dialogue else ('--synthetic-duplex' if args.synthetic_duplex else '--synthetic-voice'))
        process=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True)
    except BaseException:
        if forward is not None:adb('forward','--remove','tcp:'+str(forward))
        if remote_apk is not None:adb('shell','rm','-f',remote_apk)
        raise
    try:
        process.stdin.write(key.hex()+'\n');process.stdin.flush();process.stdin.close()
        for _ in range(20):
            line=await asyncio.wait_for(asyncio.to_thread(process.stdout.readline),15)
            if 'NATIVE_API_PROBE_READY' in line:break
            if not line:raise RuntimeError('probe_not_ready')
        else:raise RuntimeError('probe_not_ready')
        async def valid():
            client=APIClient('127.0.0.1',port,noise_psk=encoded,expected_name='r1-native-probe',keepalive=1)
            try:
                await asyncio.wait_for(client.connect(login=True,log_errors=False),10)
                info=await client.device_info();entities,services=await client.list_entities_services()
                assert info.name=='r1-native-probe' and info.model=='R1 API22'
                assert not entities and not services
                if args.satellite_metadata:
                    from aioesphomeapi.model import APIVersion, VoiceAssistantFeature
                    assert info.voice_assistant_feature_flags_compat(APIVersion(1,15)) == (
                        VoiceAssistantFeature.VOICE_ASSISTANT | VoiceAssistantFeature.SPEAKER | VoiceAssistantFeature.API_AUDIO)
                    config = await client.get_voice_assistant_configuration(timeout=5)
                    assert config.active_wake_words == ['alexa'] and config.max_active_wake_words == 1
                    assert config.available_wake_words[0].wake_word == 'Alexa'
                    await client.set_voice_assistant_configuration([])
                    assert not (await client.get_voice_assistant_configuration(timeout=5)).active_wake_words
                    await client.set_voice_assistant_configuration(['alexa'])
                    assert (await client.get_voice_assistant_configuration(timeout=5)).active_wake_words == ['alexa']
                if args.synthetic_voice:
                    received=[]; finished=asyncio.Event(); played=asyncio.Event(); second_finished=asyncio.Event(); starts=0
                    async def handle_start(conversation,flags,settings,wake):
                        nonlocal starts
                        starts+=1
                        assert conversation == ("synthetic-conversation" if starts == 2 else "")
                        assert flags == 0 and wake is None
                        assert settings.volume_multiplier == 1.0
                        return 0
                    async def handle_audio(data,data2):
                        assert data2 == b''
                        received.append(data)
                    async def handle_stop(abort):
                        assert not abort
                        (second_finished if starts == 2 else finished).set()
                    async def handle_played(result):
                        assert result.success
                        played.set()
                    unsubscribe=client.subscribe_voice_assistant(handle_start=handle_start,
                            handle_stop=handle_stop,handle_audio=handle_audio,
                            handle_announcement_finished=handle_played)
                    await asyncio.wait_for(finished.wait(),5)
                    assert received == [bytes(i % 127 for i in range(640))]*2
                    if args.synthetic_duplex:
                        event=client.send_voice_assistant_event
                        if args.synthetic_dialogue:
                            event(VoiceAssistantEventType.VOICE_ASSISTANT_INTENT_END,
                                  {"conversation_id":"synthetic-conversation","continue_conversation":"0"})
                        event(VoiceAssistantEventType.VOICE_ASSISTANT_TTS_START,{})
                        event(VoiceAssistantEventType.VOICE_ASSISTANT_TTS_END,{})
                        event(VoiceAssistantEventType.VOICE_ASSISTANT_RUN_END,{})
                        event(VoiceAssistantEventType.VOICE_ASSISTANT_TTS_STREAM_START,{})
                        data=bytes(i % 127 for i in range(1886))
                        for lo,hi in [(0,128),(128,1152),(1152,1886)]:
                            client.send_voice_assistant_audio(data[lo:hi])
                        await asyncio.sleep(0.05)
                        assert not played.is_set(), 'playback completed before stream end'
                        ended=time.monotonic()
                        event(VoiceAssistantEventType.VOICE_ASSISTANT_TTS_STREAM_END,{})
                        await asyncio.wait_for(played.wait(),5)
                        assert time.monotonic()-ended >= 0.25, 'playback did not wait for sink drain'
                        if args.synthetic_dialogue:
                            await asyncio.wait_for(second_finished.wait(),5)
                            assert starts == 2 and received == [bytes(i % 127 for i in range(640))]*4
                            event(VoiceAssistantEventType.VOICE_ASSISTANT_INTENT_END,
                                  {"conversation_id":"synthetic-conversation","continue_conversation":"0"})
                            event(VoiceAssistantEventType.VOICE_ASSISTANT_RUN_END,{})
                    else:
                        client.send_voice_assistant_event(VoiceAssistantEventType.VOICE_ASSISTANT_RUN_END,None)
                    unsubscribe()
                await asyncio.sleep(2.2) # Official client keepalive ping/pong.
                assert await client.list_entities_services() == ([], [])
            finally:await client.disconnect()
        await valid()
        wrong=APIClient('127.0.0.1',port,noise_psk=base64.b64encode(os.urandom(32)).decode())
        try:
            try:await asyncio.wait_for(wrong.connect(login=True,log_errors=False),10)
            except Exception as error:
                assert type(error).__name__!='TimeoutError', 'wrong-key rejection must be prompt'
                rejection=type(error).__name__
                if args.satellite_metadata: assert rejection == 'InvalidEncryptionKeyAPIError'
            else:raise AssertionError('wrong_key_accepted')
        finally:await wrong.disconnect()
        if args.satellite_metadata:
            unkeyed = APIClient('127.0.0.1', port)
            try:
                try: await asyncio.wait_for(unkeyed.connect(login=True, log_errors=False), 5)
                except Exception as error: assert type(error).__name__ == 'RequiresEncryptionAPIError'
                else: raise AssertionError('unkeyed_client_accepted')
            finally: await unkeyed.disconnect()
        async def raw_checks():
            reader,writer=await asyncio.open_connection('127.0.0.1',port)
            writer.write(b'\x00\x00\x00');await writer.drain()
            if args.satellite_metadata:
                assert await asyncio.wait_for(reader.readexactly(3),3)==b'\x01\x00\x00'
            assert await asyncio.wait_for(reader.read(1),3)==b''
            writer.close();await writer.wait_closed()
            reader,writer=await asyncio.open_connection('127.0.0.1',port)
            async def send(data):writer.write(b'\x01'+len(data).to_bytes(2,'big')+data);await writer.drain()
            async def receive():
                header=await reader.readexactly(3);assert header[0]==1
                return await reader.readexactly(int.from_bytes(header[1:],'big'))
            await send(b'');assert (await receive())[0]==1
            cipher=NoiseConnection.from_name(b'Noise_NNpsk0_25519_ChaChaPoly_SHA256')
            cipher.set_as_initiator();cipher.set_psks(psk=key);cipher.set_prologue(b'NoiseAPIInit\x00\x00');cipher.start_handshake()
            await send(b'\x00'+cipher.write_message());reply=await receive();assert reply[0]==0;cipher.read_message(reply[1:])
            forged=bytearray(cipher.encrypt(b'\x00'*4));forged[-1]^=1;await send(forged)
            assert await asyncio.wait_for(reader.read(1),3)==b''
            writer.close();await writer.wait_closed()
        await asyncio.wait_for(raw_checks(),10)
        await valid() # Bad clients cannot prevent a fresh authenticated session.
        print(json.dumps({'surface':'R1_API22' if args.adb else 'host_JVM','client':'aioesphomeapi 45.6.1',
                          'valid_key_device_info_entities_ping_disconnect':'passed','wrong_key':'rejected',
                          'wrong_key_error_type':rejection,'plaintext':'rejected','tampered_ciphertext':'rejected',
                          'reconnect_after_rejections':'passed','synthetic_voice_uplink': 'passed' if args.synthetic_voice else 'not_run','synthetic_downlink_and_delayed_drain':'passed' if args.synthetic_duplex else 'not_run','synthetic_followup_same_conversation':'passed' if args.synthetic_dialogue else 'not_run','satellite_metadata_and_wake_toggle': 'passed' if args.satellite_metadata else 'not_run','audio_opened':False,'psk_saved':False}))
    finally:
        try:process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:process.kill();process.wait()
        if forward is not None:adb('forward','--remove','tcp:'+str(forward))
        if remote_apk is not None:adb('shell','rm','-f',remote_apk)
        key=b'';encoded=''

if __name__=='__main__':
    try:asyncio.run(main())
    except Exception as error:
        print('Native interoperability failed: '+type(error).__name__)
        raise SystemExit(1)
