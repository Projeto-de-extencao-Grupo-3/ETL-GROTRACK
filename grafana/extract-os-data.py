"""
Script para extrair dados de ordens de serviço do banco de dados e armazenar em CSV no S3/LocalStack.
"""
import logging
import os
from pathlib import Path
from io import BytesIO

import pandas as pd
import mysql.connector
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

# Constantes - Storage
STORAGE_TYPE = os.getenv('STORAGE_TYPE', 's3')  # 's3' ou 'local'
BUCKET_NAME = os.getenv('BUCKET_NAME', 'grotrack-bucket')
S3_ENDPOINT_URL = os.getenv('S3_ENDPOINT_URL', 'http://localhost:4566')  # LocalStack
AWS_REGION = os.getenv('AWS_REGION', 'us-east-1')
AWS_ACCESS_KEY = os.getenv('AWS_ACCESS_KEY_ID', 'test')
AWS_SECRET_KEY = os.getenv('AWS_SECRET_ACCESS_KEY', 'test')
OUTPUT_DIR = Path('refined/os')

# Queries
QUERY_ORDEM_SERVICO = """
SELECT os.*, re.*, year(os.data_saida_efetiva) AS ano, month(os.data_saida_efetiva) AS mes, day(os.data_saida_efetiva) AS dia
FROM ordem_de_servicos os
JOIN registro_entrada re 
ON os.id_ordem_servico = re.fk_ordem_servico
WHERE os.status = 'FINALIZADO'
ORDER BY os.data_saida_efetiva;
"""

QUERY_SERVICOS = """
SELECT os.id_ordem_servico, s.*, year(os.data_saida_efetiva) AS ano, month(os.data_saida_efetiva) AS mes, day(os.data_saida_efetiva) AS dia
FROM ordem_de_servicos os
JOIN itens_servicos s
ON os.id_ordem_servico = s.fk_ordem_servico
JOIN registro_entrada re
ON os.id_ordem_servico = re.fk_ordem_servico
WHERE os.status = 'FINALIZADO'
ORDER BY os.data_saida_efetiva;
"""


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


def connect_to_database() -> mysql.connector.MySQLConnection:
    """
    Conectar ao banco de dados MySQL.
    
    Returns:
        Conexão com o banco de dados.
        
    Raises:
        MySQLError: Erro ao conectar ao banco.
    """
    try:
        conn = mysql.connector.connect(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME
        )
        logger.info("Conectado ao banco de dados")
        return conn
    except MySQLError as e:
        logger.error(f"Erro ao conectar ao banco de dados: {e}")
        raise


def fetch_data_from_query(conn: mysql.connector.MySQLConnection, query: str, query_name: str) -> pd.DataFrame | None:
    """
    Executar query e retornar dados como DataFrame.
    
    Args:
        conn: Conexão com o banco de dados.
        query: SQL query a ser executada.
        query_name: Nome descritivo da query (para logs).
        
    Returns:
        DataFrame com os dados ou None se erro.
    """
    try:
        df = pd.read_sql(query, conn)
        
        if df.empty:
            logger.warning(f"Nenhum dado encontrado para {query_name}")
            return None
        
        logger.info(f"{query_name}: {len(df)} registros")
        return df
        
    except (MySQLError, pd.errors.DatabaseError) as e:
        logger.error(f"Erro ao buscar dados de {query_name}: {e}")
        return None


def save_to_storage(df: pd.DataFrame, filename: str, s3_client=None) -> bool:
    """
    Salvar DataFrame em S3 ou armazenamento local.
    
    Args:
        df: DataFrame com dados.
        filename: Nome do arquivo (sem extensão).
        s3_client: Cliente S3 (obrigatório se STORAGE_TYPE='s3').
        
    Returns:
        True se sucesso, False caso contrário.
    """
    if STORAGE_TYPE == 's3':
        return _save_to_s3(df, filename, s3_client)
    else:
        return _save_to_local(df, filename)


def _save_to_local(df: pd.DataFrame, filename: str) -> bool:
    """Salvar arquivo localmente."""
    try:
        file_path = OUTPUT_DIR / f'{filename}.csv'
        df.to_csv(file_path, index=False)
        logger.info(f"Arquivo salvo localmente: {filename}.csv")
        return True
    except IOError as e:
        logger.error(f"Erro ao salvar arquivo {filename}.csv: {e}")
        return False


def _save_to_s3(df: pd.DataFrame, filename: str, s3_client) -> bool:
    """Salvar arquivo no S3."""
    try:
        # Criar path S3
        s3_key = f"{OUTPUT_DIR}/{filename}.csv"
        
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
    """Executar fluxo principal de extração de dados."""
    try:
        # Inicializar storage
        s3_client = None
        if STORAGE_TYPE == 's3':
            s3_client = get_s3_client()
            if not ensure_bucket_exists(s3_client):
                raise Exception("Não foi possível garantir a existência do bucket S3")
        else:
            create_output_directory()
        
        # Conectar ao banco
        conn = connect_to_database()
        
        # Extrair e salvar dados de ordens de serviço
        df_ordens = fetch_data_from_query(conn, QUERY_ORDEM_SERVICO, "Ordens de Serviço")
        if df_ordens is not None:
            save_to_storage(df_ordens, "os_data", s3_client)
        
        # Extrair e salvar dados de serviços
        df_servicos = fetch_data_from_query(conn, QUERY_SERVICOS, "Serviços")
        if df_servicos is not None:
            save_to_storage(df_servicos, "os_servicos", s3_client)
        
        logger.info("✓ Extração de dados de ordens concluída")
        
    except Exception as e:
        logger.error(f"Erro inesperado: {e}", exc_info=True)
        raise
    finally:
        if 'conn' in locals() and conn.is_connected():
            conn.close()


if __name__ == '__main__':
    main()
