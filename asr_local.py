# -*- coding: utf-8 -*-
"""Transcrição local opcional (Whisper tiny), somente para cortes sem legendas."""
from pathlib import Path
import threading
import subprocess
import shutil

_model = None
_lock = threading.Lock()
_disabled_reason = None

def transcribe_clip(file: Path, models_dir: Path):
    global _model, _disabled_reason
    with _lock:
        if _disabled_reason:
            return [], _disabled_reason
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            _disabled_reason = "Transcrição local não instalada."
            return [], _disabled_reason
        try:
            if _model is None:
                models_dir.mkdir(parents=True, exist_ok=True)
                try:
                    _model = WhisperModel(
                        "tiny", device="cpu", compute_type="int8",
                        cpu_threads=4, num_workers=1,
                        download_root=str(models_dir))
                except Exception:
                    _disabled_reason = "Modelo local de transcrição indisponível."
                    return [], _disabled_reason
            # Transcrição de áudio PCM em memória: contorna incompatibilidade
            # PyAV metadata_errors encontrada no Python 3.14 no Windows.
            import numpy as np
            import imageio_ffmpeg
            ff = shutil.which("ffmpeg") or imageio_ffmpeg.get_ffmpeg_exe()
            decoded = subprocess.run(
                [ff, "-hide_banner", "-loglevel", "error", "-i", str(file),
                 "-vn", "-ac", "1", "-ar", "16000", "-f", "s16le",
                 "-acodec", "pcm_s16le", "-"],
                capture_output=True, timeout=60, check=True)
            if len(decoded.stdout) < 32000:
                return [], "Áudio insuficiente para transcrição."
            waveform = np.frombuffer(decoded.stdout, dtype=np.int16).astype(np.float32) / 32768.0
            chunks, info = _model.transcribe(
                waveform, beam_size=1, vad_filter=True,
                condition_on_previous_text=False,
                no_speech_threshold=0.5,
                temperature=0.0)
            segments=[]
            for seg in chunks:
                value=" ".join(str(seg.text).split()).strip()
                if value:
                    segments.append((float(seg.start),value))
            if sum(len(s.split()) for _,s in segments)<4:
                return [], "Nenhuma fala inteligível detectada no áudio."
            return segments, ""
        except Exception as exc:
            # Nunca registrar arquivos internos, detalhes de credenciais ou texto do áudio.
            reason="Falha na transcrição local: "+type(exc).__name__
            return [], reason
