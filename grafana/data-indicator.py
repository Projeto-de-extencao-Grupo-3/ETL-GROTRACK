import pandas as pd
import numpy as np
from datetime import datetime
import os

df_os = pd.read_csv('refined/grafana/os_data.csv')

# Carregar dados de feriados de SP
df_feriados = pd.read_csv('refined/refined_feriados_sp.csv')

mes_analise_desejado = os.getenv('MES_ANALISE')
ano_analise_desejado = os.getenv('ANO_ANALISE')

if (mes_analise_desejado is None) and (ano_analise_desejado is None):
    print("⚠️ Variáveis de ambiente MES_ANALISE e ANO_ANALISE não definidas. Usando mês e ano atuais.")
    mes_analise_desejado = datetime.now().month
    ano_analise_desejado = datetime.now().year

# Ajustando Datas existentem no dataframe de OS 
df_os['ANO'] = pd.to_datetime(df_os['data_saida_prevista'], errors='coerce').dt.year
df_os['MES'] = pd.to_datetime(df_os['data_saida_prevista'], errors='coerce').dt.month
df_os['DIA'] = pd.to_datetime(df_os['data_saida_prevista'], errors='coerce').dt.day


# Filtrar OS para o mês e ano desejados
df_os = df_os[(df_os['MES'] == int(mes_analise_desejado)) & (df_os['ANO'] == int(ano_analise_desejado))].copy()


# Filtrar base de feriados para o mês e ano desejados
df_feriados = df_feriados[(df_feriados['MES'] == int(mes_analise_desejado)) & (df_feriados['ANO'] == int(ano_analise_desejado))].copy()

# Filtra feriados somente do município da Capital de São Paulo
df_feriados = df_feriados[df_feriados['CODIGO_MUNICIPIO'] == 3550308.0].copy()

# Calcular atraso em dias para cada OS
df_os['ATRASO_DIAS'] = (pd.to_datetime(df_os['data_saida_efetiva'], errors='coerce') - pd.to_datetime(df_os['data_saida_prevista'], errors='coerce')).dt.days     

# Filtrar OS que foram abertas na semana do feriado
df_os_feriado = df_os[df_os['data_entrada_efetiva'].isin(df_feriados['DATA'])]

# Filtrar OS que foram abertas fora da semana do feriado
df_os_sem_feriado = df_os[~df_os['data_entrada_efetiva'].isin(df_feriados['DATA'])]

atraso_medio_com_feriado = df_os_feriado['ATRASO_DIAS'].mean() if len(df_os_feriado) > 0 else 0
atraso_medio_sem_feriado = df_os_sem_feriado['ATRASO_DIAS'].mean() if len(df_os_sem_feriado) > 0 else 0

total_os_com_atraso = len(df_os_sem_feriado[df_os_sem_feriado['ATRASO_DIAS'] > 0])
total_os = len(df_os)

percentual_atraso_os = (total_os_com_atraso / total_os) * 100 if total_os > 0 else 0

margem_dias_seguranca = (atraso_medio_com_feriado+atraso_medio_sem_feriado)/0.75 if not pd.isna(atraso_medio_com_feriado) and not pd.isna(atraso_medio_sem_feriado) else 0

if (margem_dias_seguranca < 0):
    margem_dias_seguranca = 0


# Montar o DF com resultados finais e converter para CSV
df_resultado = pd.DataFrame({
    'mes_analise': [mes_analise_desejado],
    'ano_analise': [ano_analise_desejado],
    'atraso_medio_com_feriado': [atraso_medio_com_feriado],
    'atraso_medio_sem_feriado': [atraso_medio_sem_feriado],
    'percentual_os_com_atraso': [percentual_atraso_os],
    'margem_dias_seguranca': [margem_dias_seguranca]
})

df_resultado.to_csv(f'refined/grafana/indicador-data-{mes_analise_desejado}-{ano_analise_desejado}.csv', index=False)