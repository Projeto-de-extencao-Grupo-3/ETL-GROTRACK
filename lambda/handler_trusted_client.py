import io
import os
from urllib.parse import unquote_plus

import boto3
import pandas as pd

s3 = boto3.client("s3")
DEST_BUCKET = "grotrack-bucket-client"

def _read_csv(bucket: str, key: str) -> pd.DataFrame:
    obj = s3.get_object(Bucket=bucket, Key=key)
    content = obj["Body"].read().decode("utf-8-sig")
    
    df = pd.read_csv(io.StringIO(content), sep=None, engine='python')
    
    if isinstance(df.columns[0], int) or df.columns[0] == '0':
        df.columns = df.iloc[0] 
        df = df[1:].reset_index(drop=True) 
    
    df.columns = [str(col).strip().upper() for col in df.columns]
    
    print(f"DEBUG: Colunas finais após correção: {df.columns.tolist()}")
    return df


def _write_csv(bucket: str, key: str, df: pd.DataFrame) -> None:
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    s3.put_object(Bucket=bucket, Key=key, Body=buf.getvalue().encode("utf-8"), ContentType="text/csv")


def _refine_datatran_sp_falhas_mecanicas(df: pd.DataFrame) -> pd.DataFrame:
    # client: SP + falhas mecânicas/elétricas
    df_sp = df[df["ESTADO"].astype(str).str.upper().str.strip().eq("SP")].copy()
    df_out = df_sp[df_sp["CAUSA_ACIDENTE"].astype(str).str.contains("falhas mec", case=False, na=False)].copy()
    return df_out

def _refine_datatran_sp(df: pd.DataFrame) -> pd.DataFrame:
    # client: SP
    df_out = df[df["ESTADO"].astype(str).str.upper().str.strip().eq("SP")].copy()
    return df_out

def _refine_feriados_mes(df: pd.DataFrame) -> pd.DataFrame:
    return df

def _refine_feriados_nacional(df: pd.DataFrame) -> pd.DataFrame:
    if "TIPO" in df.columns:
        df = df[df["TIPO"].isna() | (df["TIPO"].astype(str).str.upper().str.strip().eq("NACIONAL"))].copy()
    return df

def _refine_feriados_qtd_por_tipo(df: pd.DataFrame) -> pd.DataFrame:
    if "TIPO" in df.columns:
        df_out = df.groupby("TIPO").size().reset_index(name="QTD_FERIADOS")
    else:
        df_out = pd.DataFrame(columns=["TIPO", "QTD_FERIADOS"])
    return df_out

def _refine_feriados_qtd_por_estado(df: pd.DataFrame) -> pd.DataFrame:
    if "ESTADO" in df.columns:
        df_out = df.groupby("ESTADO").size().reset_index(name="QTD_FERIADOS")
    else:
        df_out = pd.DataFrame(columns=["ESTADO", "QTD_FERIADOS"])
    return df_out

def _refine_feriados_qtd_por_mes(df: pd.DataFrame) -> pd.DataFrame:
    df_out = df.groupby("MES").size().reset_index(name="QTD_FERIADOS")
    return df_out

def _refine_feriados_sp(df: pd.DataFrame) -> pd.DataFrame:
    if "ESTADO" in df.columns:
        df_out = df[df["ESTADO"].astype(str).str.upper().str.strip().eq("SP")].copy()
    else:
        df_out = pd.DataFrame(columns=df.columns)
    return df_out

def lambda_handler(event, context):
    processed = []
    client_prefix = "client/"

    for record in event.get("Records", []):
        bucket = record["s3"]["bucket"]["name"]
        key = unquote_plus(record["s3"]["object"]["key"])

        if not key.lower().endswith(".csv"):
            continue

        lower_key = key.lower()

        # usa SOMENTE os consolidados do trusted
        if lower_key == "datatran/trusted_datatran.csv":
            df = _read_csv(bucket, key)

            outputs = {
                f"{client_prefix}datatran/refined_datatran_sp.csv": _refine_datatran_sp(df),
                f"{client_prefix}datatran/refined_datatran_sp_falhas_mecanicas.csv": _refine_datatran_sp_falhas_mecanicas(df),
            }

        elif lower_key == "feriados/trusted_feriados.csv":
            df_raw = _read_csv(bucket, key)
            
            if "DATA" not in df_raw.columns:
                print(f"ERRO: Coluna DATA não encontrada. Colunas: {df_raw.columns.tolist()}")
                continue
            
            df_raw["DATA"] = pd.to_datetime(df_raw["DATA"], errors="coerce", dayfirst=True)
            df_raw["MES"] = df_raw["DATA"].dt.month

            outputs = {
                f"{client_prefix}feriados/refined_feriados_sp.csv": _refine_feriados_sp(df_raw.copy()),
                f"{client_prefix}feriados/refined_feriados_mes.csv": _refine_feriados_mes(df_raw.copy()),
                f"{client_prefix}feriados/refined_feriados_nacional.csv": _refine_feriados_nacional(df_raw.copy()),
                f"{client_prefix}feriados/refined_feriados_por_tipo.csv": _refine_feriados_qtd_por_tipo(df_raw.copy()),
                f"{client_prefix}feriados/refined_feriados_por_estado.csv": _refine_feriados_qtd_por_estado(df_raw.copy()),
                f"{client_prefix}feriados/refined_feriados_por_mes.csv": _refine_feriados_qtd_por_mes(df_raw.copy()),
            }

        else:
            continue

        for out_key, df_out in outputs.items():
            _write_csv(DEST_BUCKET, out_key, df_out)
            processed.append({"in": key, "out": out_key, "rows": len(df_out)})

    return {"statusCode": 200, "processed": processed}