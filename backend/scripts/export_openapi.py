"""Print the API's OpenAPI schema as JSON, for generating the frontend's types.

    python -m scripts.export_openapi > openapi.json
    (cd ../frontend && npm run check:api -- ../backend/openapi.json)

Nothing connects to Postgres or Redis, but app.db reads DATABASE_URL and
REDIS_URL at import, so they must be set (any value will do).
"""

import json
import sys

from app.main import app


def main() -> None:
    json.dump(app.openapi(), sys.stdout)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
