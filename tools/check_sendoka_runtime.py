"""Estado seguro do CutShortPlus local; nao mostra dados pessoais."""
import json
from urllib.request import urlopen
try:
    with urlopen("http://127.0.0.1:8765/api/bootstrap", timeout=3) as resp:
        bootstrap = json.load(resp)
    with urlopen("http://127.0.0.1:8765/api/status", timeout=3) as resp:
        status = json.load(resp)
    print("SERVER_UP=YES")
    print("SENDOKA_RUNTIME_AVAILABLE=" + str("sendoka_mode" in bootstrap.get("settings", {})))
    print("ACTIVE_TASKS=" + str(sum(t.get("status") == "working" for t in status.get("tasks", []))))
except Exception as e:
    print("SERVER_UP=NO; REASON=" + type(e).__name__)
