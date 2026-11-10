"""Cliente da API PlantCare AI (o dashboard so fala com o backend via REST - Figura 1)."""
import os
from pathlib import Path
from typing import Any, Optional

import requests
import streamlit as st


def _tem_secrets() -> bool:
    # Acessar st.secrets sem o arquivo exibe um erro na pagina
    return any(p.exists() for p in (Path.cwd() / ".streamlit" / "secrets.toml",
                                    Path.home() / ".streamlit" / "secrets.toml"))


def _config(chave: str, padrao: str = "") -> str:
    """Variavel de ambiente (servidor) ou .streamlit/secrets.toml (Streamlit Cloud)."""
    if os.getenv(chave):
        return os.environ[chave]
    if _tem_secrets() and chave in st.secrets:
        return st.secrets[chave]
    return padrao


API_URL = _config("FAZENDA_API_URL", "http://165.22.190.56:8000").rstrip("/")
API_TOKEN = _config("FAZENDA_API_TOKEN")
TIMEOUT = 15


class ErroAPI(Exception):
    pass


def _req(metodo: str, caminho: str, **kwargs) -> requests.Response:
    try:
        r = requests.request(
            metodo, f"{API_URL}{caminho}", timeout=TIMEOUT,
            headers={"Authorization": f"Bearer {API_TOKEN}"}, **kwargs,
        )
    except requests.RequestException as exc:
        raise ErroAPI(f"API indisponivel: {exc}") from exc
    if r.status_code >= 400:
        try:
            detalhe = r.json().get("detail", r.text)
        except ValueError:
            detalhe = r.text
        raise ErroAPI(f"{r.status_code}: {detalhe}")
    return r


@st.cache_data(ttl=55, show_spinner=False)
def get(caminho: str, **params) -> Any:
    return _req("GET", caminho, params={k: v for k, v in params.items() if v is not None}).json()


def get_sem_cache(caminho: str, **params) -> Any:
    return _req("GET", caminho, params=params).json()


def baixar_csv(id_experimento: int) -> bytes:
    return _req("GET", "/leituras/export.csv", params={"id_experimento": id_experimento}).content


def enviar(metodo: str, caminho: str, dados: dict) -> Any:
    r = _req(metodo, caminho, json=dados)
    get.clear()  # escrita invalida o cache de leitura
    return r.json()


def leitura_opcional(caminho: str, **params) -> Optional[Any]:
    """GET que devolve None em 404 (ex.: nenhuma leitura ainda)."""
    try:
        return get(caminho, **params)
    except ErroAPI as exc:
        if str(exc).startswith("404"):
            return None
        raise
