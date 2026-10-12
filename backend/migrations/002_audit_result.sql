ALTER TABLE audit ADD COLUMN result text NOT NULL DEFAULT 'success'
    CHECK(result IN ('success','denied'));
ALTER TABLE audit ADD COLUMN version_ref uuid;
