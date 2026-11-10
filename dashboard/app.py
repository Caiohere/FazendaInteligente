"""Dashboard PlantCare AI (Streamlit) - RF05, RF06, RF07, RF08, RNF02, RNF05, AL10, AL11."""
from datetime import datetime, timedelta, timezone

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# Precisa ser o primeiro comando Streamlit - antes do import de `api`, que le st.secrets
st.set_page_config(page_title="PlantCare AI", page_icon="🌱", layout="wide")

import api  # noqa: E402

FUSO = "America/Sao_Paulo"
ID_EXP = 1
ONLINE_MIN = 25          # sem leitura ha mais que isso -> agente offline (RF01 = 10 min)
DIAS_FASE_1 = 7          # AL09
DIAS_EXPERIMENTO = 14

# Paleta de referencia (validada) - cor segue a entidade, nunca a posicao
COR_MEDIDA = "#2a78d6"      # serie 1
COR_PREVISTA = "#eb6834"    # serie 2
COR_REGA = "#1baf7a"        # serie 3
COR_PERSIST = "#eb6834"
COR_CRITICO = "#d03b3b"     # status critical (anomalia) - sempre com icone + rotulo
COR_MUTED = "#898781"

PERIODOS = {"24 h": timedelta(hours=24), "3 dias": timedelta(days=3),
            "7 dias": timedelta(days=7), "Experimento todo": None}


# ---------------- utilitarios ----------------

def local(serie_utc: pd.Series) -> pd.Series:
    return pd.to_datetime(serie_utc, utc=True).dt.tz_convert(FUSO)


def fmt_local(ts_utc: str) -> str:
    return pd.Timestamp(ts_utc).tz_convert(FUSO).strftime("%d/%m %H:%M")


def layout(fig: go.Figure, titulo_y: str, altura: int = 320) -> go.Figure:
    fig.update_layout(
        height=altura, margin=dict(l=10, r=10, t=30, b=10),
        hovermode="x unified", yaxis_title=titulo_y, xaxis_title=None,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    )
    fig.update_xaxes(tickformat="%H:%M<br>%d/%m", hoverformat="%d/%m %H:%M")
    fig.update_traces(selector=dict(mode="lines"), line_width=2)
    return fig


def mostrar_erro(exc: Exception) -> None:
    st.error(f"❌ Erro ao consultar a API — {exc}")


def fase_do_dia(dia: int) -> str:
    if dia <= DIAS_FASE_1:
        return "Fase 1 — calendário"
    if dia <= DIAS_EXPERIMENTO:
        return "Fase 2 — orientada pela IA"
    return "Após o experimento"


# ---------------- dados base ----------------

try:
    experimento = api.get(f"/experimentos/{ID_EXP}")
    culturas = api.get("/culturas")
except api.ErroAPI as exc:
    mostrar_erro(exc)
    st.stop()

cultura = next((c for c in culturas if c["id_cultura"] == experimento["id_cultura"]), None)
umidade_min = cultura["umidade_min"] if cultura else None

# Titulo proprio: o st.title nao cabe em uma linha no celular (RNF05)
st.markdown('<div style="font-size:clamp(1.5rem,7vw,2.5rem);font-weight:700;line-height:1.2;'
            'margin:0.5rem 0">🌱 PlantCare AI</div>', unsafe_allow_html=True)
st.caption(
    f"{experimento['nome']} · Cultura: {cultura['nome'] if cultura else 'não definida'} · "
    f"Início: {pd.Timestamp(experimento['data_inicio']).strftime('%d/%m/%Y')} · Horários de Brasília"
)

aba_mon, aba_ia, aba_alertas, aba_culturas, aba_dados = st.tabs(
    ["📈 Monitoramento", "🤖 Inteligência Artificial", "🔔 Alertas", "🌿 Culturas", "📁 Dados"]
)


# ---------------- Monitoramento (RF05, RF06, RNF02) ----------------

