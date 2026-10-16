-- Customer credentials are tenant scoped; history and memory remain store scoped.
CREATE TABLE customer_account (
    id uuid PRIMARY KEY, tenant_id uuid NOT NULL REFERENCES tenant(id),
    username text NOT NULL, password_hash text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(tenant_id,username), UNIQUE(tenant_id,id)
);
ALTER TABLE visitor ADD COLUMN customer_id uuid;
ALTER TABLE visitor ADD COLUMN memory_enabled boolean NOT NULL DEFAULT false;
ALTER TABLE visitor ADD COLUMN behavior_enabled boolean NOT NULL DEFAULT false;
ALTER TABLE visitor ADD COLUMN memory_generation integer NOT NULL DEFAULT 0;
ALTER TABLE agent_run ADD COLUMN customer_memory_generation integer;
ALTER TABLE visitor ADD CONSTRAINT visitor_customer_fk
    FOREIGN KEY(tenant_id,customer_id) REFERENCES customer_account(tenant_id,id);
CREATE UNIQUE INDEX customer_store_identity ON visitor(tenant_id,store_id,customer_id)
    WHERE customer_id IS NOT NULL;
ALTER TABLE auth_session ADD COLUMN customer_id uuid;
ALTER TABLE auth_session ADD CONSTRAINT session_customer_fk
    FOREIGN KEY(tenant_id,customer_id) REFERENCES customer_account(tenant_id,id);
CREATE TABLE customer_memory (
    visitor_id uuid NOT NULL REFERENCES visitor(id),
    key text NOT NULL CHECK(key IN ('comfort','visit_time','budget','communication')),
    value text NOT NULL CHECK(length(value)<=80),
    source_thread_id uuid NOT NULL REFERENCES conversation(id),
    source_run_id uuid NOT NULL REFERENCES agent_run(id),
    updated_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL DEFAULT now()+interval '90 days',
    PRIMARY KEY(visitor_id,key)
);
CREATE TABLE customer_behavior (
    id uuid PRIMARY KEY, visitor_id uuid NOT NULL REFERENCES visitor(id),
    event text NOT NULL CHECK(event IN ('project_view','category_view','consultation_started')),
    target text NOT NULL CHECK(length(target)<=80),
    occurred_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX customer_behavior_recent ON customer_behavior(visitor_id,occurred_at DESC);
