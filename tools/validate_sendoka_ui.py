"""Valida sintaxe do JavaScript embutido e elementos do plugin Sendoka."""
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
html = (root / "index.html").read_text(encoding="utf-8")
scripts = re.findall(r"<script(?:\s[^>]*)?>(.*?)</script>", html, re.S | re.I)
assert len(scripts) == 1, "Script embutido nao encontrado"
for name in ("sendokaKey", "sendokaSender", "sendokaTo", "sendokaBody",
             "sendokaSave", "sendokaSend", "sendokaOtpStart", "sendokaOtpCheck",
             "sendokaOtpCode", "sendokaOtpFlow", "sendokaState", "sendokaFeedback"):
    assert f'id="{name}"' in html, name
for route in ("/api/sendoka/sms", "/api/sendoka/verify/start", "/api/sendoka/verify/check"):
    assert route in html, route
node = shutil.which("node")
if not node:
    print("UI_IDS_OK; JS_PARSE_SKIPPED (Node indisponivel)")
else:
    with tempfile.TemporaryDirectory() as folder:
        js = Path(folder) / "cutshortplus-embedded.js"
        js.write_text(scripts[0], encoding="utf-8")
        completed = subprocess.run([node, "--check", str(js)], capture_output=True, text=True)
        if completed.returncode:
            raise RuntimeError(completed.stderr[-4000:])
    print("UI_IDS_OK; JS_SYNTAX_OK")
