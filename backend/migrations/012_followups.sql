CREATE TABLE followup_task (
 id uuid PRIMARY KEY, tenant_id uuid NOT NULL, store_id uuid NOT NULL, visitor_id uuid NOT NULL,
 case_id uuid NOT NULL, case_version integer NOT NULL, created_by uuid NOT NULL,
 version integer NOT NULL CHECK(version>0),
 state text NOT NULL CHECK(state IN ('awaiting_confirmation','scheduled','completed','declined','cancelled')),
 due_at timestamptz NOT NULL, plan_cipher text NOT NULL, snapshot_hash text NOT NULL,
 opted_out boolean NOT NULL DEFAULT false, simulated boolean NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(tenant_id,store_id,visitor_id,case_id,id),
 FOREIGN KEY(tenant_id,store_id,visitor_id,case_id,case_version)
 REFERENCES consultation_revision(tenant_id,store_id,visitor_id,case_id,version),
 FOREIGN KEY(tenant_id,created_by) REFERENCES staff(tenant_id,id)
);
CREATE UNIQUE INDEX followup_one_open ON followup_task(case_id)
 WHERE state IN ('awaiting_confirmation','scheduled');
CREATE INDEX followup_store_queue ON followup_task(tenant_id,store_id,state,due_at,id);
CREATE TABLE followup_event (
 tenant_id uuid NOT NULL, store_id uuid NOT NULL, visitor_id uuid NOT NULL, case_id uuid NOT NULL,
 task_id uuid NOT NULL, version integer NOT NULL, actor_id uuid NOT NULL,
 actor_kind text NOT NULL CHECK(actor_kind IN ('staff','visitor')),
 kind text NOT NULL CHECK(kind IN ('created','accept','reject','feedback','cancel','resume','note')),
 method text NOT NULL CHECK(method IN ('staff_button','customer_button')),
 payload_cipher text NOT NULL, payload_hash text NOT NULL, evidence_request_id uuid NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(tenant_id,store_id,visitor_id,case_id,task_id,version),
 FOREIGN KEY(tenant_id,store_id,visitor_id,case_id,task_id)
 REFERENCES followup_task(tenant_id,store_id,visitor_id,case_id,id)
);
CREATE TABLE followup_command (
 tenant_id uuid NOT NULL, store_id uuid NOT NULL, visitor_id uuid NOT NULL, case_id uuid NOT NULL,
 task_id uuid NOT NULL, actor_id uuid NOT NULL, request_key uuid NOT NULL, request_hash text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(tenant_id,actor_id,request_key),
 FOREIGN KEY(tenant_id,store_id,visitor_id,case_id,task_id)
 REFERENCES followup_task(tenant_id,store_id,visitor_id,case_id,id)
);
