# -*- coding: utf-8 -*-
"""Provedores de IA de texto isolados. Nunca registrar tokens."""
import json
import re

PROVIDERS = {
    "openrouter": {"models": "https://openrouter.ai/api/v1/models",
                   "chat": "https://openrouter.ai/api/v1/chat/completions", "name": "OpenRouter"},
    "nvidia": {"models": "https://integrate.api.nvidia.com/v1/models",
               "chat": "https://integrate.api.nvidia.com/v1/chat/completions", "name": "NVIDIA"},
    "anthropic": {"models": "https://api.anthropic.com/v1/models",
                  "chat": "https://api.anthropic.com/v1/messages", "name": "Claude (Anthropic)", "style": "anthropic"},
    "xai": {"models": "https://api.x.ai/v1/models",
            "chat": "https://api.x.ai/v1/chat/completions", "name": "Grok (xAI)"},
    "gemini": {"models": "https://generativelanguage.googleapis.com/v1beta/openai/models",
               "chat": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
               "name": "Gemini (Google)"},
    "deepseek": {"models": "https://api.deepseek.com/models",
                 "chat": "https://api.deepseek.com/chat/completions", "name": "DeepSeek"},
    "mistral": {"models": "https://api.mistral.ai/v1/models",
                "chat": "https://api.mistral.ai/v1/chat/completions", "name": "Mistral"},
    "groq": {"models": "https://api.groq.com/openai/v1/models",
             "chat": "https://api.groq.com/openai/v1/chat/completions", "name": "Groq Cloud"},
}
MODEL_PATTERN = re.compile(r"^[a-zA-Z0-9_./:+-]{1,160}$")
EXCLUDED = ("embed", "rerank", "re-rank", "safety", "guard", "moderation", "ocr",
            "tts", "transcribe", "whisper", "speech", "audio", "image-gen", "diffusion")


def check_provider(provider):
    if provider not in PROVIDERS:
        raise ValueError("Provedor de IA não reconhecido.")


def validate_model(model):
    if not isinstance(model, str) or not MODEL_PATTERN.fullmatch(model):
        raise ValueError("Identificador de modelo inválido.")
    return model


def provider_error(provider, response):
    label = PROVIDERS[provider]["name"]
    code = response.status_code
    if code == 401:
        return ValueError(f"{label}: chave inválida ou expirada (401).")
    if code == 403:
        return ValueError(f"{label}: acesso não autorizado (403). Verifique as permissões.")
    if code == 429:
        return RuntimeError(f"{label}: limite de requisições/créditos atingido (429). Confira sua conta.")
    return RuntimeError(f"{label}: solicitação recusada (HTTP {code}). Verifique modelo e permissões.")


def request_models(provider, key, client=None):
    check_provider(provider)
    # Os catálogos públicos podem ser consultados antes de configurar a chave;
    # a autenticação é exigida somente para gerar inferências.
    if client is None:
        import requests
        client = requests
    if not key and provider not in ("openrouter", "nvidia"):
        raise ValueError("Configure a chave do provedor antes de buscar modelos.")
    try:
        headers = {"Authorization": "Bearer " + key.strip()} if key else {}
        if provider == "anthropic":
            headers = {"x-api-key": key.strip(), "anthropic-version": "2026-10-21"}
        response = client.get(PROVIDERS[provider]["models"],
                              headers=headers, timeout=30)
    except Exception:
        raise RuntimeError("Falha de conexão ao consultar os modelos.") from None
    if not response.ok:
        if provider == "nvidia" and response.status_code in (404, 405, 501):
            raise RuntimeError("A NVIDIA não disponibilizou a listagem neste endpoint. "
                               "Consulte o catálogo NVIDIA Build e informe o ID manualmente.")
        raise provider_error(provider, response)
    try:
        raw = response.json().get("data", [])
        if isinstance(raw, dict):
            raw = list(raw.values())
        models = []
        for item in raw:
            if not isinstance(item, dict): continue
            ident = item.get("id")
            if not isinstance(ident, str) or not MODEL_PATTERN.fullmatch(ident): continue
            lower = ident.lower()
            if any(x in lower for x in EXCLUDED): continue
            if provider == "openrouter":
                arch = item.get("architecture") or {}
                outputs, inputs = arch.get("output_modalities"), arch.get("input_modalities")
                if outputs and "text" not in outputs: continue
                if inputs and "text" not in inputs: continue
            if provider == "mistral":
                cap = item.get("capabilities") or {}
                if cap.get("completion_chat") is False: continue
            if provider == "xai" and item.get("type") in ("image","video","embedding"):
                continue
            if provider == "groq" and item.get("active") is False: continue
            models.append(ident)
        models = sorted(set(models), key=str.casefold)
    except (ValueError, KeyError, TypeError, AttributeError):
        raise RuntimeError("Resposta do catálogo de modelos inválida.") from None
    if provider == "openrouter":
        # A modalidade :free é oferecida sem compra de créditos; demais modelos
        # com preço $0 podem exigir conta financiada. Preferir :free.
        models = [m for m in models if m.endswith(":free") or m == "openrouter/free"]
        if "openrouter/free" not in models:
            models.insert(0, "openrouter/free")
    return {"connected": bool(key), "catalog_available": True, "provider": provider,
            "models": models, "count": len(models),
            "free_filter": ("free_variant" if provider == "openrouter"
                            else "trial_credits_unverified" if provider == "nvidia"
                            else "credits_required"),
            "recommended": ("openrouter/free" if provider == "openrouter"
                            else models[0] if models else "")}


