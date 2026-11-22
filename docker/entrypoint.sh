#!/bin/sh
# Container start: wait for the database, apply migrations, then run the server.
set -e

python - <<'EOF'
import sys, time
from sqlalchemy import create_engine
from app.db.session import DATABASE_URL

for attempt in range(30):
    try:
        create_engine(DATABASE_URL).connect().close()
        break
    except Exception as exc:
        print(f"waiting for database ({type(exc).__name__})...", flush=True)
        time.sleep(2)
else:
    sys.exit("database not reachable after 60s")
EOF

alembic upgrade head
exec "$@"
