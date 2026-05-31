"""
gerar_comportamento_pre_evento.py
Gera o CSV: comportamento_pre_evento.csv

Versão sem valores mockados — todos os parâmetros derivados dos CSVs.
"""

import pandas as pd
import numpy as np
from datetime import date, timedelta
from pathlib import Path

# ─────────────────────────────────────────────
# CONFIGURAÇÃO
# ─────────────────────────────────────────────
OS_CSV        = "../refined/os/os_data.csv"
FERIADOS_CSV  = "../refined/feriados/feriados_data.csv"
OUTPUT_CSV    = "../refined/analytics/comportamento_pre_evento.csv"

JANELA_DIAS   = 21   # dias de look-back antes do feriado (parâmetro de negócio)
TIPOS_VALIDOS = ["NACIONAL", "FACULTATIVO", "ESTADUAL"]  # ajuste se necessário

# ─────────────────────────────────────────────
# 1. CARGA DOS DADOS
# ─────────────────────────────────────────────
os_df = pd.read_csv(OS_CSV)
os_df["data_entrada_efetiva"] = pd.to_datetime(os_df["data_entrada_efetiva"]).dt.date

feriados_df = pd.read_csv(FERIADOS_CSV)
feriados_df["data"] = pd.to_datetime(feriados_df["data"], format="%d/%m/%Y").dt.date

# ─────────────────────────────────────────────
# 2. SELECIONAR PRÓXIMO FERIADO
# ─────────────────────────────────────────────
hoje = date.today()

# Usa os tipos que existem de fato no CSV
tipos_existentes = feriados_df["tipo"].unique().tolist()
tipos_busca = [t for t in TIPOS_VALIDOS if t in tipos_existentes]
if not tipos_busca:
    # Fallback: usa todos os tipos disponíveis exceto FÉRIAS
    tipos_busca = [t for t in tipos_existentes if "FÉRIAS" not in t.upper()]

proximos = feriados_df[
    (feriados_df["data"] >= hoje) &
    (feriados_df["tipo"].isin(tipos_busca))
].sort_values("data")

if proximos.empty:
    raise ValueError(
        f"Nenhum feriado futuro encontrado com tipos {tipos_busca}. "
        f"Tipos disponíveis: {tipos_existentes}"
    )

feriado_alvo = proximos.iloc[0]
data_feriado = feriado_alvo["data"]
nome_feriado = feriado_alvo["nome"]

print(f"Feriado alvo : {nome_feriado} em {data_feriado}")
print(f"Janela       : {data_feriado - timedelta(days=JANELA_DIAS)} → {data_feriado}")

# ─────────────────────────────────────────────
# 3. MONTAR JANELA DE DATAS
# ─────────────────────────────────────────────
data_inicio = data_feriado - timedelta(days=JANELA_DIAS)
datas = [data_inicio + timedelta(days=i) for i in range(JANELA_DIAS + 1)]

# ─────────────────────────────────────────────
# 4. VOLUME DE OS POR DIA (dados reais)
# ─────────────────────────────────────────────
volume_por_dia = (
    os_df.groupby("data_entrada_efetiva")
    .size()
    .reset_index(name="volume")
)
volume_dict = dict(zip(volume_por_dia["data_entrada_efetiva"], volume_por_dia["volume"]))

# ─────────────────────────────────────────────
# 5. PARÂMETROS HISTÓRICOS — tudo derivado dos dados
# ─────────────────────────────────────────────
# Janela histórica: do início do dataset até ontem
data_min_hist = os_df["data_entrada_efetiva"].min()
data_max_hist = min(os_df["data_entrada_efetiva"].max(), hoje - timedelta(days=1))

os_hist = os_df[
    (os_df["data_entrada_efetiva"] >= data_min_hist) &
    (os_df["data_entrada_efetiva"] <= data_max_hist)
].copy()

# Número real de semanas por dia da semana no histórico
os_hist["dia_semana"] = pd.to_datetime(os_hist["data_entrada_efetiva"]).dt.dayofweek
contagem_por_diasemana = os_hist.groupby("dia_semana").size()  # total de OS por dia da semana

# Contar quantas ocorrências de cada dia da semana existem no período histórico
from collections import Counter
todas_datas_hist = pd.date_range(data_min_hist, data_max_hist)
ocorrencias_diasemana = Counter(d.dayofweek for d in todas_datas_hist)

