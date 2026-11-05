# -*- coding: utf-8 -*-
"""Títulos curtos, ancorados nas falas/legendas do trecho, e nomes MP4 seguros."""
import re
import unicodedata

STOP_PREFIX = re.compile(
    r"^(?:é que|porque|então|mas|assim|tipo assim|sabe|olha|gente|bom|bem|"
    r"né|ah|hum|é|e|aí|eu acho que|você sabe|vocês sabem|"
    r"certo|okay|ok|ou seja|na verdade|basicamente)\b[\s,:;-]*", re.I)
WINDOWS_FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
REPEATED_SPACES = re.compile(r"\s+")
RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{x}" for x in range(1,10)),
            *(f"LPT{x}" for x in range(1,10))}
TRAILING_GENERIC = re.compile(r"\s*(?:[|•—–-]\s*)?(?:parte|part|corte|short|trecho)\s*\d+\s*$",re.I)


def tidy(text):
    value = REPEATED_SPACES.sub(" ",re.sub(r"<[^>]*>"," ",str(text or ""))).strip()
    value = value.strip(" \t\n\r.,;|!?:_#—–-")
    while True:
        clean = STOP_PREFIX.sub("", value).strip(" \t\n\r.,;|!?:_#—–-")
        if clean == value or not clean: break
        value=clean
    return value


def short_title(text, max_chars=58):
    raw = tidy(text).strip(" \t\n\r\"'“”«»")
    raw = TRAILING_GENERIC.sub("",raw).strip(" \t\n\r.,;|!?:_#—–-")
    if not raw: return ""
    # Não truncar no meio de uma palavra; manter nomes próprios e acentos.
    if len(raw) > max_chars:
        before = raw[:max_chars+1]
        words = before.rsplit(" ",1)
        raw = words[0] if len(words)>1 and len(words[0])>=17 else raw[:max_chars].rstrip()
    return raw[:1].upper()+raw[1:] if raw else ""


def subtitles_for_window(segments,start,duration):
    end=start+duration
    snippets=[]
    seen=set()
    for at,phrase in segments:
        if start-1 <= at <= end+0.2:
            line=tidy(phrase)
            if not line: continue
            marker=re.sub(r"\W+","",line.casefold())
            if marker in seen: continue
            seen.add(marker)
            snippets.append((float(at),line))
    return snippets


def relevant_title(segments,start,duration,source_title,chapter_title="",suggested="",
                   index=1,has_ai=False):
    """Nunca inventar assunto: preferir subtítulo real do trecho, capítulo e depois vídeo."""
    window=subtitles_for_window(segments,start,duration) if segments else []
    context=" ".join(v for _,v in window).casefold()
    ai=short_title(suggested)
    # Título sugerido pela IA só é usado quando há texto do trecho.
    if ai and window and has_ai:
        return ai
    if window:
        options=[]
        for at,line in window:
            parts=re.split(r"(?<=[.!?])\s+|[;]\s+",line)
            for part in parts:
                candidate=short_title(part)
                words=re.findall(r"[^\W_]+",candidate,re.U)
                if len(words)<4: continue
                # Preferir fala com ideia completa, pergunta ou frase de impacto.
                score=(3 if "?" in part else 0)+(2 if "!" in part else 0)
                score+=min(len(words),11)/4
                if any(x in candidate.casefold() for x in
                       ("como ", "por que", "porque", "o segredo", "a verdade",
                        "a diferença", "importante", "cuidado", "aprenda", "descubra")):
                    score+=2
                if len(candidate)>=28: score+=1
                if part[:1].islower(): score-=0.5
                options.append((score,-abs(at-(start+duration/3)),candidate))
        if options:
            return max(options)[2]
        joined=short_title(" ".join(line for _,line in window)[:200])
        if joined:return joined
    if chapter_title:
        chapter=short_title(chapter_title)
        if chapter:return chapter
    original=short_title(source_title)
    if original:
        return original
    return f"Corte {index:02d} — assunto não identificado"


def filename_stem(title):
    base=WINDOWS_FORBIDDEN.sub("",short_title(title,max_chars=65))
    base=re.sub(r"\\s+"," ",base).rstrip(" .")
    if not base: base="Corte"
    if base.upper() in RESERVED: base="Corte "+base
    return base


def clip_filename(title,cid=None):
    # O ID hexadecimal identifica o registro e NÃO faz parte do nome do MP4.
    if cid is not None and not re.fullmatch(r"[a-f0-9]{16}",str(cid)):
        raise ValueError("Identificador de corte inválido.")
    return filename_stem(title)+".mp4"


def unique_clip_filename(title,*directories,reserved=()):
    """Mantém nome limpo e adiciona (2), (3)... somente quando há colisão."""
    base=filename_stem(title)
    existing={str(item).casefold() for item in reserved}
    for folder in directories:
        if folder.exists():
            existing.update(p.name.casefold() for p in folder.iterdir() if p.is_file())
    for n in range(1,10001):
        name=(base if n==1 else f"{base} ({n})")+".mp4"
        if name.casefold() not in existing:
            return name
    raise RuntimeError("Muitos arquivos com o mesmo título.")


def managed_filename(name,cid,title=None):
    if not re.fullmatch(r"[a-f0-9]{16}",str(cid)): return False
    if name==cid+".mp4": return True # legado
    if name.endswith("--"+cid+".mp4"):
        text=name[:-(len(cid)+6)]
        return bool(text) and len(text)<=80 and text==WINDOWS_FORBIDDEN.sub("",text) and not text.endswith((" ","."))
    if title is None:
        return False
    base=filename_stem(title)
    if name==base+".mp4": return True
    match=re.fullmatch(re.escape(base)+r" \(([2-9][0-9]*)\)\.mp4",name)
    return bool(match)

def chapter_at(chapters,start):
    for chapter in chapters or []:
        try:
            at=float(chapter.get("start_time",0))
            end=float(chapter.get("end_time",float("inf")))
            if at <= start < end:
                return str(chapter.get("title") or "")
        except (TypeError,ValueError,OverflowError):continue
    return ""
