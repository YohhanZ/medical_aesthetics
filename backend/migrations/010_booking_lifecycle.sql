ALTER TABLE appointment ADD COLUMN arrived_at timestamptz;
ALTER TABLE appointment_event DROP CONSTRAINT appointment_event_event_check;
ALTER TABLE appointment_event ADD CHECK(event IN (
 'submitted','confirmed','arrived','completed','cancelled','declined','no_show',
 'change_proposed','change_accepted','change_rejected'
));
CREATE TABLE booking_change_proposal (
 id uuid PRIMARY KEY, tenant_id uuid NOT NULL, store_id uuid NOT NULL, visitor_id uuid NOT NULL,
 appointment_id uuid NOT NULL, staff_id uuid NOT NULL, proposed_version integer NOT NULL,
 snapshot_cipher text NOT NULL, snapshot_hash text NOT NULL, proposed_at timestamptz NOT NULL,
 status text NOT NULL CHECK(status IN ('active','superseded','accepted','rejected','cancelled')),
 expires_at timestamptz NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(tenant_id,store_id,visitor_id,appointment_id,id),
 FOREIGN KEY(tenant_id,store_id,visitor_id,appointment_id) REFERENCES appointment(tenant_id,store_id,visitor_id,id),
 FOREIGN KEY(tenant_id,staff_id) REFERENCES staff(tenant_id,id)
);
CREATE UNIQUE INDEX one_active_booking_change ON booking_change_proposal(appointment_id) WHERE status='active';
CREATE TABLE booking_action_confirmation (
 id uuid PRIMARY KEY, tenant_id uuid NOT NULL, store_id uuid NOT NULL, visitor_id uuid NOT NULL,
 appointment_id uuid NOT NULL, actor_id uuid NOT NULL,
 operation text NOT NULL CHECK(operation IN ('change_proposed','change_accepted','change_rejected','cancelled','arrived')),
 snapshot_hash text NOT NULL, snapshot_cipher text NOT NULL,
 confirmation_text text NOT NULL, method text NOT NULL CHECK(method IN ('customer_button','staff_button')),
 confirmed_at timestamptz NOT NULL DEFAULT now(), evidence_request_id uuid NOT NULL,
 FOREIGN KEY(tenant_id,store_id,visitor_id,appointment_id) REFERENCES appointment(tenant_id,store_id,visitor_id,id)
);
