"""Проверки маршрутизации чата без микрофона и облачных запросов."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from config import Config
from controller import Controller
from core.pipeline import Pipeline, Job


class ChatTests(unittest.TestCase):
    def controller(self, opened=True):
        c = Mock()
        c.cfg = Config()
        c._action = None
        c._ready = True
        c.card.is_open.return_value = opened
        c.recorder.stop_capture.return_value = np.ones(16000, dtype=np.float32)
        c.recorder.duration_of.return_value = 1.0
        c.recorder.is_silent.return_value = False
        c._style_for.side_effect = lambda action: Controller._style_for(c, action)
        c._finish_recording.side_effect = lambda: Controller._finish_recording(c)
        return c

    def test_f8_routes_to_chat_and_release_stops_recording(self):
        c = self.controller()
        Controller._begin_recording(c, 'record')
        self.assertEqual(c._action, 'record')
        c.card.dismiss.assert_not_called()
        Controller._on_released(c, 'record')
        self.assertIsNone(c._action)
        job = c.pipeline.submit.call_args.args[0]
        self.assertTrue(job.ask)
        self.assertTrue(job.followup)
        self.assertIsNone(job.style)
        self.assertEqual(job.hotkey, c.cfg.hotkeys.record)

    def test_closed_chat_restores_dictation(self):
        c = self.controller(opened=False)
        Controller._begin_recording(c, 'record')
        Controller._on_released(c, 'record')
        self.assertFalse(c.pipeline.submit.call_args.args[0].ask)

    def test_toggle_stops_chat_recording(self):
        c = self.controller()
        c.cfg.hotkeys.mode = 'toggle'
        Controller._begin_recording(c, 'record')
        Controller._on_released(c, 'record')
        c.recorder.stop_capture.assert_not_called()
        Controller._on_pressed(c, 'record')
        self.assertTrue(c.pipeline.submit.call_args.args[0].ask)

    def test_text_bypasses_whisper_and_audio_archive(self):
        p = Mock()
        p._sample_rate = 16000
        p._audio.silence_rms = 0.01
        p._asker.conversation.return_value = SimpleNamespace(id='test', turns=[])
        Pipeline._process_ask(p, Job(np.zeros(0, dtype=np.float32), None, '',
                                    ask=True, question=' Вопрос ', followup=True))
        p._transcribe.assert_not_called()
        p._asker.keep_audio.assert_not_called()
        self.assertEqual(p._ask.call_args.args[1], 'Вопрос')
        p._asker.conversation.assert_called_once_with(keep=True)

    def test_unavailable_chat_keeps_draft(self):
        c = self.controller()
        c.asker = None
        Controller._on_text_question(c, 'Вопрос')
        c.card.clear_question.assert_not_called()
        c.pipeline.submit.assert_not_called()


if __name__ == '__main__':
    unittest.main()
