import pandas as pd
import numpy as np
from datetime import date, timedelta
import os

BASE = os.path.dirname(os.path.abspath(__file__))

PATH_DATATRAN  = os.path.join(BASE, "../../refined/refined_datatran.csv")
PATH_OS        = os.path.join(BASE, "../../refined/grafana/os_data_com_servicos.csv")
PATH_FERIADOS  = os.path.join(BASE, "../../trusted/trusted_feriados.csv")

OUTPUT         = os.path.join(BASE, "indicadores_feriados.csv")

# ── Parâmetros configuráveis ───────────────────────────────────────────────────
BOXES_TOTAL           = 3        # capacidade total de boxes de funilaria pesada
ESTOQUE_TOTAL_KG      = 100.0    # referência de 100% de estoque (ajuste conforme real)
JANELA_PROXIMOS_DIAS  = 30
JANELA_SEMANA         = 7

# Mapeamento tipo de feriado → perfil de dano (baseado no dashboard)
PERFIL_DANO = {
    "NACIONAL":    {"perfil": "Severo",   "descricao": "Dano amplo em cabine e lateral"},
    "ESTADUAL":    {"perfil": "Moderado", "descricao": "Para-choque e lateral parcial"},
    "FACULTATIVO": {"perfil": "Moderado", "descricao": "Para-choque e lateral parcial"},
    "MUNICIPAL":   {"perfil": "Leve",     "descricao": "Amassado leve e arranhão"},
}

# ── Leitura dos dados ──────────────────────────────────────────────────────────
def projetar_feriados_ano_atual(feriados: pd.DataFrame, ano_alvo: int) -> pd.DataFrame:
    """
    O CSV de feriados pode conter apenas um ano de referência.
    Esta função replica as datas para o ano alvo, ajustando apenas o ano
    (feriados fixos como 01/01, 01/05, 07/09 etc.).
    Feriados móveis (Carnaval, Corpus Christi, Páscoa) NÃO são replicados
    automaticamente — eles continuam com a data original.
    """
    ano_orig = feriados["DATA"].dt.year.mode()[0]
    if ano_orig == ano_alvo:
        return feriados  # já está no ano certo

    feriados_proj = feriados.copy()
    try:
        feriados_proj["DATA"] = feriados_proj["DATA"].apply(
            lambda d: d.replace(year=ano_alvo) if pd.notna(d) else d
        )
    except ValueError:
        # 29/02 em ano não bissexto — descarta essas linhas
        def safe_replace(d):
            try:
                return d.replace(year=ano_alvo) if pd.notna(d) else d
            except ValueError:
                return pd.NaT
        feriados_proj["DATA"] = feriados_proj["DATA"].apply(safe_replace)
        feriados_proj = feriados_proj.dropna(subset=["DATA"])

    return feriados_proj


def load_data():
    datatran = pd.read_csv(PATH_DATATRAN)
    datatran["DATA"] = pd.to_datetime(datatran["DATA"], dayfirst=True)

    os_df = pd.read_csv(PATH_OS)
    os_df["data_entrada_efetiva"]  = pd.to_datetime(os_df["data_entrada_efetiva"],  errors="coerce")
    os_df["data_saida_efetiva"]    = pd.to_datetime(os_df["data_saida_efetiva"],    errors="coerce")
    os_df["data_saida_prevista"]   = pd.to_datetime(os_df["data_saida_prevista"],   errors="coerce")

    feriados = pd.read_csv(PATH_FERIADOS)
    feriados["DATA"] = pd.to_datetime(feriados["DATA"], dayfirst=True)

    # Projeta para o ano corrente se necessário
    ano_atual = date.today().year
    feriados = projetar_feriados_ano_atual(feriados, ano_atual)
    print(f"[INFO] Feriados projetados para o ano {ano_atual}: {len(feriados)} registros")

    return datatran, os_df, feriados


