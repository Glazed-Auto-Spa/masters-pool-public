CREATE TABLE IF NOT EXISTS pool_state (
  id SMALLINT PRIMARY KEY,
  state_schema_version INTEGER NOT NULL,
  state_json JSONB NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS pool_ledger (
  id BIGSERIAL PRIMARY KEY,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  entry_type TEXT NOT NULL,
  payload_hash TEXT NOT NULL,
  payload JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_pool_ledger_created_at
ON pool_ledger (created_at DESC);
