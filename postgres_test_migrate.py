"""Explicit V90 migration. Only accepts the pinned TEST branch's direct URL."""
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
        db.execute(Path(__file__).with_name('migrations').joinpath('v90_test_console.sql').read_text(encoding='utf-8'))
    print('V90 test schema migration complete')


if __name__ == '__main__':
    migrate()
