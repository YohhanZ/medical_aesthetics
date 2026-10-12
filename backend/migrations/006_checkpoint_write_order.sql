-- LangGraph may persist task writes before its asynchronously saved parent checkpoint.
-- Both are independently owned by a fenced run; loading joins through that run/checkpoint ID.
ALTER TABLE agent_checkpoint_write DROP CONSTRAINT agent_checkpoint_write_run_id_checkpoint_id_fkey;
ALTER TABLE agent_checkpoint_write ADD CONSTRAINT checkpoint_write_run_fk
    FOREIGN KEY(run_id) REFERENCES agent_run(id);
