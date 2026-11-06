# -*- coding: utf-8 -*-
"""CutShortPlus - estúdio de cortes local (Windows, localhost)."""
from __future__ import annotations
import base64
import ctypes
from ctypes import wintypes
from datetime import datetime
import html
import json
import math
import os
from pathlib import Path
import re
import secrets
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import ai_providers
import youtube_search
import live_studio
import highlight_engine
import topic_interest
import clip_titles
import asr_local
import sendoka_plugin
from urllib.parse import parse_qs, quote, unquote, urlparse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
IMPORTS = ROOT / "imports"
OUTPUT = ROOT / "cortes"
for folder in (DATA, IMPORTS, OUTPUT):
    folder.mkdir(parents=True, exist_ok=True)
SETTINGS_FILE = DATA / "settings.json"
TOKEN_FILE = DATA / "youtube_token.dpapi"
DB_FILE = DATA / "cutshort.db"
CSRF = secrets.token_urlsafe(36)
DB_LOCK = threading.RLock()
TASK_LOCK = threading.Lock()
TASKS: dict[str, dict] = {}
ALLOWED_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be", "www.youtu.be", "youtube-nocookie.com"}
DEFAULTS = {"model": "", "max_clips": 10, "seconds": 60,
            "privacy": "private", "meta_page_id": "", "yt_client_file": "",
            "ai_provider": "openai", "openrouter_model": "", "nvidia_model": "",
            "anthropic_model": "", "xai_model": "", "gemini_model": "",
            "deepseek_model": "", "mistral_model": "", "groq_model": "",
            "sendoka_sender": ""}
SECRET_FIELDS = ("youtube_api_key", "openai_api_key", "meta_page_token",
                 "openrouter_api_key", "nvidia_api_key", "anthropic_api_key",
                 "xai_api_key", "gemini_api_key", "deepseek_api_key",
                 "mistral_api_key", "groq_api_key", "sendoka_api_key")
AI_PROVIDERS = {"openai": ("openai_api_key", "model"),
                "openrouter": ("openrouter_api_key", "openrouter_model"),
                "nvidia": ("nvidia_api_key", "nvidia_model"),
                "anthropic": ("anthropic_api_key", "anthropic_model"),
                "xai": ("xai_api_key", "xai_model"),
                "gemini": ("gemini_api_key", "gemini_model"),
                "deepseek": ("deepseek_api_key", "deepseek_model"),
                "mistral": ("mistral_api_key", "mistral_model"),
                "groq": ("groq_api_key", "groq_model")}
def now(): return datetime.now().astimezone().isoformat(timespec="seconds")

class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]

def protected(value: str) -> str:
    raw = value.encode("utf-8")
    buf = ctypes.create_string_buffer(raw)
    inp = DATA_BLOB(len(raw), ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte)))
    out = DATA_BLOB()
    crypt = ctypes.windll.crypt32
    if not crypt.CryptProtectData(ctypes.byref(inp), "CutShortPlus", None, None, None, 0, ctypes.byref(out)):
        raise OSError("Falha ao proteger credencial pelo Windows DPAPI")
    try:
        return base64.b64encode(ctypes.string_at(out.pbData, out.cbData)).decode("ascii")
    finally:
        free = ctypes.windll.kernel32.LocalFree
        free.argtypes = [ctypes.c_void_p]
        free.restype = ctypes.c_void_p
        free(ctypes.cast(out.pbData, ctypes.c_void_p))

def unprotected(data: str) -> str:
    raw = base64.b64decode(data)
    buf = ctypes.create_string_buffer(raw)
    inp = DATA_BLOB(len(raw), ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte)))
    out = DATA_BLOB()
    if not ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(inp), None, None, None, None, 0, ctypes.byref(out)):
        raise OSError("Não foi possível descriptografar credenciais deste usuário Windows")
    try:
        return ctypes.string_at(out.pbData, out.cbData).decode("utf-8")
    finally:
        free = ctypes.windll.kernel32.LocalFree
        free.argtypes = [ctypes.c_void_p]
        free.restype = ctypes.c_void_p
        free(ctypes.cast(out.pbData, ctypes.c_void_p))

def read_settings():
    try: loaded = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError): loaded = {}
    config = {**DEFAULTS, **loaded}
    for key in SECRET_FIELDS:
        stored = config.get(key, "")
        if stored.startswith("dpapi:"):
            try: config[key] = unprotected(stored[6:])
            except Exception: config[key] = ""
    return config

