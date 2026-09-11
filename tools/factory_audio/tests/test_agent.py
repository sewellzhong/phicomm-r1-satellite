"""Host contract tests for the synthetic factory-audio agent."""

import importlib.util
import os
from pathlib import Path
import socket
import struct
import subprocess
import sys
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[3]
AGENT = ROOT / "local-deps/build/factory-audio-agent-host/r1-factory-audio-agent"
VENDOR_MOCK = ROOT / "local-deps/build/factory-audio-agent-host/libr1-factory-audio-vendor-mock.so"
PROTO = ROOT / "protocol/factory_audio/factory_audio.proto"
PROTOC = ROOT / "local-deps/protoc-3.25.5/protoc"


class AgentTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.generated = tempfile.TemporaryDirectory()
        subprocess.run([
            str(PROTOC), "-I" + str(PROTO.parent),
            "--python_out=" + cls.generated.name, str(PROTO)
        ], check=True)
        sys.path.insert(0, cls.generated.name)
        import factory_audio_pb2
        cls.pb = factory_audio_pb2

    @classmethod
    def tearDownClass(cls):
        sys.path.remove(cls.generated.name)
        cls.generated.cleanup()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.socket_path = Path(self.temporary.name) / "agent.sock"
        self.agent = subprocess.Popen([
            str(AGENT), "--fake", "--expected-uid", str(os.getuid()),
            "--socket", str(self.socket_path)
        ], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        deadline = time.monotonic() + 5
        while self.agent.poll() is None and not self.socket_path.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        if not self.socket_path.exists():
            detail = "agent did not create socket"
            if self.agent.poll() is not None:
                detail = self.agent.stderr.read().decode()
            self.fail(detail)
        self.client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.client.settimeout(2)
        self.client.connect(str(self.socket_path))

    def tearDown(self):
        self.client.close()
        self.stop_agent()
        self.temporary.cleanup()

    def stop_agent(self):
        if self.agent.poll() is None:
            self.agent.terminate()
        self.agent.communicate(timeout=5)

    def send(self, envelope):
        payload = envelope.SerializeToString()
        self.client.sendall(struct.pack(">I", len(payload)) + payload)

    def receive(self):
        header = self.read_exact(4)
        length = struct.unpack(">I", header)[0]
        result = self.pb.Envelope()
        result.ParseFromString(self.read_exact(length))
        return result

    def read_exact(self, length):
        chunks = []
        while length:
            chunk = self.client.recv(length)
            if not chunk:
                raise EOFError()
            chunks.append(chunk)
            length -= len(chunk)
        return b"".join(chunks)

    def negotiate(self, expected_backend="synthetic-fake"):
        request = self.pb.Envelope(protocol_version=1, request_id=1)
        request.hello.minimum_version = 1
        request.hello.maximum_version = 1
        request.hello.client_name = "host-test"
        self.send(request)
        reply = self.receive()
        self.assertEqual(1, reply.hello_reply.selected_version)
        self.assertEqual(expected_backend, reply.hello_reply.backend_name)

    def test_negotiate_stream_reference_health_and_stop(self):
        self.negotiate()
        start = self.pb.Envelope(protocol_version=1, request_id=2)
        start.start_capture.format.sample_rate_hz = 16000
        start.start_capture.format.channels = 1
        start.start_capture.format.sample_width_bytes = 2
        start.start_capture.format.frame_duration_ms = 20
        self.send(start)
        self.assertEqual(self.pb.CAPTURE_STATE_STREAMING, self.receive().health.capture_state)
        frame = self.receive().audio_frame
        self.assertEqual(640, len(frame.pcm_s16le))
        self.assertEqual(1, frame.sequence)

        reference = self.pb.Envelope(protocol_version=1, request_id=3)
        reference.playback_reference.sequence = 1
        reference.playback_reference.monotonic_time_ns = time.monotonic_ns()
        reference.playback_reference.pcm_s16le = bytes(640)
        reference.playback_reference.source = "tts"
        self.send(reference)
        while True:
            reply = self.receive()
            if reply.request_id == 3:
                break
        self.assertEqual(self.pb.REFERENCE_STATE_ACTIVE, reply.health.reference_state)

        stop = self.pb.Envelope(protocol_version=1, request_id=4)
        stop.stop_capture.SetInParent()
        self.send(stop)
        while True:
            reply = self.receive()
            if reply.request_id == 4:
                break
        self.assertEqual(self.pb.CAPTURE_STATE_IDLE, reply.health.capture_state)

    def test_format_mismatch_fails_explicitly(self):
        self.negotiate()
        request = self.pb.Envelope(protocol_version=1, request_id=2)
        request.start_capture.format.sample_rate_hz = 48000
        request.start_capture.format.channels = 1
        request.start_capture.format.sample_width_bytes = 2
        request.start_capture.format.frame_duration_ms = 20
        self.send(request)
        self.assertEqual(self.pb.ERROR_CODE_FORMAT_MISMATCH, self.receive().error.code)

    def test_protocol_mismatch_fails_explicitly(self):
        request = self.pb.Envelope(protocol_version=2, request_id=9)
        request.hello.minimum_version = 2
        request.hello.maximum_version = 2
        self.send(request)
        self.assertEqual(self.pb.ERROR_CODE_PROTOCOL_MISMATCH, self.receive().error.code)

    def test_wrong_uid_is_rejected(self):
        self.client.close()
        self.stop_agent()
        self.agent = subprocess.Popen([
            str(AGENT), "--fake", "--expected-uid", str(os.getuid() + 1),
            "--socket", str(self.socket_path)
        ], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        deadline = time.monotonic() + 5
        while self.agent.poll() is None and not self.socket_path.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        if not self.socket_path.exists():
            detail = self.agent.stderr.read().decode() if self.agent.poll() is not None else "agent did not create socket"
            self.fail(detail)
        self.client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.client.settimeout(2)
        self.client.connect(str(self.socket_path))
        reply = self.receive()
        self.assertEqual(self.pb.ERROR_CODE_PERMISSION_DENIED, reply.error.code)

    def test_non_fake_backend_fails_closed(self):
        result = subprocess.run([
            str(AGENT), "--expected-uid", str(os.getuid()), "--socket", str(self.socket_path) + ".x"
        ], capture_output=True, text=True)
        self.assertEqual(3, result.returncode)
        self.assertIn("factory_backend_unimplemented", result.stderr)

    def test_debug_allow_flag_requires_vendor_backend(self):
        result = subprocess.run([
            str(AGENT), "--fake", "--allow-vendor-debug-files",
            "--expected-uid", str(os.getuid()), "--socket", str(self.socket_path) + ".debug"
        ], capture_output=True, text=True)
        self.assertEqual(2, result.returncode)
        self.assertIn("vendor_debug_files_require_vendor_backend", result.stderr)

    def test_micarray_tap_allow_flag_requires_vendor_backend(self):
        result = subprocess.run([
            str(AGENT), "--fake", "--allow-micarray-diagnostic-tap",
            "--expected-uid", str(os.getuid()), "--socket", str(self.socket_path) + ".tap"
        ], capture_output=True, text=True)
        self.assertEqual(2, result.returncode)
        self.assertIn("micarray_diagnostic_tap_requires_vendor_backend", result.stderr)

    def test_sdcard_group_is_retained_only_for_explicit_vendor_debug_boot(self):
        source = (ROOT / "android/factory-audio-agent/src/main.cpp").read_text()
        self.assertIn("constexpr gid_t kR1SdcardWriteGid = 1015", source)
        self.assertIn("allow_vendor_debug_files ? 1 : 0", source)
        self.assertIn("supplementary_group_drop_mismatch", source)

    def test_android_init_socket_is_inherited_without_rebinding_path(self):
        self.client.close()
        self.stop_agent()
        inherited_path = Path(self.temporary.name) / "init.sock"
        inherited = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        inherited.bind(str(inherited_path))
        environment = dict(os.environ)
        environment["ANDROID_SOCKET_r1_factory_audio"] = str(inherited.fileno())
        self.agent = subprocess.Popen([
            str(AGENT), "--fake", "--expected-uid", str(os.getuid()),
            "--init-socket-name", "r1_factory_audio"
        ], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, env=environment,
            pass_fds=(inherited.fileno(),))
        self.client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.client.settimeout(2)
        deadline = time.monotonic() + 5
        while True:
            try:
                self.client.connect(str(inherited_path))
                break
            except (ConnectionRefusedError, FileNotFoundError):
                if self.agent.poll() is not None or time.monotonic() >= deadline:
                    self.fail(self.agent.stderr.read().decode())
                time.sleep(0.01)
        inherited.close()
        self.negotiate()

    def test_vendor_backend_requires_explicit_shape_and_reports_only_proven_state(self):
        self.client.close()
        self.stop_agent()
        self.agent = subprocess.Popen([
            str(AGENT), "--expected-uid", str(os.getuid()),
            "--socket", str(self.socket_path),
            "--vendor-library", str(VENDOR_MOCK),
            "--vendor-open-channels", "2",
            "--vendor-output-channels", "2",
            "--vendor-output-channel", "1",
        ], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        deadline = time.monotonic() + 5
        while self.agent.poll() is None and not self.socket_path.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(self.socket_path.exists())
        self.client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.client.settimeout(2)
        self.client.connect(str(self.socket_path))
        self.negotiate("unisound_uni4mic_3448")
        start = self.pb.Envelope(protocol_version=1, request_id=2)
        start.start_capture.format.sample_rate_hz = 16000
        start.start_capture.format.channels = 1
        start.start_capture.format.sample_width_bytes = 2
        start.start_capture.format.frame_duration_ms = 20
        start.start_capture.include_diagnostic_output = True
        start.start_capture.vendor_debug_files = True
        self.send(start)
        denied = self.receive()
        self.assertEqual(self.pb.ERROR_CODE_PERMISSION_DENIED, denied.error.code)
        self.assertEqual("vendor_debug_files_not_allowed", denied.error.detail)
        start.request_id = 21
        start.start_capture.vendor_debug_files = False
        start.start_capture.micarray_diagnostic_tap = True
        self.send(start)
        denied = self.receive()
        self.assertEqual(self.pb.ERROR_CODE_PERMISSION_DENIED, denied.error.code)
        self.assertEqual("micarray_diagnostic_tap_not_allowed", denied.error.detail)
        start.request_id = 3
        start.start_capture.micarray_diagnostic_tap = False
        self.send(start)
        health = self.receive().health
        self.assertEqual("unisound_uni4mic_3448", health.backend_name)
        self.assertEqual("MOCK_UNI_4MIC_V1.1", health.vendor_board_version)
        self.assertEqual(4, health.raw_mic_channels)
        self.assertEqual(0, health.aec_reference_channels)
        self.assertEqual(2, health.configured_aec_reference_channels)
        self.assertTrue(health.array_processing_active)
        self.assertFalse(health.aec_active)
        self.assertTrue(health.aec_configured)
        frame = self.receive().audio_frame
        self.assertEqual(145, frame.doa_degrees)
        self.assertTrue(frame.doa_valid)
        self.assertEqual((1, 3), struct.unpack_from("<hh", frame.pcm_s16le))
        self.assertEqual(2, frame.diagnostic_output_channels)
        self.assertEqual(1, frame.diagnostic_selected_output_channel)
        self.assertEqual(1280, len(frame.diagnostic_interleaved_pcm_s16le))
        self.assertEqual((0, 1, 2, 3), struct.unpack_from(
            "<hhhh", frame.diagnostic_interleaved_pcm_s16le))

        # The next 20 ms frame comes from the remainder of the same original
        # 2400-byte HAL read instead of forcing an old 1280-byte call boundary.
        next_frame = self.receive().audio_frame
        self.assertEqual(1280, len(next_frame.diagnostic_interleaved_pcm_s16le))
        self.assertEqual((640, 641, 642, 643), struct.unpack_from(
            "<hhhh", next_frame.diagnostic_interleaved_pcm_s16le))

        stop = self.pb.Envelope(protocol_version=1, request_id=4)
        stop.stop_capture.SetInParent()
        self.send(stop)
        while self.receive().request_id != 4:
            pass
        start.request_id = 5
        start.start_capture.include_diagnostic_output = False
        self.send(start)
        while self.receive().request_id != 5:
            pass
        production_frame = self.receive().audio_frame
        self.assertEqual(0, production_frame.diagnostic_output_channels)
        self.assertEqual(0, len(production_frame.diagnostic_interleaved_pcm_s16le))

    def test_vendor_debug_files_require_agent_allow_and_diagnostic_request(self):
        self.client.close()
        self.stop_agent()
        environment = dict(os.environ)
        environment["R1_FACTORY_AUDIO_TEST_DEBUG_DIR"] = self.temporary.name
        environment["R1_VENDOR_MOCK_SYSTEM_COMMAND"] = (
            "mkdir -p " + self.temporary.name + "/")
        wake_trace = Path(self.temporary.name) / "wake-status"
        environment["R1_VENDOR_MOCK_WAKE_STATUS_FILE"] = str(wake_trace)
        self.agent = subprocess.Popen([
            str(AGENT), "--expected-uid", str(os.getuid()),
            "--socket", str(self.socket_path),
            "--vendor-library", str(VENDOR_MOCK),
            "--vendor-open-channels", "2",
            "--vendor-output-channels", "2",
            "--vendor-output-channel", "0",
            "--allow-vendor-debug-files",
        ], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, env=environment)
        deadline = time.monotonic() + 5
        while (self.agent.poll() is None and not self.socket_path.exists()
               and time.monotonic() < deadline):
            time.sleep(0.01)
        self.assertTrue(self.socket_path.exists())
        self.client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.client.settimeout(2)
        self.client.connect(str(self.socket_path))
        self.negotiate("unisound_uni4mic_3448")

        invalid = self.pb.Envelope(protocol_version=1, request_id=2)
        invalid.start_capture.format.sample_rate_hz = 16000
        invalid.start_capture.format.channels = 1
        invalid.start_capture.format.sample_width_bytes = 2
        invalid.start_capture.format.frame_duration_ms = 20
        invalid.start_capture.vendor_debug_files = True
        self.send(invalid)
        self.assertEqual(self.pb.ERROR_CODE_INVALID_REQUEST, self.receive().error.code)

        valid = self.pb.Envelope(protocol_version=1, request_id=3)
        valid.start_capture.CopyFrom(invalid.start_capture)
        valid.start_capture.include_diagnostic_output = True
        self.send(valid)
        health = self.receive().health
        self.assertEqual(self.pb.CAPTURE_STATE_STREAMING, health.capture_state)
        self.assertTrue(health.vendor_debug_files_active)
        for _ in range(51):
            self.receive()
        wake_lifecycle = wake_trace.read_text()
        self.assertTrue(wake_lifecycle.startswith("001"), wake_lifecycle)

        stop = self.pb.Envelope(protocol_version=1, request_id=4)
        stop.stop_capture.SetInParent()
        self.send(stop)
        while True:
            reply = self.receive()
            if reply.request_id == 4:
                break
        self.assertFalse(reply.health.vendor_debug_files_active)
        self.assertTrue(wake_trace.read_text().endswith("0"))

    def test_micarray_tap_forwards_and_copies_only_with_both_opt_ins(self):
        self.client.close()
        self.stop_agent()
        environment = dict(os.environ)
        environment["R1_VENDOR_MOCK_CONCURRENT_TAP"] = "1"
        self.agent = subprocess.Popen([
            str(AGENT), "--expected-uid", str(os.getuid()),
            "--socket", str(self.socket_path),
            "--vendor-library", str(VENDOR_MOCK),
            "--vendor-open-channels", "2",
            "--vendor-output-channels", "2",
            "--vendor-output-channel", "0",
            "--allow-micarray-diagnostic-tap",
        ], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, env=environment)
        deadline = time.monotonic() + 5
        while (self.agent.poll() is None and not self.socket_path.exists()
               and time.monotonic() < deadline):
            time.sleep(0.01)
        self.assertTrue(self.socket_path.exists())
        self.client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.client.settimeout(2)
        self.client.connect(str(self.socket_path))
        self.negotiate("unisound_uni4mic_3448")

        invalid = self.pb.Envelope(protocol_version=1, request_id=2)
        invalid.start_capture.format.sample_rate_hz = 16000
        invalid.start_capture.format.channels = 1
        invalid.start_capture.format.sample_width_bytes = 2
        invalid.start_capture.format.frame_duration_ms = 20
        invalid.start_capture.micarray_diagnostic_tap = True
        self.send(invalid)
        denied = self.receive()
        self.assertEqual(self.pb.ERROR_CODE_INVALID_REQUEST, denied.error.code)
        self.assertEqual("micarray_diagnostic_tap_requires_diagnostic_capture",
                         denied.error.detail)

        valid = self.pb.Envelope(protocol_version=1, request_id=3)
        valid.start_capture.CopyFrom(invalid.start_capture)
        valid.start_capture.include_diagnostic_output = True
        self.send(valid)
        health = self.receive().health
        self.assertTrue(health.micarray_diagnostic_tap_active)
        self.assertEqual(0, health.micarray_diagnostic_tap_dropped)
        self.assertEqual(0, health.micarray_diagnostic_tap_invalid)
        frame = self.receive().audio_frame
        self.assertGreaterEqual(len(frame.micarray_diagnostic_calls), 1)
        self.assertLessEqual(len(frame.micarray_diagnostic_calls), 4)
        call = frame.micarray_diagnostic_calls[0]
        self.assertGreaterEqual(call.sequence, 1)
        self.assertEqual(256, call.samples_per_channel)
        self.assertEqual(4, call.raw_mic_channels)
        self.assertEqual(2, call.echo_reference_channels)
        self.assertEqual(2048, len(call.raw_mic_pcm_s16le))
        self.assertEqual(1024, len(call.echo_reference_pcm_s16le))
        self.assertEqual(512, len(call.asr_pcm_s16le))
        self.assertEqual(512, len(call.vad_pcm_s16le))
        self.assertEqual((1000, 1001, 1002, 1003), struct.unpack_from(
            "<hhhh", call.raw_mic_pcm_s16le))
        self.assertEqual((200, 201, 202, 203), struct.unpack_from(
            "<hhhh", call.echo_reference_pcm_s16le))
        self.assertEqual((800, 802), struct.unpack_from("<hh", call.asr_pcm_s16le))
        self.assertEqual((807, 809), struct.unpack_from("<hh", call.vad_pcm_s16le))
        self.assertEqual(73, call.result)
        self.assertFalse(call.is_waked)

        observed_waked_call = False
        for _ in range(60):
            later = self.receive().audio_frame
            observed_waked_call = observed_waked_call or any(
                item.is_waked for item in later.micarray_diagnostic_calls)
        self.assertTrue(observed_waked_call)

        stop = self.pb.Envelope(protocol_version=1, request_id=4)
        stop.stop_capture.SetInParent()
        self.send(stop)
        while True:
            reply = self.receive()
            if reply.request_id == 4:
                break
        self.assertFalse(reply.health.micarray_diagnostic_tap_active)

        production = self.pb.Envelope(protocol_version=1, request_id=5)
        production.start_capture.format.sample_rate_hz = 16000
        production.start_capture.format.channels = 1
        production.start_capture.format.sample_width_bytes = 2
        production.start_capture.format.frame_duration_ms = 20
        self.send(production)
        while self.receive().request_id != 5:
            pass
        production_frame = self.receive().audio_frame
        self.assertEqual(0, len(production_frame.micarray_diagnostic_calls))

    def test_vendor_debug_files_refuse_non_allowlisted_shell_command(self):
        self.client.close()
        self.stop_agent()
        environment = dict(os.environ)
        environment["R1_FACTORY_AUDIO_TEST_DEBUG_DIR"] = self.temporary.name
        environment["R1_VENDOR_MOCK_SYSTEM_COMMAND"] = "touch " + self.temporary.name + "/bad"
        self.agent = subprocess.Popen([
            str(AGENT), "--expected-uid", str(os.getuid()),
            "--socket", str(self.socket_path),
            "--vendor-library", str(VENDOR_MOCK),
            "--vendor-open-channels", "2",
            "--vendor-output-channels", "2",
            "--vendor-output-channel", "0",
            "--allow-vendor-debug-files",
        ], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, env=environment)
        deadline = time.monotonic() + 5
        while (self.agent.poll() is None and not self.socket_path.exists()
               and time.monotonic() < deadline):
            time.sleep(0.01)
        self.assertTrue(self.socket_path.exists())
        self.client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.client.settimeout(2)
        self.client.connect(str(self.socket_path))
        self.negotiate("unisound_uni4mic_3448")
        request = self.pb.Envelope(protocol_version=1, request_id=2)
        request.start_capture.format.sample_rate_hz = 16000
        request.start_capture.format.channels = 1
        request.start_capture.format.sample_width_bytes = 2
        request.start_capture.format.frame_duration_ms = 20
        request.start_capture.include_diagnostic_output = True
        request.start_capture.vendor_debug_files = True
        self.send(request)
        reply = self.receive()
        self.assertEqual(self.pb.ERROR_CODE_BACKEND_FAILURE, reply.error.code)
        self.assertFalse((Path(self.temporary.name) / "bad").exists())

    def test_vendor_backend_rejects_unproven_defaults(self):
        self.client.close()
        self.stop_agent()
        result = subprocess.run([
            str(AGENT), "--expected-uid", str(os.getuid()),
            "--socket", str(self.socket_path),
            "--vendor-library", str(VENDOR_MOCK),
        ], capture_output=True, text=True)
        self.assertEqual(2, result.returncode)
        self.assertIn("invalid_vendor_backend_shape", result.stderr)

    def test_disconnect_releases_capture_and_next_client_can_start(self):
        self.negotiate()
        start = self.pb.Envelope(protocol_version=1, request_id=2)
        start.start_capture.format.sample_rate_hz = 16000
        start.start_capture.format.channels = 1
        start.start_capture.format.sample_width_bytes = 2
        start.start_capture.format.frame_duration_ms = 20
        self.send(start)
        self.assertEqual(self.pb.CAPTURE_STATE_STREAMING, self.receive().health.capture_state)
        self.client.close()

        self.client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.client.settimeout(2)
        self.client.connect(str(self.socket_path))
        self.negotiate()
        self.send(start)
        self.assertEqual(self.pb.CAPTURE_STATE_STREAMING, self.receive().health.capture_state)
        self.assertEqual(1, self.receive().audio_frame.sequence)

    def test_accelerated_twenty_second_and_thirty_minute_budgets_are_contiguous(self):
        self.client.close()
        self.stop_agent()
        self.agent = subprocess.Popen([
            str(AGENT), "--fake", "--fake-frame-period-us", "1",
            "--expected-uid", str(os.getuid()), "--socket", str(self.socket_path)
        ], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        deadline = time.monotonic() + 5
        while self.agent.poll() is None and not self.socket_path.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        if not self.socket_path.exists():
            detail = self.agent.stderr.read().decode() if self.agent.poll() is not None else "agent did not create socket"
            self.fail(detail)
        self.client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.client.settimeout(5)
        self.client.connect(str(self.socket_path))
        self.negotiate()
        start = self.pb.Envelope(protocol_version=1, request_id=2)
        start.start_capture.format.sample_rate_hz = 16000
        start.start_capture.format.channels = 1
        start.start_capture.format.sample_width_bytes = 2
        start.start_capture.format.frame_duration_ms = 20
        self.send(start)
        self.assertEqual(self.pb.CAPTURE_STATE_STREAMING, self.receive().health.capture_state)
        # 1,000 frames covers 20 seconds and 90,000 covers 30 minutes; time is accelerated.
        for expected_sequence in range(1, 90001):
            sequence = self.receive().audio_frame.sequence
            self.assertEqual(expected_sequence, sequence)
            if expected_sequence == 1000:
                self.assertEqual(20, expected_sequence * 20 // 1000)


if __name__ == "__main__":
    unittest.main()
