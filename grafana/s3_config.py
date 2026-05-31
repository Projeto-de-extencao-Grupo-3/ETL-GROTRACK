"""
Módulo centralizado de configuração e funções reutilizáveis para S3/LocalStack.
Centraliza todas as configurações de storage para facilitar gestão e desenvolvimento.
"""
import logging
import os
from pathlib import Path
from io import BytesIO

import pandas as pd
import boto3
from botocore.exceptions import ClientError

# Configuração de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============================================================================
# CONSTANTES DE CONFIGURAÇÃO S3/LOCALSTACK
# ============================================================================

STORAGE_TYPE = os.getenv('STORAGE_TYPE', 'local')  # 's3' ou 'local'
BUCKET_NAME = os.getenv('BUCKET_NAME', 'grotrack-bucket-os')
S3_ENDPOINT_URL = os.getenv('S3_ENDPOINT_URL', 'http://localhost:4566')  # LocalStack
AWS_REGION = os.getenv('AWS_REGION', 'us-east-1')
AWS_ACCESS_KEY = os.getenv('AWS_ACCESS_KEY_ID', 'test')
AWS_SECRET_KEY = os.getenv('AWS_SECRET_ACCESS_KEY', 'test')

# ============================================================================
# FUNÇÕES REUTILIZÁVEIS PARA S3
# ============================================================================


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


def _load_from_s3(s3_client, s3_key: str, filename: str) -> pd.DataFrame:
    """
    Carregar arquivo CSV do S3.
    
    Args:
        s3_client: Cliente S3.
        s3_key: Chave do arquivo no S3.
        filename: Nome descritivo do arquivo (para logs).
        
    Returns:
        DataFrame com os dados.
        
    Raises:
        ClientError: Se erro ao ler do S3.
    """
    try:
        response = s3_client.get_object(Bucket=BUCKET_NAME, Key=s3_key)
        df = pd.read_csv(response['Body'])
        logger.info(f"✓ Carregados {len(df)} registros de {filename} do S3")
        return df
    except ClientError as e:
        logger.error(f"Erro ao carregar {filename} do S3: {e}")
        raise


def _load_from_local(file_path: Path, filename: str) -> pd.DataFrame:
    """
    Carregar arquivo CSV localmente.
    
    Args:
        file_path: Caminho do arquivo local.
        filename: Nome descritivo do arquivo (para logs).
        
    Returns:
        DataFrame com os dados.
        
    Raises:
        FileNotFoundError: Se arquivo não existir.
    """
    if not file_path.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {file_path}")
    
    df = pd.read_csv(file_path)
    logger.info(f"✓ Carregados {len(df)} registros de {filename}")
    return df


def load_data_from_storage(file_path_local: Path, s3_key: str, filename: str, s3_client=None) -> pd.DataFrame:
    """
    Carregar arquivo de S3 ou armazenamento local (abstração).
    
    Args:
        file_path_local: Caminho do arquivo local (usado se STORAGE_TYPE='local').
        s3_key: Chave do arquivo no S3 (usado se STORAGE_TYPE='s3').
        filename: Nome descritivo do arquivo (para logs).
        s3_client: Cliente S3 (obrigatório se STORAGE_TYPE='s3').
    
    Returns:
        DataFrame com os dados.
        
    Raises:
        FileNotFoundError ou ClientError: Se arquivo não existir.
    """
    if STORAGE_TYPE == 's3':
        return _load_from_s3(s3_client, s3_key, filename)
    else:
        return _load_from_local(file_path_local, filename)


def _save_to_local(df: pd.DataFrame, file_path: Path) -> bool:
    """
    Salvar arquivo localmente.
    
    Args:
        df: DataFrame com dados.
        file_path: Caminho completo do arquivo (incluindo nome e extensão).
        
    Returns:
        True se sucesso, False caso contrário.
    """
    try:
        df.to_csv(file_path, index=False)
        logger.info(f"✓ Arquivo salvo localmente: {file_path}")
        return True
    except IOError as e:
        logger.error(f"Erro ao salvar arquivo {file_path}: {e}")
        return False


def _save_to_s3(df: pd.DataFrame, s3_key: str, s3_client) -> bool:
    """
    Salvar arquivo no S3.
    
    Args:
        df: DataFrame com dados.
        s3_key: Chave do arquivo no S3 (caminho completo com nome).
        s3_client: Cliente S3.
        
    Returns:
        True se sucesso, False caso contrário.
    """
    try:
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
        logger.info(f"✓ Arquivo salvo no S3: s3://{BUCKET_NAME}/{s3_key}")
        return True
        
    except ClientError as e:
        logger.error(f"Erro ao salvar no S3: {e}")
        return False


def save_data_to_storage(
    df: pd.DataFrame,
    file_path_local: Path,
    s3_key: str,
    s3_client=None
) -> bool:
    """
    Salvar arquivo em S3 ou armazenamento local (abstração).
    
    Args:
        df: DataFrame com dados.
        file_path_local: Caminho completo do arquivo local (usado se STORAGE_TYPE='local').
        s3_key: Chave do arquivo no S3 (usado se STORAGE_TYPE='s3').
        s3_client: Cliente S3 (obrigatório se STORAGE_TYPE='s3').
        
    Returns:
        True se sucesso, False caso contrário.
    """
    if STORAGE_TYPE == 's3':
        return _save_to_s3(df, s3_key, s3_client)
    else:
        return _save_to_local(df, file_path_local)


def create_output_directory(output_dir: Path) -> None:
    """
    Criar diretório de saída se não existir (para armazenamento local).
    
    Args:
        output_dir: Caminho do diretório a ser criado.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
