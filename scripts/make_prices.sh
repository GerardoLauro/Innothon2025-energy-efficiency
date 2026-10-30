#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ $# -lt 1 ]; then echo 'Uso: make_prices.sh CITTA [--flat VALORE | --values SERIE]' >&2; exit 2; fi
CITY="$1"; shift
VALUES=''; FLAT='0.25'
while [ $# -gt 0 ]; do
  case "$1" in
    --values|--flat)
      if [ $# -lt 2 ]; then echo "Valore mancante per $1" >&2; exit 2; fi
      if [ "$1" = '--values' ]; then VALUES="$2"; else FLAT="$2"; fi
      shift 2 ;;
    *) echo "Opzione sconosciuta: $1" >&2; exit 2 ;;
  esac
done
if [ -z "$VALUES" ]; then
  for ((i=0; i<24; i++)); do VALUES+="${VALUES:+,}$FLAT"; done
fi
exec "${PYTHON:-python3}" "$SCRIPT_DIR/../run_app.py" prices paste --city "$CITY" --values "$VALUES"
