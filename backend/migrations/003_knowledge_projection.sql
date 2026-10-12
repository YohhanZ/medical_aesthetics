CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE knowledge_detail (
    version_id uuid PRIMARY KEY REFERENCES knowledge_version(id),
    audience text NOT NULL CHECK (audience IN ('public','internal')),
    topics text[] NOT NULL DEFAULT '{}',
    entities jsonb NOT NULL DEFAULT '[]',
    relations jsonb NOT NULL DEFAULT '[]'
);
INSERT INTO knowledge_detail(version_id,audience)
SELECT id,CASE WHEN category='communication' THEN 'internal' ELSE 'public' END
FROM knowledge_version;

CREATE TABLE knowledge_import (
    tenant_id uuid NOT NULL,
    store_id uuid NOT NULL,
    knowledge_key text NOT NULL,
    content_hash text NOT NULL,
    version_id uuid NOT NULL REFERENCES knowledge_version(id),
    imported_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(tenant_id,store_id,knowledge_key,content_hash),
    FOREIGN KEY(tenant_id,store_id,version_id)
        REFERENCES knowledge_version(tenant_id,store_id,id)
);

CREATE TABLE knowledge_embedding (
    version_id uuid PRIMARY KEY REFERENCES knowledge_version(id),
    content_hash text NOT NULL,
    model text NOT NULL,
    embedding vector(256) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE outbox ADD COLUMN lease_token uuid;
ALTER TABLE outbox ADD COLUMN lease_until timestamptz;
ALTER TABLE outbox ADD COLUMN available_at timestamptz NOT NULL DEFAULT now();
ALTER TABLE outbox ADD COLUMN last_error text;
CREATE INDEX outbox_available ON outbox(available_at,id) WHERE processed_at IS NULL;
