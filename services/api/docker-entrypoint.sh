#!/bin/sh
set -e

echo "cubicle: applying database migrations"
alembic upgrade head

exec "$@"
