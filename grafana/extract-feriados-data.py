"""
Script para extrair dados de feriados da API e armazenar em CSV no S3/LocalStack.
"""
import logging
import os
from pathlib import Path
from typing import List
from io import BytesIO

import pandas as pd
import mysql.connector
import requests
import boto3
from mysql.connector import Error as MySQLError
from botocore.exceptions import ClientError

# Configuração de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Constantes - Banco de Dados
DB_HOST = os.getenv('DB_HOST', 'localhost')
DB_PORT = int(os.getenv('DB_PORT', 3306))
DB_USER = os.getenv('DB_USER', 'root')
DB_PASSWORD = os.getenv('DB_PASSWORD', '123456')
DB_NAME = os.getenv('DB_NAME', 'grotrack')

# Constantes - API
API_KEY = os.getenv('FERIADOS_API_KEY', 'AQUI_VAI_SUA_CHAVE_DE_API')
API_URL = 'https://feriadosapi.com/api/v1/feriados/nacionais'
REQUEST_TIMEOUT = 10

# Constantes - Storage
STORAGE_TYPE = os.getenv('STORAGE_TYPE', 's3')  # 's3' ou 'local'
BUCKET_NAME = os.getenv('BUCKET_NAME', 'grotrack-bucket')
S3_ENDPOINT_URL = os.getenv('S3_ENDPOINT_URL', 'http://localhost:4566')  # LocalStack
AWS_REGION = os.getenv('AWS_REGION', 'us-east-1')
AWS_ACCESS_KEY = os.getenv('AWS_ACCESS_KEY_ID', 'test')
AWS_SECRET_KEY = os.getenv('AWS_SECRET_ACCESS_KEY', 'test')
OUTPUT_DIR = Path('refined/feriados')


