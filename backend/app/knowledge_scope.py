"""Only independently reviewed, sourced medical education in explicit local simulation."""

# Fixed aliases belong to the two authority queries, never user-controlled identifiers.
MEDICAL_VISIBILITY_SQL = (
    "(k.category<>'medical' OR (%s AND k.simulated AND r.simulated "
    "AND s.simulated AND t.simulated "
    "AND d.audience='public' AND d.guidance->>'review_scope'='demo_education' "
    "AND d.guidance->>'source_type' IN ('official_public','authoritative_medical') "
    "AND jsonb_array_length(d.guidance->'source_urls')>0 "
    "AND d.guidance->>'source_date' IS NOT NULL)) "
)
