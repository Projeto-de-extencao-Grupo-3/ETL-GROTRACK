import pandas as pd
from pathlib import Path
import s3_config

# ── Caminhos dos arquivos de entrada ────────────────────────────────────────
OS_PATH       = "./refined/os/os_data.csv"
FERIADOS_PATH = "./refined/feriados/feriados_data.csv"
OUTPUT_PATH   = "./refined/analytics/os_finalizada_no_prazo.csv"

# Meses de férias escolares (ajuste conforme sua região)
MESES_FERIAS = {1, 2, 7}

MESES_LABEL = {
    1: "Jan", 2: "Fev",  3: "Mar", 4: "Abr",
    5: "Mai", 6: "Jun",  7: "Jul", 8: "Ago",
    9: "Set", 10: "Out", 11: "Nov", 12: "Dez",
}

# ── Leitura e preparação das OSs ────────────────────────────────────────────
os_df = pd.read_csv(OS_PATH)
os_df["data_saida_prevista"] = pd.to_datetime(os_df["data_saida_prevista"])
os_df["data_saida_efetiva"]  = pd.to_datetime(os_df["data_saida_efetiva"])

os_df["no_prazo"] = os_df["data_saida_efetiva"] <= os_df["data_saida_prevista"]
os_df["mes_ref"]  = os_df["data_saida_efetiva"].dt.month
os_df["ano_ref"]  = os_df["data_saida_efetiva"].dt.year

# Contagem de OSs no prazo e com atraso por mês/ano
contagem = (
    os_df.groupby(["ano_ref", "mes_ref", "no_prazo"])
    .size()
    .unstack(fill_value=0)
    .reindex(columns=[True, False], fill_value=0)
)
contagem.columns = ["no_prazo", "com_atraso"]
contagem = contagem.reset_index()

# ── Leitura dos feriados ────────────────────────────────────────────────────
fer_df = pd.read_csv(FERIADOS_PATH)
fer_df["data"] = pd.to_datetime(fer_df["data"], dayfirst=True)
fer_df["mes"]  = fer_df["data"].dt.month
fer_df["ano"]  = fer_df["data"].dt.year
meses_feriado  = set(zip(fer_df["ano"], fer_df["mes"]))

# ── Enriquecer com colunas auxiliares ───────────────────────────────────────
contagem["timestamp"] = pd.to_datetime(
    contagem["ano_ref"].astype(str) + "-"
    + contagem["mes_ref"].astype(str).str.zfill(2) + "-01"
)

contagem["ferias_escolares"] = contagem["mes_ref"].isin(MESES_FERIAS).astype(int)

contagem["mes_com_feriado"] = contagem.apply(
    lambda r: 1 if (int(r["ano_ref"]), int(r["mes_ref"])) in meses_feriado else 0,
    axis=1,
)

contagem["mes_label"] = (
    contagem["mes_ref"].map(MESES_LABEL)
    + "/"
    + contagem["ano_ref"].astype(str).str[-2:]
)

# ── Exportar ────────────────────────────────────────────────────────────────
final = contagem[[
    "timestamp", "mes_label", "ano_ref", "mes_ref",
    "no_prazo", "com_atraso", "ferias_escolares", "mes_com_feriado",
]]

# Preparar caminhos/keys
output_path = Path(OUTPUT_PATH)
s3_key = str(output_path.as_posix()).lstrip("./")

# Garantir diretório local (se STORAGE_TYPE for local)
s3_config.create_output_directory(output_path.parent)

# Se necessário, obter cliente S3 e garantir bucket
s3_client = None
if s3_config.STORAGE_TYPE == "s3":
    s3_client = s3_config.get_s3_client()
    s3_config.ensure_bucket_exists(s3_client)

# Salvar no storage configurado (local ou s3)
saved = s3_config.save_data_to_storage(final, output_path, s3_key, s3_client=s3_client)

if saved:
    if s3_config.STORAGE_TYPE == "s3":
        print(f"CSV enviado para o bucket: s3://{s3_config.BUCKET_NAME}/{s3_key}")
    else:
        print(f"CSV gerado localmente: {output_path}")
else:
    print("Falha ao salvar o CSV no storage configurado.")

print(f"Total de linhas: {len(final)}")
print()
print(final.to_string(index=False))