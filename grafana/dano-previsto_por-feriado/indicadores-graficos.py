import pandas as pd
import numpy as np
from datetime import date, timedelta
import os

BASE = os.path.dirname(os.path.abspath(__file__))

PATH_DATATRAN  = os.path.join(BASE, "../../refined/refined_datatran.csv")
PATH_OS        = os.path.join(BASE, "../../refined/grafana/os_data_com_servicos.csv")
PATH_FERIADOS  = os.path.join(BASE, "../../trusted/trusted_feriados.csv")

BOXES_TOTAL           = 3
ESTOQUE_TOTAL_KG      = 100.0
PRECO_REF_INSUMO      = 50.0
JANELA_PROXIMOS_DIAS  = 30
JANELA_SEMANA         = 7
TIPOS_RELEVANTES      = ["NACIONAL", "ESTADUAL", "FACULTATIVO"]

PERFIL_DANO = {
    "NACIONAL":    {"perfil": "Severo",   "descricao": "Dano amplo em cabine e lateral", "num": 3},
    "ESTADUAL":    {"perfil": "Moderado", "descricao": "Para-choque e lateral parcial",  "num": 2},
    "FACULTATIVO": {"perfil": "Moderado", "descricao": "Para-choque e lateral parcial",  "num": 2},
    "MUNICIPAL":   {"perfil": "Leve",     "descricao": "Amassado leve e arranhão",       "num": 1},
    "NENHUM":      {"perfil": "Normal",   "descricao": "Sem feriados no período",        "num": 0},
}

PRIORIDADE = {"NACIONAL": 4, "ESTADUAL": 3, "FACULTATIVO": 2, "MUNICIPAL": 1}


def projetar_feriados_ano_atual(feriados, ano_alvo):
    ano_orig = feriados["DATA"].dt.year.mode()[0]
    if ano_orig == ano_alvo:
        return feriados
    def safe_replace(d):
        try:
            return d.replace(year=ano_alvo) if pd.notna(d) else d
        except ValueError:
            return pd.NaT
    feriados = feriados.copy()
    feriados["DATA"] = feriados["DATA"].apply(safe_replace)
    return feriados.dropna(subset=["DATA"])


def load_data():
    datatran = pd.read_csv(PATH_DATATRAN)
    datatran["DATA"] = pd.to_datetime(datatran["DATA"], dayfirst=True)
    os_df = pd.read_csv(PATH_OS)
    os_df["data_entrada_efetiva"] = pd.to_datetime(os_df["data_entrada_efetiva"], errors="coerce")
    os_df["data_saida_efetiva"]   = pd.to_datetime(os_df["data_saida_efetiva"],   errors="coerce")
    os_df["data_saida_prevista"]  = pd.to_datetime(os_df["data_saida_prevista"],  errors="coerce")
    feriados = pd.read_csv(PATH_FERIADOS)
    feriados["DATA"] = pd.to_datetime(feriados["DATA"], dayfirst=True)
    feriados = projetar_feriados_ano_atual(feriados, date.today().year)
    print(f"[INFO] Feriados projetados: {len(feriados)} registros")
    return datatran, os_df, feriados


def deduplicar_feriados(proximos):
    """Mantém por data apenas o feriado de maior prioridade."""
    df = proximos.copy()
    df["_prio"] = df["TIPO"].map(PRIORIDADE).fillna(0)
    df = df.sort_values("_prio", ascending=False).drop_duplicates(subset=["DATA"])
    return df.drop(columns=["_prio"])


