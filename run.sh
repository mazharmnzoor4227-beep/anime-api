#!/bin/sh
# Start the anime-api server on port 8000 using the project venv.
# Usage: ./run.sh   (from ~/workspace/anime-api)
set -e
cd "$(dirname "$0")"
exec ~/workspace/anime-api-work/venv/bin/python app.py
