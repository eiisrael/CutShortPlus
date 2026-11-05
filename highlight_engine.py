# -*- coding: utf-8 -*-
"""Seleção auditável de Shorts: fala, capítulos, picos reais da barra do YouTube e movimento.
Picos de replay são sinais relativos, não números absolutos de visualizações.
Nunca sintetizar dados de espectadores que o YouTube não forneceu.
"""
from __future__ import annotations
from pathlib import Path
from urllib.parse import urlparse, parse_qs
import json
import math
import re
import statistics
import subprocess

VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}\Z")
EMPHASIS = ("importante", "atenção", "revel", "confirm", "segredo", "problema",
            "por que", "porquê", "verdade", "novo", "final", "precisa", "erro",
            "descob", "incrível", "exclusivo", "mudou", "anunci", "agora",
            "why", "how", "what", "news", "update", "official")
STOP = {"como","para","por","que","uma","com","das","dos","está","isso","aqui",
        "também","quando","onde","muito","mais","mesmo","have","this","that",
        "from","about","there","they","the","and","you","your"}

def youtube_video_id(url):
    u=urlparse(str(url))
    if u.scheme not in ("http","https"):return ""
    host=(u.hostname or "").lower()
    if host in ("youtu.be","www.youtu.be"):
        ident=u.path.strip("/").split("/")[0]
    elif host in ("youtube.com","www.youtube.com","m.youtube.com","music.youtube.com"):
        ident=(parse_qs(u.query).get("v") or [""])[0]
    else:return ""
    return ident if VIDEO_ID.fullmatch(ident) else ""


def heat_points_from_html(html):
    """Lê apenas heatMarkerRenderer fornecidos no HTML da página do vídeo."""
    matches=[]
    for m in re.finditer(r'"heatMarkerRenderer"\s*:\s*(\{[^{}]{0,700}\})',html):
        try:
            item=json.loads(m.group(1))
            start=float(item["timeRangeStartMillis"])/1000
            duration=float(item["markerDurationMillis"])/1000
            intensity=float(item["heatMarkerIntensityScoreNormalized"])
            if all(map(math.isfinite,(start,duration,intensity))) and start>=0 and duration>0 and 0<=intensity<=1:
                matches.append({"at":start+duration/2,"score":intensity})
        except (ValueError,TypeError,KeyError,OverflowError):
            continue
    # Markers repetidos podem ocorrer dentro de vários objetos do YouTube.
    return list({round(x["at"],2):x for x in matches}.values())


def public_youtube_heatmap(url):
    """Consulta apenas a watch page HTTPS fixa do YouTube. Ausência => lista vazia."""
    vid=youtube_video_id(url)
    if not vid:return []
    import requests
    try:
        response=requests.get("https://www.youtube.com/watch?v="+vid,timeout=13,
            headers={"Accept-Language":"pt-BR,pt;q=0.9",
                     "User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0 Safari/537.36"})
        if not response.ok:return []
        return heat_points_from_html(response.text)
    except Exception:
        return []


def normalized_info_heatmap(info):
    """Caso um extractor forneça o campo explicitamente, converta à mesma estrutura."""
    result=[]
    for point in (info or {}).get("heatmap") or []:
        try:
            if isinstance(point,dict):
                at=float(point.get("start_time",point.get("at",-1)))
                raw=float(point.get("value",point.get("score",-1)))
            elif isinstance(point,(tuple,list)) and len(point)>=2:
                at,raw=float(point[0]),float(point[1])
            else:continue
            if math.isfinite(at) and math.isfinite(raw) and at>=0 and 0<=raw<=1:
                result.append({"at":at,"score":raw})
        except (TypeError,ValueError):continue
    return result


MAX_TURBO_SHORTS = 60