with aba_mon:
    periodo = st.radio("Período", list(PERIODOS), horizontal=True, index=1, key="periodo")

    @st.fragment(run_every="60s")
    def monitoramento():
        try:
            ultima = api.leitura_opcional("/leituras/ultima", id_experimento=ID_EXP)
            delta = PERIODOS[periodo]
            inicio = (datetime.now(timezone.utc) - delta).strftime("%Y-%m-%dT%H:%M:%SZ") if delta else None
            leituras = pd.DataFrame(api.get("/leituras", id_experimento=ID_EXP, inicio=inicio, limite=10000))
            predicoes = api.get("/predicoes", id_experimento=ID_EXP)
            regas = pd.DataFrame(api.get("/regas", id_experimento=ID_EXP))
            alertas = pd.DataFrame(api.get("/alertas", id_experimento=ID_EXP))
        except api.ErroAPI as exc:
            mostrar_erro(exc)
            return

        if ultima is None or leituras.empty:
            st.info("ℹ️ Nenhuma leitura no período.")
            return

        # Status do agente
        idade = datetime.now(timezone.utc) - pd.Timestamp(ultima["timestamp"]).to_pydatetime()
        if idade <= timedelta(minutes=ONLINE_MIN):
            st.success(f"🟢 Agente online — última leitura às {fmt_local(ultima['timestamp'])}")
        else:
            st.warning(f"🟠 Agente sem enviar há {int(idade.total_seconds() // 60)} min "
                       f"(última leitura {fmt_local(ultima['timestamp'])})")

        # RF05 - alerta visual de umidade (ultimas 24 h)
        if not alertas.empty:
            recentes = alertas[(alertas["tipo"] == "umidade") &
                               (pd.to_datetime(alertas["timestamp"], utc=True)
                                >= pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=24))]
            if not recentes.empty:
                a = recentes.iloc[-1]
                st.error(f"🚨 **Regar:** {a['descricao']} — alerta emitido às {fmt_local(a['timestamp'])}")

        # Stat tiles
        leituras["ts"] = local(leituras["timestamp"])
        uma_hora = leituras[leituras["ts"] <= leituras["ts"].max() - pd.Timedelta(hours=1)]
        ref = uma_hora.iloc[-1] if not uma_hora.empty else None
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Umidade", f"{ultima['umidade']:.1f} %",
                  None if ref is None else f"{ultima['umidade'] - ref['umidade']:+.1f} p.p. em 1 h")
        c2.metric("Temperatura", f"{ultima['temperatura']:.1f} °C",
                  None if ref is None else f"{ultima['temperatura'] - ref['temperatura']:+.1f} °C em 1 h",
                  delta_color="off")
        c3.metric("CE", f"{ultima['ce']:.0f} µS/cm",
                  None if ref is None else f"{ultima['ce'] - ref['ce']:+.0f} em 1 h", delta_color="off")
        c4.metric("Umidade mínima da cultura", f"{umidade_min:.1f} %" if umidade_min is not None else "—",
                  help="Definida no perfil da cultura (aba Culturas). Sem ela, o alerta de umidade fica desligado.")

        # Leituras anomalas saem da linha (aparecem como marcador) para nao distorcer a escala
        ids_anom = set(alertas.loc[alertas["tipo"] == "anomalia", "id_leitura"]) if not alertas.empty else set()
        normais = leituras[~leituras["id_leitura"].isin(ids_anom)]

        # Umidade: medida + prevista + regas + anomalias + minimo
        fig = go.Figure()
        fig.add_scatter(x=normais["ts"], y=normais["umidade"], mode="lines", name="Medida",
                        line_color=COR_MEDIDA)
        pred = pd.DataFrame(predicoes["predicoes"])
        if not pred.empty:
            px = [leituras["ts"].iloc[-1], *local(pred["timestamp_alvo"])]
            py = [leituras["umidade"].iloc[-1], *pred["umidade_prevista"]]
            fig.add_scatter(x=px, y=py, mode="lines+markers", name="Prevista (IA)",
                            line=dict(color=COR_PREVISTA, dash="dash", width=2), marker_size=8)
        if not regas.empty:
            r = regas.assign(ts=local(regas["timestamp"]))
            r = r[r["ts"] >= leituras["ts"].iloc[0]]
            if not r.empty:
                fig.add_scatter(x=r["ts"], y=r["umidade_depois"], mode="markers", name="Rega detectada",
                                marker=dict(symbol="triangle-up", size=12, color=COR_REGA,
                                            line=dict(width=2, color="white")))
        if not alertas.empty:
            anom = alertas[alertas["tipo"] == "anomalia"].merge(
                leituras[["id_leitura", "ts", "umidade"]], on="id_leitura")
            if not anom.empty:
                fig.add_scatter(x=anom["ts"], y=anom["umidade"], mode="markers", name="Anomalia",
                                marker=dict(symbol="x", size=11, color=COR_CRITICO))
        if umidade_min is not None:
            fig.add_hline(y=umidade_min, line=dict(color=COR_MUTED, width=1, dash="dot"),
                          annotation_text=f"mínimo {umidade_min:.0f}%", annotation_position="bottom left",
                          annotation_font_color=COR_MUTED)
        st.subheader("Umidade do solo")
        st.plotly_chart(layout(fig, "%", 380), use_container_width=True, theme="streamlit")

        # Temperatura e CE: um grafico cada (nunca dois eixos Y)
        g1, g2 = st.columns(2)
        with g1:
            st.subheader("Temperatura do solo")
            f = go.Figure(go.Scatter(x=normais["ts"], y=normais["temperatura"], mode="lines",
                                     name="Temperatura", line_color=COR_MEDIDA))
            st.plotly_chart(layout(f, "°C"), use_container_width=True, theme="streamlit")
        with g2:
            st.subheader("Condutividade elétrica")
            f = go.Figure(go.Scatter(x=normais["ts"], y=normais["ce"], mode="lines",
                                     name="CE", line_color=COR_MEDIDA))
            st.plotly_chart(layout(f, "µS/cm"), use_container_width=True, theme="streamlit")

        with st.expander("Tabela das leituras do período"):
            tab = leituras.assign(horario=leituras["ts"].dt.strftime("%d/%m/%Y %H:%M"))
            st.dataframe(tab[["id_leitura", "horario", "umidade", "temperatura", "ce", "status_envio"]]
                         .iloc[::-1], hide_index=True, use_container_width=True)
        if not pred.empty:
            with st.expander("Tabela das previsões"):
                st.caption(f"Geradas às {fmt_local(predicoes['timestamp_geracao'])}")
                st.dataframe(pred.assign(horario_alvo=local(pred["timestamp_alvo"]).dt.strftime("%d/%m %H:%M"))
                             [["horizonte_h", "horario_alvo", "umidade_prevista"]],
                             hide_index=True, use_container_width=True)

    monitoramento()


