-- Test-only reminder plans, separate from delivery events. No sender is enabled.
ALTER TABLE servamar_test.vessels ADD COLUMN IF NOT EXISTS automatic_notices_suspended boolean NOT NULL DEFAULT false;
ALTER TABLE servamar_test.vessels ADD COLUMN IF NOT EXISTS automatic_notices_reason text;
CREATE TABLE IF NOT EXISTS servamar_test.v96_notification_schedule (
 vessel_id bigint NOT NULL REFERENCES servamar_test.vessels(id) ON DELETE CASCADE,
 expiry_date date NOT NULL, days_before integer NOT NULL CHECK(days_before IN (30,15,1)),
 due_date date NOT NULL CHECK(due_date=expiry_date-days_before),
 channel text NOT NULL CHECK(channel IN ('email','push','windows')),
 status text NOT NULL DEFAULT 'planned' CHECK(status IN ('planned','cancelled')),
 PRIMARY KEY(vessel_id,expiry_date,days_before,channel));
-- Supersede V95's permanent suspension without enabling any delivery transport.
UPDATE servamar_test.vessels SET automatic_notices_suspended=FALSE,automatic_notices_reason=NULL,version=version+1
 WHERE declaration ~ '^ST-(DEMO|TEST)-' AND (automatic_notices_suspended OR automatic_notices_reason IS NOT NULL);
UPDATE servamar_test.alert_settings a SET enabled=FALSE FROM servamar_test.vessels v
 WHERE a.vessel_id=v.id AND a.enabled=TRUE AND v.declaration ~ '^ST-(DEMO|TEST)-';
UPDATE servamar_test.v96_notification_schedule p SET status='cancelled' FROM servamar_test.vessels v
 WHERE p.vessel_id=v.id AND v.declaration ~ '^ST-(DEMO|TEST)-' AND p.status='planned'
 AND (v.stage NOT IN ('ingreso','ampliacion','deposito') OR p.expiry_date IS DISTINCT FROM v.expiry_date
 OR p.due_date<(CURRENT_TIMESTAMP AT TIME ZONE 'America/Guatemala')::date
 OR EXISTS (SELECT 1 FROM servamar_test.v91_notification_events e WHERE e.vessel_id=p.vessel_id
 AND e.channel=p.channel AND e.kind='expiry_'||p.days_before::text AND e.due_date=p.due_date AND e.status='sent'));
UPDATE servamar_test.v91_notification_events e SET status='cancelled',error_code='expiry_recalculated'
 FROM servamar_test.vessels v WHERE e.vessel_id=v.id AND v.declaration ~ '^ST-(DEMO|TEST)-'
 AND e.kind IN ('expiry_30','expiry_15','expiry_1') AND e.status IN ('pending','failed')
 AND (v.stage NOT IN ('ingreso','ampliacion','deposito')
 OR (e.due_date + CASE e.kind WHEN 'expiry_30' THEN 30 WHEN 'expiry_15' THEN 15 ELSE 1 END) IS DISTINCT FROM v.expiry_date
 OR e.due_date<(CURRENT_TIMESTAMP AT TIME ZONE 'America/Guatemala')::date);
INSERT INTO servamar_test.v96_notification_schedule(vessel_id,expiry_date,days_before,due_date,channel,status)
 SELECT v.id,v.expiry_date,d.days,v.expiry_date-d.days,c.channel,'planned'
 FROM servamar_test.vessels v CROSS JOIN (VALUES(30),(15),(1)) d(days)
 CROSS JOIN (VALUES('email'),('push'),('windows')) c(channel)
 WHERE v.declaration ~ '^ST-(DEMO|TEST)-' AND v.stage IN ('ingreso','ampliacion','deposito')
 AND v.expiry_date-d.days >= (CURRENT_TIMESTAMP AT TIME ZONE 'America/Guatemala')::date
 AND NOT EXISTS (SELECT 1 FROM servamar_test.v91_notification_events e WHERE e.vessel_id=v.id
 AND e.channel=c.channel AND e.kind='expiry_'||d.days::text AND e.due_date=v.expiry_date-d.days AND e.status='sent')
 ON CONFLICT(vessel_id,expiry_date,days_before,channel) DO UPDATE SET status='planned'
 WHERE servamar_test.v96_notification_schedule.status='cancelled';
