"""
Lambda para padronizar CSVs do bucket raw e enviar para o bucket trusted.
Triggered por: s3:ObjectCreated:* no bucket grotrack-bucket-raw
"""
import io
import logging
import urllib.parse

import boto3
import pandas as pd

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3 = boto3.client('s3')

TRUSTED_BUCKET = 'grotrack-bucket-trusted'

# Mapeamento: nome do arquivo -> prefixo de destino no trusted
FILE_MAP = {
    'feriados_data.csv': 'feriados/',
    'os_data.csv':       'database/',
    'os_servicos.csv':   'database/',
}

# Colunas numéricas com 2 casas decimais por arquivo
NUMERIC_COLS = {
    'feriados_data.csv': [],
    'os_data.csv':       ['valor_total', 'valor_total_servicos', 'valor_total_produtos'],
    'os_servicos.csv':   ['preco_cobrado'],
}

# Colunas de data para converter para ISO (YYYY-MM-DD) por arquivo
DATE_COLS = {
    'feriados_data.csv': ['data'],
    'os_data.csv':       ['data_saida_prevista', 'data_saida_efetiva',
                          'data_atualizacao', 'data_entrada_prevista',
                          'data_entrada_efetiva'],
    'os_servicos.csv':   [],
}


def _parse_date(series: pd.Series) -> pd.Series:
    """Tenta converter datas em múltiplos formatos para ISO YYYY-MM-DD."""
    for fmt in ('%d/%m/%Y', '%Y-%m-%d', '%Y-%m-%d %H:%M:%S'):
        try:
            return pd.to_datetime(series, format=fmt, errors='raise').dt.strftime('%Y-%m-%d')
        except (ValueError, TypeError):
            continue
    return pd.to_datetime(series, errors='coerce').dt.strftime('%Y-%m-%d')


def transform(df: pd.DataFrame, filename: str) -> pd.DataFrame:
    """Aplicar transformações de padronização no DataFrame."""

    # 1. Cabeçalhos em maiúsculo
    df.columns = [col.upper() for col in df.columns]

    # 2. Remover espaços em branco nos valores de texto
    str_cols = df.select_dtypes(include='object').columns
    df[str_cols] = df[str_cols].apply(lambda col: col.str.strip())

    # 3. Valores numéricos com 2 casas decimais
    for col in NUMERIC_COLS.get(filename, []):
        col_upper = col.upper()
        if col_upper in df.columns:
            df[col_upper] = pd.to_numeric(df[col_upper], errors='coerce').round(2)

    # 4. Datas para formato ISO
    for col in DATE_COLS.get(filename, []):
        col_upper = col.upper()
        if col_upper in df.columns:
            df[col_upper] = _parse_date(df[col_upper])

    # 5. Booleanos padronizados (True/False -> SIM/NAO)
    bool_cols = ['BANCARIO', 'NF_REALIZADA', 'PAGT_REALIZADO', 'ATIVO']
    for col in bool_cols:
        if col in df.columns:
            df[col] = df[col].map(
                lambda v: 'SIM' if str(v).strip().upper() in ('TRUE', '1', 'SIM') else 'NAO'
            )

    # 6. Remover linhas completamente vazias
    df.dropna(how='all', inplace=True)

    return df


def lambda_handler(event, context):
    for record in event['Records']:
        src_bucket = record['s3']['bucket']['name']
        src_key    = urllib.parse.unquote_plus(record['s3']['object']['key'])

        logger.info(f"Processando: s3://{src_bucket}/{src_key}")

        filename   = src_key.split('/')[-1]
        dst_prefix = FILE_MAP.get(filename)

        if dst_prefix is None:
            logger.warning(f"Arquivo '{filename}' não mapeado, ignorando.")
            continue

        dst_key = dst_prefix + filename

        # Ler CSV do raw
        try:
            response = s3.get_object(Bucket=src_bucket, Key=src_key)
            df = pd.read_csv(io.BytesIO(response['Body'].read()))
            logger.info(f"Lidos {len(df)} registros de '{filename}'")
        except Exception as e:
            logger.error(f"Erro ao ler '{src_key}': {e}")
            raise

        # Transformar
        df = transform(df, filename)
        logger.info(f"Transformação concluída: {len(df)} registros, {len(df.columns)} colunas")

        # Salvar no trusted
        try:
            buf = io.BytesIO()
            df.to_csv(buf, index=False)
            buf.seek(0)
            s3.put_object(Bucket=TRUSTED_BUCKET, Key=dst_key, Body=buf.getvalue())
            logger.info(f"Salvo em: s3://{TRUSTED_BUCKET}/{dst_key}")
        except Exception as e:
            logger.error(f"Erro ao salvar '{dst_key}': {e}")
            raise

    return {'statusCode': 200, 'body': 'OK'}