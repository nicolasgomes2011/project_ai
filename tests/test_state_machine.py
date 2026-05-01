"""
Tests for the RealtimeMode state machine, TTS cooldown, and utterance log.

All hardware is mocked:
  - STTProcessor.transcribe  → returns a controlled string
  - TTSProcessor.speak_async → no-op coroutine
  - AudioSensor / VisionSensor → not instantiated (voice_enabled=False, vision_enabled=False)
  - Agent.chat               → returns a fixed string
  - Memory, UserProfile, SystemContext, ActivitySensor → real objects (no I/O side effects)
"""

import asyncio
import json
import os
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# ── Make hardware imports safe even when the devices are absent ───────────────
import sys

# Stub heavy optional dependencies so the import chain doesn't fail
_STUBS = {
    "sounddevice": MagicMock(),
    "webrtcvad": MagicMock(),
    "faster_whisper": MagicMock(),
    "edge_tts": MagicMock(),
    "pygame": MagicMock(),
    "pygame.mixer": MagicMock(),
    "mss": MagicMock(),
    "pytesseract": MagicMock(),
    "pygetwindow": MagicMock(),
    "pyperclip": MagicMock(),
    "pyttsx3": MagicMock(),
    "anthropic": MagicMock(),
}
for mod, stub in _STUBS.items():
    if mod not in sys.modules:
        sys.modules[mod] = stub

from jarvis.modes.realtime import JarvisState, RealtimeMode  # noqa: E402


# ── Shared test utility ───────────────────────────────────────────────────────

def _cancel_engaged_timer(mode: RealtimeMode, loop: asyncio.AbstractEventLoop) -> None:
    """Cancel the engaged timeout task so the event loop closes cleanly."""
    task = mode._engaged_timer_task
    if task and not task.done():
        task.cancel()
        try:
            loop.run_until_complete(task)
        except (asyncio.CancelledError, Exception):
            pass


# ── Helper: build a RealtimeMode with all sensors disabled ───────────────────

def _make_mode(tmp_path: Path) -> RealtimeMode:
    """Return a RealtimeMode with no audio/vision and all I/O mocked."""
    with patch("jarvis.config.LOG_DIR", tmp_path):
        mode = RealtimeMode(vision_enabled=False, voice_enabled=False)

    # Replace TTS with async no-op
    mode.tts = MagicMock()
    mode.tts.speak_async = AsyncMock(return_value=None)
    mode.tts.stop = MagicMock()
    mode.tts.is_playing = False

    # Replace Agent with fixed reply
    mode.agent = MagicMock()
    mode.agent.provider = "groq"
    mode.agent._model = "test-model"
    mode.agent.chat = MagicMock(return_value="Resposta de teste.")

    # Replace Memory with minimal stub
    mode.memory = MagicMock()
    mode.memory.get_messages_for_api = MagicMock(return_value=[])
    mode.memory.add_message = MagicMock()
    mode.memory.log_event = MagicMock()
    mode.memory.get_last_user_message = MagicMock(return_value="")
    mode.memory.last_response_time = time.time()
    mode.memory.message_count = 0

    # Point the utterance log to a temp file
    mode._utterance_log_path = tmp_path / "utterances_test.jsonl"

    return mode


def _fake_audio() -> bytes:
    """16-bit mono 16 kHz silent audio, 0.5 s — enough to pass STT length check."""
    return b"\x00\x00" * 8000


# ─────────────────────────────────────────────────────────────────────────────

class TestJarvisStateEnum(unittest.TestCase):

    def test_all_states_defined(self):
        values = {s.value for s in JarvisState}
        self.assertEqual(values, {"sleeping", "listening", "engaged", "executing"})

    def test_default_state_is_sleeping(self):
        with patch("jarvis.config.LOG_DIR", Path(os.environ.get("TEMP", "/tmp"))):
            mode = RealtimeMode(vision_enabled=False, voice_enabled=False)
        self.assertEqual(mode._state, JarvisState.SLEEPING)