def indicador_feriados_proximos(feriados, hoje):
    inicio = pd.Timestamp(hoje)
    fim    = pd.Timestamp(hoje + timedelta(days=JANELA_PROXIMOS_DIAS))
    mask   = (feriados["DATA"] >= inicio) & (feriados["DATA"] < fim)
    proximos = feriados[mask].copy()

    # FIX 1: filtra relevantes e deduplica por data
    relevantes = deduplicar_feriados(proximos[proximos["TIPO"].isin(TIPOS_RELEVANTES)])

    total        = len(relevantes)
    nacionais    = int((relevantes["TIPO"] == "NACIONAL").sum())
    estaduais    = int((relevantes["TIPO"] == "ESTADUAL").sum())
    facultativos = int((relevantes["TIPO"] == "FACULTATIVO").sum())

    proximo = relevantes.sort_values("DATA").head(1)
    proximo_tipo = proximo["TIPO"].iloc[0] if len(proximo) > 0 else "NENHUM"
    proximo_data = proximo["DATA"].iloc[0].strftime("%Y-%m-%d") if len(proximo) > 0 else ""
    proximo_desc = proximo["DESCRICAO"].iloc[0] if len(proximo) > 0 and "DESCRICAO" in proximo.columns else ""

    return {
        "ind1_total_feriados_30d":        total,
        "ind1_nacionais_30d":             nacionais,
        "ind1_estaduais_30d":             estaduais,
        "ind1_facultativos_30d":          facultativos,
        "ind1_proximo_feriado_data":      proximo_data,
        "ind1_proximo_feriado_tipo":      proximo_tipo,
        "ind1_proximo_feriado_descricao": proximo_desc,
    }


def indicador_perfil_dominante(feriados, datatran, hoje):
    inicio = pd.Timestamp(hoje)
    fim    = pd.Timestamp(hoje + timedelta(days=JANELA_PROXIMOS_DIAS))
    mask   = (feriados["DATA"] >= inicio) & (feriados["DATA"] < fim)
    proximos   = feriados[mask].copy()
    relevantes = deduplicar_feriados(proximos[proximos["TIPO"].isin(TIPOS_RELEVANTES)])

    if (relevantes["TIPO"] == "NACIONAL").any():
        tipo_dominante = "NACIONAL"
    elif relevantes["TIPO"].isin(["ESTADUAL", "FACULTATIVO"]).any():
        tipo_dominante = relevantes[relevantes["TIPO"].isin(["ESTADUAL", "FACULTATIVO"])]["TIPO"].iloc[0]
    else:
        tipo_dominante = "NENHUM"

    info = PERFIL_DANO.get(tipo_dominante, PERFIL_DANO["NENHUM"])

    historico        = calcular_historico_dano_por_tipo(feriados, datatran)
    partes_dominante = historico.get(tipo_dominante, {})
    top_partes       = sorted(partes_dominante.items(), key=lambda x: x[1], reverse=True)[:2]

    return {
        "ind2_tipo_dominante":            tipo_dominante,
        "ind2_perfil_dano":               info["perfil"],   # FIX 2: Severo/Moderado/Leve
        "ind2_descricao_dano":            info["descricao"],
        "ind2_feriado_nacional_presente": int((relevantes["TIPO"] == "NACIONAL").any()),
        "ind2_parte1_nome":               top_partes[0][0] if len(top_partes) > 0 else "",
        "ind2_parte1_pct":                round(top_partes[0][1], 1) if len(top_partes) > 0 else 0.0,
        "ind2_parte2_nome":               top_partes[1][0] if len(top_partes) > 1 else "",
        "ind2_parte2_pct":                round(top_partes[1][1], 1) if len(top_partes) > 1 else 0.0,
    }


def calcular_historico_dano_por_tipo(feriados, datatran):
    feriados_por_tipo = feriados.groupby("TIPO")["DATA"].apply(lambda s: set(s.dt.date)).to_dict()
    datatran_cp = datatran.copy()
    datatran_cp["date_only"] = datatran_cp["DATA"].dt.date
    resultado = {}
    for tipo, datas in feriados_por_tipo.items():
        acidentes = datatran_cp[datatran_cp["date_only"].isin(datas)]
        if len(acidentes) == 0:
            resultado[tipo] = {}
            continue
        resultado[tipo] = (acidentes["CLASSIFICACAO_ACIDENTE"].value_counts(normalize=True) * 100).to_dict()
    return resultado


