-- Additive owner-approved paid-trial budget ledger. No migration rewrites old jobs.
CREATE TABLE IF NOT EXISTS paid_trial_authorizations (
  id TEXT PRIMARY KEY,
  owner_id TEXT NOT NULL REFERENCES owners(id) ON DELETE CASCADE,
  profile_id TEXT NOT NULL,
  profile_version INTEGER NOT NULL,
  total_cap_usd TEXT NOT NULL,
  per_send_cap_usd TEXT NOT NULL,
  max_jobs INTEGER NOT NULL CHECK(max_jobs > 0),
  expires_at TEXT NOT NULL,
  state TEXT NOT NULL CHECK(state IN ('active','revoked')),
  approved_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_trial_owner ON paid_trial_authorizations(owner_id,approved_at);
CREATE TABLE IF NOT EXISTS paid_trial_reservations (
  job_id TEXT PRIMARY KEY REFERENCES generation_jobs(id) ON DELETE CASCADE,
  authorization_id TEXT NOT NULL REFERENCES paid_trial_authorizations(id),
  reserved_usd TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_trial_reservations_grant ON paid_trial_reservations(authorization_id);