# ── Indicador 1 – Feriados nos próximos 30 dias ────────────────────────────────
def indicador_feriados_proximos(feriados: pd.DataFrame, hoje: date) -> dict:
    inicio = pd.Timestamp(hoje)
    fim    = pd.Timestamp(hoje + timedelta(days=JANELA_PROXIMOS_DIAS))

    mask    = (feriados["DATA"] >= inicio) & (feriados["DATA"] < fim)
    proximos = feriados[mask].copy()

    total     = len(proximos)
    nacionais = int((proximos["TIPO"] == "NACIONAL").sum())
    estaduais = int((proximos["TIPO"] == "ESTADUAL").sum())
    municipais= int((proximos["TIPO"] == "MUNICIPAL").sum())
    facultativos = int((proximos["TIPO"] == "FACULTATIVO").sum())

    # Próximo feriado (para determinar perfil dominante)
    proximo = proximos.sort_values("DATA").head(1)
    if len(proximo) > 0:
        proximo_tipo = proximo["TIPO"].iloc[0]
        proximo_data = proximo["DATA"].iloc[0].strftime("%Y-%m-%d")
        proximo_desc = proximo["DESCRICAO"].iloc[0] if "DESCRICAO" in proximo.columns else ""
    else:
        proximo_tipo = "NENHUM"
        proximo_data = ""
        proximo_desc = ""

    return {
        "ind1_total_feriados_30d":       total,
        "ind1_nacionais_30d":            nacionais,
        "ind1_estaduais_30d":            estaduais,
        "ind1_municipais_30d":           municipais,
        "ind1_facultativos_30d":         facultativos,
        "ind1_proximo_feriado_data":     proximo_data,
        "ind1_proximo_feriado_tipo":     proximo_tipo,
        "ind1_proximo_feriado_descricao": proximo_desc,
    }


# ── Indicador 2 – Perfil dominante esperado ────────────────────────────────────
def indicador_perfil_dominante(feriados: pd.DataFrame, datatran: pd.DataFrame, hoje: date) -> dict:
    inicio = pd.Timestamp(hoje)
    fim    = pd.Timestamp(hoje + timedelta(days=JANELA_PROXIMOS_DIAS))

    mask    = (feriados["DATA"] >= inicio) & (feriados["DATA"] < fim)
    proximos = feriados[mask].copy()

    # Prioridade: NACIONAL > ESTADUAL/FACULTATIVO > MUNICIPAL
    if (proximos["TIPO"] == "NACIONAL").any():
        tipo_dominante = "NACIONAL"
    elif proximos["TIPO"].isin(["ESTADUAL", "FACULTATIVO"]).any():
        tipo_dominante = proximos[proximos["TIPO"].isin(["ESTADUAL", "FACULTATIVO"])]["TIPO"].iloc[0]
    elif (proximos["TIPO"] == "MUNICIPAL").any():
        tipo_dominante = "MUNICIPAL"
    else:
        tipo_dominante = "NENHUM"

    info = PERFIL_DANO.get(tipo_dominante, {"perfil": "Sem feriado", "descricao": "Sem feriados no período"})

    # Calcula % histórico de cada parte do veículo por tipo de feriado (via datatran + feriados)
    # Junta acidentes com feriados pela data
    historico = calcular_historico_dano_por_tipo(feriados, datatran)

    # Partes mais afetadas para o tipo dominante
    partes_dominante = historico.get(tipo_dominante, {})
    top_partes = sorted(partes_dominante.items(), key=lambda x: x[1], reverse=True)[:2]

    parte1_nome = top_partes[0][0] if len(top_partes) > 0 else ""
    parte1_pct  = top_partes[0][1] if len(top_partes) > 0 else 0.0
    parte2_nome = top_partes[1][0] if len(top_partes) > 1 else ""
    parte2_pct  = top_partes[1][1] if len(top_partes) > 1 else 0.0

    return {
        "ind2_tipo_dominante":     tipo_dominante,
        "ind2_perfil_dano":        info["perfil"],
        "ind2_descricao_dano":     info["descricao"],
        "ind2_feriado_nacional_presente": int((proximos["TIPO"] == "NACIONAL").any()),
        "ind2_parte1_nome":        parte1_nome,
        "ind2_parte1_pct":         round(parte1_pct, 1),
        "ind2_parte2_nome":        parte2_nome,
        "ind2_parte2_pct":         round(parte2_pct, 1),
    }


