-- Preserve historical pgvector rows; never change applied migration 003 or delete data here.
-- Active application writes/queries only Milvus. PostgreSQL stores its projection receipts.
CREATE TABLE vector_projection (
    version_id uuid PRIMARY KEY REFERENCES knowledge_version(id),
    tenant_id uuid NOT NULL,
    store_id uuid NOT NULL,
    content_hash text NOT NULL,
    model text NOT NULL,
    collection_name text NOT NULL,
    state text NOT NULL CHECK (state IN ('pending','unknown','ready','removed')),
    updated_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY(tenant_id,store_id,version_id)
        REFERENCES knowledge_version(tenant_id,store_id,id)
);
ALTER TABLE knowledge_detail ADD COLUMN guidance jsonb NOT NULL DEFAULT '{}';

-- All active knowledge must be reprojected and independently verified in Milvus.
UPDATE publication SET vector_ready=false,state='pending' WHERE state='ready';
UPDATE knowledge_version SET status='publishing' WHERE status='published';
UPDATE outbox SET processed_at=NULL,lease_token=NULL,lease_until=NULL,available_at=now(),
    last_error=NULL WHERE topic='publish' AND version_id IN (
        SELECT id FROM knowledge_version WHERE status='publishing'
    );
