import csv
import io
import sqlite3
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import StreamingResponse

from app.database import connect
from app.schemas import LeituraIn, LeituraOut, iso_utc, para_utc

router = APIRouter(prefix="/leituras", tags=["leituras"])

COLUNAS = ["id_leitura", "id_experimento", "timestamp", "temperatura", "umidade", "ce", "status_envio"]


def _filtro(id_experimento: int, inicio: Optional[datetime], fim: Optional[datetime]):
    where, params = ["id_experimento = ?"], [id_experimento]
    if inicio:
        where.append("timestamp >= ?")
        params.append(iso_utc(para_utc(inicio)))
    if fim:
        where.append("timestamp <= ?")
        params.append(iso_utc(para_utc(fim)))
    return " AND ".join(where), params


def _experimento_ativo(conn) -> int:
    """Experimento que recebe as leituras do sensor quando ele nao informa o id:
    o mais recente sem data_fim (ou, se todos encerraram, o mais recente)."""
    row = conn.execute(
        "SELECT id_experimento FROM experimento "
        "ORDER BY (data_fim IS NULL) DESC, id_experimento DESC LIMIT 1"
    ).fetchone()
    return row["id_experimento"] if row else 1


@router.post("", response_model=LeituraOut, status_code=status.HTTP_201_CREATED)
def criar_leitura(leitura: LeituraIn) -> LeituraOut:
    """RF02/RF03 - recebe a leitura do ESP32 e persiste com timestamp UTC."""
    ts = iso_utc(leitura.timestamp)
    try:
        with connect() as conn:
            if leitura.id_experimento is None:
                leitura.id_experimento = _experimento_ativo(conn)
            cur = conn.execute(
                """
                INSERT INTO leitura
                    (id_experimento, timestamp, temperatura, umidade, ce, status_envio)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (leitura.id_experimento, ts, leitura.temperatura, leitura.umidade,
                 leitura.ce, leitura.status_envio),
            )
    except sqlite3.IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Violacao de integridade: {exc}",
        )
    return LeituraOut(id_leitura=cur.lastrowid, timestamp=ts,
                      **leitura.model_dump(exclude={"timestamp"}))


@router.get("", response_model=list[LeituraOut])
def listar_leituras(
    id_experimento: int = 1,
    inicio: Optional[datetime] = Query(default=None, description="UTC, ISO-8601"),
    fim: Optional[datetime] = Query(default=None, description="UTC, ISO-8601"),
    limite: int = Query(default=1000, ge=1, le=10000),
) -> list[LeituraOut]:
    """RF06 - serie temporal em ordem cronologica (as mais recentes, ate `limite`)."""
    where, params = _filtro(id_experimento, inicio, fim)
    with connect() as conn:
        rows = conn.execute(
            f"""
            SELECT * FROM (
                SELECT * FROM leitura WHERE {where}
                ORDER BY timestamp DESC LIMIT ?
            ) ORDER BY timestamp
            """,
            (*params, limite),
        ).fetchall()
    return [LeituraOut(**dict(r)) for r in rows]


@router.get("/ultima", response_model=LeituraOut)
def ultima_leitura(id_experimento: int = 1) -> LeituraOut:
    """RF06/RNF02 - leitura mais recente para os indicadores do dashboard."""
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM leitura WHERE id_experimento = ? ORDER BY timestamp DESC LIMIT 1",
            (id_experimento,),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Nenhuma leitura")
    return LeituraOut(**dict(row))


@router.get("/export.csv")
def exportar_csv(
    id_experimento: int = 1,
    inicio: Optional[datetime] = None,
    fim: Optional[datetime] = None,
) -> StreamingResponse:
    """RF07/CT05 - dataset completo em CSV."""
    where, params = _filtro(id_experimento, inicio, fim)
    with connect() as conn:
        rows = conn.execute(
            f"SELECT {', '.join(COLUNAS)} FROM leitura WHERE {where} ORDER BY timestamp",
            params,
        ).fetchall()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(COLUNAS)
    writer.writerows(tuple(r) for r in rows)
    buf.seek(0)

    nome = f"leituras_exp{id_experimento}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{nome}"'},
    )
