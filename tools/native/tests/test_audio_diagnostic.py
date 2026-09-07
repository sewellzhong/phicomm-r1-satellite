import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
def module(name, filename):
    spec=importlib.util.spec_from_file_location(name, ROOT/filename)
    value=importlib.util.module_from_spec(spec); spec.loader.exec_module(value); return value
manage=module('manage_diagnostic', 'manage-r1-native.py')
decode=module('decode_diagnostic', 'decode-audio-diagnostic.py')
analyze=module('analyze_diagnostic', 'analyze-silence-diagnostic.py')
capture=module('capture_diagnostic', 'capture-silence-diagnostic.py')

class FakeDevice:
    def __init__(self, corrupt=False):
        self.data=b'R1D1'+b'x'*5000
        self.digest=hashlib.sha256(self.data).hexdigest()
        self.corrupt=corrupt; self.cleared=False; self.forwards=[]
    def adb(self,*args):
        self.forwards.append(args); return '12345'
    def control(self,command):
        if command['action']=='diagnostic-status':
            return {'ready':True,'bytes':len(self.data),'sha256':self.digest,'reason':'requested'}
        if command['action']=='diagnostic-export':
            offset=command['offset']; data=self.data[offset:offset+2048]
            if self.corrupt: data=b'z'*len(data)
            return {'offset':offset,'data':base64.b64encode(data).decode()}
        if command['action']=='diagnostic-clear':
            assert command['sha256']==self.digest; self.cleared=True; return {}
        raise AssertionError(command)

class DiagnosticTests(unittest.TestCase):
    def test_export_checks_hash_before_deletion(self):
        with tempfile.TemporaryDirectory() as directory:
            device=FakeDevice(); path=Path(directory)/'capture.r1diag'
            manage.export_diagnostic(device,path)
            self.assertTrue(device.cleared)
            self.assertEqual(path.read_bytes(),device.data)
            self.assertTrue(json.loads(path.with_suffix('.r1diag.json').read_text())['complete'])
            self.assertFalse(hasattr(device,'export_port'))
    def test_corruption_preserves_device_and_partial_local_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            device=FakeDevice(True); path=Path(directory)/'capture.r1diag'
            with self.assertRaises(RuntimeError): manage.export_diagnostic(device,path)
            self.assertFalse(device.cleared); self.assertTrue(path.exists())
            self.assertFalse(path.with_suffix('.r1diag.json').exists())
            self.assertFalse(hasattr(device,'export_port'))
    def test_local_evidence_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            device=FakeDevice(); path=Path(directory)/'capture.r1diag'; path.write_bytes(b'old')
            with self.assertRaises(FileExistsError): manage.export_diagnostic(device,path)
            self.assertFalse(device.cleared); self.assertEqual(path.read_bytes(),b'old')
    def test_decode_truncation_and_signed_pcm(self):
        def utf(value): return struct.pack('>H',len(value))+value
        data=b'R1D1'+struct.pack('>qq',0,123)+utf(b'raw')+utf(b'frame=1')+struct.pack('>i',4)+struct.pack('<hh',-32768,32767)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'capture.r1diag'; path.write_bytes(data)
            self.assertEqual(decode.decode(path,Path(directory)/'decoded'),{'raw':2})
            path.write_bytes(data[:-1])
            with self.assertRaises(ValueError): list(decode.records(path))

class AnalysisTests(unittest.TestCase):
    def fixture(self, directory, complete=True, commands=0, duration=10_000_000_000, offer_us=1):
        directory=Path(directory)
        def utf(value):
            data=value.encode('ascii'); return struct.pack('>H',len(data))+data
        def record(index,nanos,kind,detail,pcm=b''):
            return struct.pack('>qq',index,nanos)+utf(kind)+utf(detail)+struct.pack('>i',len(pcm))+pcm
        data=b'R1D1'
        data+=record(0,1_000_000_000,'event','window_open=1')
        data+=record(1,1_000_000_001,'raw','read_started_ns=999999999',b'\x00\x00'*320)
        data+=record(2,1_020_000_001,'raw','read_started_ns=1000000000',b'\x00\x00'*320)
        data+=record(3,1_000_000_000+duration,'event','window_timeout=1')
        (directory/'capture.r1diag').write_bytes(data)
        counters=dict.fromkeys(('commands','stt_results','tts_streams','no_input_windows','ending_prompts'),0)
        (directory/'before.json').write_text(json.dumps({'wait_seconds':10,'audio':counters}))
        counters.update(commands=commands,no_input_windows=1,ending_prompts=1,input_bytes=commands*640,reference_max_us=1000,reference_over_budget_frames=0)
        (directory/'snapshots.json').write_text(json.dumps([{'state':{'status':'listening','audio':counters}}]))
        (directory/'capture.r1diag.json').write_text(json.dumps({'complete':complete,'reason':'requested' if complete else 'queue_overflow','max_offer_us':offer_us}))
        return analyze.analyze(directory)
    def test_complete_silent_window_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertTrue(self.fixture(directory)['silence_regression_passed'])
    def test_incomplete_evidence_cannot_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertFalse(self.fixture(directory,complete=False)['silence_regression_passed'])
    def test_upload_or_early_timeout_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertFalse(self.fixture(directory,commands=1)['silence_regression_passed'])
            self.assertFalse(self.fixture(directory,duration=5_000_000_000)['silence_regression_passed'])

    def test_queue_budget_failure_does_not_hide_silence_behavior(self):
        with tempfile.TemporaryDirectory() as directory:
            result=self.fixture(directory,offer_us=41624)
            self.assertTrue(result['silence_behavior_passed'])
            self.assertFalse(result['diagnostic_budget_passed'])
            self.assertFalse(result['silence_regression_passed'])

