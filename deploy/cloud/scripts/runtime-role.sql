-- Run against the bathhouse database as its owner after the security migration.
-- This does not set or print a password. Set it with psql \password xiquan_app.
BEGIN;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='xiquan_app') THEN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='xiquan_app'
                   AND (rolsuper OR rolcreaterole OR rolcreatedb OR rolreplication OR rolbypassrls)) THEN
            RAISE EXCEPTION 'Existing xiquan_app is privileged. Choose a dedicated runtime role.';
        END IF;
    ELSE
        CREATE ROLE xiquan_app NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
    END IF;
END $$;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.member
               WHERE r.rolname='xiquan_app')
       OR EXISTS (SELECT 1 FROM pg_namespace n WHERE n.nspname='public'
                  AND pg_has_role('xiquan_app', n.nspowner, 'MEMBER'))
       OR EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                  WHERE n.nspname='public' AND pg_has_role('xiquan_app', c.relowner, 'MEMBER'))
       OR EXISTS (SELECT 1 FROM pg_database d WHERE d.datname=current_database()
                  AND pg_has_role('xiquan_app', d.datdba, 'MEMBER')) THEN
        RAISE EXCEPTION 'Runtime role must have no memberships or schema/table/database ownership.';
    END IF;
END $$;
SELECT format('GRANT CONNECT ON DATABASE %I TO xiquan_app', current_database()) \gexec
ALTER ROLE xiquan_app NOLOGIN;
GRANT USAGE ON SCHEMA public TO xiquan_app;
REVOKE CREATE ON SCHEMA public FROM PUBLIC, xiquan_app;
REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM xiquan_app;
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM xiquan_app;
-- Table-level revocation does not remove old column grants.
SELECT format('REVOKE ALL PRIVILEGES (%s) ON TABLE %I.%I FROM xiquan_app',
              string_agg(quote_ident(column_name), ', '), table_schema, table_name)
FROM information_schema.columns WHERE table_schema='public'
GROUP BY table_schema, table_name \gexec
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO xiquan_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO xiquan_app;
REVOKE UPDATE, DELETE, TRUNCATE ON audit_logs, payments, stored_value_ledgers,
    pass_ledgers, inventory_movements, settlement_visits, revoked_sessions,
    idempotency_records, stock_movements, order_stock_consumptions FROM xiquan_app;
-- Additive 0.4.7 table may not exist on older schemas.
SELECT 'REVOKE UPDATE,DELETE,TRUNCATE ON stock_costs FROM xiquan_app'
WHERE to_regclass('public.stock_costs') IS NOT NULL \gexec
SELECT 'REVOKE ALL ON schema_upgrade_markers FROM xiquan_app'
WHERE to_regclass('public.schema_upgrade_markers') IS NOT NULL \gexec
SELECT 'GRANT SELECT ON schema_upgrade_markers TO xiquan_app'
WHERE to_regclass('public.schema_upgrade_markers') IS NOT NULL \gexec
-- Additive 0.4.9 security state; no runtime deletion or receipt rewriting.
SELECT 'REVOKE DELETE,TRUNCATE ON registration_token_state,registration_rate_limits FROM xiquan_app'
WHERE to_regclass('public.registration_token_state') IS NOT NULL \gexec
SELECT 'REVOKE UPDATE,DELETE,TRUNCATE ON registration_receipts,registration_token_views FROM xiquan_app'
WHERE to_regclass('public.registration_receipts') IS NOT NULL \gexec
REVOKE DELETE, TRUNCATE ON settlements FROM xiquan_app;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON alembic_version FROM xiquan_app;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON business_state, business_periods,
    access_policies, reset_tasks, reset_events FROM xiquan_app;
COMMIT;
