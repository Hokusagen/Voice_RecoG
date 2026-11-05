"""Переход на страницу истории не должен прерывать текущий ответ."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QComboBox
from config import UIConfig
from ui.card import AnswerCard


class NavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "chats.json"
        self.card = AnswerCard(UIConfig(), self.path)
        self.card._stay_hidden = True
        self.events = []
        self.card.conversation_selected.connect(lambda key, turns: self.events.append((key, turns)))

    def tearDown(self):
        self.card.hide()
        self.card.deleteLater()
        self.app.processEvents()
        self.directory.cleanup()

    def answer(self, key, question="Вопрос"):
        self.card.start(key, 1, question, False)
        self.card.feed("Ответ")
        self.card.finish([])

    def item(self, key):
        return next(self.card._history.item(i) for i in range(self.card._history.count())
                    if self.card._history.item(i).data(Qt.UserRole) == key)

    def test_page_replaces_popup_and_preserves_draft(self):
        self.answer("first")
        self.card._input.setText("Черновик")
        self.card._back.click()
        self.assertTrue(self.card._showing_history)
        self.assertEqual(self.card.findChildren(QComboBox), [])
        self.assertTrue(self.card._composer.isHidden())
        self.assertEqual(self.card._question_label.text(), "История чатов")
        self.card._select_history(self.item("first"))
        self.assertFalse(self.card._showing_history)
        self.assertEqual(self.card._input.text(), "Черновик")
        self.assertEqual(self.events, [])

    def test_switch_restores_context_and_both_drafts(self):
        self.answer("first", "Первый")
        self.card._input.setText("Первый черновик")
        self.card._new_chat()
        self.answer("second", "Второй")
        self.card._input.setText("Второй черновик")
        self.card._show_history()
        self.card._select_history(self.item("first"))
        self.assertEqual(self.card._input.text(), "Первый черновик")
        self.assertEqual(self.events[-1], ("first", [{"question": "Первый", "answer": "Ответ"}]))
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8"))["chats"]["second"]["draft"], "Второй черновик")

    def test_view_history_during_stream_cannot_switch_but_can_return(self):
        self.answer("old")
        self.card._new_chat()
        self.card.start("active", 1, "Новый вопрос", False)
        self.card.set_busy(True)
        self.card.feed("Начало")
        self.card._show_history()
        self.assertFalse(self.card._new.isEnabled())
        self.assertFalse(self.item("old").flags() & Qt.ItemIsEnabled)
        self.card._select_history(self.item("old"))
        self.card._new_chat()
        self.assertEqual(self.card.conversation_id, "active")
        self.card._select_history(self.item("active"))
        self.assertEqual(self.card._pending, 0)
        self.card.feed(" и конец")
        self.card.finish([])
        self.card.set_busy(False)
        self.assertEqual(self.card.context()[0]["answer"], "Начало и конец")

    def test_finish_in_history_keeps_page_and_unlocks_selection(self):
        self.card.start("active", 1, "Вопрос", False)
        self.card._show_history()
        self.card.feed("Готовый ответ")
        self.card.finish([])
        self.assertTrue(self.card._showing_history)
        self.assertEqual(self.card._question_label.text(), "История чатов")
        self.assertTrue(self.card._actions.isHidden())
        self.assertTrue(self.card._new.isEnabled())
        self.card._new.click()
        self.assertFalse(self.card._showing_history)
        self.assertEqual(self.card.context(), [])
        self.assertEqual(self.card._saved["active"]["turns"][0]["answer"], "Готовый ответ")

    def test_voice_preparation_returns_to_active_conversation(self):
        self.answer("active")
        self.card._show_history()
        self.card.prepare_question()
        self.assertFalse(self.card._showing_history)
        self.assertEqual(self.card.conversation_id, "active")

    def test_close_from_history_does_not_reopen_on_stream(self):
        self.card.start("active", 1, "Вопрос", False)
        self.card._show_history()
        self.card._on_close()
        self.card.feed("Ответ после закрытия")
        self.card.finish([])
        self.assertFalse(self.card.is_open())
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8"))["chats"]["active"]["turns"][0]["answer"], "Ответ после закрытия")


if __name__ == "__main__":
    unittest.main()
