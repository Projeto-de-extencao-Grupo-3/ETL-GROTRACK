"""
Script para extrair dados de feriados da API e períodos de férias do banco, consolidando em CSV no S3/LocalStack.
"""
import logging
import os
from pathlib import Path
from typing import List
from uuid import uuid4

import pandas as pd
import mysql.connector
import requests
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

# Constantes - API
API_KEY = os.getenv('FERIADOS_API_KEY', 'sk_live_ca4bf9d7427ab2f5ad00511f70b585a629a1000179ccdd5c')
API_URL = 'https://feriadosapi.com/api/v1/feriados/nacionais'
REQUEST_TIMEOUT = 10

# Constantes - Storage
OUTPUT_DIR = Path('refined/feriados')


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


def fetch_vacation_periods_from_database(year: int) -> pd.DataFrame | None:
    """
    Buscar períodos de férias escolares (junho e janeiro) do banco de dados para um ano específico.
    
    Args:
        year: Ano para buscar períodos de férias.
        
    Returns:
        DataFrame com dados de férias ou None se falha na conexão.
    """
    try:
        conn = mysql.connector.connect(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME
        )
        
        # Query para buscar períodos de férias em junho e janeiro
        select_ferias = """
            SELECT 
                MONTH(data_entrada_efetiva) as mes,
                YEAR(data_entrada_efetiva) as ano,
                MIN(DATE_FORMAT(data_entrada_efetiva, '%d/%m/%Y')) as data_inicio,
                MAX(DATE_FORMAT(data_entrada_efetiva, '%d/%m/%Y')) as data_fim,
                COUNT(*) as quantidade
            FROM registro_entrada 
            WHERE YEAR(data_entrada_efetiva) = %s 
            AND MONTH(data_entrada_efetiva) IN (1, 6)
            AND data_entrada_efetiva IS NOT NULL
            GROUP BY YEAR(data_entrada_efetiva), MONTH(data_entrada_efetiva)
            ORDER BY MONTH(data_entrada_efetiva)
        """
        
        with conn.cursor() as cursor:
            cursor.execute(select_ferias, (year,))
            rows = cursor.fetchall()
        
        if not rows:
            return None
        
        # Formatar dados para DataFrame
        data_list = []
        mes_nomes = {1: 'Janeiro', 6: 'Junho'}
        
        for row in rows:
            mes = row[0]
            ano = row[1]
            data_inicio = row[2]
            data_fim = row[3]
            quantidade = row[4]
            
            data_list.append({
                'id': str(uuid4()),
                'data': data_inicio,  # data de início do período
                'nome': f'Férias Escolares - {mes_nomes[mes]}',
                'tipo': 'FÉRIAS',
                'descricao': f"Período de férias escolares de {mes_nomes[mes].lower()} de {ano}. Período: {data_inicio} a {data_fim} ({quantidade} registros).",
                'uf': '',
                'codigo_ibge': '',
                'bancario': False
            })
        
        df = pd.DataFrame(data_list)
        logger.info(f"Períodos de férias para {year}: {len(df)} período(s)")
        return df
        
    except MySQLError as e:
        logger.error(f"Erro ao buscar períodos de férias para {year}: {e}")
        return None
    finally:
        if conn.is_connected():
            conn.close()


def main() -> None:
    """Executar fluxo principal de extração de feriados e períodos de férias."""
    try:
        # Inicializar storage
        s3_client = None
        if STORAGE_TYPE == 's3':
            s3_client = get_s3_client()
            if not ensure_bucket_exists(s3_client):
                raise Exception("Não foi possível garantir a existência do bucket S3")
        else:
            create_output_directory(OUTPUT_DIR)
        
        # Obter anos do banco
        anos = fetch_years_from_database()
        
        if not anos:
            logger.warning("Nenhum ano encontrado no banco de dados")
            return
        
        # Coletar DataFrames de todos os anos
        all_dataframes = []
        
        for ano in anos:
            logger.info(f"Processando ano: {ano}")
            
            # Buscar feriados
            df_feriados = fetch_holidays_from_api(ano)
            if df_feriados is not None and not df_feriados.empty:
                all_dataframes.append(df_feriados)
            else:
                logger.warning(f"Sem dados de feriados para o ano {ano}")
            
            # Buscar períodos de férias
            df_ferias = fetch_vacation_periods_from_database(ano)
            if df_ferias is not None and not df_ferias.empty:
                all_dataframes.append(df_ferias)
            else:
                logger.warning(f"Sem dados de férias para o ano {ano}")
        
        # Consolidar todos os DataFrames em um único arquivo
        if all_dataframes:
            df_consolidado = pd.concat(all_dataframes, ignore_index=True)
            # Garantir que as colunas estejam na ordem correta
            colunas_esperadas = ['id', 'data', 'nome', 'tipo', 'descricao', 'uf', 'codigo_ibge', 'bancario']
            df_consolidado = df_consolidado[colunas_esperadas]
            
            # Salvar usando função centralizada
            file_path_local = OUTPUT_DIR / 'feriados_data.csv'
            s3_key = 'refined/feriados/feriados_data.csv'
            save_data_to_storage(df_consolidado, file_path_local, s3_key, s3_client)
            logger.info(f"✓ Extração de feriados e férias concluída com {len(df_consolidado)} registros totais")
        else:
            logger.warning("Nenhum dado foi coletado para nenhum ano")
        
    except Exception as e:
        logger.error(f"Erro inesperado: {e}", exc_info=True)
        raise


if __name__ == '__main__':
    main()