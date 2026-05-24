import io
import os
import re
from urllib.parse import unquote_plus

import boto3
import pandas as pd

s3 = boto3.client("s3")
DEST_BUCKET = "grotrack-bucket-trusted"

def _read_text(bucket: str, key: str) -> str:
    obj = s3.get_object(Bucket=bucket, Key=key)
    data = obj["Body"].read()
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("latin1")


def _read_csv_flex(text: str, default_sep: str = ",") -> pd.DataFrame:
    text = re.sub(r",\s*$", "", text, flags=re.MULTILINE)

    for sep in [default_sep, ";", ","]:
        try:
            return pd.read_csv(
                io.StringIO(text),
                sep=sep,
                dtype=str,
                on_bad_lines="skip",
                engine="python",
                header=None if sep == "," else "infer",
            )
        except Exception:
            pass
    raise ValueError("Não foi possível ler CSV")


def _clean_datatran(df: pd.DataFrame) -> pd.DataFrame:
    df.columns = df.columns.astype(str).str.strip().str.upper().str.replace(",", "", regex=False)
    df = df.rename(columns={"DATA_INVERSA": "DATA", "UF": "ESTADO", "MUNICIPIO": "CIDADE"})
    df = df.drop(
        columns=["BR", "KM", "LATITUDE", "LONGITUDE", "DELEGACIA", "UOP", "USO_SOLO", "FERIDOS_LEVES", "FERIDOS_GRAVES", "IGNORADOS"],
        errors="ignore",
    )
    for c in df.select_dtypes(include=["object"]).columns:
        df[c] = df[c].astype(str).str.strip()
    if "DATA" in df.columns:
        df["DATA"] = pd.to_datetime(df["DATA"], errors="coerce", dayfirst=True)
        df["MES"] = df["DATA"].dt.month
    return df


def _clean_feriado(df: pd.DataFrame, key: str) -> pd.DataFrame:
    df = df.dropna(axis=1, how="all")

    col_count = df.shape[1]

    if "nacional" in key:
        headers = ["DATA", "DIA", "TIPO", "DESCRICAO"]
    elif "estadual" in key:
        headers = ["DATA", "DIA", "TIPO", "DESCRICAO", "ESTADO"]
    else:
        if col_count == 6:
            headers = ["DATA", "DIA", "TIPO", "DESCRICAO", "ESTADO", "CODIGO_MUNICIPIO"]
        else:
            headers = ["DATA", "DIA", "TIPO", "DESCRICAO", "ESTADO"]

    df.columns = headers
    df["DIA"] = (
        df["DIA"].astype(str)
        .str.replace(r"^\s*Dia d[eoa]?\s+", "", regex=True, case=False)
        .str.strip()
    )
    return df


def _write_csv(bucket: str, key: str, df: pd.DataFrame) -> None:
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    s3.put_object(Bucket=bucket, Key=key, Body=buf.getvalue().encode("utf-8"), ContentType="text/csv")

def _exists(bucket: str, key: str) -> bool:
    try:
        s3.head_object(Bucket=bucket, Key=key)
        return True
    except Exception:
        return False


def _merge_feriados(bucket: str, trusted_prefix: str) -> None:
    keys = [
        f"{trusted_prefix}trusted_feriado_estadual.csv",
        f"{trusted_prefix}trusted_feriado_facultativo.csv",
        f"{trusted_prefix}trusted_feriado_nacional.csv",
        f"{trusted_prefix}trusted_feriado_municipal.csv",
    ]

    if not all(_exists(bucket, k) for k in keys):
        return

    dfs = []
    for k in keys:
        obj = s3.get_object(Bucket=bucket, Key=k)
        dfs.append(pd.read_csv(io.BytesIO(obj["Body"].read()), header=0))

    df_final = pd.concat(dfs, ignore_index=True)
    _write_csv(bucket, f"{trusted_prefix}trusted_feriados.csv", df_final)

def lambda_handler(event, context):
    trusted_prefix = os.environ.get("TRUSTED_PREFIX", "trusted/")
    processed = []

    for record in event.get("Records", []):
        source_bucket = record["s3"]["bucket"]["name"]
        key = unquote_plus(record["s3"]["object"]["key"])

        if not key.startswith("analise/") or not key.lower().endswith(".csv"):
            continue

        text = _read_text(source_bucket, key)
        is_datatran = "datatran" in key.lower()
        default_sep = ";" if is_datatran else ","
        df_raw = _read_csv_flex(text, default_sep=default_sep)

        if is_datatran:
            df_out = _clean_datatran(df_raw)
            trusted_prefix = "datatran/"
        else:
            df_out = _clean_feriado(df_raw, key.lower())
            trusted_prefix = "feriados/"

        filename = key.split("/")[-1].replace("raw_", "trusted_")
        out_key = f"{trusted_prefix}{filename}"
        _write_csv(DEST_BUCKET, out_key, df_out)

        if not is_datatran and "feriado" in key.lower():
            _merge_feriados(DEST_BUCKET, trusted_prefix)

        processed.append({
            "in": f"s3://{source_bucket}/{key}",
            "out": f"s3://{DEST_BUCKET}/{out_key}",
            "rows": len(df_out),
        })

    return {"statusCode": 200, "processed": processed}