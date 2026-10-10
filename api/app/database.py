import os
import sqlite3
from pathlib import Path

DB_PATH = Path(os.getenv("FAZENDA_DB_PATH", "/opt/fazenda-inteligente/data/fazenda.db"))

SCHEMA = """
-- AL11 - perfis de cultura; limiares de alerta vem daqui
CREATE TABLE IF NOT EXISTS cultura (
    id_cultura      INTEGER PRIMARY KEY AUTOINCREMENT,
    nome            TEXT    NOT NULL UNIQUE,
    umidade_min     REAL    CHECK (umidade_min IS NULL OR (umidade_min >= 0 AND umidade_min <= 100)),
    umidade_max     REAL    CHECK (umidade_max IS NULL OR (umidade_max >= 0 AND umidade_max <= 100)),
    ce_min          REAL    CHECK (ce_min IS NULL OR ce_min >= 0),
    ce_max          REAL    CHECK (ce_max IS NULL OR ce_max >= 0),
    temperatura_min REAL,
    temperatura_max REAL
);

CREATE TABLE IF NOT EXISTS experimento (
    id_experimento INTEGER PRIMARY KEY AUTOINCREMENT,
    nome           TEXT    NOT NULL,
    id_cultura     INTEGER REFERENCES cultura(id_cultura),
    area_m2        REAL    CHECK (area_m2 IS NULL OR area_m2 > 0),
    data_inicio    TEXT    NOT NULL,
    data_fim       TEXT
);

CREATE TABLE IF NOT EXISTS leitura (
    id_leitura     INTEGER PRIMARY KEY AUTOINCREMENT,
    id_experimento INTEGER NOT NULL REFERENCES experimento(id_experimento),
    timestamp      TEXT    NOT NULL,
    temperatura    REAL    NOT NULL CHECK (temperatura >= -10 AND temperatura <= 80),
    umidade        REAL    NOT NULL CHECK (umidade >= 0 AND umidade <= 100),
    ce             REAL    NOT NULL CHECK (ce >= 0),
    status_envio   TEXT    NOT NULL DEFAULT 'S' CHECK (status_envio IN ('S', 'F', 'R'))
);

CREATE INDEX IF NOT EXISTS idx_leitura_timestamp ON leitura(timestamp);

-- RF05/RF08/RF10 - alertas de umidade prevista e de leitura anomala (AL10)
CREATE TABLE IF NOT EXISTS alerta (
    id_alerta      INTEGER PRIMARY KEY AUTOINCREMENT,
    id_experimento INTEGER NOT NULL REFERENCES experimento(id_experimento),
    timestamp      TEXT    NOT NULL,
    tipo           TEXT    NOT NULL CHECK (tipo IN ('umidade', 'anomalia')),
    valor_previsto REAL,
    horizonte_h    INTEGER,
    id_leitura     INTEGER REFERENCES leitura(id_leitura),
    descricao      TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_alerta_timestamp ON alerta(timestamp);
CREATE UNIQUE INDEX IF NOT EXISTS uq_alerta_anomalia ON alerta(id_leitura) WHERE tipo = 'anomalia';

-- RF04 - predicoes de umidade geradas a cada execucao do job (AL10)
CREATE TABLE IF NOT EXISTS predicao (
    id_predicao       INTEGER PRIMARY KEY AUTOINCREMENT,
    id_experimento    INTEGER NOT NULL REFERENCES experimento(id_experimento),
    timestamp_geracao TEXT    NOT NULL,
    horizonte_h       INTEGER NOT NULL,
    timestamp_alvo    TEXT    NOT NULL,
    umidade_prevista  REAL    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_predicao_geracao ON predicao(id_experimento, timestamp_geracao);

-- Historico de metricas de cada treino (Tabelas 9 e 10 do TCC)
CREATE TABLE IF NOT EXISTS treino_modelo (
    id_treino         INTEGER PRIMARY KEY AUTOINCREMENT,
    id_experimento    INTEGER NOT NULL REFERENCES experimento(id_experimento),
    timestamp         TEXT    NOT NULL,
    horizonte_h       INTEGER NOT NULL,
    n_amostras        INTEGER NOT NULL,
    rmse              REAL    NOT NULL,
    mae               REAL    NOT NULL,
    r2                REAL,
    rmse_persistencia REAL    NOT NULL,
    importancias      TEXT    NOT NULL
);

-- Apenas para consulta: horario de Brasilia (UTC-3, sem horario de verao desde 2019).
-- O dado persistido continua em UTC (RF03).
CREATE VIEW IF NOT EXISTS leitura_local AS
SELECT
    id_leitura,
    id_experimento,
    timestamp,
    strftime('%Y-%m-%d %H:%M:%S', timestamp, '-3 hours') AS timestamp_local,
    temperatura,
    umidade,
    ce,
    status_envio
FROM leitura;
"""

