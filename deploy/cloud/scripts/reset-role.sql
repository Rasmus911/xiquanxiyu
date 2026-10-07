-- Run manually as maintenance owner AFTER db upgrade. Never embeds a password.
-- Enable login explicitly later with psql \password xiquan_reset and ALTER ROLE.
BEGIN;
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='xiquan_reset') THEN
        CREATE ROLE xiquan_reset NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='xiquan_reset'
               AND (rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls))
       OR EXISTS (SELECT 1 FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.member WHERE r.rolname='xiquan_reset')
       OR EXISTS (SELECT 1 FROM pg_namespace n WHERE n.nspname='public' AND pg_has_role('xiquan_reset',n.nspowner,'MEMBER'))
       OR EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                  WHERE n.nspname='public' AND pg_has_role('xiquan_reset',c.relowner,'MEMBER'))
       OR EXISTS (SELECT 1 FROM pg_database d WHERE d.datname=current_database() AND pg_has_role('xiquan_reset',d.datdba,'MEMBER')) THEN
        RAISE EXCEPTION 'Reset role must be a dedicated nonprivileged nonowner without memberships.';
    END IF;
END $$;
SELECT format('GRANT CONNECT ON DATABASE %I TO xiquan_reset', current_database()) \gexec
ALTER ROLE xiquan_reset NOLOGIN;
REVOKE CREATE ON SCHEMA public FROM PUBLIC, xiquan_reset;
GRANT USAGE ON SCHEMA public TO xiquan_reset;
REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM xiquan_reset;
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM xiquan_reset;
SELECT format('REVOKE ALL PRIVILEGES (%s) ON TABLE %I.%I FROM xiquan_reset',
              string_agg(quote_ident(column_name), ', '), table_schema, table_name)
FROM information_schema.columns WHERE table_schema='public'
GROUP BY table_schema, table_name \gexec
GRANT SELECT ON ALL TABLES IN SCHEMA public TO xiquan_reset;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO xiquan_reset;
GRANT INSERT, UPDATE ON reset_tasks TO xiquan_reset;
GRANT INSERT ON business_periods TO xiquan_reset;
GRANT UPDATE (closed_at, updated_at) ON business_periods TO xiquan_reset;
GRANT UPDATE (period_id, business_revision, maintenance, maintenance_reset_id) ON business_state TO xiquan_reset;
GRANT UPDATE (status, closed_at, version, updated_at) ON visits TO xiquan_reset;
GRANT UPDATE (status, closed_at, close_note, version, updated_at) ON shifts TO xiquan_reset;
GRANT UPDATE (stock_quantity, version, updated_at) ON catalog_items TO xiquan_reset;
GRANT UPDATE (stock_quantity, version, updated_at) ON stock_items TO xiquan_reset;
GRANT UPDATE (status, note, version, updated_at) ON wristbands TO xiquan_reset;
GRANT UPDATE (session_version, updated_at) ON employees TO xiquan_reset;
GRANT INSERT ON inventory_movements, stock_movements, audit_logs, reset_events TO xiquan_reset;
GRANT UPDATE (delivered_at, updated_at) ON reset_events TO xiquan_reset;
COMMIT;
