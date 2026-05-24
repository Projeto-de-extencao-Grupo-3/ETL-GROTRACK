"""
Script para extrair dados de ordens de serviço do banco de dados e armazenar em CSV.
"""
import logging
import os
from pathlib import Path
from typing import List

import pandas as pd
import mysql.connector
from mysql.connector import Error as MySQLError

# Configuração de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Constantes
DB_HOST = os.getenv('DB_HOST', 'localhost')
DB_PORT = int(os.getenv('DB_PORT', 3306))
DB_USER = os.getenv('DB_USER', 'root')
DB_PASSWORD = os.getenv('DB_PASSWORD', '123456')
DB_NAME = os.getenv('DB_NAME', 'grotrack')
OUTPUT_DIR = Path('refined/os')
REQUEST_TIMEOUT = 10

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
    """Criar diretório de saída se não existir."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


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


def save_to_csv(df: pd.DataFrame, filename: str) -> bool:
    """
    Salvar DataFrame em arquivo CSV.
    
    Args:
        df: DataFrame com dados.
        filename: Nome do arquivo (sem extensão).
        
    Returns:
        True se sucesso, False caso contrário.
    """
    try:
        file_path = OUTPUT_DIR / f'{filename}.csv'
        df.to_csv(file_path, index=False)
        logger.info(f"Arquivo salvo: {filename}.csv")
        return True
        
    except IOError as e:
        logger.error(f"Erro ao salvar arquivo {filename}.csv: {e}")
        return False


def main() -> None:
    """Executar fluxo principal de extração de dados."""
    try:
        create_output_directory()
        conn = connect_to_database()
        
        # Extrair e salvar dados de ordens de serviço
        df_ordens = fetch_data_from_query(conn, QUERY_ORDEM_SERVICO, "Ordens de Serviço")
        if df_ordens is not None:
            save_to_csv(df_ordens, "os_data")
        
        # Extrair e salvar dados de serviços
        df_servicos = fetch_data_from_query(conn, QUERY_SERVICOS, "Serviços")
        if df_servicos is not None:
            save_to_csv(df_servicos, "os_servicos")
        
        logger.info("✓ Extração de dados de ordens concluída")
        
    except Exception as e:
        logger.error(f"Erro inesperado: {e}", exc_info=True)
        raise
    finally:
        if 'conn' in locals() and conn.is_connected():
            conn.close()


if __name__ == '__main__':
    main()
