-- Only test records: preserve the suspension even if history is later corrected.
ALTER TABLE servamar_test.vessels ADD COLUMN IF NOT EXISTS automatic_notices_suspended boolean NOT NULL DEFAULT false;
ALTER TABLE servamar_test.vessels ADD COLUMN IF NOT EXISTS automatic_notices_reason text
 CHECK (automatic_notices_reason IN ('ampliacion','deposito'));
UPDATE servamar_test.vessels v SET automatic_notices_suspended=TRUE,
 automatic_notices_reason=(SELECT h.kind FROM servamar_test.history h WHERE h.vessel_id=v.id
 AND h.kind IN ('ampliacion','deposito') ORDER BY h.event_date DESC NULLS LAST,h.id DESC LIMIT 1),
 version=version+1
 WHERE v.declaration ~ '^ST-(DEMO|TEST)-' AND NOT v.automatic_notices_suspended
 AND EXISTS (SELECT 1 FROM servamar_test.history h WHERE h.vessel_id=v.id AND h.kind IN ('ampliacion','deposito'));
UPDATE servamar_test.alert_settings a SET enabled=FALSE
 FROM servamar_test.vessels v WHERE a.vessel_id=v.id AND a.enabled=TRUE
 AND v.declaration ~ '^ST-(DEMO|TEST)-' AND v.automatic_notices_suspended;
UPDATE servamar_test.v91_notification_events e SET status='cancelled',error_code='automatic_notices_suspended'
 FROM servamar_test.vessels v WHERE e.vessel_id=v.id
 AND v.declaration ~ '^ST-(DEMO|TEST)-' AND v.automatic_notices_suspended
 AND e.kind IN ('expiry_30','expiry_15','expiry_1') AND e.status IN ('pending','failed');
