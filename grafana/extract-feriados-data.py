import logging
import os
from pathlib import Path
from typing import List

import pandas as pd
import mysql.connector
import requests
from mysql.connector import Error as MySQLError

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

DB_HOST = os.getenv('DB_HOST', 'localhost')
DB_PORT = int(os.getenv('DB_PORT', 3306))
DB_USER = os.getenv('DB_USER', 'root')
DB_PASSWORD = os.getenv('DB_PASSWORD', '123456')
DB_NAME = os.getenv('DB_NAME', 'grotrack')
API_KEY = os.getenv('FERIADOS_API_KEY', 'removidaPorseg')
API_URL = 'https://feriadosapi.com/api/v1/feriados/nacionais'
OUTPUT_DIR = Path('refined/feriados')
REQUEST_TIMEOUT = 10


def create_output_directory() -> None:
    """Criar diretório de saída se não existir."""
    OUTPUT_DIR.mkdir(exist_ok=True)


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


def save_to_csv(df: pd.DataFrame, year: int) -> bool:
    """
    Salvar DataFrame em arquivo CSV.
    
    Args:
        df: DataFrame com dados de feriados.
        year: Ano dos feriados.
        
    Returns:
        True se sucesso, False caso contrário.
    """
    try:
        file_path = OUTPUT_DIR / f'feriados_{year}.csv'
        df.to_csv(file_path, index=False)
        logger.info(f"Arquivo salvo: feriados_{year}.csv")
        return True
        
    except IOError as e:
        logger.error(f"Erro ao salvar arquivo para {year}: {e}")
        return False


def main() -> None:
    """Executar fluxo principal de extração de feriados."""
    try:
        create_output_directory()
        anos = fetch_years_from_database()
        
        if not anos:
            logger.warning("Nenhum ano encontrado no banco de dados")
            return
        
        for ano in anos:
            logger.info(f"Processando ano: {ano}")
            df = fetch_holidays_from_api(ano)
            
            if df is not None and not df.empty:
                save_to_csv(df, ano)
            else:
                logger.warning(f"Sem dados para o ano {ano}")
        
        logger.info("✓ Extração de feriados concluída")
        
    except Exception as e:
        logger.error(f"Erro inesperado: {e}", exc_info=True)
        raise


if __name__ == '__main__':
    main()