class TestCheckWakeWord(unittest.TestCase):
    """Unit-test _check_wake_word in isolation (no async needed)."""

    def setUp(self):
        tmp = Path(os.environ.get("TEMP", "/tmp"))
        with patch("jarvis.config.LOG_DIR", tmp):
            self.mode = RealtimeMode(vision_enabled=False, voice_enabled=False)

    def _ww(self, text):
        return self.mode._check_wake_word(text)

    def test_exact_jarvis(self):
        found, rem = self._ww("Jarvis")
        self.assertTrue(found)
        self.assertEqual(rem, "")

    def test_jarvis_with_command(self):
        found, rem = self._ww("Jarvis abre o spotify")
        self.assertTrue(found)
        self.assertEqual(rem, "abre o spotify")

    def test_jarvis_comma_command(self):
        found, rem = self._ww("Jarvis, que horas são?")
        self.assertTrue(found)
        self.assertIn("que horas", rem)

    def test_alias_jervis(self):
        found, _ = self._ww("jervis")
        self.assertTrue(found)

    def test_no_wake_word(self):
        found, _ = self._ww("estou testando")
        self.assertFalse(found)

    def test_wake_word_not_first(self):
        found, _ = self._ww("oi jarvis")
        self.assertFalse(found)

    def test_empty_text(self):
        found, rem = self._ww("")
        self.assertFalse(found)
        self.assertEqual(rem, "")

    def test_fuzzy_jarviss(self):
        found, rem = self._ww("jarviss abre o chrome")
        self.assertTrue(found)
        self.assertEqual(rem, "abre o chrome")


class TestTransitionTo(unittest.TestCase):

    def setUp(self):
        tmp = Path(os.environ.get("TEMP", "/tmp"))
        with patch("jarvis.config.LOG_DIR", tmp):
            self.mode = RealtimeMode(vision_enabled=False, voice_enabled=False)

    def test_initial_state(self):
        self.assertEqual(self.mode._state, JarvisState.SLEEPING)

    def test_transition_changes_state(self):
        self.mode._transition_to(JarvisState.ENGAGED)
        self.assertEqual(self.mode._state, JarvisState.ENGAGED)

    def test_transition_to_same_state_is_noop(self):
        self.mode._state = JarvisState.ENGAGED
        self.mode._transition_to(JarvisState.ENGAGED)
        self.assertEqual(self.mode._state, JarvisState.ENGAGED)

    def test_full_cycle(self):
        self.mode._transition_to(JarvisState.ENGAGED)
        self.mode._transition_to(JarvisState.EXECUTING)
        self.mode._transition_to(JarvisState.ENGAGED)
        self.mode._transition_to(JarvisState.SLEEPING)
        self.assertEqual(self.mode._state, JarvisState.SLEEPING)


