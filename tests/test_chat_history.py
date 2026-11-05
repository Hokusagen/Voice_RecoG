"""История и закрытие окна не должны терять разговор и возвращать фокус сами."""
import sys
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from config import UIConfig, AskConfig
from core.ask import Asker
from ui.card import AnswerCard
from ui.chat_button import ChatButton


class HistoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / 'chats.json'
        self.card = AnswerCard(UIConfig(), self.path)
        self.windows = [self.card]

    def tearDown(self):
        for window in self.windows:
            window.hide()
            window.deleteLater()
        self.app.processEvents()
        self.directory.cleanup()

    def answer(self, key='first', question='Первый вопрос', answer='Ответ'):
        self.card.start(key, 1, question, False)
        self.card.feed(answer)
        self.card.finish(['https://example.org'])

    def test_close_and_restart_restore_context_and_draft(self):
        self.card.open_chat()
        self.answer()
        self.card._input.setText('Уточнение')
        self.card._on_close()
        self.assertFalse(self.card.is_open())
        self.card.open_chat()
        self.assertEqual(self.card._turns[0].answer, 'Ответ')
        restored = AnswerCard(UIConfig(), self.path)
        self.windows.append(restored)
        self.assertEqual(restored.context(), self.card.context())
        self.assertEqual(restored._input.text(), 'Уточнение')
        self.assertEqual(restored._turns[0].sources, ['https://example.org'])
        asker = Asker.__new__(Asker)
        asker.cfg = AskConfig()
        asker.restore(restored._conversation, restored.context())
        conversation = asker.conversation(keep=True)
        self.assertEqual(conversation.id, 'first')
        self.assertEqual(asker.messages('Продолжи', conversation)[-2]['content'], 'Ответ')

    def test_close_before_first_token_stays_hidden_and_keeps_answer(self):
        self.card.open_chat()
        self.card._on_close()
        self.card.start('first', 1, 'Вопрос', False)
        self.card.feed('Первая часть')
        QTest.qWait(700)
        self.card.feed(' и продолжение')
        self.card.finish([])
        self.assertFalse(self.card.is_open())
        self.card.open_chat()
        self.assertEqual(self.card._turns[0].answer, 'Первая часть и продолжение')

    def test_history_can_resume_an_older_chat(self):
        self.answer()
        self.card._new_chat()
        self.assertEqual(self.card.context(), [])
        self.answer('second', 'Другой вопрос', 'Другой ответ')
        selected = []
        self.card.conversation_selected.connect(lambda key, turns: selected.append((key, turns)))
        self.card._show_history()
        item = next(self.card._history.item(i) for i in range(self.card._history.count())
                    if self.card._history.item(i).data(Qt.UserRole) == 'first')
        self.card._select_history(item)
        self.assertEqual(selected[-1], ('first', [{'question': 'Первый вопрос', 'answer': 'Ответ'}]))
        self.assertEqual(self.card._conversation, 'first')
        self.assertIn('second', self.card._saved)

    def test_unfinished_answer_is_readable_but_not_model_context(self):
        self.card.start('first', 1, 'Вопрос', False)
        self.card.feed('Начало')
        self.card._on_close()
        restored = AnswerCard(UIConfig(), self.path)
        self.windows.append(restored)
        self.assertEqual(restored._turns[0].answer, 'Начало')
        self.assertEqual(restored.context(), [])

    def test_busy_chat_cannot_switch_context(self):
        self.answer('old')
        self.card._new_chat()
        self.answer('first')
        self.card.set_busy(True)
        self.card._show_history()
        item = next(self.card._history.item(i) for i in range(self.card._history.count())
                    if self.card._history.item(i).data(Qt.UserRole) == 'old')
        self.assertFalse(item.flags() & Qt.ItemIsEnabled)
        self.card._select_history(item)
        self.card._new_chat()
        self.assertEqual(self.card._conversation, 'first')
        self.assertFalse(self.card._new.isEnabled())

    def test_old_journal_imports_answers_and_rechecks(self):
        rows = [
            {"kind": "dictation", "text": "Обычный текст"},
            {"kind": "ask", "conversation": "old", "turn": 1,
             "question": "Старый вопрос", "answer": "Первый ответ"},
            {"kind": "ask", "conversation": "old", "turn": 1,
             "question": "Старый вопрос", "answer": "Проверенный ответ"},
            {"kind": "ask", "conversation": "old", "turn": 2,
             "question": "Ошибка", "answer": "", "error": "Нет сети"},
        ]
        journal = self.path.parent / 'dictations.jsonl'
        journal.write_text('\n'.join(json.dumps(row) for row in rows) + '\n{оборвано', encoding='utf-8')
        imported = AnswerCard(UIConfig(), self.path)
        self.windows.append(imported)
        self.assertEqual(imported.context(), [{'question': 'Старый вопрос', 'answer': 'Проверенный ответ'}])
        self.assertEqual(imported.conversation_id, 'old')

    def test_launcher_opens_in_one_click_and_returns_on_close(self):
        button = ChatButton(UIConfig())
        self.windows.append(button)
        button.open_requested.connect(self.card.open_chat)
        self.card.opened.connect(button.hide)
        self.card.closed.connect(button.show)
        button.show()
        button.click()
        QTest.qWait(600)
        self.assertTrue(self.card.is_open())
        self.assertFalse(button.isVisible())
        self.assertLess(self.card._composer.geometry().bottom(), self.card._body.height())
        self.card._on_close()
        self.assertTrue(button.isVisible())
        self.assertFalse(self.card.is_open())


if __name__ == '__main__':
    unittest.main()