def write_settings(payload):
    current = read_settings()
    for key in ("ai_provider","privacy","yt_client_file","meta_page_id","sendoka_sender",
                *(name for _,name in AI_PROVIDERS.values())):
        if key in payload:
            current[key] = str(payload[key]).strip()[:400]
    for key, minimum, maximum in (("max_clips", 1, 10), ("seconds", 12, 60)):
        if key in payload: current[key] = max(minimum, min(maximum, int(payload[key])))
    if current.get("sendoka_sender"): sendoka_plugin.valid_sender(current["sendoka_sender"])
    if current["privacy"] not in ("private", "unlisted", "public"): raise ValueError("Privacidade inválida")
    if current["ai_provider"] not in AI_PROVIDERS: raise ValueError("Provedor de IA inválido")
    for _, field in AI_PROVIDERS.values():
        if current.get(field): ai_providers.validate_model(current[field])
    for key in SECRET_FIELDS:
        if payload.get(key): current[key] = str(payload[key]).strip()
        if payload.get("clear_" + key): current[key] = ""
    stored = dict(current)
    try: previous_raw = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError): previous_raw = {}
    for key in SECRET_FIELDS:
        if current.get(key):
            stored[key] = "dpapi:" + protected(current[key])
        elif not payload.get("clear_" + key) and not payload.get(key) and str(previous_raw.get(key, "")).startswith("dpapi:"):
            # Nunca apagar o blob protegido por erro temporário de leitura DPAPI.
            stored[key] = previous_raw[key]
        else:
            stored[key] = ""
    temp = SETTINGS_FILE.with_suffix(".tmp")
    temp.write_text(json.dumps(stored, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(temp, SETTINGS_FILE)
    # Não confirmar sucesso apenas com o estado em memória: conferir persistência/DPAPI.
    reread = read_settings()
    for key in SECRET_FIELDS:
        if current.get(key) and reread.get(key) != current[key]:
            raise RuntimeError("Falha ao verificar gravação protegida de " + key)
    return public_settings(reread)

def public_settings(config=None):
    config = config or read_settings()
    return {k: v for k,v in config.items() if k not in SECRET_FIELDS} | {
       "youtube_api_key_ready": bool(config.get("youtube_api_key")),
       "openai_api_key_ready": bool(config.get("openai_api_key")),
       "openrouter_api_key_ready": bool(config.get("openrouter_api_key")),
       "nvidia_api_key_ready": bool(config.get("nvidia_api_key")),
       **{key + "_ready": bool(config.get(key))
          for provider,(key,_) in AI_PROVIDERS.items()
          if provider not in ("openai","openrouter","nvidia")},
       "sendoka_api_key_ready": bool(config.get("sendoka_api_key")),
       "sendoka_mode": ("test" if str(config.get("sendoka_api_key", "")).startswith("sok_test_") else
                        "live" if str(config.get("sendoka_api_key", "")).startswith("sok_live_") else "unconfigured"),
       "meta_page_token_ready": bool(config.get("meta_page_token")),
       "youtube_oauth_ready": TOKEN_FILE.exists()}

def text_model_id(value):
    # API /models inclui também modelos de imagem, áudio e snapshots; listar os de texto.
    return bool(re.fullmatch(
        r"(?:gpt-(?:[3-9](?:\.\d+)?(?:-(?:mini|nano|pro|astra|luna|sol|terra))?|4o(?:-mini)?)|o[1-9](?:-(?:mini|pro))?)",
        str(value)))


def list_openai_models(temporary_key=""):
    import requests
    key = str(temporary_key or "").strip() or read_settings().get("openai_api_key", "")
    if not key:
        raise ValueError("Nenhuma chave OpenAI configurada. Digite a chave e clique em Buscar modelos.")
    try:
        response = requests.get("https://api.openai.com/v1/models",
                                headers={"Authorization": "Bearer " + key}, timeout=25)
    except requests.RequestException:
        raise RuntimeError("Falha de conexão com a OpenAI. Confira a internet e tente novamente.") from None
    if response.status_code == 401:
        raise ValueError("Chave OpenAI inválida ou revogada (HTTP 401). Confira sua API key.")
    if response.status_code == 403:
        raise ValueError("A chave não possui permissão de listar modelos (HTTP 403).")
    if response.status_code == 429:
        raise RuntimeError("OpenAI limitou temporariamente as consultas (HTTP 429).")
    if not response.ok:
        raise RuntimeError("OpenAI não respondeu à lista de modelos (HTTP " + str(response.status_code) + ").")
    try:
        values = [m["id"] for m in response.json().get("data", []) if text_model_id(m.get("id"))]
    except (ValueError, KeyError, TypeError):
        raise RuntimeError("Resposta de modelos da OpenAI inválida.") from None
    models = sorted(set(values), key=lambda name: (
        -int((re.match(r"^(?:gpt-|o)(\d+)", name) or [0, 0])[1]), name))
    return {"connected": True, "models": models, "count": len(models),
            "recommended": next((x for x in ("gpt-5.4-mini", "gpt-5-mini", "gpt-6-astra") if x in models),
                                models[0] if models else "")}


def list_provider_models(provider, temporary_key=""):
    if provider == "openai":
        result = list_openai_models(temporary_key)
        return {**result, "provider": "openai", "free_filter": "credits_required"}
    ai_providers.check_provider(provider)
    field, _ = AI_PROVIDERS[provider]
    key = str(temporary_key or "").strip() or read_settings().get(field, "")
    return ai_providers.request_models(provider, key)


def test_provider_generation(provider, model, temporary_key=""):
    if provider not in AI_PROVIDERS: raise ValueError("Provedor de IA inválido")
    key_field, model_field = AI_PROVIDERS[provider]
    key = str(temporary_key or "").strip() or read_settings().get(key_field, "")
    if not key: raise ValueError("Configure a chave de " + provider + ".")
    ai_providers.validate_model(model)
    config = {key_field: key, model_field: model, "ai_provider": provider}
    example = [(1.0, "Dica: comece o Short com uma pergunta e finalize com uma resposta.")]
    result = ai_suggest(example, 40, 1, 20, config)
    if not result: raise RuntimeError("O modelo não gerou sugestões. Tente outro modelo.")
    return {"ok": True, "provider": provider, "model": model,
            "message": "Geração real validada com o modelo selecionado."}


def test_openai_generation(model, temporary_key=""):
    key = str(temporary_key or "").strip() or read_settings().get("openai_api_key", "")
    if not key: raise ValueError("Informe uma chave OpenAI.")
    if not text_model_id(model): raise ValueError("Selecione um modelo de texto da lista.")
    example = [(1.0, "Dica: comece o Short com uma pergunta e finalize com a resposta.")]
    result = ai_suggest(example, 40, 1, 20, {"openai_api_key": key, "model": model})
    if not result: raise RuntimeError("O modelo não gerou sugestões. Tente outro modelo.")
    return {"ok": True, "model": model, "message": "Geração real validada com este modelo."}


def connect():
    con = sqlite3.connect(DB_FILE, timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    return con

def init_db():
    with connect() as db:
        db.executescript("""CREATE TABLE IF NOT EXISTS clips (
          id TEXT PRIMARY KEY, source TEXT NOT NULL, origin_title TEXT NOT NULL,
          title TEXT NOT NULL, description TEXT NOT NULL, file TEXT NOT NULL,
          start REAL NOT NULL, duration REAL NOT NULL, method TEXT NOT NULL,
          created TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS publications (
          clip_id TEXT NOT NULL, platform TEXT NOT NULL, state TEXT NOT NULL,
          external_id TEXT NOT NULL DEFAULT '', message TEXT NOT NULL DEFAULT '',
          updated TEXT NOT NULL, PRIMARY KEY (clip_id,platform));
          CREATE TABLE IF NOT EXISTS tasks (
          id TEXT PRIMARY KEY, type TEXT NOT NULL, status TEXT NOT NULL,
          message TEXT NOT NULL, progress INTEGER NOT NULL, created TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS deleted_clips (
          clip_id TEXT PRIMARY KEY, removed TEXT NOT NULL, trash_file TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS clip_models (
          clip_id TEXT PRIMARY KEY, provider TEXT NOT NULL,
          model TEXT NOT NULL, role TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS favorite_models (
          provider TEXT NOT NULL, model TEXT NOT NULL,
          added TEXT NOT NULL, PRIMARY KEY (provider,model));
          CREATE TABLE IF NOT EXISTS topic_interests (
          topic TEXT PRIMARY KEY, downloads INTEGER NOT NULL DEFAULT 0,
          generations INTEGER NOT NULL DEFAULT 0,
          selections INTEGER NOT NULL DEFAULT 0, updated TEXT NOT NULL);
        """)
init_db()

def remember_task(task):
    with DB_LOCK, connect() as db:
        db.execute("INSERT OR REPLACE INTO tasks VALUES (?,?,?,?,?,?)",
                   (task["id"], task["type"], task["status"], task["message"], task["progress"], task["created"]))
        db.commit()

def task_update(tid, message, progress=None, status=None):
    task = TASKS[tid]
    task["message"] = str(message)[:700]
    if progress is not None: task["progress"] = int(progress)
    if status: task["status"] = status
    remember_task(task)

def start_task(kind, fn, *args):
    with TASK_LOCK:
        if kind in ("cut", "publish", "live_export") and any(t["type"] in ("cut", "publish", "live_export") and t["status"] == "working" for t in TASKS.values()):
            raise ValueError("Já existe uma tarefa deste tipo em andamento. Acompanhe em Atividade.")
        tid = secrets.token_hex(5)
        task = {"id": tid, "type": kind, "status": "working", "progress": 0,
                "message": "Iniciando...", "created": now()}
        TASKS[tid] = task
    remember_task(task)
    def run():
        try:
            fn(tid, *args)
            if TASKS[tid]["status"] == "working": task_update(tid, "Concluído.", 100, "done")
        except Exception as exc:
            print("TASK ERROR", tid, type(exc).__name__, str(exc)[:350], flush=True)
            task_update(tid, "Erro: " + str(exc)[:450], status="error")
    threading.Thread(target=run, daemon=True, name=f"cutshort-{tid}").start()
    return task

def record_topic_interest(title, event="selection"):
    """Histórico somente local para recomendações. Não observa navegação externa."""
    topic=topic_interest.safe_topic(title)
    if not topic or event not in ("download","generation","selection"):
        return {"topic": ""}
    dl,gen,sel=(int(event=="download"),int(event=="generation"),int(event=="selection"))
    with DB_LOCK, connect() as db:
        db.execute("""INSERT INTO topic_interests (topic,downloads,generations,selections,updated)
                      VALUES (?,?,?,?,?) ON CONFLICT(topic) DO UPDATE SET
                      downloads=downloads+excluded.downloads,
                      generations=generations+excluded.generations,
                      selections=selections+excluded.selections,
                      updated=excluded.updated""",
                   (topic,dl,gen,sel,now()))
        db.commit()
    return {"topic":topic}


def top_interest():
    with DB_LOCK,connect() as db:
        row=db.execute("""SELECT topic,downloads,generations,selections
             FROM topic_interests ORDER BY (downloads*6+generations*3+selections) DESC,
             updated DESC LIMIT 1""").fetchone()
        if row:
            return dict(row), "Seu histórico local de cortes e downloads"
        row=db.execute("""SELECT origin_title,COUNT(*) AS qty FROM clips
                          GROUP BY origin_title ORDER BY qty DESC LIMIT 1""").fetchone()
    if row:
        name=topic_interest.safe_topic(row["origin_title"])
        if name:return {"topic":name}, "Temas anteriores da biblioteca"
    # O próprio usuário já usou o nicho GTA 6 nesta instalação; não alegar download medido.
    return {"topic":"GTA 6"}, "Sugestão inicial; as próximas serão personalizadas"


_LIVE_SUGGESTIONS={"key":"","expires":0,"videos":[]}
_LIVE_SUGGESTIONS_LOCK=threading.RLock()


def recommended_lives(refresh=False):
    record,basis=top_interest()
    topic=record["topic"]
    stamp=time.monotonic()
    with _LIVE_SUGGESTIONS_LOCK:
        if not refresh and _LIVE_SUGGESTIONS["key"]==topic and stamp<_LIVE_SUGGESTIONS["expires"]:
            return {"videos":_LIVE_SUGGESTIONS["videos"],"topic":topic,"basis":basis}
        # Apenas lives confirmadas como ativas pela busca YouTube; sem inventar resultados.
        videos=youtube_search.search_videos(topic_interest.recommended_query(topic),
                                          live=True,limit=30)
        _LIVE_SUGGESTIONS.update(key=topic,expires=time.monotonic()+240,videos=videos)
        return {"videos":videos,"topic":topic,"basis":basis}


def clear_finished_activities():
    """Limpa somente o histórico. Não apaga arquivos, tarefas ativas nem publicações."""
    with TASK_LOCK,DB_LOCK,connect() as db:
        db.execute("BEGIN IMMEDIATE")
        try:
            finished=[r["id"] for r in db.execute(
                "SELECT id FROM tasks WHERE status IN ('done','error')")]
            db.execute("DELETE FROM tasks WHERE status IN ('done','error')")
            db.commit()
        except Exception:
            db.rollback()
            raise
        for task_id in finished:
            if task_id in TASKS and TASKS[task_id].get("status") in ("done","error"):
                TASKS.pop(task_id,None)
    return {"cleared":len(finished),"message":"Somente atividades finalizadas foram removidas."}


def favorite_models():
    """Favoritos de IA persistidos no SQLite; chave de cada item = provedor + modelo."""
    with DB_LOCK, connect() as db:
        values = db.execute("""SELECT provider, model FROM favorite_models
                               ORDER BY added ASC, provider ASC, model ASC""").fetchall()
    return {"favorites": [dict(row) for row in values]}


def update_favorite_model(provider, model, favorite):
    if provider not in AI_PROVIDERS:
        raise ValueError("Provedor de IA inválido.")
    ai_providers.validate_model(model)
    if type(favorite) is not bool:
        raise ValueError("Atributo favorito inválido.")
    with DB_LOCK, connect() as db:
        if favorite:
            db.execute("""INSERT OR IGNORE INTO favorite_models
                          (provider,model,added) VALUES (?,?,?)""",
                       (provider,model,now()))
        else:
            db.execute("""DELETE FROM favorite_models WHERE provider=? AND model=?""",
                       (provider,model))
        db.commit()
    return favorite_models()


def get_clips():
    with connect() as db:
        rows = db.execute("""SELECT * FROM clips WHERE id NOT IN
                             (SELECT clip_id FROM deleted_clips)
                             ORDER BY created DESC LIMIT 150""").fetchall()
        pubs = db.execute("SELECT * FROM publications").fetchall()
        models = db.execute("SELECT * FROM clip_models").fetchall()
    by_model = {m["clip_id"]: dict(m) for m in models}
    by_clip = {}
    for p in pubs:
        by_clip.setdefault(p["clip_id"], {})[p["platform"]] = {
            "state": p["state"], "external_id": p["external_id"],
            "message": p["message"], "updated": p["updated"]}
    names = {"openai": "OpenAI", "openrouter": "OpenRouter", "nvidia": "NVIDIA",
             "local": "Local", "none": "Sem IA"}
    result = []
    for r in rows:
        meta = by_model.get(r["id"])
        model_label = ((names.get(meta["provider"], meta["provider"]) + " · " + meta["model"])
                       if meta and meta["provider"] not in ("none", "local")
                       else meta["model"] if meta else "Não registrado (corte anterior)")
        result.append({**dict(r), "filename": Path(r["file"]).name,
                       "model_used": model_label,
                       "model_role": meta["role"] if meta else "desconhecido",
                       "publications": by_clip.get(r["id"], {})})
    return result

def checked_deleted_file(row, require_file=True):
    """Valida caminho e identidade para acessar somente MP4s gerenciados na lixeira."""
    cid = row["clip_id"]
    raw = Path(row["trash_file"])
    candidate = raw.resolve()
    trash_root = (DATA / "lixeira").resolve()
    if (not re.fullmatch(r"[a-f0-9]{16}", cid) or raw.is_symlink()
            or candidate.parent != trash_root
            or not clip_titles.managed_filename(candidate.name, cid, row["title"])):
        raise ValueError("Arquivo da lixeira não é um MP4 gerenciado válido.")
    if require_file and not candidate.is_file():
        raise FileNotFoundError("Arquivo da lixeira ausente.")
    return candidate


def get_deleted_clips():
    """Inventário somente leitura: inclui entradas históricas com MP4 ausente."""
    with DB_LOCK, connect() as db:
        rows = db.execute("""SELECT d.clip_id, d.removed, d.trash_file,
                            c.title, c.origin_title, c.duration,
                            m.model FROM deleted_clips d
                            JOIN clips c ON c.id=d.clip_id
                            LEFT JOIN clip_models m ON m.clip_id=d.clip_id
                            ORDER BY d.removed DESC LIMIT 500""").fetchall()
    result = []
    for row in rows:
        file_name = Path(row["trash_file"]).name
        try:
            path = checked_deleted_file(row)
            size, available = path.stat().st_size, True
        except (ValueError, OSError):
            size, available = 0, False
        result.append({
            "id": row["clip_id"], "title": row["title"],
            "origin_title": row["origin_title"], "removed": row["removed"],
            "duration": row["duration"], "filename": file_name,
            "model": row["model"] or "Não registrado",
            "available": available, "bytes": size
        })
    return {"clips": result, "total": len(result),
            "available": sum(1 for item in result if item["available"]),
            "missing": sum(1 for item in result if not item["available"])}


def permanently_delete_clips(ids, confirmation):
    """Remove somente arquivos gerenciados de data/lixeira após confirmação explícita.

    Primeiro move para staging privado; commit de remoção dos registros ocorre antes
    de apagar os arquivos movidos. Em falha anterior ao commit, devolve os MP4s.
    Registros de publicações externas são mantidos para auditoria.
    """
    if confirmation != "EXCLUIR PERMANENTEMENTE":
        raise ValueError("Confirmação de exclusão permanente ausente.")
    ids = validated_clip_ids(ids)
    with TASK_LOCK, DB_LOCK, connect() as db:
        ensure_not_processing()
        targets = {}
        for cid in ids:
            row = db.execute("""SELECT d.clip_id, d.trash_file, c.title
                                FROM deleted_clips d JOIN clips c ON c.id=d.clip_id
                                WHERE d.clip_id=?""", (cid,)).fetchone()
            if not row:
                raise ValueError("Corte não está na lixeira: " + cid)
            source = checked_deleted_file(row)
            targets[cid] = source
        pending_dir = DATA / ".purge_pending"
        pending_dir.mkdir(parents=True, exist_ok=True)
        staged = []
        committed = False
        try:
            # Caminhos gerados internamente: nunca usar nome/caminho enviados pela UI.
            for cid, source in targets.items():
                pending = pending_dir / (secrets.token_hex(10) + ".mp4")
                if pending.exists():
                    raise RuntimeError("Nome temporário inesperadamente ocupado.")
                source.replace(pending)
                staged.append((source, pending))
            for cid in ids:
                db.execute("DELETE FROM deleted_clips WHERE clip_id=?", (cid,))
                db.execute("DELETE FROM clip_models WHERE clip_id=?", (cid,))
                db.execute("DELETE FROM clips WHERE id=?", (cid,))
            db.commit()
            committed = True
        except Exception:
            if not committed:
                db.rollback()
                for source, pending in reversed(staged):
                    if pending.exists() and not source.exists():
                        pending.replace(source)
            raise

        cleanup_failed = []
        for _, pending in staged:
            try:
                pending.unlink()
            except OSError:
                cleanup_failed.append(pending.name)
        if cleanup_failed:
            print("PURGE PENDING CLEANUP", len(cleanup_failed), "em", pending_dir, flush=True)
        return {"deleted": len(ids), "ids": ids,
                "pending_cleanup": len(cleanup_failed),
                "message": ("Exclusão concluída." if not cleanup_failed else
                            "Registros excluídos, mas há arquivos pendentes de limpeza no disco.")}


def validated_clip_ids(ids):
    if not isinstance(ids, list) or not ids or len(ids) > 150:
        raise ValueError("Selecione de 1 a 150 cortes.")
    if any(not isinstance(cid, str) or not re.fullmatch(r"[a-f0-9]{16}", cid)
           for cid in ids):
        raise ValueError("Seleção de cortes inválida.")
    return list(dict.fromkeys(ids))


def ensure_not_processing():
    if any(t["status"] == "working" and t["type"] in ("cut", "publish", "live_export")
           for t in TASKS.values()):
        raise ValueError("Aguarde o término da geração ou publicação para remover/restaurar cortes.")


def trash_clips(ids):
    """Remoção reversível: move somente MP4s gerados, preservando registros e publicações."""
    ids = validated_clip_ids(ids)
    trash_dir = DATA / "lixeira"
    moved = []
    with TASK_LOCK, DB_LOCK, connect() as db:
        ensure_not_processing()
        rows = {}
        for cid in ids:
            row = db.execute("""SELECT file,title FROM clips WHERE id=? AND
                                id NOT IN (SELECT clip_id FROM deleted_clips)""",
                             (cid,)).fetchone()
            if row is None: raise ValueError("Corte inexistente ou já removido: " + cid)
            actual = Path(row["file"]).resolve()
            if actual.parent != OUTPUT.resolve() or not clip_titles.managed_filename(
                    actual.name, cid, row["title"]):
                raise ValueError("Caminho do corte diverge da pasta de saída; remoção bloqueada.")
            if not actual.is_file(): raise ValueError("Arquivo do corte não encontrado: " + cid)
            dest = (trash_dir / actual.name).resolve()
            if dest.exists(): raise ValueError("Já existe arquivo na lixeira: " + cid)
            rows[cid] = (actual, dest)
        trash_dir.mkdir(parents=True, exist_ok=True)
        try:
            for cid, (source, target) in rows.items():
                source.replace(target)
                moved.append((source, target))
                db.execute("INSERT INTO deleted_clips VALUES (?,?,?)",
                           (cid, now(), str(target)))
            db.commit()
        except Exception:
            db.rollback()
            for source, target in reversed(moved):
                if target.exists() and not source.exists():
                    target.replace(source)
            raise
    return {"removed": len(ids), "ids": ids,
            "message": "Cortes movidos para a lixeira local. Arquivos originais e histórico preservados."}


def restore_clips(ids):
    ids = validated_clip_ids(ids)
    moved = []
    with TASK_LOCK, DB_LOCK, connect() as db:
        ensure_not_processing()
        rows = {}
        reserved_names=set()
        for cid in ids:
            row = db.execute("""SELECT d.trash_file,c.title FROM deleted_clips d
                                JOIN clips c ON c.id=d.clip_id WHERE d.clip_id=?""",
                             (cid,)).fetchone()
            if not row: raise ValueError("Corte não encontrado na lixeira: " + cid)
            expected = Path(row["trash_file"]).resolve()
            if expected.parent != (DATA / "lixeira").resolve() or not clip_titles.managed_filename(
                    expected.name, cid, row["title"]):
                raise ValueError("Caminho na lixeira divergente; restauração bloqueada.")
            if not expected.is_file(): raise ValueError("Arquivo da lixeira não encontrado: " + cid)
            clean_name = clip_titles.unique_clip_filename(
                row["title"], OUTPUT, reserved=reserved_names)
            reserved_names.add(clean_name.casefold())
            # Mesmo os arquivos antigos restaurados passam a ter título sem código.
            destination = (OUTPUT / clean_name).resolve()
            if destination.exists(): raise ValueError("Já existe um arquivo com este nome: " + cid)
            rows[cid] = (expected, destination)
        try:
            for cid, (source, target) in rows.items():
                source.replace(target)
                moved.append((source, target))
                db.execute("DELETE FROM deleted_clips WHERE clip_id=?", (cid,))
                db.execute("UPDATE clips SET file=? WHERE id=?", (str(target),cid))
            db.commit()
        except Exception:
            db.rollback()
            for source, target in reversed(moved):
                if target.exists() and not source.exists():
                    target.replace(source)
            raise
    return {"restored": len(ids), "ids": ids, "message": "Cortes restaurados na biblioteca."}


def record_pub(cid, platform, state, external_id="", message=""):
    with DB_LOCK, connect() as db:
        db.execute("INSERT OR REPLACE INTO publications VALUES (?,?,?,?,?,?)",
                   (cid, platform, state, str(external_id), str(message)[:350], now()))
        db.commit()

def youtube_url(url):
    p = urlparse(str(url).strip())
    if p.scheme not in ("https", "http") or (p.hostname or "").lower() not in ALLOWED_HOSTS:
        raise ValueError("Use um link válido de vídeo do YouTube.")
    return url

def get_ffmpeg():
    candidate = shutil.which("ffmpeg")
    if candidate: return candidate
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception: return None

def get_ydl():
    try:
        import yt_dlp
        return yt_dlp
    except ImportError: raise RuntimeError("yt-dlp não instalado. Execute Iniciar-CutShortPlus.cmd.")

LIVE = live_studio.LiveRecorder(DATA, get_ffmpeg, get_ydl)

def search_videos(text, sort="relevance", published="any", duration="any", live=False):
    return youtube_search.search_videos(text, sort, published, duration, live)

def video_info(url):
    url = youtube_url(url)
    yt = get_ydl()
    with yt.YoutubeDL({"quiet": True, "no_warnings": True, "skip_download": True,
                       "noplaylist": True, "socket_timeout": 25,
                       "extractor_args": {"youtube": {"lang": ["pt"]}}}) as y:
        info = y.extract_info(url, download=False)
    if not info or info.get("_type") == "playlist": raise ValueError("Escolha um vídeo, não uma playlist.")
    return {"url": url, "title": info.get("title") or "Vídeo",
            "duration": info.get("duration") or 0, "channel": info.get("channel") or "",
            "thumbnail": info.get("thumbnail") or "",
            "id": info.get("id") or ""}

def parse_timestamp(value):
    chunks = re.split(r"[:,.]", value)
    if len(chunks) == 4: return int(chunks[0])*3600+int(chunks[1])*60+int(chunks[2])+int(chunks[3])/1000
    if len(chunks) == 3: return int(chunks[0])*60+int(chunks[1])+int(chunks[2])/1000
    return 0

def parse_vtt(file):
    lines = file.read_text(encoding="utf-8-sig", errors="ignore").splitlines()
    segments, previous = [], ""
    for index, line in enumerate(lines):
        if "-->" not in line: continue
        start = parse_timestamp(line.split("-->")[0].strip())
        words = []
        for nxt in lines[index+1:index+5]:
            if not nxt.strip() or "-->" in nxt: break
            word = html.unescape(re.sub(r"<[^>]+>", "", nxt)).strip()
            word = re.sub(r"\s+", " ", word)
            if word: words.append(word)
        phrase = " ".join(words)
        if phrase and phrase != previous:
            segments.append((start, phrase[:500]))
            previous = phrase
    return segments

def fetch_subtitles(url, folder):
    yt = get_ydl()
    opts = {"quiet": True, "no_warnings": True, "skip_download": True,
            "writesubtitles": True, "writeautomaticsub": True,
            "subtitleslangs": ["pt.*", "en.*"], "subtitlesformat": "vtt",
            "outtmpl": str(folder / "transcript.%(ext)s"), "noplaylist": True}
    try:
        with yt.YoutubeDL(opts) as y: y.download([url])
    except Exception: return []
    files = list(folder.glob("transcript.*.vtt"))
    files.sort(key=lambda p: (not (".pt" in p.name), p.name))
    for f in files:
        parsed = parse_vtt(f)
        if parsed: return parsed
    return []

def ai_suggest(segments, length, count, seconds, settings):
    provider = settings.get("ai_provider") or "openai"
    if provider not in AI_PROVIDERS: raise ValueError("Provedor de IA inválido")
    key_field, model_field = AI_PROVIDERS[provider]
    key = settings.get(key_field)
    if not key or not segments: return None
    import requests
    transcript = "\n".join(f"{t:.1f}s {v}" for t,v in segments)[:26000]
    prompt = ("Você edita Shorts em português. Analise a transcrição com timestamps. "
              f"Selecione até {count} momentos interessantes de até {seconds} segundos "
              "para vídeos verticais autossuficientes, sem sobreposições. "
              "Crie um título curto de 4 a 9 palavras, no máximo 58 caracteres, " 
              "atraente e fiel EXCLUSIVAMENTE ao assunto efetivamente falado no intervalo do corte. " 
              "Evite Parte 1, títulos genéricos, exageros e informações inventadas. " 
              "Responda SOMENTE JSON no formato {\"clips\":[{\"start\":numero_segundos,"
              "\"title\":\"título curto\",\"description\":\"descrição objetiva\"}]}. "
              f"Vídeo tem {length:.0f}s. Não invente informações. Transcrição:\n" + transcript)
    model = settings.get(model_field)
    if not model: raise ValueError("Selecione um modelo da " + provider + " em Integrações.")
    if provider != "openai":
        return ai_providers.generate(provider, key, model, prompt)
    # OpenAI: Responses API com JSON Schema.
    schema = {"type": "object", "additionalProperties": False,
              "properties": {"clips": {"type": "array", "items": {
                  "type": "object", "additionalProperties": False,
                  "properties": {"start": {"type": "number"},
                                 "title": {"type": "string"},
                                 "description": {"type": "string"}},
                  "required": ["start", "title", "description"]}}},
              "required": ["clips"]}
    try:
        resp = requests.post("https://api.openai.com/v1/responses",
            headers={"Authorization": "Bearer " + key},
            json={"model": model, "input": prompt, "store": False,
                  "max_output_tokens": 3000,
                  "text": {"format": {"type": "json_schema", "name": "cutshort_clips",
                                      "strict": True, "schema": schema}}},
            timeout=90)
    except requests.RequestException:
        raise RuntimeError("Falha de conexão ao gerar cortes com a OpenAI.") from None
    if not resp.ok:
        try: reason = resp.json().get("error", {}).get("code") or "request_rejected"
        except ValueError: reason = "request_rejected"
        if reason in ("credit_balance_exhausted", "insufficient_quota", "billing_hard_limit_reached"):
            raise RuntimeError("Créditos da API OpenAI esgotados. Adicione saldo em platform.openai.com/settings/organization/billing/overview.")
        if resp.status_code == 429:
            raise RuntimeError("Limite de requisições OpenAI atingido (429). Aguarde ou verifique sua cota.")
        raise RuntimeError("Modelo " + model + " indisponível nesta operação (HTTP " +
                           str(resp.status_code) + ", " + str(reason)[:60] + ").")
    data = resp.json()
    parts = [part.get("text", "") for item in data.get("output", [])
             for part in item.get("content", []) if part.get("type") == "output_text"]
    if not parts: raise RuntimeError("O modelo não retornou conteúdo de texto.")
    clips = json.loads("".join(parts)).get("clips", [])
    if not isinstance(clips, list): raise RuntimeError("Resposta da IA sem cortes válidos.")
    return clips

HIGHLIGHTS = ("importante", "atenção", "segredo", "incrível", "nunca", "descubra",
              "dica", "aprenda", "resultado", "erro", "cuidado", "melhor", "agora",
              "why", "how", "best", "amazing", "don't")
def select_segments(segments, length, count, seconds, title, suggested=None):
    if length < 4: raise ValueError("O vídeo é curto demais para cortar.")
    dur = min(seconds, length)
    picks, mode = [], "Distribuição automática (sem transcrição)"
    if suggested:
        for it in suggested:
            try: start = float(it.get("start", -1))
            except (TypeError, ValueError): continue
            if start < 0 or start + dur > length + 1: continue
            if any(abs(start - p["start"]) < dur * .8 for p in picks): continue
            picks.append({"start": max(0, start), "title": str(it.get("title") or title)[:90],
                          "description": str(it.get("description") or "")[:500]})
            if len(picks) >= count: break
        if picks: mode = "Seleção com IA e transcrição"
    if not picks and segments:
        mode = "Seleção por transcrição (heurística)"
        choices = []
        for timestamp, phrase in segments:
            if timestamp < 5 or timestamp > length - max(5, dur/2): continue
            score = len(set(re.findall(r"\w+", phrase.lower())))
            score += 14 * sum(word in phrase.lower() for word in HIGHLIGHTS)
            score += 8 * int("?" in phrase) + 6 * int("!" in phrase)
            choices.append((score, timestamp, phrase))
        for _, at, phrase in sorted(choices, reverse=True):
            start = min(max(0, at - 5), max(0, length-dur))
            if any(abs(start - p["start"]) < dur * .9 for p in picks): continue
            name = re.sub(r"\s+", " ", phrase).strip(" -.,")[:67]
            picks.append({"start": start, "title": name or title,
                          "description": "Trecho de " + title})
            if len(picks) == count: break
    if not picks:
        for i in range(count):
            start = min(max(0, (length - dur)*(i+1)/(count+1)), max(0, length-dur))
            if any(abs(start - p["start"]) < dur*.8 for p in picks): continue
            picks.append({"start": start, "title": f"{title[:63]} · Parte {i+1}",
                          "description": "Corte automático de " + title})
    return picks, mode

def get_duration(file):
    ff = get_ffmpeg()
    if not ff: raise RuntimeError("FFmpeg não encontrado.")
    r = subprocess.run([ff, "-hide_banner", "-i", str(file)],
                       capture_output=True, text=True, timeout=15, errors="replace")
    m = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", r.stderr)
    if not m: raise RuntimeError("Não foi possível analisar a duração do arquivo de vídeo.")
    return int(m[1])*3600 + int(m[2])*60 + float(m[3])

def youtube_download_options(jobdir):
    ffmpeg = get_ffmpeg()
    if not ffmpeg or not Path(ffmpeg).is_file():
        raise RuntimeError("FFmpeg indisponível para baixar e unir áudio/vídeo do YouTube.")
    return {"quiet": True, "no_warnings": True, "noplaylist": True,
            "format": "bv*[height<=720]+ba/best[height<=720]/best",
            "ffmpeg_location": ffmpeg, "merge_output_format": "mp4",
            "outtmpl": str(jobdir / "source.%(ext)s"),
            "extractor_args": {"youtube": {"lang": ["pt"]}}}

def job_make_clips(tid, source, num, seconds, autopublish=False, ai_provider=None, ai_model=None, turbo=False):
    if not get_ffmpeg(): raise RuntimeError("FFmpeg não instalado.")
    num, seconds = max(1,min(10,int(num))), max(12,min(60,int(seconds)))
    if type(turbo) is not bool:
        raise ValueError("Configuração Turbo Short inválida.")
    youtube = source.startswith("http://") or source.startswith("https://")
    if youtube: source = youtube_url(source)
    jobdir = DATA / ("job_" + tid)
    jobdir.mkdir(exist_ok=True)
    task_update(tid, "Obtendo informações do vídeo...", 6)
    if youtube:
        yt = get_ydl()
        with yt.YoutubeDL(youtube_download_options(jobdir)) as y:
            info = y.extract_info(source, download=True)
        inputs = [f for f in jobdir.glob("source.*") if f.suffix.lower() in (".mp4",".mkv",".webm")]
        if not inputs: raise RuntimeError("Download não produziu vídeo. Verifique disponibilidade e direitos de uso.")
        filename = inputs[0]
        original_title = str(info.get("title") or "Vídeo")[:150]
        chapters = info.get("chapters") or []
        # O tempo do arquivo realmente baixado prevalece sobre o metadado remoto:
        # streams truncados nunca podem gerar intervalos no vazio.
        length = float(get_duration(filename))
    else:
        filename = Path(source).resolve()
        if not filename.is_file() or filename.suffix.lower() not in (".mp4",".mkv",".mov",".webm"):
            raise ValueError("Arquivo local inválido. Escolha MP4, MKV, MOV ou WEBM.")
        original_title = filename.stem[:150]
        chapters = []
        length = get_duration(filename)
    original_requested=num
    if turbo:
        _,num=highlight_engine.turbo_plan(length,seconds)
        task_update(tid,f"⚡ Turbo Short: analisando até {num} intervalos independentes...",26)
    record_topic_interest(original_title,"generation")
    task_update(tid, "Procurando momentos relevantes...", 27)
    segs = fetch_subtitles(source, jobdir) if youtube else []
    source_transcribed = False
    speech_warning = ""
    # No fallback anterior o ASR só era executado APÓS escolher intervalos
    # aleatórios. Agora a fala do próprio vídeo guia os candidatos.
    if not segs and length <= 900:
        task_update(tid, "Transcrevendo o vídeo para identificar assuntos reais...", 28)
        segs, speech_warning = asr_local.transcribe_clip(filename, DATA / "models")
        source_transcribed = bool(segs)
    heatmap = []
    if youtube:
        heatmap = highlight_engine.normalized_info_heatmap(info)
        if not heatmap:
            task_update(tid, "Consultando trechos mais reproduzidos, quando disponíveis...", 31)
            heatmap = highlight_engine.public_youtube_heatmap(source)
    ai_cfg = read_settings()
    active_provider = ai_provider or ai_cfg.get("ai_provider") or "openai"
    ai_warning, suggestions = "", None
    if active_provider != "none":
        if active_provider not in AI_PROVIDERS: raise ValueError("Provedor de IA inválido")
        key_field, model_field = AI_PROVIDERS[active_provider]
        if ai_model: ai_cfg[model_field] = ai_providers.validate_model(ai_model)
        ai_cfg["ai_provider"] = active_provider
        if not ai_cfg.get(key_field): ai_warning = "Chave ausente para " + active_provider + "."
        elif not ai_cfg.get(model_field): ai_warning = "Modelo não configurado."
        elif not segs: ai_warning = "Nenhuma transcrição para a IA avaliar."
        else:
            try:
                suggestions = ai_suggest(segs, length, min(num,10), seconds, ai_cfg)
            except Exception as exc:
                ai_warning = str(exc)[:190]
                print("IA indisponível, seleção contextual local:", ai_warning, flush=True)
    task_update(tid, "Avaliando contexto e movimento, rejeitando imagens estáticas...", 35)
    picks, selection = highlight_engine.choose_moments(
        get_ffmpeg(), filename, segs, length, num, seconds,
        heatmap=heatmap, chapters=chapters, suggestions=suggestions, turbo=turbo,
        progress=lambda done,total: task_update(
            tid, f"Analisando movimento e contexto: {done}/{total} janelas avaliadas...", 
            35 + min(5,int(5*done/max(1,total)))))
    if not picks:
        why = ("não foram detectados trechos com movimento suficiente" if
               (segs or chapters or heatmap) else "faltam transcrição, capítulos e dados de replay")
        raise ValueError(
            "Nenhum Short contextual seguro foi identificado: " + why +
            ". Evitei criar cortes com imagens estáticas ou trechos aleatórios. " +
            (speech_warning or "Experimente outro vídeo com falas e cenas dinâmicas."))
    mode = ("Destaques mais reproduzidos + fala" if heatmap and segs else
            "Destaques mais reproduzidos" if heatmap else
            "Seleção por fala e movimento" if segs else
            "Capítulos e movimento" if chapters else "Seleção visual por movimento")
    if turbo:mode="Turbo Short · "+mode
    for index, pick in enumerate(picks, start=1):
        clip_length = pick["duration"]
        chapter = clip_titles.chapter_at(chapters, pick["start"])
        ai_choice = next((x for x in (suggestions or [])
                          if abs(float(x.get("start",-1000))-pick["start"]) <= 5), None)
        suggested = str(ai_choice.get("title") or "") if ai_choice else ""
        pick["title"] = clip_titles.relevant_title(
            segs, pick["start"], clip_length, original_title,
            chapter_title=chapter, suggested=suggested,
            index=index, has_ai=bool(suggested))
        pick["description"] = ("Trecho contextual: " + pick["title"] +
                               (" · Indicação de replay público" if heatmap else ""))
    created_ids = []
    task_update(tid, f"{len(picks)} momentos selecionados. Criando Shorts 9:16...", 40)
    ff = get_ffmpeg()
    for i, pick in enumerate(picks, start=1):
        cid = secrets.token_hex(8)
        out = jobdir / ("render-" + cid + ".mp4")
        model_provider = "none"
        model_name = "Sem IA (seleção automática)"
        model_role = "seleção automática"
        if mode == "Seleção com IA e transcrição" and suggestions:
            model_provider = active_provider
            model_name = ai_cfg.get(AI_PROVIDERS[active_provider][1], "")
            model_role = "seleção do trecho e título"
        elif segs:
            model_name = "Sem IA (seleção por legendas)"
            model_role = "seleção por legendas"
        dur = min(float(pick["duration"]), length-pick["start"])
        if dur < 12: continue
        # Recorte inteligente 9:16: prioriza a região com movimento real.
        # Resolve casos em que o corte central exibia apenas uma imagem parada.
        framing=highlight_engine.best_vertical_crop(ff,filename,pick["start"],dur)
        crop_expr={"left":"0","center":"(in_w-out_w)/2",
                   "right":"in_w-out_w"}[framing["position"]]
        vf=("scale=720:1280:force_original_aspect_ratio=increase,"
            "crop=720:1280:x="+crop_expr+",setsar=1,fps=30,format=yuv420p")
        cmd = [ff, "-hide_banner", "-loglevel", "error", "-y",
               "-ss", str(round(pick["start"],3)), "-i", str(filename),
               "-t", str(round(dur,3)), "-vf", vf,
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "24",
               "-c:a", "aac", "-b:a", "160k", "-ar", "48000",
               "-movflags", "+faststart", str(out)]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600, errors="replace")
        if proc.returncode != 0 or not out.exists() or out.stat().st_size < 2000:
            out.unlink(missing_ok=True)
            raise RuntimeError("FFmpeg falhou: " + proc.stderr[-600:])
        rendered_motion = highlight_engine.visual_motion_score(ff, out, 0, dur)
        rendered_quality=highlight_engine.classify_moment(rendered_motion,pick,relaxed=turbo)
        if not rendered_quality:
            out.unlink(missing_ok=True)
            print("SHORT_REJECTED_STILL_VIDEO", i, flush=True)
            continue
        # Se o vídeo não possui legendas, transcrevemos o áudio do Short localmente
        # e usamos EXCLUSIVAMENTE o trecho real, não a live inteira, para nomeá-lo.
        if not segs and dur >= 15:
            task_update(tid, f"Analisando a fala do Short {i}/{len(picks)}...", 40 + int(52 * i / len(picks)))
            spoken, speech_warning = asr_local.transcribe_clip(out, DATA / "models")
            if spoken:
                model_provider = "local"
                model_name = "Whisper tiny (local)"
                model_role = "título pela fala; seleção temporal"
                if ai_warning == "Vídeo sem transcrição disponível; seleção automática sem IA.":
                    ai_warning = ""
                if mode == "Distribuição automática (sem transcrição)":
                    mode = "Seleção temporal · título baseado na fala"
                suggested_title = ""
                if active_provider != "none" and ai_cfg.get(AI_PROVIDERS[active_provider][0]):
                    try:
                        suggestion = ai_suggest(spoken, dur, 1, dur, ai_cfg)
                        suggested_title = str(suggestion[0].get("title") or "") if suggestion else ""
                        if suggested_title:
                            model_provider = active_provider
                            model_name = ai_cfg.get(AI_PROVIDERS[active_provider][1], "")
                            model_role = "título pela transcrição local"
                    except Exception as exc:
                        ai_warning = (ai_warning + " " + str(exc))[:190]
                pick["title"] = clip_titles.relevant_title(
                    spoken, 0, dur, original_title, suggested=suggested_title,
                    index=i, has_ai=bool(suggested_title))
                pick["description"] = "Trecho sobre: " + pick["title"]
            elif speech_warning:
                ai_warning = (ai_warning + " " + speech_warning)[:190]
        with TASK_LOCK, DB_LOCK, connect() as db:
            # A alocação de nome e a inserção são serializadas com a lixeira/restauração.
            clean_name = clip_titles.unique_clip_filename(
                pick["title"], OUTPUT, DATA / "lixeira")
            final_path = OUTPUT / clean_name
            if final_path.exists():
                raise RuntimeError("Arquivo de destino já existe. Não sobrescrever.")
            out.rename(final_path)
            try:
                db.execute("INSERT INTO clips VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (cid, source, original_title, pick["title"], pick["description"],
                     str(final_path), round(pick["start"], 2), round(dur,2), mode, now()))
                db.execute("INSERT INTO clip_models VALUES (?,?,?,?)",
                    (cid, model_provider, model_name, model_role))
                db.commit()
            except Exception:
                db.rollback()
                if final_path.is_file() and not out.exists():
                    final_path.rename(out)
                raise
            out = final_path
        created_ids.append(cid)
        task_update(tid, f"Short {len(created_ids)}/{len(picks)} pronto.", 40 + int(58*i/len(picks)))
    if not created_ids:
        raise ValueError("Todos os trechos foram rejeitados pela verificação de movimento; nenhum vídeo estático foi salvo.")
    if autopublish:
        task_update(tid, "Cortes prontos; publicando automaticamente nos dois canais...", 80)
        job_publish(tid, created_ids, ["youtube", "facebook"], read_settings()["privacy"])
    else:
        note = (" IA indisponível: " + ai_warning) if ai_warning else ""
        shortage = (f" Planejados {num}, gerados {len(created_ids)}; capacidade ou qualidade da fonte limitou o resultado."
                    if len(created_ids)<num else "")
        talk = (f" {selection['low_motion']} candidato(s) com fala e movimento sutil."
                if selection.get("low_motion") else "")
        task_update(tid, f"{len(created_ids)} corte(s) criado(s) · {mode}. Duração máxima {seconds}s; sem sobreposição."+
                    shortage+talk+" Revise antes de publicar."+note,100,"done")

def oauth_youtube(tid):
    cfg = read_settings()
    client_file = Path(cfg.get("yt_client_file") or "")
    if not client_file.is_file(): raise ValueError("Informe o caminho do JSON OAuth Desktop no painel Integrações.")
    from google_auth_oauthlib.flow import InstalledAppFlow
    task_update(tid, "Autorização do Google aberta no navegador; selecione seu canal.", 20)
    flow = InstalledAppFlow.from_client_secrets_file(
        str(client_file), scopes=["https://www.googleapis.com/auth/youtube.upload"])
    credentials = flow.run_local_server(host="localhost", port=0, open_browser=True,
                                        authorization_prompt_message="Autorização: {url}",
                                        success_message="YouTube conectado. Volte ao CutShortPlus.")
    TOKEN_FILE.write_text(protected(credentials.to_json()), encoding="utf-8")
    task_update(tid, "Conta YouTube conectada com segurança.", 100, "done")

def get_youtube_credentials():
    if not TOKEN_FILE.exists(): raise ValueError("Conecte seu YouTube em Integrações.")
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    c = Credentials.from_authorized_user_info(json.loads(unprotected(TOKEN_FILE.read_text(encoding="utf-8"))))
    if not c.valid:
        if not c.refresh_token: raise RuntimeError("Token sem refresh. Conecte a conta novamente.")
        c.refresh(Request())
        TOKEN_FILE.write_text(protected(c.to_json()), encoding="utf-8")
    return c

def upload_youtube(cid, row, tid, privacy):
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    cred = get_youtube_credentials()
    service = build("youtube", "v3", credentials=cred, cache_discovery=False)
    task_update(tid, "Enviando ao YouTube...", 50)
    req = service.videos().insert(
        part="snippet,status",
        body={"snippet": {"title": row["title"][:100],
                          "description": row["description"][:4500],
                          "categoryId": "22"},
              "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False}},
        media_body=MediaFileUpload(row["file"], mimetype="video/mp4",
                                   chunksize=4*1024*1024, resumable=True))
    result = None
    while result is None:
        _, result = req.next_chunk(num_retries=3)
    vid = result.get("id")
    if not vid: raise RuntimeError("YouTube não retornou o ID do vídeo.")
    record_pub(cid, "youtube", "enviado", vid, "Upload concluído · " + privacy)
    return vid

def upload_facebook(cid, row, tid):
    import requests
    cfg = read_settings()
    page, token = cfg.get("meta_page_id"), cfg.get("meta_page_token")
    if not page or not token: raise ValueError("Informe ID da Página e token de Página do Facebook.")
    if not re.fullmatch(r"\d{5,30}", page): raise ValueError("ID da Página do Facebook inválido.")
    root = f"https://graph.facebook.com/v26.0/{page}/video_reels"
    auth = {"Authorization": "Bearer " + token}
    task_update(tid, "Facebook: criando sessão do Reel...", 50)
    start = requests.post(root, headers=auth, data={"upload_phase":"start"}, timeout=35)
    if start.status_code >= 400: raise RuntimeError("Meta iniciar Reel: " + start.text[:450])
    item = start.json()
    video_id, upload_url = str(item.get("video_id") or ""), item.get("upload_url") or ""
    if not video_id or not upload_url or urlparse(upload_url).hostname != "rupload.facebook.com":
        raise RuntimeError("A Meta não retornou uma URL de upload confiável.")
    size = Path(row["file"]).stat().st_size
    task_update(tid, "Facebook: transferindo o Reel...", 68)
    with open(row["file"], "rb") as source:
        upl = requests.post(upload_url, headers={
            "Authorization": "OAuth " + token, "offset": "0",
            "file_size": str(size), "Content-Type": "application/octet-stream"},
            data=source, timeout=480)
    if upl.status_code >= 400 or upl.json().get("success") is False:
        raise RuntimeError("Meta upload: " + upl.text[:450])
    task_update(tid, "Facebook: solicitando publicação...", 85)
    finish = requests.post(root, headers=auth, data={
        "upload_phase": "finish", "video_id": video_id, "video_state": "PUBLISHED",
        "title": row["title"][:200],
        "description": (row["title"] + "\n\n" + row["description"])[:2000]
    }, timeout=45)
    if finish.status_code >= 400 or finish.json().get("success") is False:
        raise RuntimeError("Meta finalizar Reel: " + finish.text[:450])
    # A Meta pode continuar processando após aceitar a publicação.
    record_pub(cid, "facebook", "processando", video_id,
               "Publicação aceita pela Meta; processamento externo em andamento.")
    return video_id

def job_export_live(tid, session_id, start, end, title):
    """Exporta segmento fechado da gravação local; NUNCA publica automaticamente."""
    ff = get_ffmpeg()
    if not ff: raise RuntimeError("FFmpeg indisponível.")
    title = clip_titles.short_title(title, 65) or "Corte da transmissão ao vivo"
    folder = DATA / ("job_" + tid)
    folder.mkdir(parents=True, exist_ok=True)
    task_update(tid, "Preparando segmentos gravados da live...", 12)
    segment = LIVE.prepare_export(session_id, start, end, folder)
    cid = secrets.token_hex(8)
    temporary = folder / ("live-" + cid + ".mp4")
    video_filter = "scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,setsar=1,fps=30,format=yuv420p"
    command = [ff, "-hide_banner", "-loglevel", "error", "-y",
               "-f", "concat", "-safe", "0", "-i", str(segment["file"]),
               "-ss", str(round(segment["offset"], 3)),
               "-t", str(round(segment["duration"], 3)),
               "-vf", video_filter, "-c:v", "libx264",
               "-preset", "veryfast", "-crf", "24",
               "-c:a", "aac", "-b:a", "160k", "-ar", "48000",
               "-movflags", "+faststart", str(temporary)]
    task_update(tid, "Renderizando o trecho ao vivo em formato vertical...", 40)
    result = subprocess.run(command, capture_output=True, text=True,
                            timeout=600, errors="replace")
    if result.returncode or not temporary.is_file() or temporary.stat().st_size < 2000:
        temporary.unlink(missing_ok=True)
        raise RuntimeError("Erro ao exportar gravação: " + result.stderr[-400:])
    task_update(tid, "Salvando o Short na biblioteca...", 88)
    with TASK_LOCK, DB_LOCK, connect() as db:
        filename = clip_titles.unique_clip_filename(title, OUTPUT, DATA / "lixeira")
        final = OUTPUT / filename
        if final.exists():
            raise RuntimeError("Já existe arquivo com esse nome; exportação bloqueada.")
        temporary.rename(final)
        try:
            db.execute("INSERT INTO clips VALUES (?,?,?,?,?,?,?,?,?,?)",
                       (cid, segment["source"], segment["origin_title"], title,
                        "Corte manual de transmissão ao vivo", str(final),
                        round(float(start), 2), round(segment["duration"], 2),
                        "Marcadores IN/OUT + FFmpeg (live)", now()))
            db.execute("INSERT INTO clip_models VALUES (?,?,?,?)",
                       (cid, "none", "Editor ao vivo (sem IA)", "seleção manual"))
            db.commit()
        except Exception:
            db.rollback()
            if final.exists():
                final.rename(temporary)
            raise
    task_update(tid, "Corte ao vivo exportado: " + filename, 100, "done")

def job_publish(tid, ids, platforms, privacy):
    if not ids: raise ValueError("Selecione pelo menos um corte.")
    if not platforms or any(p not in ("youtube", "facebook") for p in platforms):
        raise ValueError("Escolha YouTube e/ou Facebook.")
    if privacy not in ("public", "private", "unlisted"): raise ValueError("Privacidade inválida.")
    with connect() as db:
        rows = {r["id"]: dict(r) for r in db.execute(
            "SELECT * FROM clips WHERE id NOT IN (SELECT clip_id FROM deleted_clips) AND id IN (" +
            ",".join("?" for _ in ids) + ")", ids)}
    total, successes, fails = len(ids)*len(platforms), 0, []
    for cid in ids:
        if cid not in rows: continue
        row = rows[cid]
        if not Path(row["file"]).exists(): fails.append(f"{cid}: arquivo não existe"); continue
        for platform in platforms:
            with connect() as db:
                prev = db.execute("SELECT state FROM publications WHERE clip_id=? AND platform=?",
                                  (cid, platform)).fetchone()
            if prev and prev["state"] in ("enviado", "processando", "publicado"):
                successes += 1
                continue
            task_update(tid, f"{platform.title()}: {row['title'][:60]}", int(successes/max(1,total)*90))
            try:
                if platform == "youtube": upload_youtube(cid, row, tid, privacy)
                else: upload_facebook(cid, row, tid)
                successes += 1
            except Exception as exc:
                err = type(exc).__name__ + ": " + str(exc)[:350]
                print("UPLOAD ERROR", platform, err[:350], flush=True)
                record_pub(cid, platform, "erro", message=err)
                fails.append(f"{platform}/{row['title'][:30]}: {err[:160]}")
    if fails:
        task_update(tid, f"{successes}/{total} envios aceitos. Falhas: " + " | ".join(fails)[:480],
                    100, "error" if successes == 0 else "done")
    else: task_update(tid, f"{successes}/{total} envios concluídos/aceitos. Confira o processamento nas plataformas.",
                      100, "done")

def verify_facebook():
    import requests
    cfg = read_settings()
    if not cfg.get("meta_page_id") or not cfg.get("meta_page_token"):
        raise ValueError("Configure o token e ID da Página.")
    r = requests.get(f"https://graph.facebook.com/v26.0/{cfg['meta_page_id']}",
                     params={"fields": "id,name"}, headers={
                     "Authorization": "Bearer " + cfg["meta_page_token"]}, timeout=25)
    if r.status_code != 200: raise RuntimeError("Facebook: " + r.text[:360])
    return {"ok": True, "page": r.json().get("name")}

def dependency_status():
    try: import yt_dlp; ytdlp = True
    except ImportError: ytdlp = False
    return {"ffmpeg": bool(get_ffmpeg()), "ytdlp": ytdlp, "youtube_oauth": TOKEN_FILE.exists()}

class Handler(BaseHTTPRequestHandler):
    server_version = "CutShortPlus/1.0"
    def log_message(self, fmt, *args):
        print("%s %s" % (self.log_date_time_string(), fmt % args), flush=True)
    def send_json(self, data, code=200):
        blob = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(blob)))
        self.end_headers()
        self.wfile.write(blob)
    def send_error_json(self, exc, code=400):
        self.send_json({"error": str(exc)[:600]}, code)
    def require_write(self):
        if not secrets.compare_digest(self.headers.get("X-Cutshort-Token", ""), CSRF):
            raise PermissionError("Sessão inválida. Atualize a página.")
        origin = self.headers.get("Origin")
        if origin:
            u = urlparse(origin)
            if u.hostname not in ("127.0.0.1", "localhost") or u.port != 8765:
                raise PermissionError("Origem não autorizada.")
    def get_json(self):
        size = int(self.headers.get("Content-Length", "0"))
        if size <= 0 or size > 100000: raise ValueError("Solicitação inválida ou extensa demais.")
        return json.loads(self.rfile.read(size).decode("utf-8"))
    def do_GET(self):
        try:
            parsed = urlparse(self.path)
            path, query = parsed.path, parse_qs(parsed.query)
            if path in ("/", "/index.html"):
                data = (ROOT / "index.html").read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Frame-Options", "DENY")
                self.send_header("Content-Security-Policy", "default-src 'self' https://i.ytimg.com; img-src 'self' https://i.ytimg.com data:; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; connect-src 'self'; media-src 'self'; frame-src https://www.youtube-nocookie.com https://www.youtube.com; frame-ancestors 'none'")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            elif path in ("/favicon.ico", "/assets/cutshortplus.png"):
                # Rotas de assets estáticos explícitas, sem servir arquivos arbitrários.
                filename = "cutshortplus.ico" if path == "/favicon.ico" else "cutshortplus.png"
                media = (ROOT / "assets" / filename).read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "image/x-icon" if filename.endswith(".ico") else "image/png")
                self.send_header("Content-Length", str(len(media)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(media)
            elif path == "/api/bootstrap":
                self.send_json({"token": CSRF, "settings": public_settings(),
                                "dependencies": dependency_status()})
            elif path == "/api/status":
                with connect() as db:
                    tasks = [dict(r) for r in db.execute(
                        "SELECT * FROM tasks ORDER BY created DESC LIMIT 12")]
                self.send_json({"clips": get_clips(), "tasks": tasks,
                                "settings": public_settings(), "dependencies": dependency_status()})
            elif path == "/api/search":
                self.send_json({"videos": search_videos(
                    (query.get("q") or [""])[0],
                    (query.get("sort") or ["relevance"])[0],
                    (query.get("published") or ["any"])[0],
                    (query.get("duration") or ["any"])[0])})
            elif path == "/api/live/search":
                self.send_json({"videos": search_videos(
                    (query.get("q") or [""])[0], live=True)})
            elif path == "/api/live/recommended":
                self.send_json(recommended_lives(refresh=(query.get("refresh")==["1"])))
            elif path == "/api/live/status":
                self.send_json({"session": LIVE.status(), "sessions": LIVE.sessions()})
            elif path == "/api/clips/deleted":
                self.send_json(get_deleted_clips())
            elif path == "/api/favorites":
                self.send_json(favorite_models())
            elif path == "/api/inspect":
                self.send_json({"video": video_info((query.get("url") or [""])[0])})
            elif path.startswith("/trash-media/"):
                cid = path.rsplit("/", 1)[-1]
                if not re.fullmatch(r"[a-f0-9]{16}", cid):
                    raise ValueError("Identificador inválido.")
                with DB_LOCK, connect() as db:
                    row = db.execute("""SELECT d.clip_id, d.trash_file, c.title
                                        FROM deleted_clips d JOIN clips c ON c.id=d.clip_id
                                        WHERE d.clip_id=?""", (cid,)).fetchone()
                if not row:
                    raise FileNotFoundError("Corte não encontrado na lixeira.")
                self.send_media(checked_deleted_file(row))
            elif path.startswith("/media/") or path.startswith("/download/"):
                cid = path.split("/")[-1]
                if not re.fullmatch("[a-f0-9]{16}", cid): raise ValueError("Identificador inválido")
                with connect() as db:
                    row = db.execute("""SELECT file,origin_title FROM clips WHERE id=? AND
                                        id NOT IN (SELECT clip_id FROM deleted_clips)""",
                                     (cid,)).fetchone()
                if not row or not Path(row["file"]).is_file(): raise FileNotFoundError("Arquivo não encontrado")
                self.send_media(Path(row["file"]), attachment=path.startswith("/download/"))
                if path.startswith("/download/"):
                    record_topic_interest(row["origin_title"],"download")
            else: self.send_error_json("Rota não encontrada", 404)
        except BrokenPipeError: pass
        except Exception as exc: self.send_error_json(exc, 400)
    def send_media(self, f, attachment=False):
        size = f.stat().st_size
        rng = self.headers.get("Range", "")
        start, end = 0, size-1
        if rng:
            m = re.fullmatch(r"bytes=(\d+)-(\d*)", rng.strip())
            if not m: return self.send_error_json("Range inválido", 416)
            start = int(m.group(1))
            end = min(size-1, int(m.group(2))) if m.group(2) else size-1
        if start >= size or end < start: return self.send_error_json("Range fora do arquivo", 416)
        self.send_response(206 if rng else 200)
        self.send_header("Content-Type", "video/mp4")
        if attachment:
            self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + quote(f.name))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end-start+1))
        if rng: self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        with f.open("rb") as stream:
            stream.seek(start)
            remaining = end-start+1
            while remaining:
                chunk = stream.read(min(1024*1024, remaining))
                if not chunk: break
                self.wfile.write(chunk)
                remaining -= len(chunk)
    def do_POST(self):
        try:
            self.require_write()
            path = urlparse(self.path).path
            if path == "/api/settings":
                self.send_json({"settings": write_settings(self.get_json())})
            elif path == "/api/sendoka/sms":
                data = self.get_json()
                if data.get("confirm") != "ENVIAR SMS":
                    raise ValueError("Confirmacao obrigatoria.")
                cfg = read_settings()
                self.send_json(sendoka_plugin.send_sms(cfg.get("sendoka_api_key", ""),
                    cfg.get("sendoka_sender", ""), data.get("to", ""), data.get("body", "")))
            elif path == "/api/sendoka/verify/start":
                data = self.get_json()
                if data.get("confirm") != "ENVIAR OTP":
                    raise ValueError("Confirmacao obrigatoria.")
                cfg = read_settings()
                self.send_json(sendoka_plugin.start_verification(cfg.get("sendoka_api_key", ""),
                    cfg.get("sendoka_sender", ""), data.get("to", "")))
            elif path == "/api/sendoka/verify/check":
                data = self.get_json()
                self.send_json(sendoka_plugin.check_verification(read_settings().get("sendoka_api_key", ""),
                    data.get("id", ""), data.get("code", "")))
            elif path == "/api/clips/trash":
                self.send_json(trash_clips(self.get_json().get("ids")))
            elif path == "/api/clips/restore":
                self.send_json(restore_clips(self.get_json().get("ids")))
            elif path == "/api/clips/purge":
                request = self.get_json()
                self.send_json(permanently_delete_clips(request.get("ids"),
                                                       request.get("confirm")))
            elif path == "/api/favorites":
                request = self.get_json()
                self.send_json(update_favorite_model(
                    request.get("provider"), request.get("model"), request.get("favorite")))
            elif path == "/api/topic/selection":
                request=self.get_json()
                self.send_json(record_topic_interest(str(request.get("title") or "")[:160],"selection"))
            elif path == "/api/activities/clear":
                data=self.get_json()
                if data.get("confirm")!="LIMPAR ATIVIDADES":
                    raise ValueError("Confirme a limpeza do histórico de tarefas.")
                self.send_json(clear_finished_activities())
            elif path == "/api/openai/models":
                body = self.get_json()
                self.send_json(list_openai_models(body.get("api_key", "")))
            elif path == "/api/ai/models":
                body = self.get_json()
                self.send_json(list_provider_models(str(body.get("provider", "")),
                                                    body.get("api_key", "")))
            elif path == "/api/ai/test":
                body = self.get_json()
                self.send_json(test_provider_generation(str(body.get("provider", "")),
                    str(body.get("model", "")), body.get("api_key", "")))
            elif path == "/api/openai/test":
                body = self.get_json()
                self.send_json(test_openai_generation(str(body.get("model", "")), body.get("api_key", "")))
            elif path == "/api/live/start":
                data = self.get_json()
                self.send_json({"session": LIVE.start(youtube_url(data.get("url", "")))})
            elif path == "/api/live/stop":
                self.get_json()
                self.send_json({"session": LIVE.stop()})
            elif path == "/api/live/restore":
                data = self.get_json()
                self.send_json({"session": LIVE.restore(str(data.get("id", "")))})
            elif path == "/api/live/export":
                data = self.get_json()
                task = start_task("live_export", job_export_live,
                                  str(data.get("id", "")), data.get("start", 0),
                                  data.get("end", 0), str(data.get("title", ""))[:120])
                self.send_json({"task": task}, 202)
            elif path == "/api/import":
                self.import_video()
            elif path == "/api/create":
                data = self.get_json()
                source = str(data.get("source") or "").strip()
                if not source: raise ValueError("Cole o link ou selecione um arquivo.")
                autopub = data.get("autopublish") is True
                if autopub:
                    cfg = read_settings()
                    if not TOKEN_FILE.exists() or not cfg.get("meta_page_token") or not cfg.get("meta_page_id"):
                        raise ValueError("Para publicação automática, conecte YouTube e Facebook em Integrações.")
                provider = data.get("ai_provider") or read_settings().get("ai_provider", "openai")
                model = str(data.get("ai_model") or "")
                if provider not in (*AI_PROVIDERS.keys(), "none"):
                    raise ValueError("Provedor de IA inválido")
                if provider != "none":
                    key_field, model_field = AI_PROVIDERS[provider]
                    cfg = read_settings()
                    if not cfg.get(key_field): raise ValueError("Configure a chave de " + provider + " em Integrações.")
                    if not model: model = cfg.get(model_field, "")
                    if not model: raise ValueError("Escolha um modelo da " + provider + ".")
                    ai_providers.validate_model(model)
                turbo=data.get("turbo",False)
                if type(turbo) is not bool:
                    raise ValueError("Modo Turbo Short inválido.")
                task = start_task("cut", job_make_clips, source,
                                  data.get("count", 3), data.get("seconds", 45), autopub, provider, model, turbo)
                self.send_json({"task": task}, 202)
            elif path == "/api/publish":
                data = self.get_json()
                ids = list(dict.fromkeys(data.get("ids", [])))[:20]
                platforms = list(dict.fromkeys(data.get("platforms", [])))
                task = start_task("publish", job_publish, ids, platforms, data.get("privacy", "private"))
                self.send_json({"task": task}, 202)
            elif path == "/api/oauth/youtube":
                self.get_json()
                task = start_task("oauth", oauth_youtube)
                self.send_json({"task": task}, 202)
            elif path == "/api/test/facebook":
                self.get_json()
                self.send_json(verify_facebook())
            else: self.send_error_json("Rota não encontrada", 404)
        except Exception as exc: self.send_error_json(exc, 400)
    def import_video(self):
        rawname = unquote(self.headers.get("X-File-Name", "video.mp4"))
        name = Path(rawname.replace("\\", "/")).name
        if Path(name).suffix.lower() not in (".mp4", ".mkv", ".mov", ".webm"):
            raise ValueError("Envie um arquivo MP4, MKV, MOV ou WEBM.")
        size = int(self.headers.get("Content-Length", "0"))
        if size < 1024 or size > 2*1024*1024*1024:
            raise ValueError("Vídeo inválido ou maior que 2 GB.")
        dest = IMPORTS / (secrets.token_hex(7) + "_" + re.sub(r"[^a-zA-Z0-9._-]", "_", name)[:90])
        tmp = dest.with_suffix(dest.suffix + ".part")
        try:
            with open(tmp, "wb") as out:
                remaining = size
                while remaining:
                    chunk = self.rfile.read(min(1024*1024, remaining))
                    if not chunk: raise IOError("Transferência interrompida")
                    out.write(chunk)
                    remaining -= len(chunk)
            os.replace(tmp, dest)
        finally: tmp.unlink(missing_ok=True)
        self.send_json({"source": str(dest), "name": name}, 201)

def main():
    print("CUTSHORTPLUS_READY http://127.0.0.1:8765", flush=True)
    srv = ThreadingHTTPServer(("127.0.0.1", 8765), Handler)
    srv.daemon_threads = True
    try: srv.serve_forever(poll_interval=.25)
    except KeyboardInterrupt: pass
    finally:
        LIVE.close()
        srv.server_close()

if __name__ == "__main__":
    main()
