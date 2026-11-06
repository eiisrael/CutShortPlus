# -*- coding: utf-8 -*-
"""Smoke de rotas localhost do CutShortPlus sem chamadas externas ao Sendoka."""
import sys
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app
import requests


def main():
    with tempfile.TemporaryDirectory() as tmp, patch.object(app, "SETTINGS_FILE", Path(tmp) / "settings.json"):
        cfg = app.write_settings({"sendoka_api_key": "sok_test_not_real",
                                  "sendoka_sender": "CutShort"})
        assert cfg["sendoka_api_key_ready"] is True
        assert cfg["sendoka_mode"] == "test"
        assert "sendoka_api_key" not in cfg
        saved = app.SETTINGS_FILE.read_text(encoding="utf-8")
        assert "sok_test_not_real" not in saved and "dpapi:" in saved
        assert app.read_settings()["sendoka_api_key"] == "sok_test_not_real"
        server = app.ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = "http://127.0.0.1:%s" % server.server_address[1]
        headers = {"X-Cutshort-Token": app.CSRF}
        try:
            with patch.object(app.sendoka_plugin, "send_sms", return_value={
                "id": "test_msg_1", "status": "sent", "mode": "test"}) as sms, \
                 patch.object(app.sendoka_plugin, "start_verification", return_value={
                "id": "ver_123", "status": "pending", "mode": "test"}) as start, \
                 patch.object(app.sendoka_plugin, "check_verification", return_value={
                "id": "ver_123", "status": "approved", "approved": True}) as check:
                r = requests.get(url + "/api/bootstrap", timeout=8)
                assert r.status_code == 200 and "sok_test_not_real" not in r.text
                assert r.json()["settings"]["sendoka_mode"] == "test"
                r = requests.post(url + "/api/sendoka/sms", json={
                    "to": "+5511999999999", "body": "Teste"}, headers=headers, timeout=8)
                assert r.status_code == 400 and not sms.called
                r = requests.post(url + "/api/sendoka/sms", json={
                    "to": "+5511999999999", "body": "Teste", "confirm": "ENVIAR SMS"}, headers=headers, timeout=8)
                assert r.status_code == 200 and sms.call_count == 1, r.text
                r = requests.post(url + "/api/sendoka/verify/start", json={
                    "to": "+5511999999999", "confirm": "ENVIAR OTP"}, headers=headers, timeout=8)
                assert r.status_code == 200 and start.call_count == 1, r.text
                r = requests.post(url + "/api/sendoka/verify/check", json={
                    "id": "ver_123", "code": "000000"}, headers=headers, timeout=8)
                assert r.status_code == 200 and check.call_count == 1, r.text
                r = requests.post(url + "/api/sendoka/sms", json={
                    "to": "+5511999999999", "body": "Teste", "confirm": "ENVIAR SMS"}, timeout=8)
                assert r.status_code == 400 and sms.call_count == 1
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
    print("SENDOKA_ROUTES_OK; DPAPI_ROUNDTRIP_OK; NO_EXTERNAL_SENDS")


if __name__ == "__main__":
    main()
