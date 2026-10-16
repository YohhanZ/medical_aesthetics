-- Public store locations use WGS84, matching the browser Geolocation API.
ALTER TABLE store
    ADD COLUMN city text NOT NULL DEFAULT '',
    ADD COLUMN address text NOT NULL DEFAULT '',
    ADD COLUMN latitude double precision,
    ADD COLUMN longitude double precision,
    ADD CONSTRAINT store_coordinates_valid CHECK (
        (latitude IS NULL AND longitude IS NULL)
        OR (latitude IS NOT NULL AND longitude IS NOT NULL
            AND latitude BETWEEN -90 AND 90 AND longitude BETWEEN -180 AND 180)
    );
