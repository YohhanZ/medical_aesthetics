CREATE TABLE tenant (
    id uuid PRIMARY KEY, name text NOT NULL, simulated boolean NOT NULL
);
CREATE TABLE store (
    id uuid PRIMARY KEY, tenant_id uuid NOT NULL REFERENCES tenant(id),
    public_code text NOT NULL UNIQUE, name text NOT NULL,
    active boolean NOT NULL DEFAULT true, simulated boolean NOT NULL,
    UNIQUE(tenant_id,id)
);
CREATE TABLE staff (
    id uuid PRIMARY KEY, tenant_id uuid NOT NULL REFERENCES tenant(id),
    username text NOT NULL UNIQUE, password_hash text NOT NULL,
    active boolean NOT NULL DEFAULT true, simulated boolean NOT NULL,
    UNIQUE(tenant_id,id)
);
CREATE TABLE store_grant (
    tenant_id uuid NOT NULL, staff_id uuid NOT NULL, store_id uuid NOT NULL,
    permission text NOT NULL CHECK(permission IN ('knowledge_author','knowledge_review','knowledge_publish')),
    PRIMARY KEY(tenant_id,staff_id,store_id,permission),
    FOREIGN KEY(tenant_id,staff_id) REFERENCES staff(tenant_id,id),
    FOREIGN KEY(tenant_id,store_id) REFERENCES store(tenant_id,id)
);
CREATE TABLE visitor (
    id uuid PRIMARY KEY, tenant_id uuid NOT NULL, store_id uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(tenant_id,store_id,id),
    FOREIGN KEY(tenant_id,store_id) REFERENCES store(tenant_id,id)
);
CREATE TABLE auth_session (
    id uuid PRIMARY KEY, tenant_id uuid NOT NULL REFERENCES tenant(id),
    visitor_id uuid, staff_id uuid, store_id uuid,
    token_hash text NOT NULL UNIQUE, csrf_hash text,
    expires_at timestamptz NOT NULL, revoked_at timestamptz,
    CHECK((visitor_id IS NOT NULL AND staff_id IS NULL AND store_id IS NOT NULL AND csrf_hash IS NOT NULL)
       OR (staff_id IS NOT NULL AND visitor_id IS NULL AND store_id IS NULL)),
    FOREIGN KEY(tenant_id,store_id,visitor_id) REFERENCES visitor(tenant_id,store_id,id),
    FOREIGN KEY(tenant_id,staff_id) REFERENCES staff(tenant_id,id)
);
CREATE TABLE conversation (
    id uuid PRIMARY KEY, tenant_id uuid NOT NULL, store_id uuid NOT NULL, visitor_id uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY(tenant_id,store_id,visitor_id) REFERENCES visitor(tenant_id,store_id,id)
);
CREATE TABLE knowledge_version (
    id uuid PRIMARY KEY, tenant_id uuid NOT NULL, store_id uuid NOT NULL,
    knowledge_key text NOT NULL, version integer NOT NULL CHECK(version>0),
    category text NOT NULL CHECK(category IN ('operational','communication','medical')),
    title text NOT NULL, content text NOT NULL, source text NOT NULL,
    author_id uuid NOT NULL, simulated boolean NOT NULL,
    valid_until timestamptz NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
    status text NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','approved','rejected','publishing','published','withdrawn')),
    UNIQUE(tenant_id,store_id,knowledge_key,version), UNIQUE(tenant_id,store_id,id),
    FOREIGN KEY(tenant_id,store_id) REFERENCES store(tenant_id,id),
    FOREIGN KEY(tenant_id,author_id) REFERENCES staff(tenant_id,id)
);
CREATE TABLE knowledge_review (
    version_id uuid PRIMARY KEY, tenant_id uuid NOT NULL, store_id uuid NOT NULL,
    reviewer_id uuid NOT NULL, approved boolean NOT NULL,
    simulated boolean NOT NULL, reason text NOT NULL, reviewed_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY(tenant_id,store_id,version_id) REFERENCES knowledge_version(tenant_id,store_id,id),
    FOREIGN KEY(tenant_id,reviewer_id) REFERENCES staff(tenant_id,id)
);
CREATE TABLE publication (
    version_id uuid PRIMARY KEY, tenant_id uuid NOT NULL, store_id uuid NOT NULL,
    state text NOT NULL CHECK(state IN ('pending','ready','withdrawn')),
    vector_ready boolean NOT NULL DEFAULT false, graph_ready boolean NOT NULL DEFAULT false,
    FOREIGN KEY(tenant_id,store_id,version_id) REFERENCES knowledge_version(tenant_id,store_id,id)
);
CREATE TABLE outbox (
    id bigserial PRIMARY KEY, tenant_id uuid NOT NULL, store_id uuid NOT NULL,
    version_id uuid NOT NULL, topic text NOT NULL CHECK(topic IN ('publish','withdraw')),
    created_at timestamptz NOT NULL DEFAULT now(), processed_at timestamptz,
    attempts integer NOT NULL DEFAULT 0, UNIQUE(version_id,topic),
    FOREIGN KEY(tenant_id,store_id,version_id) REFERENCES knowledge_version(tenant_id,store_id,id)
);
CREATE TABLE audit (
    id bigserial PRIMARY KEY, tenant_id uuid NOT NULL REFERENCES tenant(id), actor_id uuid NOT NULL,
    action text NOT NULL, resource text NOT NULL, request_id uuid NOT NULL,
    occurred_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE login_bucket (
    bucket_hash text PRIMARY KEY, attempts integer NOT NULL, window_start timestamptz NOT NULL
);
CREATE INDEX conversation_owner ON conversation(tenant_id,store_id,visitor_id);
CREATE INDEX evidence_scope ON knowledge_version(tenant_id,store_id,status,valid_until);
CREATE INDEX outbox_pending ON outbox(id) WHERE processed_at IS NULL;