def create_output_directory() -> None:
    """Criar diretório local se não existir (para fallback)."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def get_s3_client():
    """
    Obter cliente S3 configurado para LocalStack ou AWS.
    
    Returns:
        Cliente boto3 S3.
    """
    if 'localhost' in S3_ENDPOINT_URL or '127.0.0.1' in S3_ENDPOINT_URL:
        # LocalStack
        return boto3.client(
            's3',
            endpoint_url=S3_ENDPOINT_URL,
            aws_access_key_id=AWS_ACCESS_KEY,
            aws_secret_access_key=AWS_SECRET_KEY,
            region_name=AWS_REGION
        )
    else:
        # AWS S3 Produção
        return boto3.client(
            's3',
            region_name=AWS_REGION,
            aws_access_key_id=AWS_ACCESS_KEY,
            aws_secret_access_key=AWS_SECRET_KEY
        )


def ensure_bucket_exists(s3_client) -> bool:
    """
    Verificar se bucket existe, criar se necessário.
    
    Args:
        s3_client: Cliente S3.
        
    Returns:
        True se bucket existe ou foi criado.
    """
    try:
        s3_client.head_bucket(Bucket=BUCKET_NAME)
        logger.info(f"Bucket '{BUCKET_NAME}' já existe")
        return True
    except ClientError as e:
        if e.response['Error']['Code'] == '404':
            try:
                s3_client.create_bucket(Bucket=BUCKET_NAME)
                logger.info(f"Bucket '{BUCKET_NAME}' criado com sucesso")
                return True
            except ClientError as create_error:
                logger.error(f"Erro ao criar bucket: {create_error}")
                return False
        else:
            logger.error(f"Erro ao verificar bucket: {e}")
            return False


def fetch_years_from_database() -> List[int]:
    """
    Recuperar anos disponíveis do banco de dados.
    
    Returns:
        Lista de anos disponíveis.
        
    Raises:
        MySQLError: Erro ao conectar ou executar query no banco.
    """
    try:
        conn = mysql.connector.connect(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME
        )
        
        select_anos = "SELECT DISTINCT YEAR(data_entrada_efetiva) AS ano FROM registro_entrada WHERE data_entrada_efetiva IS NOT NULL ORDER BY ano;"
        
        with conn.cursor() as cursor:
            cursor.execute(select_anos)
            anos = [row[0] for row in cursor.fetchall()]
        
        logger.info(f"Encontrados {len(anos)} ano(s) no banco de dados")
        return anos
        
    except MySQLError as e:
        logger.error(f"Erro ao conectar ao banco de dados: {e}")
        raise
    finally:
        if conn.is_connected():
            conn.close()


def fetch_holidays_from_api(year: int) -> pd.DataFrame | None:
    """
    Buscar dados de feriados da API.
    
    Args:
        year: Ano para buscar feriados.
        
    Returns:
        DataFrame com dados de feriados ou None se falha na requisição.
    """
    try:
        headers = {'Authorization': f'Bearer {API_KEY}'}
        response = requests.get(
            f'{API_URL}?ano={year}',
            headers=headers,
            timeout=REQUEST_TIMEOUT
        )
        response.raise_for_status()
        
        data = response.json()
        
        # Extrair dados se estiverem dentro de um dicionário
        if isinstance(data, dict):
            for key in ['data', 'feriados', 'holidays', 'results']:
                if key in data:
                    data = data[key]
                    break
        
        if not isinstance(data, list):
            logger.warning(f"Nenhum dado válido para o ano {year}")
            return None
        
        if not data:
            return pd.DataFrame()
        
        df = pd.DataFrame(data)
        logger.info(f"Feriados para {year}: {len(df)} registros")
        
        return df
        
    except (requests.exceptions.RequestException, ValueError) as e:
        logger.error(f"Erro ao buscar feriados para {year}: {e}")
        return None


def save_to_storage(df: pd.DataFrame, year: int, s3_client=None) -> bool:
    """
    Salvar DataFrame em S3 ou armazenamento local.
    
    Args:
        df: DataFrame com dados de feriados.
        year: Ano dos feriados.
        s3_client: Cliente S3 (obrigatório se STORAGE_TYPE='s3').
        
    Returns:
        True se sucesso, False caso contrário.
    """
    filename = f'feriados_{year}.csv'
    
    if STORAGE_TYPE == 's3':
        return _save_to_s3(df, filename, s3_client)
    else:
        return _save_to_local(df, filename)


def _save_to_local(df: pd.DataFrame, filename: str) -> bool:
    """Salvar arquivo localmente."""
    try:
        file_path = OUTPUT_DIR / filename
        df.to_csv(file_path, index=False)
        logger.info(f"Arquivo salvo localmente: {filename}")
        return True
    except IOError as e:
        logger.error(f"Erro ao salvar arquivo {filename}: {e}")
        return False


def _save_to_s3(df: pd.DataFrame, filename: str, s3_client) -> bool:
    """Salvar arquivo no S3."""
    try:
        # Criar path S3
        s3_key = f"{OUTPUT_DIR}/{filename}"
        
        # Converter DataFrame para CSV em memória
        csv_buffer = BytesIO()
        df.to_csv(csv_buffer, index=False)
        csv_buffer.seek(0)
        
        # Upload para S3
        s3_client.put_object(
            Bucket=BUCKET_NAME,
            Key=s3_key,
            Body=csv_buffer.getvalue()
        )
        logger.info(f"Arquivo salvo no S3: s3://{BUCKET_NAME}/{s3_key}")
        return True
        
    except ClientError as e:
        logger.error(f"Erro ao salvar no S3: {e}")
        return False


def main() -> None:
    """Executar fluxo principal de extração de feriados."""
    try:
        # Inicializar storage
        s3_client = None
        if STORAGE_TYPE == 's3':
            s3_client = get_s3_client()
            if not ensure_bucket_exists(s3_client):
                raise Exception("Não foi possível garantir a existência do bucket S3")
        else:
            create_output_directory()
        
        # Obter anos do banco
        anos = fetch_years_from_database()
        
        if not anos:
            logger.warning("Nenhum ano encontrado no banco de dados")
            return
        
        # Processar cada ano
        for ano in anos:
            logger.info(f"Processando ano: {ano}")
            df = fetch_holidays_from_api(ano)
            
            if df is not None and not df.empty:
                save_to_storage(df, ano, s3_client)
            else:
                logger.warning(f"Sem dados para o ano {ano}")
        
        logger.info("✓ Extração de feriados concluída")
        
    except Exception as e:
        logger.error(f"Erro inesperado: {e}", exc_info=True)
        raise


if __name__ == '__main__':
    main()