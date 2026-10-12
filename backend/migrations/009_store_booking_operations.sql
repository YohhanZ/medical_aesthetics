ALTER TABLE store_grant DROP CONSTRAINT store_grant_permission_check;
ALTER TABLE store_grant ADD CHECK(permission IN (
 'knowledge_author','knowledge_review','knowledge_publish',
 'appointment_read','appointment_manage','appointment_contact'
));
ALTER TABLE appointment ADD COLUMN version integer NOT NULL DEFAULT 1 CHECK(version>0);
ALTER TABLE appointment ADD COLUMN confirmed_at timestamptz;
ALTER TABLE appointment ADD COLUMN decision_reason text CHECK(decision_reason IN ('no_availability','unable_to_contact','other'));
ALTER TABLE appointment ADD COLUMN updated_at timestamptz NOT NULL DEFAULT now();
ALTER TABLE appointment ADD CHECK(state <> 'confirmed' OR confirmed_at IS NOT NULL);
ALTER TABLE appointment_event ADD COLUMN version integer NOT NULL DEFAULT 1;
ALTER TABLE appointment_event ADD COLUMN request_id uuid;
ALTER TABLE appointment_event ADD COLUMN reason text CHECK(reason IN ('no_availability','unable_to_contact','other'));
CREATE TABLE staff_booking_idempotency (
 tenant_id uuid NOT NULL, store_id uuid NOT NULL, staff_id uuid NOT NULL,
 request_key uuid NOT NULL, request_hash text NOT NULL, appointment_id uuid NOT NULL,
 visitor_id uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(tenant_id,staff_id,request_key),
 FOREIGN KEY(tenant_id,staff_id) REFERENCES staff(tenant_id,id),
 FOREIGN KEY(tenant_id,store_id,visitor_id,appointment_id) REFERENCES appointment(tenant_id,store_id,visitor_id,id)
);
CREATE INDEX appointment_store_queue ON appointment(tenant_id,store_id,state,created_at DESC,id);
