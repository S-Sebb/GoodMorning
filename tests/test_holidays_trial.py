"""Synthetic setup answers preserve the trial's intended holiday change and consent."""
import unittest

from benchmarks.holidays_live import answer


class HolidayTrialAnswersTests(unittest.TestCase):
    def form(self, title, description, labels):
        return {'fields': [{'key': 'choice', 'type': 'string', 'custom': True,
                            'title': title, 'description': description,
                            'options': [{'label': label, 'value': label} for label in labels]}]}

    def test_holiday_in_consent_does_not_turn_save_answer_into_country(self):
        form = self.form('写入确认', '把公共假期：中国写进设置吗？', ['暂不写入', '写入'])
        self.assertEqual(answer(form, 'zh-CN', 'setup'), {'choice': '写入'})

    def test_save_answer_does_not_authorize_optional_external_checks(self):
        for language, labels, expected in (
            ('en', ["Don't save", 'Save and check weather', 'Save only'], 'Save only'),
            ('zh-CN', ['先不保存', '保存并检查天气', '保存'], '保存'),
        ):
            with self.subTest(language=language):
                form = self.form('Save settings', 'Save the holiday choice?', labels)
                self.assertEqual(answer(form, language, 'setup'), {'choice': expected})

    def test_review_continues_to_holidays_instead_of_skipping_all_blank_preferences(self):
        form = self.form('其余设置', '剩下的设置怎么处理？', ['全部保持现状', '分组逐项看一遍'])
        self.assertEqual(answer(form, 'zh-CN', 'setup'), {'choice': '分组逐项看一遍'})

    def test_country_question_still_selects_china(self):
        form = self.form('公共假期', '要显示哪些地方的公共假期？', ['美国', '中国', '跳过'])
        self.assertEqual(answer(form, 'zh-CN', 'setup'), {'choice': '中国'})