def calcular_historico_dano_por_tipo(feriados: pd.DataFrame, datatran: pd.DataFrame) -> dict:
    """
    Para cada tipo de feriado, calcula qual % dos acidentes caiu naquele dia
    e quais classificações (usadas como proxy de 'parte do veículo') são mais comuns.
    Retorna dict: { tipo: { classificacao: pct } }
    """
    # Dias de feriado por tipo
    feriados_por_tipo = (
        feriados.groupby("TIPO")["DATA"]
        .apply(lambda s: set(s.dt.date))
        .to_dict()
    )

    datatran_cp = datatran.copy()
    datatran_cp["date_only"] = datatran_cp["DATA"].dt.date

    resultado = {}
    for tipo, datas in feriados_por_tipo.items():
        acidentes_tipo = datatran_cp[datatran_cp["date_only"].isin(datas)]
        if len(acidentes_tipo) == 0:
            resultado[tipo] = {}
            continue

        # Usa CLASSIFICACAO_ACIDENTE como proxy de severidade/parte
        contagem = acidentes_tipo["CLASSIFICACAO_ACIDENTE"].value_counts(normalize=True) * 100
        resultado[tipo] = contagem.to_dict()

    return resultado


# ── Indicador 3 – Boxes de funilaria pesada disponíveis ───────────────────────
def indicador_boxes(os_df: pd.DataFrame, hoje: date) -> dict:
    """
    Conta quantos boxes de funilaria pesada estarão disponíveis na semana seguinte,
    considerando OSs de FUNILARIA que ainda estarão em andamento.
    """
    inicio_semana = pd.Timestamp(hoje + timedelta(days=1))
    fim_semana    = pd.Timestamp(hoje + timedelta(days=JANELA_SEMANA))

    funilaria = os_df[os_df["tipo_servico"] == "FUNILARIA"].copy()

    # OS que estarão ocupando box na semana seguinte:
    # entrada <= fim_semana E saída >= inicio_semana
    em_andamento = funilaria[
        (funilaria["data_entrada_efetiva"] <= fim_semana) &
        (
            funilaria["data_saida_efetiva"].isna() |
            (funilaria["data_saida_efetiva"] >= inicio_semana)
        )
    ]

    boxes_ocupados   = min(em_andamento["id_ordem_servico"].nunique(), BOXES_TOTAL)
    boxes_disponiveis = max(BOXES_TOTAL - boxes_ocupados, 0)

    # Capacidade
    if boxes_disponiveis >= BOXES_TOTAL:
        capacidade_status = "Capacidade total disponível"
    elif boxes_disponiveis > 0:
        capacidade_status = "Capacidade adequada"
    else:
        capacidade_status = "Sem boxes disponíveis"

    return {
        "ind3_boxes_total":          BOXES_TOTAL,
        "ind3_boxes_ocupados_semana": int(boxes_ocupados),
        "ind3_boxes_disponiveis":    int(boxes_disponiveis),
        "ind3_capacidade_status":    capacidade_status,
    }


