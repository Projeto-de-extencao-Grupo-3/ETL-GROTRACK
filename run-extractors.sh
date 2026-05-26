#!/bin/bash

# Script para executar extractores com configuração de ambiente

set -a
if [ -f .env ]; then
    source .env
fi
set +a

# Defaults
export STORAGE_TYPE=${STORAGE_TYPE:-local}
export BUCKET_NAME=${BUCKET_NAME:-grotrack-refined}
export S3_ENDPOINT_URL=${S3_ENDPOINT_URL:-http://localhost:4566}
export AWS_REGION=${AWS_REGION:-us-east-1}
export AWS_ACCESS_KEY_ID=${AWS_ACCESS_KEY_ID:-test}
export AWS_SECRET_ACCESS_KEY=${AWS_SECRET_ACCESS_KEY:-test}

# Script selection
SCRIPT=${1:-all}

echo "=== Grotrack Data Extraction ==="
echo "Storage Type: $STORAGE_TYPE"
echo "Bucket: $BUCKET_NAME"
if [ "$STORAGE_TYPE" = "s3" ]; then
    echo "S3 Endpoint: $S3_ENDPOINT_URL"
fi
echo ""

case $SCRIPT in
    feriados)
        echo "Executando extração de feriados..."
        python grafana/extract-feriados-data.py
        ;;
    os)
        echo "Executando extração de ordens de serviço..."
        python grafana/extract-os-data.py
        ;;
    all)
        echo "Executando todas as extrações..."
        python grafana/extract-feriados-data.py
        python grafana/extract-os-data.py
        ;;
    *)
        echo "Uso: ./run-extractors.sh [feriados|os|all]"
        echo ""
        echo "Exemplos:"
        echo "  ./run-extractors.sh all        # Executar todas as extrações"
        echo "  ./run-extractors.sh feriados   # Executar apenas feriados"
        echo "  ./run-extractors.sh os         # Executar apenas ordens de serviço"
        exit 1
        ;;
esac

echo ""
echo "✓ Execução concluída"