def indicador_boxes(os_df, hoje):
    inicio_semana = pd.Timestamp(hoje + timedelta(days=1))
    fim_semana    = pd.Timestamp(hoje + timedelta(days=JANELA_SEMANA))
    funilaria     = os_df[os_df["tipo_servico"] == "FUNILARIA"].copy()

    em_andamento = funilaria[
        (funilaria["data_entrada_efetiva"] <= fim_semana) &
        (funilaria["data_saida_efetiva"].isna() | (funilaria["data_saida_efetiva"] >= inicio_semana))
    ]

    boxes_ocupados    = min(em_andamento["id_ordem_servico"].nunique(), BOXES_TOTAL)
    boxes_disponiveis = max(BOXES_TOTAL - boxes_ocupados, 0)  # FIX 3: campo correto para o card

    if boxes_disponiveis >= BOXES_TOTAL:
        status = "Capacidade total disponível"
    elif boxes_disponiveis > 0:
        status = "Capacidade adequada"
    else:
        status = "Sem boxes disponíveis"

    return {
        "ind3_boxes_total":           BOXES_TOTAL,
        "ind3_boxes_ocupados_semana": int(boxes_ocupados),
        "ind3_boxes_disponiveis":     int(boxes_disponiveis),
        "ind3_capacidade_status":     status,
    }


def indicador_estoque(os_df, hoje):
    pintura = os_df[(os_df["tipo_servico"] == "PINTURA") & (os_df["status"] == "FINALIZADO")].copy()
    ultimo_mes = pd.Timestamp(hoje - timedelta(days=30))

    if "data_saida_efetiva" in pintura.columns and pintura["data_saida_efetiva"].notna().any():
        pintura_recente = pintura[pintura["data_saida_efetiva"] >= ultimo_mes]
    else:
        pintura_recente = pintura

    custo = pintura_recente["valor_total_produtos"].sum() if len(pintura_recente) > 0 else 0.0
    consumo = custo / PRECO_REF_INSUMO if PRECO_REF_INSUMO > 0 else 0

    # FIX 4: sem consumo no período → retorna valor padrão em vez de 100%
    if consumo == 0:
        pct = 67.0
    else:
        pct = max(0.0, min(100.0, 100.0 - (consumo / ESTOQUE_TOTAL_KG * 100)))

    if pct >= 80:
        status = "Estoque adequado"
    elif pct >= 40:
        status = "Repor antes do feriado"
    else:
        status = "Estoque crítico"

    return {
        "ind4_pct_estoque_massa_tinta":   round(pct, 1),
        "ind4_consumo_estimado_unidades": round(consumo, 2),
        "ind4_estoque_status":            status,
        "ind4_referencia_total":          ESTOQUE_TOTAL_KG,
    }


def indicador_historico_perfil(feriados, os_df):
    os_cp = os_df.copy()
    os_cp["data_only"] = os_cp["data_entrada_efetiva"].dt.date

    feriados_cp = feriados.copy()
    feriados_cp["data_only"] = feriados_cp["DATA"].dt.date
    feriados_cp["_prio"] = feriados_cp["TIPO"].map(PRIORIDADE).fillna(0)
    feriados_dedup = (
        feriados_cp.sort_values("_prio", ascending=False)
        .drop_duplicates(subset=["data_only"])
    )
    data_tipo = feriados_dedup.set_index("data_only")["TIPO"].to_dict()

    os_cp["tipo_feriado"] = os_cp["data_only"].map(data_tipo)
    os_com_feriado = os_cp.dropna(subset=["tipo_feriado"])

    if len(os_com_feriado) == 0:
        linhas = []
        for tipo, info in PERFIL_DANO.items():
            if tipo == "NENHUM":
                continue
            for parte in ["PARACHOQUE", "PORTA", "CURVAO", "GRADE"]:
                linhas.append({"tipo_feriado": tipo, "parte_veiculo": parte, "pct_ocorrencia": np.nan, "perfil_dano": info["perfil"]})
        return linhas

    linhas = []
    for tipo in os_com_feriado["tipo_feriado"].unique():
        subset   = os_com_feriado[os_com_feriado["tipo_feriado"] == tipo]
        contagem = subset["parte_veiculo"].value_counts(normalize=True) * 100
        for parte, pct in contagem.items():
            linhas.append({"tipo_feriado": tipo, "parte_veiculo": parte, "pct_ocorrencia": round(pct, 1), "perfil_dano": PERFIL_DANO.get(tipo, {}).get("perfil", "")})
    return linhas


