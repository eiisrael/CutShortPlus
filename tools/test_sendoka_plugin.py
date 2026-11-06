# -*- coding: utf-8 -*-
"""Testes offline do plugin Sendoka: nenhum SMS/OTP real e enviado."""
import sys
from pathlib import Path
from unittest import TestCase, main
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import sendoka_plugin as s


class SendokaTests(TestCase):
    def test_phone_and_sender_validation(self):
        self.assertEqual(s.valid_phone("+5511999999999"), "+5511999999999")
        self.assertEqual(s.valid_sender("CutShort"), "CutShort")
        for invalid in ("5511999999999", "+012345678", "abc", "+55 11 99999", ""):
            with self.assertRaises(ValueError):
                s.valid_phone(invalid)
        with self.assertRaises(ValueError):
            s.valid_sender("invalid sender with spaces")

    def test_bad_key_rejected_without_network(self):
        with patch.object(s.requests, "post") as post:
            with self.assertRaises(ValueError):
                s.send_sms("invalid", "CutShort", "+5511999999999", "Oi")
            post.assert_not_called()

    def test_sandbox_send_and_idempotency(self):
        response = Mock(ok=True, status_code=200)
        response.json.return_value = {
            "id": "test_msg_1", "status": "sent", "segments": 1,
            "warnings": [{"code": "SENDER_NOT_REGISTERED"}]}
        with patch.object(s.requests, "post", return_value=response) as post:
            result = s.send_sms("sok_test_example", "CutShort", "+5511999999999", "Teste")
        self.assertEqual(result["mode"], "test")
        self.assertEqual(result["segments"], 1)
        args, kwargs = post.call_args
        self.assertEqual(args[0], s.BASE_URL + "/sms")
        self.assertEqual(kwargs["json"]["to"], "+5511999999999")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer sok_test_example")
        self.assertTrue(kwargs["headers"]["Idempotency-Key"])

    def test_otp_start_and_check(self):
        start = Mock(ok=True, status_code=201)
        start.json.return_value = {"id": "ver_123", "status": "pending", "expires_at": "2026-11-04T22:00:00Z"}
        checked = Mock(ok=True, status_code=200)
        checked.json.return_value = {"id": "ver_123", "status": "approved"}
        with patch.object(s.requests, "post", side_effect=[start, checked]) as post:
            a = s.start_verification("sok_test_example", "CutShort", "+5511999999999")
            b = s.check_verification("sok_test_example", a["id"], "000000")
        self.assertEqual(a["status"], "pending")
        self.assertTrue(b["approved"])
        self.assertEqual(post.call_args_list[1].kwargs["json"], {"code": "000000"})
        self.assertNotIn("Idempotency-Key", post.call_args_list[1].kwargs["headers"])

    def test_errors_do_not_echo_sensitive_values(self):
        response = Mock(ok=False, status_code=401)
        response.json.return_value = {"error": {"code": "UNAUTHORIZED",
                                                   "message": "key sok_test_sensitive leaked"}}
        with patch.object(s.requests, "post", return_value=response):
            with self.assertRaises(RuntimeError) as err:
                s.send_sms("sok_test_sensitive", "CutShort", "+5511999999999", "Oi")
        self.assertNotIn("sok_test_sensitive", str(err.exception))
        self.assertIn("401", str(err.exception))

    def test_reject_invalid_payload_without_post(self):
        with patch.object(s.requests, "post") as post:
            with self.assertRaises(ValueError):
                s.send_sms("sok_live_example", "CutShort", "+5511999999999", "x" * 1601)
            with self.assertRaises(ValueError):
                s.check_verification("sok_live_example", "bad_path", "000000")
            post.assert_not_called()


if __name__ == "__main__":
    main(verbosity=2)
