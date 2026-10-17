import unittest
from server.analysis.evaluate import check_case


class EvaluationTests(unittest.TestCase):
    def test_forbidden_milestone_fails(self):
        row = check_case({"id": "negation", "forbidden_event_types": ["milestone"]},
                         {"topics": [], "goal_events": [{"type": "milestone"}]})
        self.assertEqual(row["status"], "fail")

    def test_missing_person_and_event_fail(self):
        row = check_case({"id": "practice", "expected_event_types": ["practice"],
                          "expected_people": ["Maya"]}, {"topics": [], "goal_events": []})
        self.assertEqual(len(row["failures"]), 2)

    def test_ambiguous_identity_requires_manual_review(self):
        row = check_case({"id": "names", "review": "Check identity"},
                         {"topics": [], "goal_events": []})
        self.assertEqual(row["status"], "manual_review")