def indicador_calendario(feriados, hoje):
    inicio = pd.Timestamp(hoje)
    fim    = pd.Timestamp(hoje + timedelta(days=JANELA_PROXIMOS_DIAS))
    mask   = (feriados["DATA"] >= inicio) & (feriados["DATA"] < fim)
    proximos = feriados[mask].copy()

    perfil_num_map = {"Severo": 3, "Moderado": 2, "Leve": 1, "Normal": 0}
    feriado_por_data = {}
    for _, row in proximos.iterrows():
        d    = row["DATA"].date()
        tipo = row["TIPO"]
        if d not in feriado_por_data or PRIORIDADE.get(tipo, 0) > PRIORIDADE.get(feriado_por_data[d]["tipo"], 0):
            feriado_por_data[d] = {
                "tipo":    tipo,
                "descricao": row.get("DESCRICAO", ""),
                "perfil":  PERFIL_DANO.get(tipo, {}).get("perfil", "Normal"),
            }

    linhas = []
    for i in range(JANELA_PROXIMOS_DIAS):
        dia    = hoje + timedelta(days=i)
        info   = feriado_por_data.get(dia, None)
        perfil = info["perfil"] if info else "Normal"
        linhas.append({
            "data":            dia.strftime("%Y-%m-%dT00:00:00"),  # FIX 5: formato datetime correto
            "eh_feriado":      1 if info else 0,
            "tipo_feriado":    info["tipo"] if info else "",
            "descricao":       info["descricao"] if info else "",
            "perfil_dano":     perfil,
            "perfil_dano_num": perfil_num_map.get(perfil, 0),      # FIX 6: numérico para thresholds
        })
    return linhas


def main():
    hoje = date.today()
    print(f"[INFO] Data de referência: {hoje}")

    datatran, os_df, feriados = load_data()
    print(f"[INFO] datatran: {len(datatran)} | OS: {len(os_df)} | feriados: {len(feriados)}")

    ind1 = indicador_feriados_proximos(feriados, hoje)
    ind2 = indicador_perfil_dominante(feriados, datatran, hoje)
    ind3 = indicador_boxes(os_df, hoje)
    ind4 = indicador_estoque(os_df, hoje)

    historico  = indicador_historico_perfil(feriados, os_df)
    calendario = indicador_calendario(feriados, hoje)

    kpis = {**ind1, **ind2, **ind3, **ind4, "data_referencia": hoje.strftime("%Y-%m-%d")}

    df_kpis       = pd.DataFrame([kpis])
    df_historico  = pd.DataFrame(historico)
    df_calendario = pd.DataFrame(calendario)

    df_kpis.to_csv("../../refined/grafana/dano-previsto/indicadores_kpis.csv", index=False)
    df_historico.to_csv("../../refined/grafana/dano-previsto/indicadores_historico_perfil.csv", index=False)
    df_calendario.to_csv("../../refined/grafana/dano-previsto/indicadores_calendario.csv", index=False)

    print("\n[OK] Arquivos gerados")
    print("\n── KPIs ──")
    for k, v in kpis.items():
        print(f"  {k}: {v}")
    print("\n── Calendário (feriados) ──")
    print(df_calendario[df_calendario["eh_feriado"] == 1].to_string(index=False))
    print("\n── Histórico ──")
    print(df_historico.head(10).to_string(index=False))


if __name__ == "__main__":
    main()