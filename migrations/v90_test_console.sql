-- Additive migration for the existing TEST schema only. Run in one transaction.
SET LOCAL lock_timeout = '5s';
LOCK TABLE servamar_test.vessels, servamar_test.history IN ACCESS EXCLUSIVE MODE;
CREATE SEQUENCE IF NOT EXISTS servamar_test.v90_vessel_id_seq;
CREATE SEQUENCE IF NOT EXISTS servamar_test.v90_history_id_seq;
SELECT setval('servamar_test.v90_vessel_id_seq', GREATEST(
    (SELECT last_value FROM servamar_test.v90_vessel_id_seq),
    COALESCE((SELECT max(id) FROM servamar_test.vessels), 0)), true);
SELECT setval('servamar_test.v90_history_id_seq', GREATEST(
    (SELECT last_value FROM servamar_test.v90_history_id_seq),
    COALESCE((SELECT max(id) FROM servamar_test.history), 0)), true);
ALTER TABLE servamar_test.vessels ALTER COLUMN id SET DEFAULT nextval('servamar_test.v90_vessel_id_seq');
ALTER TABLE servamar_test.history ALTER COLUMN id SET DEFAULT nextval('servamar_test.v90_history_id_seq');
ALTER TABLE servamar_test.vessels ADD COLUMN IF NOT EXISTS version integer NOT NULL DEFAULT 1 CHECK (version > 0);
-- No FK on audit: deletion retains the before-state.
CREATE TABLE IF NOT EXISTS servamar_test.v90_audit (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    vessel_id bigint NOT NULL,
    action text NOT NULL CHECK (action IN ('create','edit','delete','movement')),
    before_state jsonb,
    after_state jsonb,
    actor text NOT NULL,
    at_time timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS v90_history_vessel_date ON servamar_test.history(vessel_id,event_date,id);
