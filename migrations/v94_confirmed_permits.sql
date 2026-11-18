-- Existing fictional records retain their manual expiry until explicitly switched.
ALTER TABLE servamar_test.vessels ADD COLUMN IF NOT EXISTS calculation_mode text NOT NULL DEFAULT 'manual'
 CHECK (calculation_mode IN ('manual','calculated'));