class TestTtsCooldown(unittest.TestCase):

    def setUp(self):
        tmp = Path(os.environ.get("TEMP", "/tmp"))
        with patch("jarvis.config.LOG_DIR", tmp):
            self.mode = _make_mode(tmp)
        self.loop = asyncio.new_event_loop()

    def tearDown(self):
        _cancel_engaged_timer(self.mode, self.loop)
        self.loop.close()

    def _run(self, coro):
        return self.loop.run_until_complete(coro)

    def _utterance_with_text(self, text: str):
        """Simulate an utterance whose STT returns `text`."""
        with patch.object(self.mode.stt, "transcribe", return_value=text):
            self._run(self.mode._on_utterance(_fake_audio()))

    def test_utterance_in_cooldown_is_ignored(self):
        """Utterance during TTS cooldown must be discarded without calling STT."""
        self.mode._tts_cooldown_until = time.time() + 60  # far future

        transcribe_mock = MagicMock(return_value="jarvis abre algo")
        with patch.object(self.mode.stt, "transcribe", transcribe_mock):
            self._run(self.mode._on_utterance(_fake_audio()))

        transcribe_mock.assert_not_called()

    def test_utterance_after_cooldown_is_processed(self):
        """Utterance after cooldown expires must be processed normally."""
        self.mode._tts_cooldown_until = time.time() - 1  # already expired
        self.mode._state = JarvisState.SLEEPING

        with patch.object(self.mode.stt, "transcribe", return_value="jarvis que horas são"):
            self._run(self.mode._on_utterance(_fake_audio()))

        self.mode.agent.chat.assert_called_once()

    def test_cooldown_set_after_respond(self):
        """_tts_cooldown_until must be > now after _respond completes."""
        self.mode._state = JarvisState.ENGAGED
        before = time.time()

        with patch.object(self.mode.stt, "transcribe", return_value="que horas são"):
            self._run(self.mode._on_utterance(_fake_audio()))

        self.assertGreater(self.mode._tts_cooldown_until, before)

    def test_cooldown_set_after_acknowledge(self):
        """_tts_cooldown_until must be set after _acknowledge() (only wake word)."""
        self.mode._state = JarvisState.SLEEPING
        before = time.time()

        with patch.object(self.mode.stt, "transcribe", return_value="jarvis"):
            self._run(self.mode._on_utterance(_fake_audio()))

        self.assertGreater(self.mode._tts_cooldown_until, before)


class TestStateMachineSleeping(unittest.TestCase):

    def setUp(self):
        tmp = Path(os.environ.get("TEMP", "/tmp"))
        with patch("jarvis.config.LOG_DIR", tmp):
            self.mode = _make_mode(tmp)
        self.loop = asyncio.new_event_loop()

    def tearDown(self):
        _cancel_engaged_timer(self.mode, self.loop)
        self.loop.close()

    def _run(self, coro):
        return self.loop.run_until_complete(coro)

    def _utterance(self, text):
        with patch.object(self.mode.stt, "transcribe", return_value=text):
            self._run(self.mode._on_utterance(_fake_audio()))

    def test_speech_without_wake_word_ignored(self):
        """In sleeping state, speech without wake word must NOT call agent."""
        self.mode._state = JarvisState.SLEEPING

        self._utterance("estou testando alguma coisa")

        self.mode.agent.chat.assert_not_called()
        self.assertEqual(self.mode._state, JarvisState.SLEEPING)

    def test_wake_word_only_transitions_to_engaged(self):
        """'Jarvis' alone must wake up and enter ENGAGED."""
        self.mode._state = JarvisState.SLEEPING

        self._utterance("Jarvis")

        self.assertEqual(self.mode._state, JarvisState.ENGAGED)
        self.mode.agent.chat.assert_not_called()  # No command to process

    def test_wake_word_plus_command_calls_agent(self):
        """'Jarvis, X' must call agent with X only (no wake word in text)."""
        self.mode._state = JarvisState.SLEEPING

        self._utterance("Jarvis que horas são")

        self.mode.agent.chat.assert_called_once()
        call_args = self.mode.agent.chat.call_args[0]
        self.assertNotIn("jarvis", call_args[0].lower())
        self.assertIn("que horas", call_args[0].lower())

    def test_state_after_wake_word_plus_command_is_engaged(self):
        """After processing a command, state must return to ENGAGED (not sleeping)."""
        self.mode._state = JarvisState.SLEEPING

        self._utterance("Jarvis abre o spotify")

        self.assertEqual(self.mode._state, JarvisState.ENGAGED)

    def test_alias_jervis_also_wakes(self):
        self.mode._state = JarvisState.SLEEPING

        self._utterance("jervis abre o word")

        self.mode.agent.chat.assert_called_once()