def extract_json(text):
    if not isinstance(text, str) or not text.strip():
        raise RuntimeError("O modelo não retornou texto para análise.")
    raw = text.strip()
    if raw.startswith(chr(96) * 3):
        raw = raw.split("\n", 1)[-1]
        raw = raw.rsplit(chr(96) * 3, 1)[0].strip()
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        if start < 0: raise RuntimeError("A IA não retornou JSON com os cortes.") from None
        try: obj, _ = json.JSONDecoder().raw_decode(raw[start:])
        except json.JSONDecodeError:
            raise RuntimeError("A IA não retornou JSON válido para os cortes.") from None
    if not isinstance(obj, dict) or not isinstance(obj.get("clips"), list):
        raise RuntimeError("Resposta da IA sem lista de cortes.")
    validated = []
    for clip in obj["clips"][:12]:
        if not isinstance(clip, dict): continue
        try:
            start = float(clip.get("start", -1))
            if not 0 <= start <= 864000: continue
            title = str(clip.get("title", ""))[:90]
            description = str(clip.get("description", ""))[:500]
            if title:
                validated.append({"start": start, "title": title, "description": description})
        except (ValueError, TypeError, OverflowError): continue
    if not validated:
        raise RuntimeError("IA não identificou trechos com timestamps válidos.")
    return validated


def generate(provider, key, model, prompt, client=None):
    check_provider(provider)
    if not key or not str(key).strip():
        raise ValueError("Chave de IA não configurada para o provedor escolhido.")
    validate_model(model)
    if client is None:
        import requests
        client = requests
    body = {"model": model, "messages": [{"role": "user", "content": prompt}],
            "stream": False, "max_tokens": 2500}
    headers={"Authorization": "Bearer " + key.strip(), "Content-Type": "application/json"}
    if provider == "anthropic":
        body.pop("stream",None)
        headers={"x-api-key":key.strip(),"anthropic-version":"2026-10-21",
                 "Content-Type":"application/json"}
    # O prompt pede JSON sem obrigar response_format, que não é comum a todas as APIs.
    try:
        resp = client.post(PROVIDERS[provider]["chat"],
                           headers=headers, json=body, timeout=110)
    except Exception:
        raise RuntimeError("Não foi possível conectar à IA. Verifique sua internet.") from None
    if not resp.ok:
        raise provider_error(provider, resp)
    try:
        data = resp.json()
        if provider == "anthropic":
            content="".join(block.get("text","") for block in data.get("content",[])
                            if isinstance(block,dict) and block.get("type")=="text")
        else:
            choice = data["choices"][0]["message"]
            content = choice.get("content")
            if isinstance(content, list):
                content = "".join(x.get("text", "") for x in content if isinstance(x, dict))
        return extract_json(content)
    except (ValueError, KeyError, IndexError, TypeError):
        raise RuntimeError("O provedor não retornou uma resposta de texto válida.") from None
