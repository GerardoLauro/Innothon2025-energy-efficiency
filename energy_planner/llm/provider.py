"""Gestione dei provider LLM (Ollama locale e provider API generico)."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Mapping, MutableMapping, Optional, Protocol, Sequence, Union
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)


def _mask_key(value: Optional[str]) -> str:
    if not value:
        return ""
    visible = value[-4:]
    return f"***{visible}"


class LLMProvider(Protocol):
    """Interfaccia comune per tutti i provider LLM supportati."""

    def complete(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        stream: bool = False,
        **gen_params: object,
    ) -> Union[str, Iterator[str]]:
        """Genera una risposta dato un elenco di messaggi (role/content).

        Il parametro `stream` abilita la generazione token-per-token: in tal caso
        viene restituito un iteratore di stringhe. In modalita non streaming viene
        restituito il testo completo come stringa. I parametri addizionali vengono
        passati al provider come temperatura, top_p, max_tokens, stop ecc.
        """

    def name(self) -> str:
        """Restituisce un identificativo leggibile del provider (es. "ollama/llama3.1:8b")."""


def _ensure_messages(messages: Sequence[Mapping[str, str]]) -> List[Dict[str, str]]:
    prepared: List[Dict[str, str]] = []
    for item in messages:
        if "role" not in item or "content" not in item:
            raise ValueError("Ogni messaggio deve contenere le chiavi 'role' e 'content'.")
        prepared.append({"role": str(item["role"]), "content": str(item["content"])})
    if not prepared:
        raise ValueError("La lista dei messaggi non puo essere vuota.")
    return prepared


@dataclass
class _GenerationParams:
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    max_tokens: Optional[int] = None
    stop: Optional[Sequence[str]] = None
    timeout: Optional[float] = None

    @classmethod
    def from_kwargs(cls, kwargs: MutableMapping[str, object]) -> "_GenerationParams":
        params = cls()
        for key in ("temperature", "top_p", "max_tokens", "stop", "timeout"):
            if key in kwargs:
                setattr(params, key if key != "max_tokens" else "max_tokens", kwargs.pop(key))
        return params


@dataclass
class OllamaProvider:
    """Client HTTP per interagire con un demone Ollama locale."""

    host: str
    model: str
    default_params: _GenerationParams = field(default_factory=_GenerationParams)

    def name(self) -> str:
        return f"ollama/{self.model}"

    def complete(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        stream: bool = False,
        **gen_params: object,
    ) -> Union[str, Iterator[str]]:
        payload_messages = _ensure_messages(messages)
        params = _GenerationParams.from_kwargs(gen_params)
        options: Dict[str, object] = {}
        if params.temperature is not None:
            options["temperature"] = params.temperature
        if params.top_p is not None:
            options["top_p"] = params.top_p
        if params.max_tokens is not None:
            options["num_predict"] = params.max_tokens
        if params.stop is not None:
            options["stop"] = list(params.stop)
        timeout = params.timeout or self.default_params.timeout or 60

        payload = {
            "model": self.model,
            "messages": payload_messages,
            "stream": stream,
            "options": options,
        }
        logger.info("Invio richiesta a Ollama host=%s model=%s stream=%s", self.host, self.model, stream)

        request = Request(
            urljoin(self.host.rstrip("/") + "/", "api/chat"),
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )

        def _stream() -> Iterator[str]:
            try:
                with urlopen(request, timeout=timeout) as response:
                    for raw_line in response:
                        if not raw_line:
                            continue
                        try:
                            chunk = json.loads(raw_line.decode("utf-8"))
                        except json.JSONDecodeError:
                            continue
                        message = chunk.get("message", {})
                        content = message.get("content")
                        if content:
                            yield content
            except (URLError, HTTPError, OSError) as exc:  # pragma: no cover - network errors
                raise ConnectionError(
                    "Impossibile raggiungere Ollama. Avvia 'ollama serve' e verifica il modello con 'ollama pull'."
                ) from exc

        if stream:
            return _stream()

        try:
            with urlopen(request, timeout=timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (URLError, HTTPError, OSError) as exc:
            raise ConnectionError(
                "Impossibile raggiungere Ollama. Avvia 'ollama serve' e verifica il modello con 'ollama pull'."
            ) from exc
        message = data.get("message", {})
        content = message.get("content", "")
        return content


@dataclass
class APIProvider:
    """Client generico per provider API compatibili con chat completions (es. OpenAI)."""

    base_url: str
    api_key: str
    model: str
    default_params: _GenerationParams = field(default_factory=_GenerationParams)
    request_timeout: float = 60.0

    def name(self) -> str:
        return f"api/{self.model}"

    def complete(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        stream: bool = False,
        **gen_params: object,
    ) -> Union[str, Iterator[str]]:
        import requests

        payload_messages = _ensure_messages(messages)
        params = _GenerationParams.from_kwargs(gen_params)
        timeout = params.timeout or self.default_params.timeout or self.request_timeout
        payload: Dict[str, object] = {
            "model": self.model,
            "messages": payload_messages,
            "stream": stream,
        }
        if params.temperature is not None:
            payload["temperature"] = params.temperature
        if params.top_p is not None:
            payload["top_p"] = params.top_p
        if params.max_tokens is not None:
            payload["max_tokens"] = params.max_tokens
        if params.stop is not None:
            payload["stop"] = list(params.stop)

        endpoint = urljoin(self.base_url.rstrip("/") + "/", "chat/completions")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        logger.info(
            "Invio richiesta al provider API base_url=%s model=%s stream=%s timeout=%s",
            self.base_url,
            self.model,
            stream,
            timeout,
        )

        if stream:
            response = requests.post(
                endpoint,
                headers=headers,
                json=payload,
                timeout=timeout,
                stream=True,
            )
            if response.status_code != 200:
                raise RuntimeError(f"Errore API ({response.status_code}): {response.text}")

            def _generator() -> Iterator[str]:
                try:
                    for line in response.iter_lines(decode_unicode=True):
                        if not line:
                            continue
                        if not line.startswith("data:"):
                            continue
                        payload_line = line.split("data:", 1)[1].strip()
                        if payload_line == "[DONE]":
                            break
                        try:
                            event = json.loads(payload_line)
                        except json.JSONDecodeError:
                            continue
                        choices = event.get("choices") or []
                        if not choices:
                            continue
                        delta = choices[0].get("delta", {})
                        content = delta.get("content")
                        if content:
                            yield content
                finally:
                    response.close()

            return _generator()

        response = requests.post(
            endpoint,
            headers=headers,
            json=payload,
            timeout=timeout,
        )
        if response.status_code != 200:
            raise RuntimeError(f"Errore API ({response.status_code}): {response.text}")
        try:
            data = response.json()
        except json.JSONDecodeError as exc:
            raise RuntimeError("Il provider API ha restituito una risposta non valida (JSON malformato).") from exc
        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError("La risposta del provider API non contiene choices.")
        message = choices[0].get("message", {})
        return message.get("content", "")

    def run(
        self,
        prompt: str,
        *,
        stream: bool = False,
        timeout: float = 60.0,
    ) -> Union[str, Iterator[str]]:
        return self.complete(
            [{"role": "user", "content": prompt}],
            stream=stream,
            timeout=timeout,
        )


@dataclass
class MockProvider:
    """Provider offline che consuma una sequenza finita di risposte esplicite."""

    responses: Sequence[str] = field(default_factory=list)

    def name(self) -> str:
        return "mock/fake-responses"

    def complete(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        stream: bool = False,
        **gen_params: object,
    ) -> Union[str, Iterator[str]]:
        if not self.responses:
            raise RuntimeError("Risposte mock esaurite: fornisci un file --mock-responses.")
        response = self.responses[0]
        self.responses = self.responses[1:]
        return iter([response]) if stream else response


def provider_from_env_or_args(
    *,
    provider: Optional[str] = None,
    ollama_host: Optional[str] = None,
    ollama_model: Optional[str] = None,
    api_base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    api_model: Optional[str] = None,
    temperature: Optional[float] = None,
    top_p: Optional[float] = None,
    max_tokens: Optional[int] = None,
    timeout: Optional[float] = None,
) -> LLMProvider:
    """Istanzia il provider LLM sulla base di flag o variabili d'ambiente.

    Priorita: argomenti espliciti > variabili d'ambiente > default. Logga il nome
    del provider scelto e i parametri salienti (senza mai mostrare API key).
    """

    provider_name = (provider or os.environ.get("LLM_PROVIDER") or "ollama").strip().lower()
    gen_defaults = _GenerationParams(
        temperature=temperature,
        top_p=top_p,
        max_tokens=max_tokens,
        timeout=timeout,
    )

    if provider_name == "ollama":
        host = ollama_host or os.environ.get("OLLAMA_HOST") or "http://127.0.0.1:11434"
        model = ollama_model or os.environ.get("OLLAMA_MODEL") or "llama3.1:8b"
        logger.info("Provider selezionato: Ollama host=%s model=%s", host, model)
        return OllamaProvider(host=host, model=model, default_params=gen_defaults)

    if provider_name == "api":
        base_url = (api_base_url or os.environ.get("API_BASE_URL") or "").strip()
        key = (api_key or os.environ.get("API_KEY") or "").strip()
        model = (api_model or os.environ.get("API_MODEL") or "").strip()
        if not base_url or not key or not model:
            raise ValueError(
                "Configurazione API incompleta: impostare API_BASE_URL, API_KEY e API_MODEL (via .env o flag)."
            )
        if gen_defaults.temperature is None:
            gen_defaults.temperature = 0.1
        if gen_defaults.top_p is None:
            gen_defaults.top_p = 1.0
        masked_key = _mask_key(key)
        logger.info("Provider selezionato: API base_url=%s model=%s key=%s", base_url, model, masked_key)
        return APIProvider(base_url=base_url, api_key=key, model=model, default_params=gen_defaults)

    if provider_name == "mock":
        logger.info("Provider selezionato: Mock (risposte preconfezionate)")
        return MockProvider()

    raise ValueError("LLM_PROVIDER sconosciuto. Valori ammessi: 'ollama', 'api', 'mock'.")


__all__ = [
    "LLMProvider",
    "OllamaProvider",
    "APIProvider",
    "MockProvider",
    "provider_from_env_or_args",
]







