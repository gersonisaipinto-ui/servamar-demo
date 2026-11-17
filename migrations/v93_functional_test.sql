-- Test schema only. No data import, expiry calculation, or delivery queue.
SET LOCAL lock_timeout='5s';
ALTER TABLE servamar_test.v90_audit DROP CONSTRAINT IF EXISTS v90_audit_action_check;
ALTER TABLE servamar_test.v90_audit ADD CONSTRAINT v90_audit_action_check CHECK(action IN (
 'create','edit','delete','movement','movement_edit','movement_delete',
 'contact_create','contact_edit','contact_delete','document_create','document_archive','document_restore'));
ALTER TABLE servamar_test.v91_documents ADD COLUMN IF NOT EXISTS archived_at timestamptz;
CREATE TABLE IF NOT EXISTS servamar_test.v93_document_content (
 document_id bigint PRIMARY KEY REFERENCES servamar_test.v91_documents(id) ON DELETE RESTRICT,
 content bytea NOT NULL CHECK(octet_length(content) BETWEEN 1 AND 2097152));
CREATE INDEX IF NOT EXISTS v93_documents_vessel ON servamar_test.v91_documents(vessel_id,uploaded_at,id);
CREATE INDEX IF NOT EXISTS v93_vessels_expiry ON servamar_test.vessels(expiry_date,id);
CREATE INDEX IF NOT EXISTS v93_vessels_start ON servamar_test.vessels(start_date,id);
