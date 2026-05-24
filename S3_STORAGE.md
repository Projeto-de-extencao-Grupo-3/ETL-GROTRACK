# Configuração de Storage S3/LocalStack

## Visão Geral

Os scripts de extração (`extract-feriados-data.py` e `extract-os-data.py`) suportam armazenamento em:
- **LocalStack** (desenvolvimento local na porta 4566)
- **AWS S3** (produção)
- **Sistema Local** (fallback)

## Instalação

Certifique-se de ter o `boto3` instalado:

```bash
pip install -r requirements.txt
```

## Configuração para Desenvolvimento (LocalStack)

### 1. Iniciar LocalStack

```bash
docker run -d -p 4566:4566 localstack/localstack
```

### 2. Executar Script com LocalStack

```bash
export STORAGE_TYPE=s3
export S3_ENDPOINT_URL=http://localhost:4566
export BUCKET_NAME=grotrack-bucket
export AWS_ACCESS_KEY_ID=test
export AWS_SECRET_ACCESS_KEY=test
export AWS_REGION=us-east-1

python grafana/extract-feriados-data.py
python grafana/extract-os-data.py
```

### 3. Verificar Dados no LocalStack

```bash
# Listar buckets
aws s3 ls --endpoint-url http://localhost:4566

# Listar arquivos no bucket
aws s3 ls s3://grotrack-bucket/refined/feriados/ --endpoint-url http://localhost:4566

# Baixar arquivo
aws s3 cp s3://grotrack-bucket/refined/feriados/feriados_2026.csv . --endpoint-url http://localhost:4566
```

## Configuração para Produção (AWS S3)

### 1. Configurar Credenciais AWS

Opção 1: Variáveis de ambiente
```bash
export AWS_ACCESS_KEY_ID=sua_chave_de_acesso
export AWS_SECRET_ACCESS_KEY=sua_chave_secreta
export AWS_REGION=us-east-1
```

Opção 2: Arquivo `~/.aws/credentials`
```
[default]
aws_access_key_id = sua_chave_de_acesso
aws_secret_access_key = sua_chave_secreta
```

### 2. Executar Script com AWS S3

```bash
# Desabilivar S3_ENDPOINT_URL para usar AWS produção
export STORAGE_TYPE=s3
export BUCKET_NAME=grotrack-refined
export AWS_REGION=us-east-1
# AWS_ACCESS_KEY_ID e AWS_SECRET_ACCESS_KEY serão lidos das credenciais configuradas

python grafana/extract-feriados-data.py
python grafana/extract-os-data.py
```

## Configuração para Armazenamento Local

### Executar Script com Sistema Local

```bash
export STORAGE_TYPE=local

python grafana/extract-feriados-data.py
python grafana/extract-os-data.py
```

Os arquivos serão salvos em:
- `refined/feriados/feriados_YYYY.csv`
- `refined/os/os_data.csv`
- `refined/os/os_servicos.csv`

## Variáveis de Ambiente Disponíveis

| Variável | Padrão | Descrição |
|----------|--------|-----------|
| `STORAGE_TYPE` | `s3` | Tipo de storage: `s3` ou `local` |
| `BUCKET_NAME` | `grotrack-bucket` | Nome do bucket S3 |
| `S3_ENDPOINT_URL` | `http://localhost:4566` | URL do endpoint S3 (LocalStack ou AWS) |
| `AWS_REGION` | `us-east-1` | Região AWS |
| `AWS_ACCESS_KEY_ID` | `test` | Chave de acesso AWS |
| `AWS_SECRET_ACCESS_KEY` | `test` | Chave secreta AWS |
| `DB_HOST` | `localhost` | Host do banco MySQL |
| `DB_PORT` | `3306` | Porta do banco MySQL |
| `DB_USER` | `root` | Usuário do banco MySQL |
| `DB_PASSWORD` | `123456` | Senha do banco MySQL |
| `DB_NAME` | `grotrack` | Nome do banco de dados |
| `FERIADOS_API_KEY` | (consulte os arquivos) | Chave da API de feriados |

## Exemplo: docker-compose.yml com LocalStack

```yaml
version: '3.8'

services:
  localstack:
    image: localstack/localstack:latest
    ports:
      - "4566:4566"
    environment:
      - SERVICES=s3
      - DEBUG=1
      - DATA_DIR=/tmp/localstack/data
    volumes:
      - "${TMPDIR:-/tmp}/localstack:/tmp/localstack"
      - "/var/run/docker.sock:/var/run/docker.sock"

  app:
    build: .
    depends_on:
      - localstack
    environment:
      - STORAGE_TYPE=s3
      - S3_ENDPOINT_URL=http://localstack:4566
      - BUCKET_NAME=grotrack-bucket
```

## Troubleshooting

### Erro: "Unable to locate credentials"
- Verifique se as credenciais AWS estão configuradas
- Para LocalStack, use as credenciais padrão: `AWS_ACCESS_KEY_ID=test` e `AWS_SECRET_ACCESS_KEY=test`

### Erro: "ConnectionError: HTTPConnectionPool"
- Verifique se LocalStack está rodando: `docker ps | grep localstack`
- Verifique a URL do endpoint: `http://localhost:4566`

### Erro: "NoSuchBucket"
- O script cria o bucket automaticamente
- Se o erro persistir, crie manualmente: `aws s3 mb s3://grotrack-bucket --endpoint-url http://localhost:4566`

## Estrutura de Arquivos no S3

```
s3://grotrack-bucket/
├── refined/
│   ├── feriados/
│   │   ├── feriados_2024.csv
│   │   ├── feriados_2025.csv
│   │   └── feriados_2026.csv
│   └── os/
│       ├── os_data.csv
│       └── os_servicos.csv
```
