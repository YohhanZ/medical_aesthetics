ALTER TABLE store_grant DROP CONSTRAINT store_grant_permission_check;
ALTER TABLE store_grant ADD CHECK(permission IN (
 'knowledge_author','knowledge_review','knowledge_publish',
 'appointment_read','appointment_manage','appointment_contact','customer_read','customer_manage'
));
CREATE TABLE consultation_case (
 id uuid PRIMARY KEY, tenant_id uuid NOT NULL, store_id uuid NOT NULL, visitor_id uuid NOT NULL,
 appointment_id uuid NOT NULL, version integer NOT NULL CHECK(version>0),
 initial_cipher text NOT NULL, simulated boolean NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(tenant_id,store_id,visitor_id,id), UNIQUE(appointment_id),
 FOREIGN KEY(tenant_id,store_id,visitor_id,appointment_id) REFERENCES appointment(tenant_id,store_id,visitor_id,id)
);
CREATE TABLE consultation_revision (
 tenant_id uuid NOT NULL, store_id uuid NOT NULL, visitor_id uuid NOT NULL, case_id uuid NOT NULL,
 version integer NOT NULL CHECK(version>0), actor_id uuid NOT NULL,
 snapshot_cipher text NOT NULL, snapshot_hash text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(tenant_id,store_id,visitor_id,case_id,version),
 FOREIGN KEY(tenant_id,store_id,visitor_id,case_id) REFERENCES consultation_case(tenant_id,store_id,visitor_id,id),
 FOREIGN KEY(tenant_id,actor_id) REFERENCES staff(tenant_id,id)
);
CREATE TABLE consultation_decision (
 tenant_id uuid NOT NULL, store_id uuid NOT NULL, visitor_id uuid NOT NULL, case_id uuid NOT NULL,
 version integer NOT NULL, decision text NOT NULL CHECK(decision IN ('accept','reject')),
 snapshot_hash text NOT NULL, snapshot_cipher text NOT NULL,
 confirmation_text text NOT NULL, method text NOT NULL CHECK(method='customer_button'),
 confirmed_at timestamptz NOT NULL DEFAULT now(), evidence_request_id uuid NOT NULL,
 PRIMARY KEY(tenant_id,store_id,visitor_id,case_id,version),
 FOREIGN KEY(tenant_id,store_id,visitor_id,case_id,version) REFERENCES consultation_revision(tenant_id,store_id,visitor_id,case_id,version)
);
CREATE TABLE consultation_command (
 tenant_id uuid NOT NULL, store_id uuid NOT NULL, visitor_id uuid NOT NULL, case_id uuid NOT NULL,
 actor_id uuid NOT NULL, request_key uuid NOT NULL, request_hash text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(tenant_id,actor_id,request_key),
 FOREIGN KEY(tenant_id,store_id,visitor_id,case_id) REFERENCES consultation_case(tenant_id,store_id,visitor_id,id)
);
CREATE INDEX consultation_store_queue ON consultation_case(tenant_id,store_id,created_at DESC,id);
