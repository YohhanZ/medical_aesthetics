ALTER TABLE conversation ADD CONSTRAINT conversation_scope UNIQUE(tenant_id,store_id,visitor_id,id);
CREATE TABLE agent_run (
    id uuid PRIMARY KEY, tenant_id uuid NOT NULL, store_id uuid NOT NULL, visitor_id uuid NOT NULL,
    thread_id uuid NOT NULL, message_id uuid NOT NULL, request_hash text NOT NULL,
    status text NOT NULL CHECK(status IN ('running','completed','failed')),
    lease_token uuid NOT NULL, lease_until timestamptz NOT NULL, fence bigint NOT NULL DEFAULT 1,
    result jsonb, error_code text, created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(thread_id,message_id),
    FOREIGN KEY(tenant_id,store_id,visitor_id,thread_id) REFERENCES conversation(tenant_id,store_id,visitor_id,id)
);
CREATE INDEX agent_active_thread ON agent_run(thread_id,status,lease_until);
CREATE INDEX agent_visitor_rate ON agent_run(visitor_id,created_at);
CREATE TABLE agent_message (
    id uuid PRIMARY KEY, run_id uuid NOT NULL REFERENCES agent_run(id),
    role text NOT NULL CHECK(role IN ('user','assistant')), content text NOT NULL,
    exportable boolean NOT NULL DEFAULT false, created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(run_id,role)
);
CREATE TABLE agent_checkpoint (
    run_id uuid NOT NULL REFERENCES agent_run(id), checkpoint_id text NOT NULL,
    parent_id text, checkpoint jsonb NOT NULL, metadata jsonb NOT NULL,
    PRIMARY KEY(run_id,checkpoint_id)
);
CREATE TABLE agent_checkpoint_write (
    run_id uuid NOT NULL, checkpoint_id text NOT NULL, task_id text NOT NULL,
    write_idx integer NOT NULL, channel text NOT NULL, value jsonb NOT NULL,
    PRIMARY KEY(run_id,checkpoint_id,task_id,write_idx),
    FOREIGN KEY(run_id,checkpoint_id) REFERENCES agent_checkpoint(run_id,checkpoint_id)
);
CREATE TABLE agent_memory (
    thread_id uuid PRIMARY KEY REFERENCES conversation(id), version bigint NOT NULL DEFAULT 1,
    snapshot jsonb NOT NULL, updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE handoff_ticket (
    id uuid PRIMARY KEY, run_id uuid NOT NULL UNIQUE REFERENCES agent_run(id),
    reason text NOT NULL, status text NOT NULL DEFAULT 'waiting' CHECK(status IN ('waiting','closed')),
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE agent_trace (
    id bigserial PRIMARY KEY, run_id uuid NOT NULL REFERENCES agent_run(id), node text NOT NULL,
    elapsed_ms integer NOT NULL, outcome text NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