# ── Indicador 4 – Estoque de massa e tinta ────────────────────────────────────
def indicador_estoque(os_df: pd.DataFrame, hoje: date) -> dict:
    """
    Estima o consumo de massa e tinta pelas OSs de PINTURA finalizadas
    e calcula o percentual de estoque restante em relação ao total configurado.

    Lógica proxy:
      - Cada OS de pintura finalizada consome valor_total_produtos / preço_referência_por_kg
      - O estoque é estimado como: 100% - (consumo acumulado / ESTOQUE_TOTAL_KG * 100)
    """
    pintura = os_df[
        (os_df["tipo_servico"] == "PINTURA") &
        (os_df["status"] == "FINALIZADO")
    ].copy()

    # Consumo acumulado proxy: soma dos valores de produtos de pintura no último mês
    ultimo_mes = pd.Timestamp(hoje - timedelta(days=30))
    pintura_recente = pintura[
        pintura["data_saida_efetiva"] >= ultimo_mes
    ] if "data_saida_efetiva" in pintura.columns else pintura

    # Custo médio de insumos por OS como proxy de consumo
    custo_total_insumos = pintura_recente["valor_total_produtos"].sum()

    # Preço de referência por unidade de estoque (R$/kg ou R$/litro — ajuste conforme real)
    PRECO_REF_INSUMO = 50.0  # R$ por kg/litro de referência
    consumo_estimado = custo_total_insumos / PRECO_REF_INSUMO if PRECO_REF_INSUMO > 0 else 0

    pct_estoque = max(0.0, min(100.0, 100.0 - (consumo_estimado / ESTOQUE_TOTAL_KG * 100)))

    # Status
    if pct_estoque >= 80:
        estoque_status = "Estoque adequado"
    elif pct_estoque >= 40:
        estoque_status = "Repor antes do feriado"
    else:
        estoque_status = "Estoque crítico"

    return {
        "ind4_pct_estoque_massa_tinta":  round(pct_estoque, 1),
        "ind4_consumo_estimado_unidades": round(consumo_estimado, 2),
        "ind4_estoque_status":           estoque_status,
        "ind4_referencia_total":         ESTOQUE_TOTAL_KG,
    }


# ── Histórico por tipo de feriado (perfil de dano para barras do dashboard) ───
def indicador_historico_perfil(feriados: pd.DataFrame, os_df: pd.DataFrame) -> list[dict]:
    """
    Para cada tipo de feriado, calcula a distribuição de partes do veículo
    mais trabalhadas nas OSs próximas às datas de feriado.
    Retorna lista de dicts (uma linha por tipo x parte).
    """
    # Junta OS com feriados pela data de entrada
    os_cp = os_df.copy()
    os_cp["data_only"] = os_cp["data_entrada_efetiva"].dt.date

    # Cria dicionário data → tipo de feriado
    feriados_cp = feriados.copy()
    feriados_cp["data_only"] = feriados_cp["DATA"].dt.date
    data_tipo = feriados_cp.groupby("data_only")["TIPO"].first().to_dict()

    os_cp["tipo_feriado"] = os_cp["data_only"].map(data_tipo)
    os_com_feriado = os_cp.dropna(subset=["tipo_feriado"])

    if len(os_com_feriado) == 0:
        # Sem cruzamento direto — usa distribuição geral de parte_veiculo por tipo_servico
        linhas = []
        for tipo, info in PERFIL_DANO.items():
            for parte in ["PARACHOQUE", "PORTA", "CURVAO", "GRADE"]:
                linhas.append({
                    "tipo_feriado": tipo,
                    "parte_veiculo": parte,
                    "pct_ocorrencia": np.nan,
                    "perfil_dano": info["perfil"],
                })
        return linhas

    linhas = []
    for tipo in os_com_feriado["tipo_feriado"].unique():
        subset = os_com_feriado[os_com_feriado["tipo_feriado"] == tipo]
        contagem = subset["parte_veiculo"].value_counts(normalize=True) * 100
        for parte, pct in contagem.items():
            linhas.append({
                "tipo_feriado":   tipo,
                "parte_veiculo":  parte,
                "pct_ocorrencia": round(pct, 1),
                "perfil_dano":    PERFIL_DANO.get(tipo, {}).get("perfil", ""),
            })
    return linhas