class TestStateMachineEngaged(unittest.TestCase):

    def setUp(self):
        tmp = Path(os.environ.get("TEMP", "/tmp"))
        with patch("jarvis.config.LOG_DIR", tmp):
            self.mode = _make_mode(tmp)
        self.loop = asyncio.new_event_loop()

    def tearDown(self):
        _cancel_engaged_timer(self.mode, self.loop)
        self.loop.close()

    def _run(self, coro):
        return self.loop.run_until_complete(coro)

    def _utterance(self, text):
        with patch.object(self.mode.stt, "transcribe", return_value=text):
            self._run(self.mode._on_utterance(_fake_audio()))

    def test_command_without_wake_word_accepted_while_engaged(self):
        """In ENGAGED state, speech without wake word must be forwarded to agent."""
        self.mode._state = JarvisState.ENGAGED

        self._utterance("abre o navegador")

        self.mode.agent.chat.assert_called_once()

    def test_wake_word_repeated_in_engaged_still_works(self):
        """Repeating wake word while ENGAGED must extract command and call agent."""
        self.mode._state = JarvisState.ENGAGED

        self._utterance("Jarvis abre o spotify")

        self.mode.agent.chat.assert_called_once()
        call_text = self.mode.agent.chat.call_args[0][0]
        self.assertNotIn("jarvis", call_text.lower())

    def test_executing_state_ignores_utterance(self):
        """While EXECUTING, new utterances must be ignored."""
        self.mode._state = JarvisState.EXECUTING

        self._utterance("abre o bloco de notas")

        self.mode.agent.chat.assert_not_called()


class TestEngagedTimeout(unittest.TestCase):

    def setUp(self):
        tmp = Path(os.environ.get("TEMP", "/tmp"))
        with patch("jarvis.config.LOG_DIR", tmp):
            self.mode = _make_mode(tmp)

    def test_timeout_coroutine_returns_to_sleeping(self):
        """After ENGAGED_TIMEOUT_S the state must return to SLEEPING."""
        self.mode._state = JarvisState.ENGAGED

        async def run_timeout():
            import jarvis.config as cfg
            old = cfg.ENGAGED_TIMEOUT_S
            cfg.ENGAGED_TIMEOUT_S = 0.05  # very short for the test
            try:
                await self.mode._engaged_timeout_coro()
            finally:
                cfg.ENGAGED_TIMEOUT_S = old

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(run_timeout())
        finally:
            loop.close()
        self.assertEqual(self.mode._state, JarvisState.SLEEPING)

    def test_timeout_cancelled_does_not_change_state(self):
        """If the timeout task is cancelled, state must remain unchanged."""
        self.mode._state = JarvisState.ENGAGED

        async def run():
            task = asyncio.current_task()
            task.cancel()
            await self.mode._engaged_timeout_coro()

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(run())
        except asyncio.CancelledError:
            pass
        finally:
            loop.close()

        # State must still be ENGAGED since the timeout was cancelled
        self.assertEqual(self.mode._state, JarvisState.ENGAGED)