class CaptureTests(unittest.TestCase):
    def test_budget_stop_before_baseline_finishes_does_not_trigger_prompt(self):
        with tempfile.TemporaryDirectory() as directory:
            device=mock.Mock()
            commands=[]
            def control(command):
                commands.append(command['action'])
                if command['action']=='status': return {'status':'listening','audio':{'ending_prompts':0}}
                if command['action']=='diagnostic-status': return {'active':False,'ready':True}
                return {}
            device.control.side_effect=control
            with mock.patch.object(capture.admin,'Device',return_value=device), \
                    mock.patch.object(capture.admin,'export_diagnostic',return_value={'exported':True}), \
                    mock.patch.object(capture.time,'sleep'), \
                    mock.patch('sys.argv',['capture','device','--output',str(Path(directory)/'round')]), \
                    mock.patch('builtins.print'):
                capture.main()
            self.assertNotIn('diagnostic-window',commands)
            self.assertIn('diagnostic-stop',commands)

class PromptSelectionCliTests(unittest.TestCase):
    def test_fixed_prompt_is_sent_only_for_diagnostic_window(self):
        device=mock.Mock(); device.control.return_value={}
        with mock.patch.object(manage,'Device',return_value=device), \
                mock.patch('sys.argv',['manage','diagnostic-window','device','--prompt-index','1']), \
                mock.patch('builtins.print'):
            manage.main()
        device.control.assert_called_once_with({'action':'diagnostic-window','followup':False,'prompt_index':1})
    def test_followup_override_is_rejected_before_touching_device(self):
        with mock.patch.object(manage,'Device') as factory, \
                mock.patch('sys.argv',['manage','diagnostic-window','device','--followup','--prompt-index','1']), \
                mock.patch('sys.stderr'):
            with self.assertRaises(SystemExit): manage.main()
            factory.assert_not_called()

    def test_capability_window_passes_requested_seconds(self):
        device=mock.Mock(); device.control.return_value={}
        with mock.patch.object(manage,'Device',return_value=device), \
                mock.patch('sys.argv',['manage','bluetooth-discoverable','device','--seconds','60']), \
                mock.patch('builtins.print'):
            manage.main()
        device.control.assert_called_once_with({'action':'bluetooth-discoverable','seconds':60})

    def test_diagnostic_capture_rejects_more_than_thirty_seconds(self):
        with mock.patch.object(manage,'Device') as factory, \
                mock.patch('sys.argv',['manage','diagnostic-start','device','--seconds','31']), \
                mock.patch('sys.stderr'):
            with self.assertRaises(SystemExit): manage.main()
            factory.assert_not_called()

class RealAlexaTests(unittest.TestCase):
    def test_real_mode_never_injects_a_local_window(self):
        with tempfile.TemporaryDirectory() as directory:
            device=mock.Mock(); commands=[]; states=iter([
                {'status':'listening','audio':{'ending_prompts':0}},
                {'status':'listening','audio':{'ending_prompts':0}},
                {'status':'listening','audio':{'ending_prompts':1}}])
            capture_states=iter([{'active':False,'armed':True,'ready':False},
                {'active':True,'armed':False,'ready':False},
                {'active':False,'armed':False,'ready':True}])
            def control(command):
                commands.append(command['action'])
                if command['action']=='status': return next(states)
                if command['action']=='diagnostic-status': return next(capture_states)
                return {}
            device.control.side_effect=control
            with mock.patch.object(capture.admin,'Device',return_value=device), \
                    mock.patch.object(capture.admin,'export_diagnostic',return_value={'exported':True}), \
                    mock.patch.object(capture.time,'sleep'), \
                    mock.patch('sys.argv',['capture','device','--trigger','alexa','--output',str(Path(directory)/'round')]), \
                    mock.patch('builtins.print'):
                capture.main()
            self.assertNotIn('diagnostic-window',commands)
            self.assertIn('diagnostic-arm',commands)
            self.assertNotIn('diagnostic-start',commands)
            self.assertIn('diagnostic-stop',commands)
    def test_real_result_requires_exactly_one_wake_and_alexa_source(self):
        with tempfile.TemporaryDirectory() as directory:
            AnalysisTests().fixture(directory)
            p=Path(directory); (p/'capture-context.json').write_text(json.dumps({'trigger':'alexa'}))
            self.assertFalse(analyze.analyze(p)['silence_regression_passed'])
            snapshots=json.loads((p/'snapshots.json').read_text())
            snapshots[-1]['state']['audio'].update(wake_detections=1,window_source='alexa',window_id=1)
            (p/'snapshots.json').write_text(json.dumps(snapshots))
            result=analyze.analyze(p)
            self.assertTrue(result['silence_regression_passed']); self.assertFalse(result['kws_bypassed'])
            snapshots[-1]['state']['audio']['window_source']='local_admin_diagnostic'
            (p/'snapshots.json').write_text(json.dumps(snapshots))
            self.assertFalse(analyze.analyze(p)['silence_regression_passed'])

if __name__=='__main__': unittest.main()
