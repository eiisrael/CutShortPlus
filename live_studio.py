"""Estúdio de lives: gravação local limitada e cortes sobre segmentos completos."""
from __future__ import annotations
import csv
import json
from pathlib import Path
import re
import secrets
import subprocess
import threading
import time

LIVE_LIMIT_SECONDS = 1800
ID_PATTERN = re.compile(r"[a-f0-9]{12}\Z")


class LiveRecorder:
    def __init__(self, data_dir, get_ffmpeg, get_ydl):
        self.root = Path(data_dir) / "live_sessions"
        self.get_ffmpeg = get_ffmpeg
        self.get_ydl = get_ydl
        self.lock = threading.RLock()
        self.current = None

    def _manifest(self, session):
        return self.root / session["id"] / "session.json"

    def _save(self, session):
        path = self._manifest(session)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({k: session[k] for k in ("id", "video_id", "title", "url", "created", "state")}, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

    def _segments(self, session):
        folder = self.root / session["id"]
        csv_file = folder / "segments.csv"
        rows = []
        try:
            with csv_file.open(encoding="utf-8", newline="") as f:
                for row in csv.reader(f):
                    if len(row) != 3:
                        continue
                    name = Path(row[0].replace(chr(92), '/')).name
                    if not re.fullmatch(r"segment_\d{5}\.ts", name):
                        continue
                    path = folder / name
                    if not path.is_file() or path.stat().st_size < 1024:
                        continue
                    try:
                        start, end = float(row[1]), float(row[2])
                    except ValueError:
                        continue
                    if start < 0 or end <= start:
                        continue
                    rows.append((path, start, end))
        except (OSError, csv.Error):
            pass
        rows.sort(key=lambda item: item[1])
        return rows

    def status(self):
        with self.lock:
            session = self.current
            if not session:
                return {"state": "idle", "recorded": 0, "id": "", "title": "", "segments": 0}
            proc = session.get("proc")
            if proc and proc.poll() is not None and session["state"] == "recording":
                session["state"] = "stopped" if proc.returncode == 0 else "error"
                self._save(session)
                stream = session.pop("log_handle", None)
                if stream:
                    stream.close()
            if proc and proc.poll() is None and session["state"] == "recording":
                age = time.monotonic() - session["started_monotonic"]
                if age > LIVE_LIMIT_SECONDS + 45:
                    proc.terminate()
            rows = self._segments(session)
            recorded = max(0.0, rows[-1][2] - rows[0][1]) if rows else 0.0
            return {
                "state": session["state"], "id": session["id"], "title": session["title"],
                "video_id": session["video_id"], "recorded": round(recorded, 1),
                "segments": len(rows), "max_seconds": LIVE_LIMIT_SECONDS,
                "message": "Somente segmentos finalizados ficam disponíveis para cortes."
            }

    def start(self, url):
        with self.lock:
            if self.current and self.status()["state"] == "recording":
                raise ValueError("Já existe uma gravação ativa. Finalize-a antes de iniciar outra.")
            ff = self.get_ffmpeg()
            if not ff:
                raise RuntimeError("FFmpeg indisponível.")
            ydl_mod = self.get_ydl()
            options = {"quiet": True, "no_warnings": True, "skip_download": True,
                       "noplaylist": True, "socket_timeout": 25,
                       "format": "bestvideo[height<=720][vcodec^=avc1]+bestaudio/bestvideo[height<=720]+bestaudio/bestvideo+bestaudio/best",
                       "extractor_args": {"youtube": {"lang": ["pt"]}}}
            with ydl_mod.YoutubeDL(options) as dl:
                info = dl.extract_info(url, download=False)
            if not info or (info.get("live_status") != "is_live" and info.get("is_live") is not True):
                raise ValueError("Este vídeo não é uma transmissão ao vivo ativa.")
            formats = info.get("requested_formats") or [info]
            video_stream = next((f for f in formats if f.get("vcodec") not in ("none", None)), None)
            audio_stream = next((f for f in formats if f.get("vcodec") == "none"), None)
            if not video_stream:
                raise RuntimeError("A transmissão não fornece fluxo de vídeo compatível.")
            video_url = str(video_stream.get("url") or "")
            audio_url = str(audio_stream.get("url") or "") if audio_stream else ""
            if not video_url.startswith("https://") or (audio_stream and not audio_url.startswith("https://")):
                raise RuntimeError("Não foi possível obter os fluxos HTTPS da live.")
            session_id = secrets.token_hex(6)
            folder = self.root / session_id
            folder.mkdir(parents=True, exist_ok=False)
            video_id = str(info.get("id") or "")
            if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
                raise RuntimeError("ID do vídeo inválido.")
            session = {
                "id": session_id, "video_id": video_id, "url": url,
                "title": str(info.get("title") or "Transmissão ao vivo")[:150],
                "created": time.strftime("%Y-%m-%d %H:%M:%S"), "state": "recording",
                "started_monotonic": time.monotonic()
            }
            self._save(session)
            logfile = (folder / "ffmpeg.log").open("ab")
            command = [ff, "-hide_banner", "-loglevel", "warning", "-nostdin", "-y"]
            for entry in ([video_stream, audio_stream] if audio_stream else [video_stream]):
                headers = entry.get("http_headers") or {}
                agent = headers.get("User-Agent")
                if agent:
                    command += ["-user_agent", agent]
                command += ["-i", str(entry["url"])]
            command += ["-t", str(LIVE_LIMIT_SECONDS), "-map", "0:v:0"]
            if audio_stream:
                command += ["-map", "1:a:0"]
            else:
                command += ["-map", "0:a:0?"]
            command += ["-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
                        "-f", "segment", "-segment_format", "mpegts",
                        "-segment_time", "4", "-segment_list_size", "0",
                        "-segment_list_type", "csv", "-segment_list",
                        str(folder / "segments.csv"),
                        "-reset_timestamps", "1", str(folder / "segment_%05d.ts")]
            try:
                proc = subprocess.Popen(
                    command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=logfile, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            except Exception:
                logfile.close()
                session["state"] = "error"
                self._save(session)
                raise
            session["proc"] = proc
            session["log_handle"] = logfile
            self.current = session
            return self.status()

    def stop(self):
        with self.lock:
            if not self.current:
                raise ValueError("Nenhuma sessão selecionada.")
            session = self.current
            proc = session.get("proc")
            if proc and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=7)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
            logfile = session.pop("log_handle", None)
            if logfile:
                logfile.close()
            session["state"] = "stopped"
            self._save(session)
            return self.status()

    def sessions(self):
        result = []
        if self.root.is_dir():
            for path in sorted(self.root.glob("*/session.json"), reverse=True)[:30]:
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    if ID_PATTERN.fullmatch(data.get("id", "")):
                        result.append({k: data.get(k, "") for k in ("id", "title", "created", "state", "video_id")})
                except (OSError, ValueError):
                    continue
        return result

    def restore(self, session_id):
        if not ID_PATTERN.fullmatch(str(session_id)):
            raise ValueError("Sessão inválida.")
        with self.lock:
            if self.current and self.status()["state"] == "recording":
                raise ValueError("Finalize a gravação ativa para abrir outra sessão.")
            manifest = self.root / session_id / "session.json"
            if not manifest.is_file():
                raise ValueError("Sessão arquivada não encontrada.")
            data = json.loads(manifest.read_text(encoding="utf-8"))
            if data.get("id") != session_id:
                raise ValueError("Sessão inválida.")
            data["state"] = "stopped"
            self.current = data
            self._save(data)
            return self.status()

    def prepare_export(self, session_id, start, end, destination_folder):
        with self.lock:
            if not self.current or self.current["id"] != session_id:
                raise ValueError("Selecione a sessão correspondente antes de exportar.")
            rows = self._segments(self.current)
            if not rows:
                raise ValueError("Aguarde a gravação concluir alguns segmentos.")
            base = rows[0][1]
            recorded = rows[-1][2] - base
            start, end = float(start), float(end)
            if not (start >= 0 and end > start and end - start <= 180 and end <= recorded + .001):
                raise ValueError(f"Selecione um trecho de até 180 s dentro dos {recorded:.1f} s já gravados.")
            subset = [(p, a, b) for p, a, b in rows if b > base + start and a < base + end]
            if not subset:
                raise ValueError("Não existem segmentos suficientes para esse trecho.")
            offset = max(0, start - (subset[0][1] - base))
            list_file = Path(destination_folder) / "live_concat.txt"
            # O ffmpeg concat requer caminhos POSIX e aspas simples escapadas.
            paths = []
            for path, _, _ in subset:
                clean = path.resolve().as_posix().replace("'", "'\\''")
                paths.append("file '" + clean + "'")
            list_file.write_text("ffconcat version 1.0\n" + "\n".join(paths) + "\n", encoding="utf-8")
            return {"file": list_file, "offset": offset, "duration": end-start,
                    "source": self.current["url"], "origin_title": self.current["title"]}

    def close(self):
        try:
            with self.lock:
                if self.current and self.current.get("proc") and self.current["proc"].poll() is None:
                    self.stop()
        except Exception:
            pass
