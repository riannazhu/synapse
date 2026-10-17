import json
import unittest
from server.models.capture import GeminiCapture
from server.models.config import build_models
from server.models.files import GeminiFiles


def reply(raw):
    return {"candidates": [{"content": {"parts": [{"text": json.dumps(raw)}]}}]}


class CaptureTests(unittest.TestCase):
    def model(self, raw):
        return GeminiCapture("test", transport=lambda *args: reply(raw))

    def test_transcript_timing_and_uncertainty(self):
        result = self.model({"text": "Piano [illegible]", "segments": [
            {"t0_ms": 0, "t1_ms": 900, "text": "Piano"}]}).transcribe(
                b"fake audio", mime_type="audio/wav", duration_ms=1000)
        self.assertEqual(result["state"], "needs_review")
        self.assertEqual(result["uncertain_spans"][0]["quote"], "[illegible]")

    def test_bad_transcript_timestamps_rejected(self):
        with self.assertRaises(ValueError):
            self.model({"text": "Piano", "segments": [{"t0_ms": 0, "t1_ms": 2000, "text": "Piano"}]}).transcribe(
                b"audio", mime_type="audio/wav", duration_ms=1000)

    def test_page_order_and_uncertainty(self):
        result = self.model({"pages": [{"page": 1, "text": "I want [illegible]"}]}).extract_pages(
            [{"mime_type": "image/png", "data": b"fake image"}])
        self.assertTrue(result["pages"][0]["uncertain_spans"])
        with self.assertRaises(ValueError):
            self.model({"pages": [{"page": 2, "text": "Wrong order"}]}).extract_pages(
                [{"mime_type": "image/png", "data": b"fake image"}])

    def test_summary_omits_assistant_input_and_rejects_assistant_evidence(self):
        messages = [{"id": "u", "role": "user", "text": "I want piano lessons."},
                    {"id": "a", "role": "assistant", "text": "You mastered piano."}]
        def transport(url, key, payload):
            data = json.loads(payload["contents"][0]["parts"][0]["text"])
            self.assertEqual([m["id"] for m in data], ["u"])
            return reply({"sentences": [{"text": "I want piano lessons.",
                "source_refs": [{"message_id": "a", "quote": "You mastered piano."}]}]})
        with self.assertRaises(ValueError):
            GeminiCapture("test", transport=transport).summarize(messages)

    def test_summary_has_source_mapping(self):
        model = self.model({"sentences": [{"text": "I want piano lessons.", "source_refs": [
            {"message_id": "u", "quote": "I want piano lessons."}]}]})
        result = model.summarize([{"id": "u", "role": "user", "text": "I want piano lessons."}])
        self.assertEqual(result["draft_text"][result["source_refs"][0]["start"]:result["source_refs"][0]["end"]], "I want piano lessons.")

    def test_history_opt_in_and_unknown_citation(self):
        model = self.model({"text": "A question?", "evidence_ids": ["unknown"]})
        messages = [{"id": "u", "role": "user", "text": "Hello"}]
        with self.assertRaises(ValueError):
            model.reply(messages, evidence=[{"id": "e"}])
        with self.assertRaises(ValueError):
            model.reply(messages, history_enabled=True, evidence=[{"id": "e"}])

    def test_offline_summary_keeps_only_user_statements(self):
        capture = build_models("fixture").capture
        result = capture.summarize([{"id": "u", "role": "user", "text": "My words"},
                                    {"id": "a", "role": "assistant", "text": "Invented"}])
        self.assertEqual(result["draft_text"], "My words")

    def test_large_media_upload_is_cleaned_on_generation_failure(self):
        class Files:
            deleted = False
            def upload(self, *args): return {"name": "files/test", "state": "ACTIVE", "uri": "provider-uri"}
            def wait(self, file): return file
            def delete(self, file): self.deleted = True
        files = Files()
        def transport(url, key, payload):
            self.assertIn("fileData", payload["contents"][0]["parts"][0])
            raise ValueError("Simulated provider failure")
        with self.assertRaises(ValueError):
            GeminiCapture("test", files=files, transport=transport).transcribe(
                b"x" * 14_300_000, mime_type="audio/wav", duration_ms=1000)
        self.assertTrue(files.deleted)

    def test_upload_protocol_and_untrusted_upload_host(self):
        calls = []
        def transport(method, url, headers, data=None):
            calls.append((method, url))
            if len(calls) == 1:
                return {"x-goog-upload-url": "https://generativelanguage.googleapis.com/upload/session"}, {}
            return {}, {"file": {"name": "files/test", "state": "ACTIVE", "uri": "provider-uri"}}
        files = GeminiFiles("test", transport=transport)
        file = files.upload(b"audio", "audio/wav")
        self.assertEqual(files.wait(file)["name"], "files/test")
        files.delete(file)
        self.assertEqual(calls[-1][0], "DELETE")
        with self.assertRaises(ValueError):
            GeminiFiles("test", transport=lambda *args: ({"x-goog-upload-url": "https://evil.example"}, {})).upload(b"a", "audio/wav")