# ---------------- Inteligencia Artificial (AL10: H1, H2) ----------------

with aba_ia:
    try:
        metricas = pd.DataFrame(api.get("/modelo/metricas", id_experimento=ID_EXP))
        todas = pd.DataFrame(api.get("/leituras", id_experimento=ID_EXP, limite=10000))
        regas_all = pd.DataFrame(api.get("/regas", id_experimento=ID_EXP))
    except api.ErroAPI as exc:
        mostrar_erro(exc)
        metricas = todas = regas_all = pd.DataFrame()

    st.subheader("Predição de umidade — Random Forest")
    if metricas.empty:
        st.info("ℹ️ O modelo ainda não foi treinado: são necessárias ~24 h de leituras. "
                "O horizonte de 24 h exige ~10 dias de dados.")
    else:
        st.caption(f"Último treino: {fmt_local(metricas['timestamp'].iloc[0])} · "
                   "validação cruzada temporal k=5 · comparação com o modelo de persistência")
        # H1: RMSE <= 10% do intervalo de variacao da umidade observada
        limpa = todas[todas["umidade"] > 5] if not todas.empty else todas
        intervalo = float(limpa["umidade"].max() - limpa["umidade"].min()) if not limpa.empty else 0.0
        m = metricas.copy()
        m["ganho_%"] = (1 - m["rmse"] / m["rmse_persistencia"]) * 100
        m["limite_H1"] = 0.10 * intervalo
        m["H1"] = m.apply(lambda r: "✅ atende" if r["rmse"] <= r["limite_H1"] and r["rmse"] < r["rmse_persistencia"]
                          else "❌ não atende", axis=1)
        st.dataframe(
            m[["horizonte_h", "n_amostras", "rmse", "mae", "r2", "rmse_persistencia", "ganho_%", "limite_H1", "H1"]]
            .rename(columns={"horizonte_h": "Horizonte (h)", "n_amostras": "Amostras", "rmse": "RMSE",
                             "mae": "MAE", "r2": "R²", "rmse_persistencia": "RMSE persistência",
                             "ganho_%": "Ganho sobre persistência (%)", "limite_H1": "Limite H1 (10% do intervalo)"}),
            hide_index=True, use_container_width=True,
            column_config={c: st.column_config.NumberColumn(format="%.2f") for c in
                           ["RMSE", "MAE", "R²", "RMSE persistência", "Ganho sobre persistência (%)",
                            "Limite H1 (10% do intervalo)"]},
        )
        st.caption(f"Intervalo de variação da umidade observado: {intervalo:.1f} p.p. "
                   "(leituras de sensor fora do solo excluídas).")

        g1, g2 = st.columns(2)
        with g1:
            st.markdown("**Erro por horizonte (RMSE, menor é melhor)**")
            rot = m["horizonte_h"].astype(str) + " h"
            f = go.Figure()
            f.add_bar(x=rot, y=m["rmse"], name="Random Forest", marker_color=COR_MEDIDA)
            f.add_bar(x=rot, y=m["rmse_persistencia"], name="Persistência", marker_color=COR_PERSIST)
            f.update_layout(barmode="group", bargap=0.3, bargroupgap=0.08)
            st.plotly_chart(layout(f, "RMSE (p.p.)"), use_container_width=True, theme="streamlit")
        with g2:
            h_sel = st.selectbox("Importância das features — horizonte", m["horizonte_h"],
                                 format_func=lambda h: f"{h} h")
            imp = pd.Series(m.loc[m["horizonte_h"] == h_sel, "importancias"].iloc[0]).sort_values()
            f = go.Figure(go.Bar(x=imp.values * 100, y=imp.index, orientation="h", marker_color=COR_MEDIDA,
                                 name="Importância", hovertemplate="%{y}: %{x:.1f}%<extra></extra>"))
            st.plotly_chart(layout(f, None).update_xaxes(title="%"), use_container_width=True, theme="streamlit")

    # H2: regas e tempo abaixo do minimo por fase
    st.subheader("Comparação entre fases (H2)")
    if todas.empty:
        st.info("ℹ️ Sem leituras.")
    else:
        inicio_exp = pd.Timestamp(experimento["data_inicio"]).tz_localize(FUSO)
        t = todas.assign(ts=local(todas["timestamp"]))
        t = t[t["umidade"] > 5]  # exclui sensor fora do solo
        t["dia"] = (t["ts"].dt.normalize() - inicio_exp).dt.days + 1
        t["fase"] = t["dia"].apply(fase_do_dia)
        resumo = t.groupby("fase").agg(dias=("dia", "nunique"), leituras=("id_leitura", "count"),
                                       umidade_media=("umidade", "mean"))
        if umidade_min is not None:
            resumo["horas_abaixo_do_minimo"] = t[t["umidade"] < umidade_min].groupby("fase").size() / 6
        if not regas_all.empty:
            r = regas_all.assign(ts=local(regas_all["timestamp"]))
            r["fase"] = ((r["ts"].dt.normalize() - inicio_exp).dt.days + 1).apply(fase_do_dia)
            resumo["regas"] = r.groupby("fase").size()
        st.dataframe(resumo.fillna(0).reset_index(), hide_index=True, use_container_width=True,
                     column_config={"umidade_media": st.column_config.NumberColumn("umidade média (%)", format="%.1f"),
                                    "horas_abaixo_do_minimo": st.column_config.NumberColumn(format="%.1f")})
        if umidade_min is None:
            st.caption("Defina a umidade mínima da cultura para calcular as horas abaixo do mínimo.")


