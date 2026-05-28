"""
gerar_comportamento_pre_evento.py
Gera o CSV: comportamento_pre_evento.csv
"""

import pandas as pd
import numpy as np
from datetime import date, timedelta

# ─────────────────────────────────────────────
# CONFIGURAÇÃO — ajuste conforme necessário
# ─────────────────────────────────────────────
OS_CSV = "../refined/os/os_data.csv"
FERIADOS_CSV = "../refined/feriados/feriados_data.csv"
OUTPUT_CSV = "../refined/analytics/comportamento_pre_evento.csv"

JANELA_DIAS = 21  # dias antes do feriado na janela
LIMIAR = 6.0  # linha crítica de urgência

# ─────────────────────────────────────────────
# 1. CARGA DOS DADOS
# ─────────────────────────────────────────────
os_df = pd.read_csv(OS_CSV, parse_dates=["data_saida_prevista", "data_saida_efetiva"])
feriados_df = pd.read_csv(FERIADOS_CSV)

# Normaliza datas do feriados (formato DD/MM/YYYY → date)
feriados_df["data"] = pd.to_datetime(feriados_df["data"], format="%d/%m/%Y").dt.date

# ─────────────────────────────────────────────
# 2. SELECIONAR PRÓXIMO FERIADO
# ─────────────────────────────────────────────
hoje = date.today()

proximos = feriados_df[
    (feriados_df["data"] >= hoje) &
    (feriados_df["tipo"].isin(["NACIONAL", "FACULTATIVO"]))
    ].sort_values("data")

if proximos.empty:
    raise ValueError("Nenhum feriado futuro encontrado em feriados_data.csv")

feriado_alvo = proximos.iloc[0]
data_feriado = feriado_alvo["data"]
nome_feriado = feriado_alvo["nome"]

print(f"Feriado alvo: {nome_feriado} em {data_feriado}")
print(f"Janela: {data_feriado - timedelta(days=JANELA_DIAS)} → {data_feriado}")

# ─────────────────────────────────────────────
# 3. MONTAR JANELA DE DATAS
# ─────────────────────────────────────────────
data_inicio = data_feriado - timedelta(days=JANELA_DIAS)
datas = [data_inicio + timedelta(days=i) for i in range(JANELA_DIAS + 1)]

# ─────────────────────────────────────────────
# 4. VOLUME DE OS POR DIA (real = passado/hoje)
# ─────────────────────────────────────────────
# Conta OS abertas por data de entrada efetiva
os_df["data_entrada_efetiva"] = pd.to_datetime(os_df["data_entrada_efetiva"]).dt.date
volume_por_dia = (
    os_df.groupby("data_entrada_efetiva")
    .size()
    .reset_index(name="volume")
)
volume_dict = dict(zip(volume_por_dia["data_entrada_efetiva"], volume_por_dia["volume"]))

# ─────────────────────────────────────────────
# 5. CALCULAR MÉDIAS HISTÓRICAS PARA PROJEÇÃO
# ─────────────────────────────────────────────
# Pega média de OS por dia da semana nos últimos 90 dias como base
ultimos_90 = hoje - timedelta(days=90)
os_hist = os_df[os_df["data_entrada_efetiva"] >= ultimos_90].copy()
os_hist["dia_semana"] = pd.to_datetime(os_hist["data_entrada_efetiva"]).dt.dayofweek
media_por_diasemana = os_hist.groupby("dia_semana").size() / 13  # ~13 semanas
media_geral = os_hist.shape[0] / 90 if not os_hist.empty else 1.0


def volume_projetado(d):
    """Volume médio esperado baseado no dia da semana."""
    dia_semana = pd.Timestamp(d).dayofweek
    return round(media_por_diasemana.get(dia_semana, media_geral), 2)


# ─────────────────────────────────────────────
# 6. CALCULAR ÍNDICE DE URGÊNCIA
# ─────────────────────────────────────────────
def calcular_urgencia(d, vol, dias_restantes):
    """
    Urgência = f(volume acumulado, proximidade do feriado)
    Escala 0–10.
    """
    if dias_restantes <= 0:
        return round(min(10.0, vol * 0.4), 2)

    # Peso da proximidade: quanto mais perto, mais urgente
    peso_proximidade = max(0, (JANELA_DIAS - dias_restantes) / JANELA_DIAS)

    # Volume normalizado (assume max ~10 OS/dia)
    peso_volume = min(1.0, vol / 10.0)

    urgencia = (peso_proximidade * 6 + peso_volume * 4)
    return round(min(10.0, urgencia), 2)


# ─────────────────────────────────────────────
# 7. MONTAR DATAFRAME FINAL
# ─────────────────────────────────────────────
rows = []

for d in datas:
    dias_restantes = (data_feriado - d).days
    is_passado_ou_hoje = d <= hoje

    # Volume
    vol_real = volume_dict.get(d, None) if is_passado_ou_hoje else None
    vol_proj = volume_projetado(d) if not is_passado_ou_hoje else None

    # Para urgência usa volume real se disponível, senão projetado
    vol_para_urgencia = vol_real if vol_real is not None else (vol_proj or media_geral)

    urgencia = calcular_urgencia(d, vol_para_urgencia, dias_restantes)

    rows.append({
        "data": d.strftime("%Y-%m-%d"),
        "urgencia_real": urgencia if is_passado_ou_hoje else None,
        "urgencia_proj": urgencia if not is_passado_ou_hoje else None,
        "volume_real": vol_real,
        "volume_proj": vol_proj,
        "is_hoje": 1 if d == hoje else 0,
        "is_feriado": 1 if d == data_feriado else 0,
        "nome_feriado": nome_feriado,
        "limiar_critico": LIMIAR,
    })

df_out = pd.DataFrame(rows)

# ─────────────────────────────────────────────
# 8. SALVAR
# ─────────────────────────────────────────────
df_out.to_csv(OUTPUT_CSV, index=False)
print(f"\nCSV gerado: {OUTPUT_CSV}")
print(f"Linhas: {len(df_out)}")
print("\nAmostra:")
print(df_out.to_string(index=False))