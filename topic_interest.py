# -*- coding: utf-8 -*-
"""Assuntos locais usados para sugerir lives relevantes (sem histórico do navegador externo)."""
import re
import unicodedata

TOPICS = (
    (r"\b(?:gta[\s\-]*(?:6|vi)|grand theft auto[\s\-]*(?:6|vi|six))\b", "GTA 6"),
    (r"\b(?:gta[\s\-]*(?:5|v)|grand theft auto[\s\-]*(?:5|v))\b", "GTA 5"),
    (r"\bminecraft\b", "Minecraft"),
    (r"\bfortnite\b", "Fortnite"),
    (r"\broblox\b", "Roblox"),
    (r"\bvalorant\b", "Valorant"),
    (r"\b(?:counter[\s\-]*strike|cs[\s\-]*2)\b", "Counter-Strike 2"),
    (r"\b(?:league of legends|lol)\b", "League of Legends"),
    (r"\b(?:free[\s\-]*fire)\b", "Free Fire"),
    (r"\b(?:call of duty|warzone)\b", "Call of Duty"),
    (r"\b(?:futebol|flamengo|palmeiras|corinthians|sele[cç][aã]o brasileira)\b", "Futebol"),
    (r"\b(?:bitcoin|criptomoedas|cripto)\b", "Bitcoin"),
    (r"\b(?:intelig[eê]ncia artificial|chatgpt)\b", "Inteligência artificial"),
)
BANNED = {
    "isso","aqui","que","o","a","os","as","um","uma","sobre","como",
    "de","do","da","das","dos","em","no","na","nos","nas","para","por",
    "nao","não","mais","nosso","esta","está","voce","você","novo","nova",
    "veja","esse","essa","atualizado","cortes","shorts","short","live",
    "video","vídeo","transmissão","hoje","fazer","mundo","jogo","games",
}


def guess_topic(value):
    if not isinstance(value, str):
        return ""
    title = re.sub(r"\s+", " ", value.strip())[:180]
    if not title:
        return ""
    for pattern, canonical in TOPICS:
        if re.search(pattern, title, flags=re.IGNORECASE):
            return canonical
    # Não transforma identificadores, URLs ou títulos genéricos em buscas aleatórias.
    if re.match(r"https?://", title, re.I):
        return ""
    words = [x for x in re.findall(r"[\wÀ-ÿ][\wÀ-ÿ+\-]*", title) if len(x) > 2]
    filtered = [x for x in words if x.lower() not in BANNED]
    if len(filtered) < 2:
        return ""
    return " ".join(filtered[:3])[:55]


def safe_topic(value):
    topic = guess_topic(value)
    if not topic:
        return ""
    return re.sub(r"[^\wÀ-ÿ +\-]", "", topic).strip()[:64]


def recommended_query(topic):
    return (topic.strip() + " ao vivo") if topic else "jogos ao vivo"
