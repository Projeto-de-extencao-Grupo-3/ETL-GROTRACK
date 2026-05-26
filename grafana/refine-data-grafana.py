"""
Script para refinar dados de OS e feriados, gerando análises históricas.
Suporta leitura e escrita em S3/LocalStack ou armazenamento local.
"""
import logging
import math
from pathlib import Path
from datetime import datetime

import pandas as pd

# Importar configurações centralizadas de S3
from s3_config import (
    STORAGE_TYPE,
    get_s3_client,
    ensure_bucket_exists,
    load_data_from_storage,
    save_data_to_storage,
    create_output_directory
)

# Configuração de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Constantes - Paths
OS_DATA_PATH = Path('refined/os/os_data.csv')
FERIADOS_DATA_PATH = Path('refined/feriados/feriados_data.csv')
ANALYTICS_OUTPUT_DIR = Path('refined/analytics')


def load_data_files(s3_client=None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Carregar arquivos CSV de OS e feriados do S3 ou armazenamento local.
    
    Args:
        s3_client: Cliente S3 (obrigatório se STORAGE_TYPE='s3').
    
    Returns:
        Tupla contendo (DataFrame OS, DataFrame Feriados).
        
    Raises:
        FileNotFoundError ou ClientError: Se algum arquivo não existir.
    """
    try:
        df_os = load_data_from_storage(
            OS_DATA_PATH,
            "refined/os/os_data.csv",
            "OS",
            s3_client
        )
        df_feriados = load_data_from_storage(
            FERIADOS_DATA_PATH,
            "refined/feriados/feriados_data.csv",
            "Feriados",
            s3_client
        )
        
        return df_os, df_feriados
        
    except Exception as e:
        logger.error(f"Erro ao carregar arquivos: {e}")
        raise

def find_next_event_day(df_feriados: pd.DataFrame, data: datetime = datetime.now()) -> datetime:
    """Carregar data do próximo evento (feriado) a partir do DataFrame de feriados."""
    try:
        df_feriados['data'] = pd.to_datetime(df_feriados['data'], format='%d/%m/%Y', errors='coerce')
        df_feriados = df_feriados.dropna(subset=['data'])
        
        next_event = df_feriados[df_feriados['data'] >= data].sort_values('data').iloc[0]
        logger.info(f"✓ Próximo evento: {next_event['nome']} em {next_event['data'].date()}")
        next_event_date = next_event['data'].date()

        return next_event
    except Exception as e:
        logger.error(f"Erro ao carregar próximo evento: {e}")
        raise

def calculate_historic_feriado(df_feriados: pd.DataFrame, df_os: pd.DataFrame) -> pd.DataFrame:
    """
    Calcular histórico de OS por tipo de feriado e semana.
    
    Args:
        df_feriados: DataFrame com dados de feriados.
        df_os: DataFrame com dados de OS.
        
    Returns:
        DataFrame com estatísticas históricas de volume por tipo de feriado.
    """
    try:
        # Preparar dados de feriados
        df_feriados_prep = df_feriados.copy()
        df_feriados_prep['data'] = pd.to_datetime(df_feriados_prep['data'], format='%d/%m/%Y', errors='coerce')
        df_feriados_prep['semana'] = df_feriados_prep['data'].dt.isocalendar().week
        df_feriados_prep['ano'] = df_feriados_prep['data'].dt.year
        
        # Preparar dados de OS
        df_os_prep = df_os.copy()
        df_os_prep['dias_atraso'] = (pd.to_datetime(df_os_prep['data_saida_efetiva'], errors='coerce') - pd.to_datetime(df_os_prep['data_saida_prevista'], errors='coerce')).dt.days
        df_os_prep['data_saida_efetiva'] = pd.to_datetime(df_os_prep['data_saida_efetiva'], errors='coerce')
        df_os_prep['semana'] = df_os_prep['data_saida_efetiva'].dt.isocalendar().week
        df_os_prep['ano'] = df_os_prep['data_saida_efetiva'].dt.year
        
        # Fazer merge entre OS e feriados pela semana e ano
        df_merged = pd.merge(
            df_os_prep,
            df_feriados_prep[['tipo', 'nome', 'semana', 'ano']],
            on=['semana', 'ano'],
            how='inner'
        )

        # Agrupar por tipo de feriado e calcular volume total de OS
        df_historico = df_merged.groupby(['tipo', 'ano']).agg({
            'id_ordem_servico': 'count',
            'dias_atraso': 'mean'
        }).round(2)


        # Simplificar nomes de colunas
        df_historico.columns = ['volume_total', 'atraso_medio']
        df_historico = df_historico.reset_index()

        

        logger.info(f"✓ Histórico de feriados calculado: {len(df_historico)} tipos de feriado")
        
        return df_historico
        
    except Exception as e:
        logger.error(f"Erro ao calcular histórico de feriado: {e}")
        raise


def estimate_volume_expected_for_next_event(proximo_feriado: pd.Series, df_historico: pd.DataFrame) -> dict:
    """
    Estimar volume esperado para o próximo feriado baseado no histórico.
    
    Args:
        proximo_feriado: Series do pandas contendo dados do próximo feriado.
        df_historico: DataFrame com histórico de volumes por tipo e ano.
        
    Returns:
        Dicionário com estimativa de volume para o próximo feriado.
    """
    try:
        tipo_feriado = proximo_feriado['tipo']
        
        # Filtrar histórico pelo tipo do próximo feriado
        df_tipo = df_historico[df_historico['tipo'] == tipo_feriado]
        
        if df_tipo.empty:
            logger.warning(f"Nenhum histórico para tipo: {tipo_feriado}")
            return {}
        
        # Calcular estatísticas da média histórica de volumes
        volume_esperado = math.floor(df_tipo['volume_total'].mean())
        desvio_padrao = df_tipo['volume_total'].std()
        
        estimativa = {
            'data': proximo_feriado['data'].date(),
            'nome': proximo_feriado['nome'],
            'tipo': tipo_feriado,
            'volume_esperado': volume_esperado,
            'desvio_padrao': round(desvio_padrao, 2)
        }
        
        logger.info(f"✓ Volume estimado para {proximo_feriado['nome']}: {volume_esperado} ordens de serviço")
        
        return estimativa
        
    except Exception as e:
        logger.error(f"Erro ao estimar volume esperado: {e}")
        raise

def estimate_delay_for_next_event(proximo_feriado: pd.Series, df_historico: pd.DataFrame) -> dict:
    """
    Estimar atraso esperado para o próximo feriado baseado no histórico.
    
    Args:
        proximo_feriado: Series do pandas contendo dados do próximo feriado.
        df_historico: DataFrame com histórico de volumes por tipo e ano.
        
    Returns:
        Dicionário com estimativa de atraso para o próximo feriado.
    """
    try:
        tipo_feriado = proximo_feriado['tipo']
        
        # Filtrar histórico pelo tipo do próximo feriado
        df_tipo = df_historico[df_historico['tipo'] == tipo_feriado]
        
        if df_tipo.empty:
            logger.warning(f"Nenhum histórico para tipo: {tipo_feriado}")
            return {}
        
        # Calcular estatísticas da média histórica de atrasos
        atraso_esperado = df_tipo['atraso_medio'].mean()
        desvio_padrao = df_tipo['atraso_medio'].std()
        atraso_esperado_descricao = formatar_dias(atraso_esperado)  # Converter dias para formato legível
        
        estimativa = {
            'data': proximo_feriado['data'].date(),
            'nome': proximo_feriado['nome'],
            'tipo': tipo_feriado,
            'atraso_esperado': round(atraso_esperado, 2),
            'desvio_padrao': round(desvio_padrao, 2),
            'atraso_esperado_descricao': atraso_esperado_descricao  # Converter dias para formato legível
        }
        
        logger.info(f"✓ Atraso estimado para {proximo_feriado['nome']}: {atraso_esperado_descricao}")
        
        return estimativa
        
    except Exception as e:
        logger.error(f"Erro ao estimar atraso esperado: {e}")
        raise

def formatar_dias(total_dias: float) -> str:
    # 1. Converte o total de dias para minutos totais para garantir a precisão
    total_minutos = round(total_dias * 24 * 60)
    
    # 2. Calcula as unidades de tempo
    minutos_por_dia = 24 * 60
    dias = total_minutos // minutos_por_dia
    resto_minutos = total_minutos % minutos_por_dia
    
    horas = resto_minutos // 60
    minutos = resto_minutos % 60
    
    # 3. Aplica a regra de exibição baseada no valor
    if dias < 1:
        # Se for menor que 1 dia, exibe apenas horas (e minutos se existirem)
        if minutos > 0:
            return f"{horas}h {minutos}m"
        return f"{horas}h"
    else:
        # Se for 1 dia ou mais, exibe Dias e Horas (omite minutos para o painel ficar limpo)
        if horas > 0:
            return f"{dias}d {horas}h"
        return f"{dias}d"




def gerar_analise_final(
    proximo_feriado: pd.Series,
    estimativa_volume: dict,
    estimativa_delay: dict,
    s3_client=None
) -> None:
    """
    Gerar análise final combinando volume esperado, atraso esperado e dados do próximo feriado.
    Salvar em S3 ou armazenamento local.
    
    Args:
        proximo_feriado: Series com dados do próximo feriado.
        estimativa_volume: Dicionário com estimativa de volume.
        estimativa_delay: Dicionário com estimativa de atraso.
        s3_client: Cliente S3 (obrigatório se STORAGE_TYPE='s3').
    """
    try:
        # Combinar dados em um único registro
        analise_final = {
            'data_feriado': proximo_feriado['data'].date(),
            'nome_feriado': proximo_feriado['nome'],
            'tipo_feriado': proximo_feriado['tipo'],
            'volume_esperado': estimativa_volume.get('volume_esperado', 0),
            'volume_desvio_padrao': estimativa_volume.get('desvio_padrao', 0),
            'atraso_esperado_dias': estimativa_delay.get('atraso_esperado', 0),
            'atraso_desvio_padrao': estimativa_delay.get('desvio_padrao', 0),
            'atraso_esperado_descricao': estimativa_delay.get('atraso_esperado_descricao', ''),
            'data_geracao': datetime.now().date()
        }
        
        # Converter para DataFrame
        df_analise = pd.DataFrame([analise_final])
        
        # Salvar em storage (S3 ou local) usando função centralizada
        file_path_local = ANALYTICS_OUTPUT_DIR / "proxima_previsao_feriado.csv"
        s3_key = "refined/analytics/proxima_previsao_feriado.csv"
        save_data_to_storage(df_analise, file_path_local, s3_key, s3_client)
        
    except Exception as e:
        logger.error(f"Erro ao gerar análise final: {e}")
        raise

def main():
    """Função principal para refinar dados e gerar análises."""
    try:
        # Inicializar storage
        s3_client = None
        if STORAGE_TYPE == 's3':
            s3_client = get_s3_client()
            if not ensure_bucket_exists(s3_client):
                raise Exception("Não foi possível garantir a existência do bucket S3")
        else:
            create_output_directory(ANALYTICS_OUTPUT_DIR)
        
        # Carregar dados
        df_os, df_feriados = load_data_files(s3_client)

        data_2025_05_25 = datetime(2026, 5, 25)
        next_event_date = find_next_event_day(df_feriados, data_2025_05_25)

        df_historico = calculate_historic_feriado(df_feriados, df_os)

        estimate_volume = estimate_volume_expected_for_next_event(next_event_date, df_historico)
        estimate_delay = estimate_delay_for_next_event(next_event_date, df_historico)
        
        # Gerar análise final combinada
        gerar_analise_final(next_event_date, estimate_volume, estimate_delay, s3_client)
        
        logger.info("✓ Processo de refinamento concluído com sucesso!")

    except Exception as e:
        logger.error(f"Erro no processo de refinamento: {e}")
        raise


if __name__ == '__main__':
    main()