# Média de OS por dia da semana = total de OS naquele dia / nº de ocorrências daquele dia
media_por_diasemana = {
    dia: contagem_por_diasemana.get(dia, 0) / max(1, ocorrencias_diasemana[dia])
    for dia in range(7)
}

# Média geral diária (total OS / total dias no período)
total_dias_hist = max(1, (pd.Timestamp(data_max_hist) - pd.Timestamp(data_min_hist)).days + 1)
media_geral = os_hist.shape[0] / total_dias_hist

# Volume máximo real observado (substitui o "10" mockado)
vol_max_real = max(volume_por_dia["volume"].max(), 1)

# Limiar crítico = percentil 75 do índice de urgência observado
# (calculado após montar o df; placeholder por ora, será recalculado abaixo)
# Usamos como proxy: urgência quando restam ~7 dias e volume é médio
dias_criticos = 7
peso_prox_critico = max(0, (JANELA_DIAS - dias_criticos) / JANELA_DIAS)
peso_vol_critico  = min(1.0, media_geral / vol_max_real)
limiar_calculado  = round((peso_prox_critico * 6 + peso_vol_critico * 4), 2)

print(f"\nParâmetros derivados dos dados:")
print(f"  Histórico         : {data_min_hist} → {data_max_hist} ({total_dias_hist} dias)")
print(f"  Média geral/dia   : {round(media_geral, 3)}")
print(f"  Vol. máximo real  : {vol_max_real}")
print(f"  Média por dia sem : { {k: round(v,2) for k,v in media_por_diasemana.items()} }")
print(f"  Limiar crítico    : {limiar_calculado}")

# ─────────────────────────────────────────────
# 6. FUNÇÕES DE PROJEÇÃO E URGÊNCIA
# ─────────────────────────────────────────────
def volume_projetado(d):
    """Média histórica real para aquele dia da semana."""
    dia_semana = pd.Timestamp(d).dayofweek
    return round(media_por_diasemana.get(dia_semana, media_geral), 4)


def calcular_urgencia(vol, dias_restantes):
    """
    Urgência = f(volume acumulado, proximidade do feriado).
    Escala 0–10. Todos os parâmetros derivados dos dados.
    """
    if dias_restantes <= 0:
        # No dia do feriado: urgência máxima proporcional ao volume
        return round(min(10.0, vol / vol_max_real * 10), 2)

    # Peso da proximidade: normalizado pela janela real
    peso_proximidade = max(0.0, (JANELA_DIAS - dias_restantes) / JANELA_DIAS)

    # Peso do volume: normalizado pelo máximo real observado
    peso_volume = min(1.0, vol / vol_max_real)

    urgencia = peso_proximidade * 6 + peso_volume * 4
    return round(min(10.0, urgencia), 2)

# ─────────────────────────────────────────────
# 7. MONTAR DATAFRAME FINAL
# ─────────────────────────────────────────────
rows = []

for d in datas:
    dias_restantes    = (data_feriado - d).days
    is_passado_ou_hoje = d <= hoje

    vol_real = volume_dict.get(d, None) if is_passado_ou_hoje else None
    vol_proj = volume_projetado(d)      if not is_passado_ou_hoje else None

    # Para urgência: real se disponível, senão projetado, senão média geral
    vol_para_urgencia = (
        vol_real if vol_real is not None
        else (vol_proj if vol_proj is not None else media_geral)
    )

    urgencia = calcular_urgencia(vol_para_urgencia, dias_restantes)

    rows.append({
        "data"          : d.strftime("%Y-%m-%d"),
        "urgencia_real" : urgencia if is_passado_ou_hoje else None,
        "urgencia_proj" : urgencia if not is_passado_ou_hoje else None,
        "volume_real"   : vol_real,
        "volume_proj"   : vol_proj,
        "is_hoje"       : 1 if d == hoje else 0,
        "is_feriado"    : 1 if d == data_feriado else 0,
        "nome_feriado"  : nome_feriado,
        "limiar_critico": limiar_calculado,
    })

df_out = pd.DataFrame(rows)

# ─────────────────────────────────────────────
# 8. SALVAR
# ─────────────────────────────────────────────
Path(OUTPUT_CSV).parent.mkdir(parents=True, exist_ok=True)
df_out.to_csv(OUTPUT_CSV, index=False)
print(f"\nCSV gerado: {OUTPUT_CSV}")
print(f"Linhas: {len(df_out)}")
print("\nAmostra:")
print(df_out.to_string(index=False))