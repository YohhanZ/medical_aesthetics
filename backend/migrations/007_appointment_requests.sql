CREATE TABLE appointment_draft (
    id uuid PRIMARY KEY, tenant_id uuid NOT NULL, store_id uuid NOT NULL, visitor_id uuid NOT NULL,
    thread_id uuid NOT NULL, trigger_run_id uuid NOT NULL REFERENCES agent_run(id),
    request_key uuid NOT NULL, snapshot_cipher text NOT NULL, snapshot_hash text NOT NULL, phone_hash text NOT NULL,
    project_version_id uuid, status text NOT NULL CHECK(status IN ('active','superseded','discarded','submitted')),
    simulated boolean NOT NULL, expires_at timestamptz NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(tenant_id,store_id,visitor_id,id),
    FOREIGN KEY(tenant_id,store_id,visitor_id,thread_id) REFERENCES conversation(tenant_id,store_id,visitor_id,id),
    FOREIGN KEY(tenant_id,store_id,project_version_id) REFERENCES knowledge_version(tenant_id,store_id,id)
);
CREATE UNIQUE INDEX one_active_appointment_draft ON appointment_draft(thread_id) WHERE status='active';
CREATE TABLE contact_verification (
    id uuid PRIMARY KEY, tenant_id uuid NOT NULL, store_id uuid NOT NULL, visitor_id uuid NOT NULL,
    draft_id uuid NOT NULL, request_key uuid NOT NULL, phone_hash text NOT NULL, code_hash text NOT NULL, code_cipher text NOT NULL,
    delivery_state text NOT NULL CHECK(delivery_state IN ('unknown','sent','rejected')),
    provider_receipt text, simulated boolean NOT NULL,
    attempts integer NOT NULL DEFAULT 0 CHECK(attempts BETWEEN 0 AND 5),
    sms_consent_at timestamptz NOT NULL, sms_consent_method text NOT NULL CHECK(sms_consent_method='customer_button'),
    consent_request_id uuid NOT NULL, expires_at timestamptz NOT NULL,
    verified_at timestamptz, verified_until timestamptz, consumed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(tenant_id,store_id,visitor_id,id),
    FOREIGN KEY(tenant_id,store_id,visitor_id,draft_id) REFERENCES appointment_draft(tenant_id,store_id,visitor_id,id)
);
CREATE INDEX verification_phone_rate ON contact_verification(phone_hash,created_at);
CREATE INDEX verification_visitor_rate ON contact_verification(visitor_id,created_at);
CREATE TABLE appointment_confirmation (
    id uuid PRIMARY KEY, tenant_id uuid NOT NULL, store_id uuid NOT NULL, visitor_id uuid NOT NULL,
    draft_id uuid NOT NULL UNIQUE, verification_id uuid NOT NULL UNIQUE,
    request_key uuid NOT NULL, snapshot_hash text NOT NULL, snapshot_cipher text NOT NULL,
    confirmation_text text NOT NULL, confirmed_at timestamptz NOT NULL DEFAULT now(),
    method text NOT NULL CHECK(method='customer_button'), evidence_request_id uuid NOT NULL,
    UNIQUE(tenant_id,store_id,visitor_id,id),
    FOREIGN KEY(tenant_id,store_id,visitor_id,draft_id) REFERENCES appointment_draft(tenant_id,store_id,visitor_id,id),
    FOREIGN KEY(tenant_id,store_id,visitor_id,verification_id) REFERENCES contact_verification(tenant_id,store_id,visitor_id,id)
);
CREATE TABLE appointment (
    id uuid PRIMARY KEY, tenant_id uuid NOT NULL, store_id uuid NOT NULL, visitor_id uuid NOT NULL,
    thread_id uuid NOT NULL, confirmation_id uuid NOT NULL UNIQUE,
    state text NOT NULL CHECK(state IN ('pending_store_confirmation','confirmed','arrived','completed','cancelled','declined','no_show')),
    simulated boolean NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(tenant_id,store_id,visitor_id,id),
    FOREIGN KEY(tenant_id,store_id,visitor_id,thread_id) REFERENCES conversation(tenant_id,store_id,visitor_id,id),
    FOREIGN KEY(tenant_id,store_id,visitor_id,confirmation_id) REFERENCES appointment_confirmation(tenant_id,store_id,visitor_id,id)
);
CREATE TABLE appointment_event (
    id bigserial PRIMARY KEY, appointment_id uuid NOT NULL REFERENCES appointment(id),
    event text NOT NULL CHECK(event IN ('submitted','confirmed','arrived','completed','cancelled','declined','no_show')),
    actor_id uuid NOT NULL, occurred_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE booking_outbox (
    id bigserial PRIMARY KEY, appointment_id uuid NOT NULL UNIQUE REFERENCES appointment(id),
    topic text NOT NULL CHECK(topic='appointment.submitted'),
    created_at timestamptz NOT NULL DEFAULT now(), processed_at timestamptz
);
CREATE TABLE booking_idempotency (
    tenant_id uuid NOT NULL, store_id uuid NOT NULL, visitor_id uuid NOT NULL, operation text NOT NULL,
    request_key uuid NOT NULL, request_hash text NOT NULL, result jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(tenant_id,visitor_id,operation,request_key),
    FOREIGN KEY(tenant_id,store_id,visitor_id) REFERENCES visitor(tenant_id,store_id,id)
);
CREATE INDEX appointment_owner ON appointment(tenant_id,store_id,visitor_id,created_at);