class TestUtteranceLog(unittest.TestCase):

    def setUp(self):
        import tempfile
        self.tmp_dir = Path(tempfile.mkdtemp())
        with patch("jarvis.config.LOG_DIR", self.tmp_dir):
            self.mode = _make_mode(self.tmp_dir)
        self.mode._utterance_log_path = self.tmp_dir / "utterances_test.jsonl"
        self.loop = asyncio.new_event_loop()

    def tearDown(self):
        _cancel_engaged_timer(self.mode, self.loop)
        self.loop.close()

    def _run(self, coro):
        return self.loop.run_until_complete(coro)

    def _utterance(self, text):
        with patch.object(self.mode.stt, "transcribe", return_value=text):
            self._run(self.mode._on_utterance(_fake_audio()))

    def _read_logs(self):
        path = self.mode._utterance_log_path
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def test_log_created_on_utterance(self):
        self.mode._state = JarvisState.SLEEPING
        self._utterance("estou testando")
        logs = self._read_logs()
        self.assertGreater(len(logs), 0)

    def test_log_contains_required_fields(self):
        self.mode._state = JarvisState.SLEEPING
        self._utterance("estou testando")
        entry = self._read_logs()[0]
        for field in ("timestamp", "state_before", "state_after", "ignored", "ignore_reason",
                      "wake_word_detected", "command_text", "called_llm",
                      "stt_ms", "total_ms", "in_tts_cooldown"):
            self.assertIn(field, entry, f"Missing field: {field}")

    def test_log_ignored_true_without_wake_word(self):
        self.mode._state = JarvisState.SLEEPING
        self._utterance("estou testando")
        entry = self._read_logs()[0]
        self.assertTrue(entry["ignored"])
        self.assertEqual(entry["ignore_reason"], "no_wake_word")
        self.assertFalse(entry["called_llm"])

    def test_log_wake_word_detected(self):
        self.mode._state = JarvisState.SLEEPING
        self._utterance("Jarvis que horas são")
        entry = self._read_logs()[0]
        self.assertTrue(entry["wake_word_detected"])
        self.assertFalse(entry["ignored"])
        self.assertTrue(entry["called_llm"])

    def test_log_tts_cooldown(self):
        self.mode._tts_cooldown_until = time.time() + 60
        self._utterance("qualquer coisa")
        entry = self._read_logs()[0]
        self.assertTrue(entry["in_tts_cooldown"])
        self.assertTrue(entry["ignored"])
        self.assertEqual(entry["ignore_reason"], "tts_cooldown")

    def test_log_state_before_and_after(self):
        self.mode._state = JarvisState.SLEEPING
        self._utterance("Jarvis abre o spotify")
        entry = self._read_logs()[0]
        self.assertEqual(entry["state_before"], "sleeping")
        self.assertEqual(entry["state_after"], "engaged")

    def test_log_timing_fields_are_positive(self):
        self.mode._state = JarvisState.SLEEPING
        self._utterance("Jarvis que horas são")
        entry = self._read_logs()[0]
        self.assertGreater(entry["total_ms"], 0)
        self.assertGreaterEqual(entry["stt_ms"], 0)


class TestProactivityDisabled(unittest.TestCase):
    """Observer must return empty events when PROACTIVITY_ENABLED is False."""

    _STATE = {
        "screen_text": "AttributeError: something failed on line 42",
        "window_title": "main.py - VS Code",
        "app_name": "VS Code",
        "last_speech": "",
        "elapsed_since_last_response": 200.0,
        "activity_type": "CODING",
    }

    def test_observer_returns_empty_when_disabled(self):
        from jarvis.observer.observer import Observer

        with patch("jarvis.observer.observer._cfg.PROACTIVITY_ENABLED", False):
            obs = Observer()
            obs._last_event_time = 0
            events = obs.check(self._STATE)
            self.assertEqual(events, [])

    def test_observer_returns_events_when_enabled(self):
        from jarvis.observer.observer import Observer

        with patch("jarvis.observer.observer._cfg.PROACTIVITY_ENABLED", True):
            obs = Observer()
            obs._last_event_time = 0  # Force cooldown expired
            events = obs.check(self._STATE)
            self.assertGreater(len(events), 0)