def turbo_plan(length, maximum):
    """Maior cobertura não sobreposta usando a duração configurada, até 60 por operação."""
    length=float(length)
    maximum=float(maximum)
    if not (math.isfinite(length) and math.isfinite(maximum) and length>=12 and 12<=maximum<=60):
        raise ValueError("Duração de origem ou limite de corte inválidos para Turbo Short.")
    full=int(length//maximum)
    remainder=length-full*maximum
    target=max(1,min(MAX_TURBO_SHORTS,full+(1 if remainder>=12 else 0)))
    # Reserva um segundo entre cortes e só reduz o tempo se necessário.
    duration=min(maximum,(length-max(0,target-1)*1.0)/target)
    return max(12.0,round(duration,2)),target


def desired_duration(length,count,maximum,turbo=False):
    length=float(length)
    maximum=min(60,max(12,float(maximum)))
    if length<12:raise ValueError("O vídeo tem menos de 12 segundos, insuficiente para um Short contextual.")
    if turbo:
        return turbo_plan(length,maximum)
    count=min(10,max(1,int(count)))
    target=min(count,max(1,int((length+2)/14)))
    capacity_duration=(length-max(0,target-1)*2)/target
    duration=min(maximum,capacity_duration*.90 if maximum>=capacity_duration else maximum)
    return max(12,min(maximum,duration)),target


def _window_text(segments,start,stop):
    parts=[]
    for at,text in segments:
        if at>=start-0.3 and at<stop:
            parts.append(str(text))
    return " ".join(parts).strip()


def candidate_windows(segments,length,count,maximum,heatmap=(),chapters=(),suggestions=(),turbo=False):
    duration,limit=desired_duration(length,count,maximum,turbo=turbo)
    latest=max(0,length-duration)
    candidates={}
    def add(start,origin,heat=0):
        start=round(min(latest,max(0,float(start))),2)
        key=round(start*4)/4 if turbo else round(start/1.5)*1.5
        actual=candidates.get(key)
        if actual is None or heat>actual["heat"]:
            candidates[key]={"start":start,"duration":duration,"source":origin,"heat":float(heat)}
    if segments:
        for at,phrase in segments:
            if not isinstance(phrase,str) or not phrase.strip():continue
            if not math.isfinite(float(at)):continue
            add(float(at)-1.5,"transcricao")
    for suggestion in suggestions or []:
        try:
            at=float(suggestion.get("start",-1))
            if 0<=at<length:add(at,"ia")
        except (ValueError,TypeError):continue
    for chapter in chapters or []:
        try:
            at=float(chapter.get("start_time",-1))
            if 0<=at<length:add(at,"capitulo")
        except (ValueError,TypeError):continue
    for point in heatmap or []:
        try:
            at=float(point["at"]);score=float(point["score"])
            if 0<=at<length and 0<=score<=1:
                add(at-duration*.42,"mais_reproduzidos",score)
        except (KeyError,TypeError,ValueError):continue
    # Quanto menor o vídeo, mais útil dividir em janelas para cobrir assuntos distintos,
    # mas só devem ser escolhidas as que passam nos filtros de conteúdo e movimento.
    # Garante candidatos por faixas temporais. Sem transcrição, movimentos reais
    # podem sinalizar um destaque visual, mas não fingimos tema compreendido.
    for i in range(limit):
        anchor=(i*(length/limit))
        if turbo:add(i*(duration+1),"turbo_slot")
        else:add(i*(duration+2),"grade_consecutiva")
        add(anchor,"amostra_visual")
        add(anchor+max(0,length/limit-duration)*.5,"amostra_visual")
        if turbo and limit<=30:
            add(anchor+max(0,length/limit-duration)*.95,"amostra_visual")
    ranked=[]
    for p in candidates.values():
        start,end=p["start"],p["start"]+duration
        speech=_window_text(segments,start,end)
        words=re.findall(r"\b[\wÀ-ÿ]+\b",speech.lower())
        unique=set(w for w in words if len(w)>3 and w not in STOP)
        density=len(words)/(max(duration,1))
        meaningful=len(words)>=max(9,int(duration*.48)) and len(unique)>=5
        has_chapter=p["source"]=="capitulo"
        from_ai=p["source"]=="ia"
        peak=p["heat"]
        if heatmap:
            nearby=[h["score"] for h in heatmap if abs(h["at"]-(start+duration/2))<=duration/2]
            if nearby:peak=max(peak,max(nearby))
        # Candidatos de análise visual sem fala serão avaliados pelo FFmpeg.
        if not meaningful and not has_chapter and peak<.80 and p["source"]!="amostra_visual":
            continue
        score=(min(25,len(unique))*1.1 + min(15,density*12) +
              8*sum(w in speech.lower() for w in EMPHASIS) +
              12*int("?" in speech) + 7*int("!" in speech) +
              35*peak + 8*int(has_chapter) + 8*int(from_ai and meaningful))
        if not speech and peak>=.8:score+=8
        if meaningful and len(words)>=12:score+=6
        # Evita abertura genérica e longos intervalos silenciosos.
        ranked.append({**p,"score":score,"speech":speech[:420],"heat":peak,
                       "meaningful":meaningful})
    return sorted(ranked,key=lambda x:(-x["score"],x["start"])),limit


def visual_motion_score(ffmpeg,filename,start,duration,timeout=30):
    """Diferença média entre quadros sucessivos. 0 significa imagem praticamente fixa."""
    cmd=[ffmpeg,"-hide_banner","-loglevel","error",
         "-ss",str(round(start,3)),"-i",str(filename),"-t",str(round(duration,3)),
         "-an","-vf","fps=1/2,scale=96:54,format=gray",
         "-f","rawvideo","-pix_fmt","gray","-"]
    try:
        p=subprocess.run(cmd,capture_output=True,timeout=timeout,check=False)
        if p.returncode!=0:return None
        size=96*54
        frames=[p.stdout[i:i+size] for i in range(0,len(p.stdout)-size+1,size)]
        if len(frames)<3:return None
        # usa amostra de pixels alternados para minimizar custo CPU
        diffs=[]
        for a,b in zip(frames,frames[1:]):
            da=a[::8];db=b[::8]
            diffs.append(sum(abs(i-j) for i,j in zip(da,db))/len(da))
        changes=sum(x>=2.4 for x in diffs)/len(diffs)
        return {"motion":round(statistics.mean(diffs),3),
                "moving_fraction":round(changes,3)}
    except (OSError,subprocess.TimeoutExpired,ZeroDivisionError):
        return None


def best_vertical_crop(ffmpeg, filename, start, duration, timeout=35):
    """Escolhe recorte 9:16 pela movimentação lateral em amostra pequena.

    Uma única decodificação compara esquerda, centro e direita; não altera a
    fonte e não identifica pessoas. Regiões estáticas perdem prioridade.
    """
    positions={"left":0,"center":110,"right":219}
    width,height,window=320,180,101
    vf=("fps=1/2,scale=320:180:force_original_aspect_ratio=decrease,"
        "pad=320:180:(ow-iw)/2:(oh-ih)/2,format=gray")
    cmd=[ffmpeg,"-hide_banner","-loglevel","error",
         "-ss",str(round(float(start),3)),"-i",str(filename),
         "-t",str(round(float(duration),3)),"-an","-vf",vf,
         "-f","rawvideo","-pix_fmt","gray","-"]
    try:
        run=subprocess.run(cmd,capture_output=True,timeout=timeout,check=False)
        size=width*height
        if run.returncode or len(run.stdout)<size*3:
            return {"position":"center","motion":0.0,"samples":0}
        frames=[run.stdout[i:i+size] for i in range(0,len(run.stdout)-size+1,size)]
        ranked=[]
        for pos,x0 in positions.items():
            diffs=[]
            for prev,curr in zip(frames,frames[1:]):
                total=count=0
                for y in range(0,height,6):
                    for x in range(x0,x0+window,4):
                        idx=y*width+x
                        total+=abs(prev[idx]-curr[idx])
                        count+=1
                diffs.append(total/max(1,count))
            motion=statistics.mean(diffs) if diffs else 0
            fraction=sum(x>=2.4 for x in diffs)/len(diffs) if diffs else 0
            # O centro vence empates, evitando deslocamentos arbitrários.
            rank=motion+4*fraction+(0.25 if pos=="center" else 0)
            ranked.append((rank,pos,motion,fraction))
        ranked.sort(reverse=True)
        _,pos,motion,fraction=ranked[0]
        return {"position":pos,"motion":round(motion,3),
                "moving_fraction":round(fraction,3),"samples":len(frames)}
    except (OSError,subprocess.TimeoutExpired,OverflowError):
        return {"position":"center","motion":0.0,"samples":0}


def classify_moment(visual, item, relaxed=False):
    """Preserva prioridade visual, aceita locução real com movimento leve.
    Frame completamente parado nunca vira "cena dinâmica" artificialmente.
    """
    if not visual:
        return ""
    motion=visual["motion"]
    fraction=visual["moving_fraction"]
    if motion>=2.4 and fraction>=.34:
        return "cena_dinamica"
    if item.get("meaningful") and motion>=.60 and (fraction>=.05 or relaxed):
        return "fala_contextual"
    if motion>=1.2 and fraction>=.20:
        return "movimento_moderado"
    return ""


def choose_moments(ffmpeg,source,segments,length,count,maximum,heatmap=(),chapters=(),suggestions=(),min_motion=2.4,progress=None,turbo=False):
    """Seleciona janelas distintas, preferindo movimento e depois fala contextual."""
    ranked,target=candidate_windows(segments,length,count,maximum,heatmap,chapters,suggestions,turbo=turbo)
    accepted=[]
    checked=0
    max_checks=min(180,max(32,target*7))
    motion_cache={}
    def try_add(item):
        nonlocal checked
        if checked>=max_checks:return False
        start,dur=item["start"],item["duration"]
        gap=1 if turbo else 2
        if any(start<p["start"]+p["duration"]+gap and
               p["start"]<start+dur+gap for p in accepted):
            return False
        checked+=1
        if progress and (checked==1 or checked%5==0):
            progress(checked,max_checks)
        key=round(start,1)
        visual=motion_cache.get(key)
        if visual is None:
            visual=visual_motion_score(ffmpeg,source,start,dur)
            motion_cache[key]=visual
        quality=classify_moment(visual,item,relaxed=turbo)
        if not quality:
            return False
        accepted.append({**item,"visual":visual,"quality":quality})
        return True
    # Primeiro busca o melhor candidato contextual em cada faixa do vídeo:
    # isso evita vários cortes do mesmo minuto e aumenta diversidade de temas.
    if target>1:
        bin_width=length/target
        for slot in range(target):
            options=[x for x in ranked
                     if slot*bin_width <= x["start"]+x["duration"]/2 < (slot+1)*bin_width]
            for item in options:
                if try_add(item):break
    # Completa vagas com os melhores picos que sobraram, sem repetições.
    for item in ranked:
        if len(accepted)>=target or checked>=max_checks:break
        try_add(item)
    if len(accepted)<target and target>1 and ranked:
        # Reorganiza janelas quando o guloso escolheu um pico temporal
        # que inviabiliza intervalos independentes apesar de haver contexto.
        planned=[]
        slot_duration=ranked[0]["duration"]
        for slot in range(target):
            gap=1 if turbo else 2
            wanted=slot*(slot_duration+gap)
            options=sorted((item for item in ranked
                            if abs(item["start"]-wanted)<=5),
                           key=lambda it:(abs(it["start"]-wanted),-it["score"]))
            for item in options:
                at,dur=item["start"],item["duration"]
                if any(at<prior["start"]+prior["duration"]+gap and
                       prior["start"]<at+dur+gap for prior in planned):
                    continue
                key=round(at,1)
                visual=motion_cache.get(key)
                if visual is None:
                    visual=visual_motion_score(ffmpeg,source,at,dur)
                    motion_cache[key]=visual
                quality=classify_moment(visual,item,relaxed=turbo)
                if quality:
                    planned.append({**item,"visual":visual,"quality":quality})
                    break
        if len(planned)>len(accepted):
            accepted=planned
    accepted.sort(key=lambda p:p["start"])
    # Turbo favorece preenchimento sequencial para não desperdiçar bons assuntos
    # entre slots, sem repetir ou sobrepor intervalos já escolhidos.
    return accepted,{"requested":int(count),"capacity":target,
                     "candidates":len(ranked),"checked":checked,"turbo":bool(turbo),
                     "low_motion":sum(x["quality"]=="fala_contextual" for x in accepted),
                     "heatmap_available":bool(heatmap),
                     "transcript_available":bool(segments)}
