"""Explicit V96 migration. Only accepts the pinned TEST branch's direct URL."""
from pathlib import Path
from urllib.parse import urlsplit

from postgres_test_app import TEST_HOST, configured, connection
import os


def migrate():
    if not configured():
        raise RuntimeError('Test configuration incomplete')
    if urlsplit(os.environ['SERVAMAR_PG_TEST_DATABASE_URL']).hostname != TEST_HOST:
        raise RuntimeError('Migration requires the direct TEST endpoint')
    with connection() as db:
        for name in ('v90_test_console.sql', 'v91_test_foundation.sql', 'v93_functional_test.sql', 'v94_confirmed_permits.sql', 'v96_current_expiry_notices.sql'):
            db.execute(Path(__file__).with_name('migrations').joinpath(name).read_text(encoding='utf-8'))
    print('V96 test schema migration complete')


if __name__ == '__main__':
    migrate()
