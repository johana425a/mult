"""Real SQLite: incorrect/correct attempts, original visuals and stale writers."""
from pathlib import Path
import tempfile
import unittest
from deeptutor.learning.storage import LearningStore, LearningConflictError
from deeptutor.learning.models import LearningProgress, QuizAttempt
from deeptutor.learning.grading import grade_answer


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='DeepSteam regression ')
        self.root = Path(self.temp.name) / 'learning fixture'
        self.store = LearningStore(self.root)
        self.store.save(LearningProgress(book_id='release-fixture', name='Isolated test only'))

    def tearDown(self):
        self.temp.cleanup()

    def test_wrong_answer_then_correct_answer_survives_reopen(self):
        with self.store.transaction('release-fixture') as tx:
            for answer in ('B', 'A'):
                tx.progress.quiz_attempts.append(QuizAttempt(question_id='fixture-'+answer,
                    knowledge_point_id='km', module_id='enzyme', user_answer=answer,
                    is_correct=grade_answer(answer, 'A', 'choice'),
                    visual_context={'original_image': 'source/formula.png', 'generated': False}))
            tx.touch()
        restored = LearningStore(self.root).load('release-fixture')
        self.assertEqual([x.is_correct for x in restored.quiz_attempts], [False, True])
        self.assertEqual([x.user_answer for x in restored.quiz_attempts], ['B', 'A'])
        self.assertFalse(restored.quiz_attempts[0].visual_context['generated'])
        self.assertEqual(restored.quiz_attempts[0].visual_context['original_image'], 'source/formula.png')
        self.assertEqual(restored.mastery_levels, {}, 'Raw saved attempts must not manufacture mastery')

    def test_stale_writer_cannot_erase_a_new_learning_record(self):
        old = self.store.load('release-fixture')
        current = self.store.load('release-fixture')
        current.name = 'Committed lesson'
        self.store.save(current)
        old.name = 'Stale lesson'
        with self.assertRaises(LearningConflictError):
            self.store.save(old)
        self.assertEqual(LearningStore(self.root).load('release-fixture').name, 'Committed lesson')

    def test_failed_transaction_does_not_publish_partial_score(self):
        before = self.store.load('release-fixture').model_dump()
        with self.assertRaisesRegex(RuntimeError, 'fixture rollback'):
            with self.store.transaction('release-fixture') as tx:
                tx.progress.mastery_levels['km'] = 1.0
                tx.touch()
                raise RuntimeError('fixture rollback')
        self.assertEqual(LearningStore(self.root).load('release-fixture').model_dump(), before)


if __name__ == '__main__':
    unittest.main(verbosity=2)
