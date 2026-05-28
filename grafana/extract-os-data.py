"""
Script para extrair dados de ordens de serviço do banco de dados e armazenar em CSV no S3/LocalStack.
"""
import logging
import os
from pathlib import Path

import pandas as pd
import mysql.connector
from mysql.connector import Error as MySQLError

# Importar configurações centralizadas de S3
from s3_config import (
    STORAGE_TYPE,
    get_s3_client,
    ensure_bucket_exists,
    save_data_to_storage,
    create_output_directory
)

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
OUTPUT_DIR = Path('refined/os')

# Queries
QUERY_ORDEM_SERVICO = """
SELECT os.*, re.*, year(os.data_saida_efetiva) AS ano, month(os.data_saida_efetiva) AS mes, day(os.data_saida_efetiva) AS dia, week(os.data_saida_efetiva) AS semana
FROM ordem_de_servicos os
JOIN registro_entrada re 
ON os.id_ordem_servico = re.fk_ordem_servico
WHERE os.status = 'FINALIZADO'
ORDER BY os.data_saida_efetiva;
"""

QUERY_SERVICOS = """
SELECT os.id_ordem_servico, s.*, year(os.data_saida_efetiva) AS ano, month(os.data_saida_efetiva) AS mes, day(os.data_saida_efetiva) AS dia, week(os.data_saida_efetiva) AS semana
FROM ordem_de_servicos os
JOIN itens_servicos s
ON os.id_ordem_servico = s.fk_ordem_servico
JOIN registro_entrada re
ON os.id_ordem_servico = re.fk_ordem_servico
WHERE os.status = 'FINALIZADO'
ORDER BY os.data_saida_efetiva;
"""


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
            create_output_directory(OUTPUT_DIR)
        
        # Conectar ao banco
        conn = connect_to_database()
        
        # Extrair e salvar dados de ordens de serviço
        df_ordens = fetch_data_from_query(conn, QUERY_ORDEM_SERVICO, "Ordens de Serviço")
        if df_ordens is not None:
            file_path_local = OUTPUT_DIR / "os_data.csv"
            s3_key = "refined/os/os_data.csv"
            save_data_to_storage(df_ordens, file_path_local, s3_key, s3_client)
        
        # Extrair e salvar dados de serviços
        df_servicos = fetch_data_from_query(conn, QUERY_SERVICOS, "Serviços")
        if df_servicos is not None:
            file_path_local = OUTPUT_DIR / "os_servicos.csv"
            s3_key = "refined/os/os_servicos.csv"
            save_data_to_storage(df_servicos, file_path_local, s3_key, s3_client)
        
        logger.info("✓ Extração de dados de ordens concluída")
        
    except Exception as e:
        logger.error(f"Erro inesperado: {e}", exc_info=True)
        raise
    finally:
        if 'conn' in locals() and conn.is_connected():
            conn.close()


if __name__ == '__main__':
    main()