SEED = """
INSERT INTO experimento (id_experimento, nome, data_inicio)
SELECT 1, 'Experimento 1', date('now')
WHERE NOT EXISTS (SELECT 1 FROM experimento WHERE id_experimento = 1);
"""


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10, factory=ClosingConnection)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _colunas(conn: sqlite3.Connection, tabela: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({tabela})")}


def _migrar(conn: sqlite3.Connection) -> None:
    """Atualiza bancos criados por versoes anteriores da API."""
    tabelas = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}

    # AL10 - ADUBACAO removida (so descarta se estiver vazia)
    if "adubacao" in tabelas and conn.execute("SELECT COUNT(*) FROM adubacao").fetchone()[0] == 0:
        conn.execute("DROP TABLE adubacao")

    # AL10 - ALERTA com ce_projetada_48h -> novo formato (so recria se vazia)
    if "alerta" in tabelas and "ce_projetada_48h" in _colunas(conn, "alerta"):
        if conn.execute("SELECT COUNT(*) FROM alerta").fetchone()[0] == 0:
            conn.execute("DROP TABLE alerta")

    # AL11 - experimento.cultura (texto) -> experimento.id_cultura (FK); area_m2 opcional
    if "experimento" in tabelas and "cultura" in _colunas(conn, "experimento"):
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cultura (
                id_cultura INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT NOT NULL UNIQUE,
                umidade_min REAL, umidade_max REAL, ce_min REAL, ce_max REAL,
                temperatura_min REAL, temperatura_max REAL)
        """)
        conn.execute("INSERT OR IGNORE INTO cultura (nome) SELECT DISTINCT cultura FROM experimento")
        tem_fim = "data_fim" in _colunas(conn, "experimento")
        conn.executescript(f"""
            CREATE TABLE experimento_nova (
                id_experimento INTEGER PRIMARY KEY AUTOINCREMENT,
                nome           TEXT    NOT NULL,
                id_cultura     INTEGER REFERENCES cultura(id_cultura),
                area_m2        REAL    CHECK (area_m2 IS NULL OR area_m2 > 0),
                data_inicio    TEXT    NOT NULL,
                data_fim       TEXT
            );
            INSERT INTO experimento_nova (id_experimento, nome, id_cultura, area_m2, data_inicio, data_fim)
            SELECT e.id_experimento, e.nome, c.id_cultura, e.area_m2, e.data_inicio,
                   {"e.data_fim" if tem_fim else "NULL"}
            FROM experimento e LEFT JOIN cultura c ON c.nome = e.cultura;
            DROP TABLE experimento;
            ALTER TABLE experimento_nova RENAME TO experimento;
        """)


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = connect()
    try:
        # WAL permite leitura do dashboard durante a escrita da ingestao
        conn.execute("PRAGMA journal_mode = WAL")
        # FKs desligadas so durante a migracao (recriacao da tabela experimento)
        conn.execute("PRAGMA foreign_keys = OFF")
        _migrar(conn)
        conn.commit()
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(SCHEMA)
        conn.executescript(SEED)
        conn.commit()
    finally:
        conn.close()
