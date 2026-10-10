from datetime import date, datetime, timezone
from typing import Annotated, Literal, Optional

from pydantic import AfterValidator, BaseModel, Field


def para_utc(v: Optional[datetime]) -> Optional[datetime]:
    if v is None:
        return None
    # Sem offset, assume-se que ja esta em UTC (RF03)
    if v.tzinfo is None:
        return v.replace(tzinfo=timezone.utc)
    return v.astimezone(timezone.utc)


UtcDatetime = Annotated[datetime, AfterValidator(para_utc)]


def iso_utc(v: Optional[datetime]) -> str:
    """Formato persistido no banco (AL05): 2026-09-17T14:30:00Z."""
    return (v or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------- Leitura ----------------

class LeituraIn(BaseModel):
    id_experimento: int = Field(default=1, ge=1)
    timestamp: Optional[UtcDatetime] = None
    temperatura: float = Field(ge=-10, le=80)
    umidade: float = Field(ge=0, le=100)
    ce: float = Field(ge=0)
    status_envio: Literal["S", "F", "R"] = "S"


class LeituraOut(BaseModel):
    id_leitura: int
    id_experimento: int
    timestamp: str
    temperatura: float
    umidade: float
    ce: float
    status_envio: str


# ---------------- Cultura (AL11) ----------------

class CulturaIn(BaseModel):
    nome: str = Field(min_length=1, max_length=100)
    umidade_min: Optional[float] = Field(default=None, ge=0, le=100)
    umidade_max: Optional[float] = Field(default=None, ge=0, le=100)
    ce_min: Optional[float] = Field(default=None, ge=0)
    ce_max: Optional[float] = Field(default=None, ge=0)
    temperatura_min: Optional[float] = None
    temperatura_max: Optional[float] = None


class CulturaPatch(BaseModel):
    nome: Optional[str] = Field(default=None, min_length=1, max_length=100)
    umidade_min: Optional[float] = Field(default=None, ge=0, le=100)
    umidade_max: Optional[float] = Field(default=None, ge=0, le=100)
    ce_min: Optional[float] = Field(default=None, ge=0)
    ce_max: Optional[float] = Field(default=None, ge=0)
    temperatura_min: Optional[float] = None
    temperatura_max: Optional[float] = None


class CulturaOut(CulturaIn):
    id_cultura: int


# ---------------- Experimento ----------------

class ExperimentoOut(BaseModel):
    id_experimento: int
    nome: str
    id_cultura: Optional[int]
    area_m2: Optional[float]
    data_inicio: str
    data_fim: Optional[str]


class ExperimentoIn(BaseModel):
    nome: str = Field(min_length=1, max_length=100)
    id_cultura: int = Field(ge=1)
    area_m2: Optional[float] = Field(default=None, gt=0)
    data_inicio: date


class ExperimentoPatch(BaseModel):
    nome: Optional[str] = Field(default=None, min_length=1)
    id_cultura: Optional[int] = Field(default=None, ge=1)
    area_m2: Optional[float] = Field(default=None, gt=0)
    data_inicio: Optional[date] = None
    data_fim: Optional[date] = None


# ---------------- IA (AL10) ----------------

class AlertaOut(BaseModel):
    id_alerta: int
    id_experimento: int
    timestamp: str
    tipo: Literal["umidade", "anomalia"]
    valor_previsto: Optional[float]
    horizonte_h: Optional[int]
    id_leitura: Optional[int]
    descricao: str


class PredicaoOut(BaseModel):
    horizonte_h: int
    timestamp_alvo: str
    umidade_prevista: float


class PredicoesOut(BaseModel):
    id_experimento: int
    timestamp_geracao: Optional[str]
    predicoes: list[PredicaoOut]


class RegaOut(BaseModel):
    timestamp: str
    umidade_antes: float
    umidade_depois: float


class TreinoOut(BaseModel):
    timestamp: str
    horizonte_h: int
    n_amostras: int
    rmse: float
    mae: float
    r2: Optional[float]
    rmse_persistencia: float
    importancias: dict[str, float]
