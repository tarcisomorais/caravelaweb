PRAGMA foreign_keys = ON;

CREATE TABLE schema_metadata (
  singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
  schema_version INTEGER NOT NULL CHECK (schema_version > 0)
) WITHOUT ROWID;

INSERT INTO schema_metadata(singleton, schema_version) VALUES (1, 2);
PRAGMA user_version = 2;

CREATE TABLE targets (
  id TEXT PRIMARY KEY,
  name TEXT,
  canonical_origin TEXT,
  payload_json TEXT NOT NULL
) WITHOUT ROWID;

CREATE TABLE hosts (
  id TEXT PRIMARY KEY,
  target_id TEXT NOT NULL REFERENCES targets(id),
  hostname TEXT,
  payload_json TEXT NOT NULL
) WITHOUT ROWID;

CREATE TABLE capabilities (
  id TEXT PRIMARY KEY,
  target_id TEXT NOT NULL REFERENCES targets(id),
  capability_key TEXT NOT NULL,
  name TEXT,
  payload_json TEXT NOT NULL,
  UNIQUE(target_id, capability_key)
) WITHOUT ROWID;

CREATE TABLE evidence (
  id TEXT PRIMARY KEY,
  recorded_at TEXT,
  recorded_at_state TEXT NOT NULL CHECK (recorded_at_state IN ('RECORDED','UNRECORDED')),
  payload_json TEXT NOT NULL
) WITHOUT ROWID;

CREATE TABLE validations (
  id TEXT PRIMARY KEY,
  capability_id TEXT NOT NULL REFERENCES capabilities(id),
  host_id TEXT REFERENCES hosts(id),
  observed_at TEXT NOT NULL,
  recorded_at TEXT NOT NULL,
  time_precision TEXT NOT NULL CHECK (time_precision IN ('exact','day','fixture')),
  transport TEXT,
  context_json TEXT NOT NULL,
  payload_json TEXT NOT NULL
) WITHOUT ROWID;

CREATE TABLE observations (
  id TEXT PRIMARY KEY,
  validation_id TEXT NOT NULL REFERENCES validations(id),
  result_json TEXT NOT NULL,
  value_json TEXT,
  payload_json TEXT NOT NULL
) WITHOUT ROWID;

CREATE TABLE observation_evidence (
  observation_id TEXT NOT NULL REFERENCES observations(id),
  evidence_id TEXT NOT NULL REFERENCES evidence(id),
  PRIMARY KEY (observation_id, evidence_id)
) WITHOUT ROWID;

CREATE TABLE claims (
  id TEXT PRIMARY KEY,
  target_id TEXT NOT NULL REFERENCES targets(id),
  capability_id TEXT NOT NULL REFERENCES capabilities(id),
  host_id TEXT REFERENCES hosts(id),
  family TEXT NOT NULL,
  epistemic TEXT NOT NULL CHECK (epistemic IN ('OBSERVED','INFERRED','UNKNOWN')),
  value_json TEXT NOT NULL,
  proposal_id TEXT,
  recorded_at TEXT,
  recorded_at_state TEXT NOT NULL CHECK (recorded_at_state IN ('RECORDED','UNRECORDED')),
  payload_json TEXT NOT NULL
) WITHOUT ROWID;

CREATE TABLE claim_observations (
  claim_id TEXT NOT NULL REFERENCES claims(id),
  observation_id TEXT NOT NULL REFERENCES observations(id),
  relation TEXT NOT NULL CHECK (relation IN ('supports','contradicts')),
  PRIMARY KEY (claim_id, observation_id, relation)
) WITHOUT ROWID;

CREATE TABLE proposals (
  id TEXT PRIMARY KEY,
  target_id TEXT NOT NULL REFERENCES targets(id),
  capability_id TEXT NOT NULL REFERENCES capabilities(id),
  recorded_at TEXT,
  recorded_at_state TEXT NOT NULL CHECK (recorded_at_state IN ('RECORDED','UNRECORDED')),
  payload_json TEXT NOT NULL
) WITHOUT ROWID;

CREATE TABLE proposal_claims (
  proposal_id TEXT NOT NULL REFERENCES proposals(id),
  claim_id TEXT NOT NULL REFERENCES claims(id),
  PRIMARY KEY (proposal_id, claim_id)
) WITHOUT ROWID;

CREATE TABLE decisions (
  id TEXT PRIMARY KEY,
  target_id TEXT NOT NULL REFERENCES targets(id),
  capability_id TEXT NOT NULL REFERENCES capabilities(id),
  action TEXT NOT NULL CHECK (action IN (
    'ACCEPT','REJECT','SUPERSEDE','DEGRADE',
    'RETROACTIVE_CORRECTION','ACCEPT_SUPERSEDE'
  )),
  proposal_id TEXT REFERENCES proposals(id),
  effective_at TEXT NOT NULL,
  recorded_at TEXT NOT NULL,
  valid_from TEXT,
  valid_to TEXT,
  payload_json TEXT NOT NULL,
  CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_from < valid_to)
) WITHOUT ROWID;

CREATE TABLE decision_claims (
  decision_id TEXT NOT NULL REFERENCES decisions(id),
  claim_id TEXT NOT NULL REFERENCES claims(id),
  PRIMARY KEY (decision_id, claim_id)
) WITHOUT ROWID;

CREATE TABLE contradictions (
  observation_id TEXT NOT NULL REFERENCES observations(id),
  claim_id TEXT NOT NULL REFERENCES claims(id),
  PRIMARY KEY (observation_id, claim_id)
) WITHOUT ROWID;

CREATE INDEX idx_hosts_target ON hosts(target_id, id);
CREATE INDEX idx_capabilities_target ON capabilities(target_id, capability_key, id);
CREATE INDEX idx_validations_cap_recorded ON validations(capability_id, recorded_at, observed_at, id);
CREATE INDEX idx_validations_host ON validations(host_id, capability_id, observed_at, id);
CREATE INDEX idx_claims_cap_family ON claims(capability_id, family, epistemic, id);
CREATE INDEX idx_claims_host ON claims(host_id, capability_id, id);
CREATE INDEX idx_claims_proposal ON claims(proposal_id, id);
CREATE INDEX idx_proposals_cap_recorded ON proposals(capability_id, recorded_at, id);
CREATE INDEX idx_decisions_cap_order ON decisions(capability_id, effective_at, recorded_at, id);
CREATE INDEX idx_decisions_recorded ON decisions(capability_id, recorded_at, effective_at, id);
CREATE INDEX idx_decision_claims_claim ON decision_claims(claim_id, decision_id);
CREATE INDEX idx_claim_observations_claim ON claim_observations(claim_id, relation, observation_id);
CREATE INDEX idx_contradictions_claim ON contradictions(claim_id, observation_id);
