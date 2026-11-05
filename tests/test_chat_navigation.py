"""Переход на страницу истории не должен прерывать текущий ответ."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtWidgets import QApplication, QComboBox
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from config import UIConfig
from ui.card import AnswerCard, _ChatList, _chat_date


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

    def test_date_survives_saving_and_reopening(self):
        self.answer("dated")
        stamp = self.card._saved["dated"]["updated_at"]
        self.card._show_history()
        self.card._select_history(self.item("dated"))
        self.card.save_history()
        self.assertEqual(self.card._saved["dated"]["updated_at"], stamp)
        restored = AnswerCard(UIConfig(), self.path)
        self.assertEqual(restored._saved["dated"]["updated_at"], stamp)
        self.assertIn(_chat_date(stamp), restored._history.item(0).text())
        self.assertEqual(restored._history.item(0).textAlignment(), Qt.AlignLeft | Qt.AlignVCenter)
        restored.deleteLater()

    def test_old_dates_recovered_from_journal_without_inventing_missing_dates(self):
        self.path.write_text(json.dumps({"current": "old", "chats": {
            "old": {"turns": [], "draft": "Старый"},
            "unknown": {"turns": [], "draft": "Без даты"}}}), encoding="utf-8")
        (self.path.parent / "dictations.jsonl").write_text(
            json.dumps({"kind": "ask", "conversation": "old", "at": "2026-10-03T12:15:00"}),
            encoding="utf-8")
        restored = AnswerCard(UIConfig(), self.path)
        self.assertEqual(restored._saved["old"]["updated_at"], "2026-10-03T12:15:00")
        self.assertIn("03.10.26 · 12:15", restored._history.item(0).text())
        self.assertIn("Дата неизвестна", restored._history.item(1).text())
        restored.deleteLater()

    def test_wheel_moves_through_intermediate_positions_and_stays_in_bounds(self):
        listing = _ChatList()
        listing.resize(300, 160)
        listing.addItems([f"Разговор {i}" for i in range(60)])
        listing.show()
        QTest.qWait(30)
        bar = listing.verticalScrollBar()
        positions = []
        bar.valueChanged.connect(positions.append)
        event = QWheelEvent(QPointF(50, 50), QPointF(50, 50), QPoint(), QPoint(0, -120),
                            Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
        listing.wheelEvent(event)
        QTest.qWait(260)
        self.assertGreater(len(set(positions)), 2)
        self.assertGreater(bar.value(), 0)
        self.assertLessEqual(bar.value(), bar.maximum())
        listing.hide()
        listing.deleteLater()


if __name__ == "__main__":
    unittest.main()