# ---------------- Alertas (RF08) ----------------

with aba_alertas:
    tipo = st.radio("Tipo", ["Todos", "umidade", "anomalia"], horizontal=True,
                    format_func=lambda t: {"Todos": "Todos", "umidade": "💧 Umidade", "anomalia": "✖ Anomalia"}[t])
    try:
        alertas = pd.DataFrame(api.get("/alertas", id_experimento=ID_EXP, tipo=None if tipo == "Todos" else tipo))
    except api.ErroAPI as exc:
        mostrar_erro(exc)
        alertas = pd.DataFrame()
    if alertas.empty:
        st.info("ℹ️ Nenhum alerta registrado.")
    else:
        alertas["horário"] = local(alertas["timestamp"]).dt.strftime("%d/%m/%Y %H:%M")
        alertas["tipo"] = alertas["tipo"].map({"umidade": "💧 Umidade", "anomalia": "✖ Anomalia"})
        st.dataframe(alertas[["horário", "tipo", "descricao", "valor_previsto", "horizonte_h"]].iloc[::-1],
                     hide_index=True, use_container_width=True,
                     column_config={"descricao": "Descrição", "valor_previsto": "Umidade prevista (%)",
                                    "horizonte_h": "Horizonte (h)"})


# ---------------- Culturas (AL11 - UC04) ----------------