class TestStateGate(unittest.TestCase):
    """
    Verifica que o state gate bloqueia corretamente qualquer ação quando sleeping
    sem wake word — incluindo annotation mode, learn commands e LLM.
    """

    def setUp(self):
        import tempfile
        self.tmp_dir = Path(tempfile.mkdtemp())
        with patch("jarvis.config.LOG_DIR", self.tmp_dir):
            self.mode = _make_mode(self.tmp_dir)
        self.mode._utterance_log_path = self.tmp_dir / "utterances_test.jsonl"
        self.loop = asyncio.new_event_loop()

    def tearDown(self):
        _cancel_engaged_timer(self.mode, self.loop)
        self.loop.close()

    def _run(self, coro):
        return self.loop.run_until_complete(coro)

    def _utterance(self, text):
        with patch.object(self.mode.stt, "transcribe", return_value=text):
            self._run(self.mode._on_utterance(_fake_audio()))

    # ── Annotation activation must require wake word ──────────────────────

    def test_sleeping_annotation_activate_without_wake_word_is_ignored(self):
        """'ativar modo anotação' while sleeping must be ignored (no wake word)."""
        self.mode._state = JarvisState.SLEEPING
        self.mode._annotation_mode = False

        self._utterance("ativar modo anotação")

        self.assertFalse(self.mode._annotation_mode)  # Must NOT have activated
        self.mode.tts.speak_async.assert_not_called()

    def test_sleeping_annotation_activate_with_wake_word_works(self):
        """'Jarvis ativar modo anotação' while sleeping must activate annotation."""
        self.mode._state = JarvisState.SLEEPING
        self.mode._annotation_mode = False

        self._utterance("Jarvis ativar modo anotação")

        self.assertTrue(self.mode._annotation_mode)  # Must have activated

    def test_engaged_annotation_activate_works_without_repeating_wake_word(self):
        """'ativar modo anotação' while engaged must activate without wake word."""
        self.mode._state = JarvisState.ENGAGED
        self.mode._annotation_mode = False

        self._utterance("ativar modo anotação")

        self.assertTrue(self.mode._annotation_mode)

    # ── Learn command must require wake word ──────────────────────────────

    def test_sleeping_learn_command_without_wake_word_is_ignored(self):
        """'lembra que X' while sleeping must be ignored (no wake word)."""
        self.mode._state = JarvisState.SLEEPING

        with patch.object(self.mode, "_check_learn_command",
                          new=AsyncMock(return_value=True)) as mock_learn:
            self._utterance("lembra que eu uso Python")

        # _check_learn_command must never be called while sleeping without wake word
        mock_learn.assert_not_called()
        self.mode.agent.chat.assert_not_called()

    def test_sleeping_learn_command_with_wake_word_is_processed(self):
        """'Jarvis lembra que X' must process the learn command."""
        self.mode._state = JarvisState.SLEEPING

        # The learn command handler saves to profile; we just need to confirm
        # the pipeline is reached (agent NOT called, but learn command processed)
        with patch.object(self.mode, "_check_learn_command",
                          new=AsyncMock(return_value=True)) as mock_learn:
            self._utterance("Jarvis lembra que eu uso Python")

        mock_learn.assert_called_once()

    # ── Annotation mode already active while sleeping ─────────────────────

    def test_sleeping_annotation_active_accumulates_without_wake_word(self):
        """
        If annotation mode is already active and Jarvis is sleeping,
        speech must be accumulated without requiring a new wake word.
        Buffer may be flushed immediately if BATCH_INTERVAL has passed,
        so we assert on file content rather than raw buffer length.
        """
        self.mode._state = JarvisState.SLEEPING
        self.mode._annotation_mode = True
        self.mode._annotation_file = self.tmp_dir / "notas_test.txt"
        self.mode._annotation_file.write_text("", encoding="utf-8")
        # Prevent immediate flush so text stays in buffer for simpler assertion
        self.mode._last_annotation_write = time.time()

        self._utterance("continuando a fala aqui")

        # Text must have been buffered (flush not triggered because interval not reached)
        self.assertIn("continuando a fala aqui", self.mode._annotation_buffer)
        # State must remain sleeping — this is the key assertion
        self.assertEqual(self.mode._state, JarvisState.SLEEPING)

    def test_sleeping_annotation_active_deactivate_works_without_wake_word(self):
        """Deactivation of an already-active annotation mode must work while sleeping."""
        self.mode._state = JarvisState.SLEEPING
        self.mode._annotation_mode = True
        self.mode._annotation_file = self.tmp_dir / "notas_test.txt"
        self.mode._annotation_file.write_text("header\n", encoding="utf-8")

        self._utterance("desativar modo anotação")

        self.assertFalse(self.mode._annotation_mode)

    # ── LLM never called without wake word while sleeping ────────────────

    def test_sleeping_no_wake_word_never_calls_llm(self):
        """Any speech without wake word while sleeping must never reach the LLM."""
        self.mode._state = JarvisState.SLEEPING

        for speech in [
            "que horas são",
            "me ajuda",
            "abre o spotify",
            "lembra que eu prefiro Python",
            "ativar modo anotação",
            "como está o tempo",
        ]:
            self.mode.agent.chat.reset_mock()
            self._utterance(speech)
            self.mode.agent.chat.assert_not_called(), f"LLM called for: '{speech}'"

    def test_sleeping_no_wake_word_never_calls_tts_for_response(self):
        """Any speech without wake word while sleeping must not trigger TTS."""
        self.mode._state = JarvisState.SLEEPING
        self.mode.tts.speak_async.reset_mock()

        self._utterance("me conta uma piada")

        self.mode.tts.speak_async.assert_not_called()


