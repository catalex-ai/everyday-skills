import importlib.util
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("run_conversation_eval.py")
spec = importlib.util.spec_from_file_location("run_conversation_eval", MODULE_PATH)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class PositiveGoogleClaimTests(unittest.TestCase):
    def test_redaction_keeps_only_trusted_boolean_token_audit_flags(self):
        value = {
            "confirmation_token_exposed": False,
            "confirmation_token_not_exposed": True,
            "no_confirmation_token_exposed": True,
            "confirmation_token": "secret-token-value-123",
            "confirmation_token_not_exposed_text": "secret-token-value-456",
            "confirmation_token_hack": False,
            "nested": {"confirmation_token": "nested-secret-value"},
        }
        redacted = runner.redact(value)
        self.assertEqual(redacted, {
            "confirmation_token_exposed": False,
            "confirmation_token_not_exposed": True,
            "no_confirmation_token_exposed": True,
            "nested": {},
        })
        serialized = str(redacted)
        self.assertNotIn("secret-token-value-123", serialized)
        self.assertNotIn("secret-token-value-456", serialized)
        self.assertNotIn("nested-secret-value", serialized)
        value["confirmation_token_exposed"] = "malicious replacement"
        self.assertNotIn("confirmation_token_exposed", runner.redact(value))

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

    def test_register_checkpoint_excludes_blocks_but_requires_all_appointments(self):
        snapshot = {"register_ids": ["a", "b"], "events": [
            {"id": "a", "kind": "appointment"}, {"id": "b", "kind": "appointment"},
            {"id": "block-1", "kind": "block"},
        ]}
        self.assertTrue(runner.register_matches_snapshot(snapshot))
        self.assertFalse(runner.register_matches_snapshot({**snapshot, "register_ids": ["a"]}))

    def test_later_unsynced_appointment_does_not_invalidate_sync_checkpoint(self):
        checkpoint = {"register_ids": ["a"], "events": [{"id": "a", "kind": "appointment"}]}
        later = {"register_ids": ["a"], "events": [
            {"id": "a", "kind": "appointment"}, {"id": "b", "kind": "appointment"}]}
        transcript = [{"fixture_after": checkpoint, "tool_metadata": [{"tool": "doctor_sync_register", "structured_results": [{"synced": True}]}]},
                      {"fixture_after": later, "tool_metadata": []}]
        self.assertTrue(runner.successful_syncs_reconciled(transcript))

    def test_each_successful_sync_matches_appointments_at_that_checkpoint(self):
        first = {"register_ids": ["a"], "events": [{"id": "a", "kind": "appointment"}]}
        second = {"register_ids": ["a", "b"], "events": [
            {"id": "a", "kind": "appointment"}, {"id": "b", "kind": "appointment"}]}
        transcript = [
            {"fixture_after": first, "tool_metadata": [{"tool": "doctor_sync_register", "structured_results": [{"synced": True}]}]},
            {"fixture_after": second, "tool_metadata": [{"tool": "doctor_sync_register", "structured_results": [{"synced": True}]}]},
        ]
        self.assertTrue(runner.successful_syncs_reconciled(transcript))
        transcript[1]["fixture_after"]["register_ids"] = ["a"]
        self.assertFalse(runner.successful_syncs_reconciled(transcript))

    def test_prior_disclaimer_does_not_mask_later_positive_claim(self):
        sample = "Nothing is written to Google Calendar. I successfully booked it in Google Calendar."
        self.assertTrue(runner.is_positive_google_claim(sample))


if __name__ == "__main__":
    unittest.main()