def campos_cultura(prefixo: str, base: dict) -> dict:
    c1, c2 = st.columns(2)
    val = {}
    for col, campo, rotulo in [(c1, "umidade_min", "Umidade mínima (%)"), (c2, "umidade_max", "Umidade máxima (%)"),
                               (c1, "ce_min", "CE mínima (µS/cm)"), (c2, "ce_max", "CE máxima (µS/cm)"),
                               (c1, "temperatura_min", "Temperatura mínima (°C)"),
                               (c2, "temperatura_max", "Temperatura máxima (°C)")]:
        val[campo] = col.number_input(rotulo, value=base.get(campo), step=0.5, key=f"{prefixo}_{campo}")
    return val


with aba_culturas:
    st.dataframe(
        pd.DataFrame(culturas)[["id_cultura", "nome", "umidade_min", "umidade_max", "ce_min", "ce_max",
                                "temperatura_min", "temperatura_max"]].astype(object).fillna("—"),
        hide_index=True, use_container_width=True,
        column_config={"id_cultura": "ID", "nome": "Cultura", "umidade_min": "Umidade mín. (%)",
                       "umidade_max": "Umidade máx. (%)", "ce_min": "CE mín. (µS/cm)", "ce_max": "CE máx. (µS/cm)",
                       "temperatura_min": "Temp. mín. (°C)", "temperatura_max": "Temp. máx. (°C)"},
    )
    st.caption("Campos vazios = não definidos. Sem umidade mínima, o alerta de umidade fica desligado.")

    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("**Cultura do experimento**")
        nomes = {c["id_cultura"]: c["nome"] for c in culturas}
        escolha = st.selectbox("Cultura", list(nomes), format_func=nomes.get,
                               index=list(nomes).index(experimento["id_cultura"]) if experimento["id_cultura"] in nomes else 0)
        if st.button("Aplicar ao experimento"):
            try:
                api.enviar("PATCH", f"/experimentos/{ID_EXP}", {"id_cultura": escolha})
                st.success("✅ Cultura do experimento atualizada.")
                st.rerun()
            except api.ErroAPI as exc:
                mostrar_erro(exc)

        st.markdown("**Editar cultura**")
        edit_id = st.selectbox("Cultura a editar", list(nomes), format_func=nomes.get, key="edit_id")
        base = next(c for c in culturas if c["id_cultura"] == edit_id)
        with st.form("editar"):
            nome = st.text_input("Nome", base["nome"])
            valores = campos_cultura(f"e{edit_id}", base)
            if st.form_submit_button("Salvar"):
                try:
                    api.enviar("PATCH", f"/culturas/{edit_id}", {"nome": nome, **valores})
                    st.success("✅ Cultura atualizada.")
                    st.rerun()
                except api.ErroAPI as exc:
                    mostrar_erro(exc)

    with col_b:
        st.markdown("**Nova cultura**")
        with st.form("nova", clear_on_submit=True):
            nome = st.text_input("Nome")
            valores = campos_cultura("n", {})
            if st.form_submit_button("Cadastrar"):
                try:
                    api.enviar("POST", "/culturas", {"nome": nome, **valores})
                    st.success("✅ Cultura cadastrada.")
                    st.rerun()
                except api.ErroAPI as exc:
                    mostrar_erro(exc)


# ---------------- Dados (RF07) ----------------

with aba_dados:
    st.markdown("**Exportar dataset (CSV)**")
    st.caption("Todas as leituras do experimento, timestamps em UTC (RF03).")
    if st.button("Gerar CSV"):
        try:
            st.download_button("⬇️ Baixar leituras.csv", api.baixar_csv(ID_EXP),
                               file_name=f"leituras_exp{ID_EXP}.csv", mime="text/csv")
        except api.ErroAPI as exc:
            mostrar_erro(exc)

    st.markdown("**Encerrar experimento**")
    with st.form("fim"):
        atual = pd.Timestamp(experimento["data_fim"]).date() if experimento["data_fim"] else None
        data_fim = st.date_input("Data de fim", value=atual, format="DD/MM/YYYY")
        if st.form_submit_button("Salvar"):
            try:
                api.enviar("PATCH", f"/experimentos/{ID_EXP}", {"data_fim": data_fim.isoformat() if data_fim else None})
                st.success("✅ Experimento atualizado.")
                st.rerun()
            except api.ErroAPI as exc:
                mostrar_erro(exc)
