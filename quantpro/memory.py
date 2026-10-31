"""Persistent history. PostgreSQL via DATABASE_URL recommended on Streamlit Cloud.
SQLite is local-only and not durable on Streamlit Community Cloud.
"""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = '''
CREATE TABLE IF NOT EXISTS snapshots (
 id TEXT PRIMARY KEY, product TEXT NOT NULL, draw INTEGER NOT NULL,
 captured_at TEXT NOT NULL, source TEXT NOT NULL, payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS forecasts (
 id TEXT PRIMARY KEY, snapshot_id TEXT NOT NULL, model TEXT NOT NULL,
 created_at TEXT NOT NULL, payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS portfolios (
 id TEXT PRIMARY KEY, snapshot_id TEXT NOT NULL, strategy TEXT NOT NULL,
 created_at TEXT NOT NULL, payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS outcomes (
 id TEXT PRIMARY KEY, product TEXT NOT NULL, draw INTEGER NOT NULL,
 recorded_at TEXT NOT NULL, payload TEXT NOT NULL
);
'''

def utcnow():
    return datetime.now(timezone.utc).isoformat()

class Store:
    def __init__(self, url=None, sqlite_path='quantpro_history.sqlite3'):
        self.postgres = bool(url)
        if self.postgres:
            import psycopg
            self.db = psycopg.connect(url)
        else:
            self.db = sqlite3.connect(str(Path(sqlite_path)))
        self._initialize()

    def _initialize(self):
        sql = SCHEMA if not self.postgres else SCHEMA.replace('TEXT PRIMARY KEY', 'TEXT PRIMARY KEY')
        with self.db:
            for stmt in sql.split(';'):
                if stmt.strip(): self.db.execute(stmt) if not self.postgres else self.db.execute(stmt)

    def put(self, table, key, metadata, payload):
        if table not in ('snapshots','forecasts','portfolios','outcomes'):
            raise ValueError('Unsupported table')
        if table == 'snapshots':
            columns = ('id','product','draw','captured_at','source','payload')
            values = (key, metadata['product'], int(metadata['draw']), metadata['captured_at'], metadata['source'], json.dumps(payload, ensure_ascii=False))
        elif table == 'outcomes':
            columns = ('id','product','draw','recorded_at','payload')
            values = (key, metadata['product'], int(metadata['draw']), metadata['recorded_at'], json.dumps(payload, ensure_ascii=False))
        else:
            columns = ('id','snapshot_id','model' if table=='forecasts' else 'strategy','created_at','payload')
            values = (key, metadata['snapshot_id'], metadata['name'], metadata['created_at'], json.dumps(payload, ensure_ascii=False))
        marker = '%s' if self.postgres else '?'
        query = f"INSERT INTO {table} ({','.join(columns)}) VALUES ({','.join([marker]*len(columns))}) ON CONFLICT(id) DO NOTHING"
        with self.db:
            self.db.execute(query, values)

    def list(self, table, limit=100):
        if table not in ('snapshots','forecasts','portfolios','outcomes'):
            raise ValueError('Unsupported table')
        col = 'captured_at' if table=='snapshots' else 'recorded_at' if table=='outcomes' else 'created_at'
        limit = max(1,min(1000,int(limit)))
        cur = self.db.execute(f'SELECT * FROM {table} ORDER BY {col} DESC LIMIT {limit}')
        columns = [x[0] for x in cur.description]
        out = []
        for row in cur.fetchall():
            obj = dict(zip(columns,row)); obj['payload'] = json.loads(obj['payload']); out.append(obj)
        return out

    def close(self): self.db.close()
