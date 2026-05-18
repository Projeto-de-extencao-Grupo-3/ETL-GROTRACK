import pandas as pd
import numpy as np
from datetime import datetime

df_os = pd.read_csv('refined/grafana/os_data.csv')
df_feriados = pd.read_csv('refined/refined_feriados_sp.csv')

df_os['ANO'] = pd.to_datetime(df_os['data_saida_prevista'], errors='coerce').dt.year
df_os['MES'] = pd.to_datetime(df_os['data_saida_prevista'], errors='coerce').dt.month
df_os['DIA'] = pd.to_datetime(df_os['data_saida_prevista'], errors='coerce').dt.day

periodos_unicos = df_os[['MES', 'ANO']].drop_duplicates().sort_values(['ANO', 'MES'])

resultados = []

for _, row in periodos_unicos.iterrows():
    mes = int(row['MES'])
    ano = int(row['ANO'])
    
    df_os_filtrado = df_os[(df_os['MES'] == mes) & (df_os['ANO'] == ano)].copy()
    df_feriados_filtrado = df_feriados[(df_feriados['MES'] == mes) & (df_feriados['ANO'] == ano)].copy()
    df_feriados_filtrado = df_feriados_filtrado[df_feriados_filtrado['CODIGO_MUNICIPIO'] == 3550308.0].copy()
    
    df_os_filtrado['ATRASO_DIAS'] = (pd.to_datetime(df_os_filtrado['data_saida_efetiva'], errors='coerce') - pd.to_datetime(df_os_filtrado['data_saida_prevista'], errors='coerce')).dt.days
    
    df_os_feriado = df_os_filtrado[df_os_filtrado['data_entrada_efetiva'].isin(df_feriados_filtrado['DATA'])]
    df_os_sem_feriado = df_os_filtrado[~df_os_filtrado['data_entrada_efetiva'].isin(df_feriados_filtrado['DATA'])]
    
    atraso_medio_com_feriado = df_os_feriado['ATRASO_DIAS'].mean() if len(df_os_feriado) > 0 else 0

    if (atraso_medio_com_feriado < 0):
        atraso_medio_com_feriado = 0

    atraso_medio_sem_feriado = df_os_sem_feriado['ATRASO_DIAS'].mean() if len(df_os_sem_feriado) > 0 else 0

    if (atraso_medio_sem_feriado < 0):
        atraso_medio_sem_feriado = 0

    total_os_com_atraso = len(df_os_sem_feriado[df_os_sem_feriado['ATRASO_DIAS'] > 0])
    total_os = len(df_os_filtrado)
    
    percentual_atraso_os = (total_os_com_atraso / total_os) * 100 if total_os > 0 else 0
    
    margem_dias_seguranca = (atraso_medio_com_feriado+atraso_medio_sem_feriado)/0.75 if not pd.isna(atraso_medio_com_feriado) and not pd.isna(atraso_medio_sem_feriado) else 0
    
    if (margem_dias_seguranca < 0):
        margem_dias_seguranca = 0

    resultados.append({
        'mes_analise': mes,
        'ano_analise': ano,
        'atraso_medio_com_feriado': atraso_medio_com_feriado,
        'atraso_medio_sem_feriado': atraso_medio_sem_feriado,
        'percentual_os_com_atraso': percentual_atraso_os,
        'margem_dias_seguranca': margem_dias_seguranca
    })

df_resultado_final = pd.DataFrame(resultados)
df_resultado_final.to_csv('refined/grafana/indicadores.csv', index=False)
