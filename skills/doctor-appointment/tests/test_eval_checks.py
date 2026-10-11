import importlib.util
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("run_conversation_eval.py")
spec = importlib.util.spec_from_file_location("run_conversation_eval", MODULE_PATH)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class PositiveGoogleClaimTests(unittest.TestCase):
    def test_explicit_practice_disclaimers_are_not_claims(self):
        samples = [
            "Nothing is written to Google Calendar or Google Sheets.",
            "No Google Calendar event was created.",
            "This did not update the live calendar.",
            "Google Calendar was not written to.",
        ]
        for sample in samples:
            with self.subTest(sample=sample):
                self.assertFalse(runner.is_positive_google_claim(sample))

    def test_positive_external_write_claims_are_detected(self):
        samples = [
            "Your appointment was successfully booked in Google Calendar.",
            "I confirmed the live calendar update.",
            "The Google Sheets register was updated successfully.",
        ]
        for sample in samples:
            with self.subTest(sample=sample):
                self.assertTrue(runner.is_positive_google_claim(sample))

    def test_unrelated_no_and_not_only_do_not_mask_positive_claim(self):
        samples = [
            "No worries, your appointment was successfully booked in Google Calendar.",
            "Not only was it booked in Google Calendar, it was synced.",
        ]
        for sample in samples:
            with self.subTest(sample=sample):
                self.assertTrue(runner.is_positive_google_claim(sample))

    def test_future_google_write_is_not_reported_as_completed(self):
        samples = ["I will write this to Google Calendar.", "It will be written to Google Calendar."]
        for sample in samples:
            with self.subTest(sample=sample):
                self.assertFalse(runner.is_positive_google_claim(sample))

    def test_followup_selector_does_not_answer_initial_booking_choice(self):
        answer = ("I found your existing appointment. Would you like me to book this as "
                  "an additional appointment or reschedule the existing one?")
        self.assertIsNone(runner.clarification_followup(answer, [], "Yes, that time works for me."))

    def test_followup_selector_only_resolves_temporal_question_after_yes(self):
        answer = "Which date and time did you mean?"
        self.assertIsNotNone(runner.clarification_followup(answer, [], "Yes, please."))
        self.assertIsNone(runner.clarification_followup(answer, [], "What time do you prefer?"))

    def test_followup_selector_never_repeats_prepared_confirmation(self):
        calls = [{"result": {"content": [{"type": "text", "text": '{"confirmation_required":true}'}]}}]
        self.assertIsNone(runner.clarification_followup("Which date and time?", calls, "Yes, please."))

    def test_prior_disclaimer_does_not_mask_later_positive_claim(self):
        sample = "Nothing is written to Google Calendar. I successfully booked it in Google Calendar."
        self.assertTrue(runner.is_positive_google_claim(sample))


if __name__ == "__main__":
    unittest.main()
