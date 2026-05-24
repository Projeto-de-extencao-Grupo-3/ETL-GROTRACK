Repositório destinado para a ETL do projeto que futuramente vamos subir na infra.

## Estrutura do Projeto

```
├── grafana/                    # Scripts de extração para Grafana
│   ├── extract-feriados-data.py    # Extração de feriados da API
│   ├── extract-os-data.py          # Extração de ordens de serviço
│   └── ...
├── raw/                        # Dados brutos
├── refined/                    # Dados refinados
├── trusted/                    # Dados confiáveis
├── sql/                        # Scripts SQL
├── requirements.txt            # Dependências Python
├── .env.example               # Exemplo de variáveis de ambiente
├── docker-compose.yml         # Configuração Docker para desenvolvimento
├── run-extractors.sh          # Script para executar extractores
└── S3_STORAGE.md             # Documentação de storage S3/LocalStack
```

## Quick Start

### 1. Instalação de Dependências

```bash
pip install -r requirements.txt
```

### 2. Configurar Variáveis de Ambiente

```bash
cp .env.example .env
# Editar .env com suas configurações
```

### 3. Desenvolvimento Local com LocalStack

```bash
# Iniciar LocalStack e MySQL
docker-compose up -d

# Executar extractores
bash run-extractors.sh all
```

### 4. Produção (AWS S3)

```bash
export STORAGE_TYPE=s3
export AWS_REGION=us-east-1
export AWS_ACCESS_KEY_ID=seu_acesso
export AWS_SECRET_ACCESS_KEY=seu_secret

bash run-extractors.sh all
```

## Scripts de Extração

### extract-feriados-data.py
Extrai dados de feriados de uma API e armazena em CSV.

**Saída:**
- `refined/feriados/feriados_YYYY.csv` (um arquivo por ano)

**Execução:**
```bash
python grafana/extract-feriados-data.py
```

### extract-os-data.py
Extrai dados de ordens de serviço do banco de dados.

**Saída:**
- `refined/os/os_data.csv` (dados das ordens)
- `refined/os/os_servicos.csv` (dados dos serviços)

**Execução:**
```bash
python grafana/extract-os-data.py
```

## Variáveis de Ambiente

| Variável | Padrão | Descrição |
|----------|--------|-----------|
| `STORAGE_TYPE` | `s3` | Tipo de storage: `s3` ou `local` |
| `BUCKET_NAME` | `grotrack-refined` | Nome do bucket S3 |
| `S3_ENDPOINT_URL` | `http://localhost:4566` | URL do endpoint S3 |
| `AWS_REGION` | `us-east-1` | Região AWS |
| `DB_HOST` | `localhost` | Host do banco MySQL |
| `DB_PORT` | `3306` | Porta do banco MySQL |
| `DB_USER` | `root` | Usuário do banco |
| `DB_PASSWORD` | `123456` | Senha do banco |
| `DB_NAME` | `grotrack` | Nome do banco |

Para mais informações sobre configuração de storage, veja [S3_STORAGE.md](S3_STORAGE.md)

## Troubleshooting

### LocalStack não conecta
```bash
# Verifique se está rodando
docker ps | grep localstack

# Reinicie se necessário
docker-compose restart localstack
```

### Erro de credenciais AWS
- Para LocalStack: use `AWS_ACCESS_KEY_ID=test` e `AWS_SECRET_ACCESS_KEY=test`
- Para AWS: configure suas credenciais em `~/.aws/credentials` ou via variáveis de ambiente

### Erro de conexão com banco de dados
```bash
# Verifique conexão
docker-compose logs mysql

# Reinicie MySQL
docker-compose restart mysql
```