# ── Calendário – próximos 30 dias com classificação de dano ───────────────────
def indicador_calendario(feriados: pd.DataFrame, hoje: date) -> list[dict]:
    """
    Para cada dia dos próximos 30 dias, retorna se é feriado e qual
    o nível de dano esperado (para colorir o calendário no Grafana).
    """
    inicio = pd.Timestamp(hoje)
    fim    = pd.Timestamp(hoje + timedelta(days=JANELA_PROXIMOS_DIAS))

    mask     = (feriados["DATA"] >= inicio) & (feriados["DATA"] < fim)
    proximos = feriados[mask].copy()

    feriado_por_data = {}
    for _, row in proximos.iterrows():
        d = row["DATA"].date()
        tipo = row["TIPO"]
        # Prioridade: NACIONAL > ESTADUAL > FACULTATIVO > MUNICIPAL
        prioridade = {"NACIONAL": 4, "ESTADUAL": 3, "FACULTATIVO": 2, "MUNICIPAL": 1}
        if d not in feriado_por_data or prioridade.get(tipo, 0) > prioridade.get(feriado_por_data[d]["tipo"], 0):
            feriado_por_data[d] = {
                "tipo": tipo,
                "descricao": row.get("DESCRICAO", ""),
                "perfil": PERFIL_DANO.get(tipo, {}).get("perfil", "Sem impacto"),
            }

    linhas = []
    for i in range(JANELA_PROXIMOS_DIAS):
        dia = hoje + timedelta(days=i)
        info = feriado_por_data.get(dia, None)
        linhas.append({
            "data":          dia.strftime("%Y-%m-%d"),
            "eh_feriado":    1 if info else 0,
            "tipo_feriado":  info["tipo"] if info else "",
            "descricao":     info["descricao"] if info else "",
            "perfil_dano":   info["perfil"] if info else "Normal",
        })
    return linhas


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    hoje = date.today()
    print(f"[INFO] Data de referência: {hoje}")

    datatran, os_df, feriados = load_data()
    print(f"[INFO] Dados carregados — datatran: {len(datatran)} linhas | "
          f"OS: {len(os_df)} linhas | feriados: {len(feriados)} linhas")

    # ── Calcular indicadores ──
    ind1 = indicador_feriados_proximos(feriados, hoje)
    ind2 = indicador_perfil_dominante(feriados, datatran, hoje)
    ind3 = indicador_boxes(os_df, hoje)
    ind4 = indicador_estoque(os_df, hoje)

    historico = indicador_historico_perfil(feriados, os_df)
    calendario = indicador_calendario(feriados, hoje)

    # ── Montar saída principal (1 linha com todos os KPIs) ──
    kpis = {**ind1, **ind2, **ind3, **ind4, "data_referencia": hoje.strftime("%Y-%m-%d")}
    df_kpis = pd.DataFrame([kpis])

    # ── Tabelas auxiliares ──
    df_historico  = pd.DataFrame(historico)
    df_calendario = pd.DataFrame(calendario)

    # ── Salvar ──
    df_kpis.to_csv("../../refined/grafana/dano-previsto/indicadores_kpis.csv", index=False)
    df_historico.to_csv("../../refined/grafana/dano-previsto/indicadores_historico_perfil.csv", index=False)
    df_calendario.to_csv("../../refined/grafana/dano-previsto/indicadores_calendario.csv", index=False)

    print("\n[OK] Arquivos gerados:")
    print("  → indicadores_kpis.csv          (1 linha com os 4 KPIs principais)")
    print("  → indicadores_historico_perfil.csv  (barras por tipo de feriado)")
    print("  → indicadores_calendario.csv    (calendário dos próximos 30 dias)")

    print("\n── KPIs ──────────────────────────────────────────────────────────")
    for k, v in kpis.items():
        print(f"  {k}: {v}")

    print("\n── Histórico de Perfil (primeiras linhas) ────────────────────────")
    print(df_historico.head(10).to_string(index=False))

    print("\n── Calendário (próximos feriados) ───────────────────────────────")
    print(df_calendario[df_calendario["eh_feriado"] == 1].to_string(index=False))


if __name__ == "__main__":
    main()