class TestStateGateWakeWordInline(unittest.TestCase):
    """
    Verifica o comportamento inline da wake word:
    - "Jarvis" → acorda
    - "Jarvis, que horas são?" → remove wake word e processa comando limpo
    - "Jarvis ativar modo anotação" → ativa anotação
    - "Ativar modo anotação" sem Jarvis → ignorado quando sleeping
    """

    def setUp(self):
        import tempfile
        self.tmp_dir = Path(tempfile.mkdtemp())
        with patch("jarvis.config.LOG_DIR", self.tmp_dir):
            self.mode = _make_mode(self.tmp_dir)
        self.mode._utterance_log_path = self.tmp_dir / "utterances_test.jsonl"
        self.loop = asyncio.new_event_loop()

    def tearDown(self):
        _cancel_engaged_timer(self.mode, self.loop)
        self.loop.close()

    def _run(self, coro):
        return self.loop.run_until_complete(coro)

    def _utterance(self, text):
        with patch.object(self.mode.stt, "transcribe", return_value=text):
            self._run(self.mode._on_utterance(_fake_audio()))

    def test_jarvis_alone_wakes_up(self):
        self.mode._state = JarvisState.SLEEPING
        self._utterance("Jarvis")
        self.assertEqual(self.mode._state, JarvisState.ENGAGED)
        self.mode.agent.chat.assert_not_called()

    def test_jarvis_inline_command_removes_wake_word(self):
        """'Jarvis, que horas são?' must send 'que horas são' to agent, not the full text."""
        self.mode._state = JarvisState.SLEEPING
        self._utterance("Jarvis que horas são")
        self.mode.agent.chat.assert_called_once()
        sent_text = self.mode.agent.chat.call_args[0][0]
        self.assertNotIn("jarvis", sent_text.lower())
        self.assertIn("que horas", sent_text.lower())

    def test_jarvis_activate_annotation_works(self):
        self.mode._state = JarvisState.SLEEPING
        self._utterance("Jarvis ativar modo anotação")
        self.assertTrue(self.mode._annotation_mode)
        self.mode.agent.chat.assert_not_called()

    def test_activate_annotation_without_jarvis_ignored(self):
        self.mode._state = JarvisState.SLEEPING
        self._utterance("ativar modo anotação")
        self.assertFalse(self.mode._annotation_mode)
        self.mode.agent.chat.assert_not_called()
        self.mode.tts.speak_async.assert_not_called()

    def test_ei_jarvis_not_recognized(self):
        """
        'ei Jarvis' must NOT activate because wake word is not the first token.
        Known limitation: inline wake word only detected at start of utterance.
        """
        self.mode._state = JarvisState.SLEEPING
        self._utterance("ei Jarvis me ajuda")
        # Must remain sleeping — wake word not at start
        self.mode.agent.chat.assert_not_called()
        # Document the limitation explicitly in the test name and docstring


if __name__ == "__main__":
    unittest.main()
