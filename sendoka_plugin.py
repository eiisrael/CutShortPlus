# -*- coding: utf-8 -*-
"""Integracao opcional Sendoka (SMS e OTP) para CutShortPlus.

Nunca recebe chaves pelo navegador depois de salva-las via DPAPI.
Somente a API oficial e acessada. Nao existe envio automatico.
"""
from __future__ import annotations

import re
import uuid
import requests

BASE_URL = "https://www.sendoka.com/api/v1"
PHONE = re.compile(r"^\+[1-9]\d{1,14}$")
SENDER_ID = re.compile(r"^[A-Za-z][A-Za-z0-9]{1,10}$")
VERIFICATION_ID = re.compile(r"^ver_[A-Za-z0-9_-]{1,100}$")


def key_mode(api_key: str) -> str:
    if str(api_key).startswith("sok_test_"):
        return "test"
    if str(api_key).startswith("sok_live_"):
        return "live"
    if not api_key:
        raise ValueError("Configure a chave Sendoka em Integracoes.")
    raise ValueError("Chave Sendoka invalida: use sok_test_ ou sok_live_.")


def valid_phone(number: str) -> str:
    number = str(number).strip()
    if not PHONE.fullmatch(number):
        raise ValueError("Telefone invalido. Use E.164, por exemplo +5511999999999.")
    return number


def valid_sender(sender: str) -> str:
    sender = str(sender).strip()
    if not (PHONE.fullmatch(sender) or SENDER_ID.fullmatch(sender)):
        raise ValueError("Remetente invalido. Informe um numero E.164 ou ID alfanumerico registrado.")
    return sender


def _request(api_key: str, path: str, payload: dict, *, idempotent: bool = True) -> dict:
    key_mode(api_key)
    headers = {"Authorization": "Bearer " + api_key, "Content-Type": "application/json"}
    if idempotent:
        headers["Idempotency-Key"] = str(uuid.uuid4())
    try:
        response = requests.post(BASE_URL + path, json=payload, headers=headers, timeout=25)
    except requests.RequestException:
        raise RuntimeError("Sem conexao com Sendoka. Verifique a internet e tente novamente.") from None
    try:
        data = response.json()
    except ValueError:
        raise RuntimeError("Sendoka retornou resposta nao JSON (HTTP %d)." % response.status_code) from None
    if not isinstance(data, dict):
        raise RuntimeError("Sendoka retornou uma resposta inesperada.")
    if not response.ok:
        error = data.get("error")
        code = error.get("code") if isinstance(error, dict) else ""
        # Nunca propagar resposta bruta, possivel eco de credenciais ou telefone.
        known = {
            "UNAUTHORIZED": "Chave invalida ou revogada.",
            "INSUFFICIENT_SCOPE": "Chave sem permissao para este recurso.",
            "SENDER_NOT_REGISTERED": "Remetente ainda nao registrado no Sendoka.",
            "SENDER_NOT_VERIFIED": "Remetente ainda nao verificado no Sendoka.",
            "SENDER_CAMPAIGN_NOT_APPROVED": "Campanha de SMS do remetente nao aprovada.",
            "SMS_DESTINATION_NOT_ALLOWED": "Pais do destinatario nao autorizado na conta Sendoka.",
            "USAGE_LIMIT_EXCEEDED": "Cota de mensagens Sendoka esgotada.",
            "RATE_LIMITED": "Limite temporario de requisicoes Sendoka.",
            "SUPPRESSED": "Destinatario bloqueado/suprimido no Sendoka.",
        }
        detail = known.get(code, "Operacao recusada pelo Sendoka.")
        raise RuntimeError("%s [HTTP %d%s]" % (detail, response.status_code, " / " + code if code else ""))
    return data


def send_sms(api_key: str, sender: str, recipient: str, body: str) -> dict:
    sender, recipient = valid_sender(sender), valid_phone(recipient)
    if not isinstance(body, str) or not (1 <= len(body.strip()) <= 1600):
        raise ValueError("Mensagem SMS deve conter entre 1 e 1600 caracteres.")
    result = _request(api_key, "/sms", {"from": sender, "to": recipient,
                                       "body": body.strip(), "tags": ["cutshortplus"]})
    return {"id": str(result.get("id", ""))[:120],
            "status": str(result.get("status", ""))[:32],
            "segments": result.get("segments"),
            "mode": key_mode(api_key),
            "warnings": [str(w.get("code", ""))[:80] for w in result.get("warnings", [])
                         if isinstance(w, dict)][:5]}


def start_verification(api_key: str, sender: str, recipient: str) -> dict:
    result = _request(api_key, "/verifications", {
        "channel": "sms", "from": valid_sender(sender),
        "to": valid_phone(recipient), "code_length": 6, "ttl_seconds": 600})
    return {"id": str(result.get("id", ""))[:120],
            "status": str(result.get("status", ""))[:32],
            "expires_at": str(result.get("expires_at", ""))[:60],
            "mode": key_mode(api_key)}


def check_verification(api_key: str, verification_id: str, code: str) -> dict:
    verification_id = str(verification_id).strip()
    if not VERIFICATION_ID.fullmatch(verification_id):
        raise ValueError("Identificador de verificacao invalido.")
    if not re.fullmatch(r"\d{4,10}", str(code)):
        raise ValueError("Codigo OTP invalido.")
    result = _request(api_key, "/verifications/%s/check" % verification_id,
                      {"code": str(code)}, idempotent=False)
    return {"id": str(result.get("id", ""))[:120],
            "status": str(result.get("status", ""))[:32],
            "reason": str(result.get("reason", ""))[:80],
            "approved": result.get("status") == "approved",
            "mode": key_mode(api_key)}
