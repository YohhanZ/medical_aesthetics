CREATE TABLE marketing_job (
    id uuid PRIMARY KEY,
    tenant_id uuid NOT NULL, store_id uuid NOT NULL, staff_id uuid NOT NULL,
    request_key uuid NOT NULL, request_hash text NOT NULL,
    kind text NOT NULL CHECK(kind IN ('image','video')),
    state text NOT NULL DEFAULT 'queued'
        CHECK(state IN ('queued','submitting','running','succeeded','failed','unknown','cancelled')),
    brand text NOT NULL, title text NOT NULL, prompt text NOT NULL, caption text NOT NULL,
    aspect text NOT NULL CHECK(aspect IN ('square','portrait','landscape')),
    project_id uuid, simulated boolean NOT NULL, model text NOT NULL,
    provider_task_id text, provider_asset_url text, asset_name text, asset_mime text, asset_bytes bigint,
    error_code text, attempts integer NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
    available_at timestamptz NOT NULL DEFAULT now(), lease_until timestamptz,
    lease_token uuid,
    UNIQUE(tenant_id,store_id,request_key),
    FOREIGN KEY(tenant_id,store_id) REFERENCES store(tenant_id,id),
    FOREIGN KEY(tenant_id,staff_id) REFERENCES staff(tenant_id,id)
);
CREATE INDEX marketing_scope ON marketing_job(tenant_id,store_id,created_at DESC,id);
CREATE INDEX marketing_queue ON marketing_job(available_at)
    WHERE state IN ('queued','running','submitting');
