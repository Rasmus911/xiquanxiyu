-- Read-only full pg_dump identity. Enable login/password only by explicit user action.
BEGIN;
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='xiquan_backup') THEN
        CREATE ROLE xiquan_backup NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='xiquan_backup'
               AND (rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls))
       OR EXISTS (SELECT 1 FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.member WHERE r.rolname='xiquan_backup')
       OR EXISTS (SELECT 1 FROM pg_namespace n WHERE n.nspname='public' AND pg_has_role('xiquan_backup',n.nspowner,'MEMBER'))
       OR EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                  WHERE n.nspname='public' AND pg_has_role('xiquan_backup',c.relowner,'MEMBER'))
       OR EXISTS (SELECT 1 FROM pg_database d WHERE d.datname=current_database() AND pg_has_role('xiquan_backup',d.datdba,'MEMBER')) THEN
        RAISE EXCEPTION 'Backup role must be a dedicated nonprivileged nonowner without memberships.';
    END IF;
END $$;
SELECT format('GRANT CONNECT ON DATABASE %I TO xiquan_backup', current_database()) \gexec
ALTER ROLE xiquan_backup NOLOGIN;
REVOKE CREATE ON SCHEMA public FROM PUBLIC, xiquan_backup;
GRANT USAGE ON SCHEMA public TO xiquan_backup;
REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM xiquan_backup;
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM xiquan_backup;
SELECT format('REVOKE ALL PRIVILEGES (%s) ON TABLE %I.%I FROM xiquan_backup',
              string_agg(quote_ident(column_name), ', '), table_schema, table_name)
FROM information_schema.columns WHERE table_schema='public'
GROUP BY table_schema, table_name \gexec
GRANT SELECT ON ALL TABLES IN SCHEMA public TO xiquan_backup;
GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO xiquan_backup;
ALTER ROLE xiquan_backup SET default_transaction_read_only = on;
COMMIT;
