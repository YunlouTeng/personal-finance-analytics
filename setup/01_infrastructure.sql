-- =====================================================================
-- Personal Finance Analytics Platform :: Snowflake Infrastructure
-- =====================================================================
-- Idempotent. Safe to re-run. Rebuilds the entire environment from
-- scratch, which matters because Snowflake trial accounts expire and
-- this project should be redeployable in one command.
--
-- Run with:
--   snow sql -f setup/01_infrastructure.sql -c <your_connection>
--
-- Requires a role that can create warehouses and databases
-- (ACCOUNTADMIN or SYSADMIN + granted privileges).
-- =====================================================================

USE ROLE ACCOUNTADMIN;

-- ---------------------------------------------------------------------
-- 1. Warehouse
-- ---------------------------------------------------------------------
-- XSMALL is plenty for personal-scale data. AUTO_SUSPEND at 60 seconds
-- is the single most important cost control on a trial account: the
-- warehouse stops billing about a minute after the last query.
-- ---------------------------------------------------------------------

CREATE WAREHOUSE IF NOT EXISTS PFIN_WH
    WAREHOUSE_SIZE       = 'XSMALL'
    WAREHOUSE_TYPE       = 'STANDARD'
    AUTO_SUSPEND         = 60
    AUTO_RESUME          = TRUE
    INITIALLY_SUSPENDED  = TRUE
    COMMENT              = 'Compute for personal finance ingestion, dbt, and Streamlit';

-- ---------------------------------------------------------------------
-- 2. Database and schemas
-- ---------------------------------------------------------------------
-- RAW       : landing zone, loaded by the Plaid ingestion script. Never
--             touched by hand, never modified by dbt.
-- STAGING   : dbt staging models (cleaned, renamed, typed).
-- MARTS     : dbt marts (facts, dimensions, aggregates) that the
--             Streamlit app reads from.
-- UTIL      : helper objects, stages, file formats, seeds.
-- ---------------------------------------------------------------------

CREATE DATABASE IF NOT EXISTS PERSONAL_FINANCE
    COMMENT = 'Personal finance analytics platform';

USE DATABASE PERSONAL_FINANCE;

CREATE SCHEMA IF NOT EXISTS RAW
    COMMENT = 'Landing zone for Plaid API extracts. Write-only from ingestion.';

CREATE SCHEMA IF NOT EXISTS STAGING
    COMMENT = 'dbt staging layer';

CREATE SCHEMA IF NOT EXISTS MARTS
    COMMENT = 'dbt marts layer consumed by Streamlit';

CREATE SCHEMA IF NOT EXISTS UTIL
    COMMENT = 'Stages, file formats, and helper objects';

-- ---------------------------------------------------------------------
-- 3. File format and internal stage for Plaid extracts
-- ---------------------------------------------------------------------
-- Plaid returns nested JSON. Land it as-is and let dbt do the
-- flattening, so the raw payload is always recoverable.
-- ---------------------------------------------------------------------

CREATE FILE FORMAT IF NOT EXISTS UTIL.JSON_FORMAT
    TYPE                        = 'JSON'
    STRIP_OUTER_ARRAY           = TRUE
    COMPRESSION                 = 'AUTO'
    COMMENT                     = 'Plaid API JSON payloads';

CREATE STAGE IF NOT EXISTS UTIL.PLAID_STAGE
    FILE_FORMAT = UTIL.JSON_FORMAT
    COMMENT     = 'Internal stage for Plaid JSON extracts';

-- ---------------------------------------------------------------------
-- 4. Raw landing tables
-- ---------------------------------------------------------------------
-- One VARIANT column per source endpoint plus load metadata. This is
-- the ELT pattern: land the payload untouched, transform downstream.
-- _LOADED_AT and _SOURCE_FILE make debugging and incremental logic easy.
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS RAW.PLAID_TRANSACTIONS (
    PAYLOAD         VARIANT       NOT NULL,
    _LOADED_AT      TIMESTAMP_NTZ NOT NULL DEFAULT CURRENT_TIMESTAMP(),
    _SOURCE_FILE    VARCHAR,
    _SYNC_CURSOR    VARCHAR
)
COMMENT = 'Raw payloads from Plaid /transactions/sync';

CREATE TABLE IF NOT EXISTS RAW.PLAID_ACCOUNTS (
    PAYLOAD         VARIANT       NOT NULL,
    _LOADED_AT      TIMESTAMP_NTZ NOT NULL DEFAULT CURRENT_TIMESTAMP(),
    _SOURCE_FILE    VARCHAR
)
COMMENT = 'Raw payloads from Plaid /accounts/get';

CREATE TABLE IF NOT EXISTS RAW.PLAID_BALANCES (
    PAYLOAD         VARIANT       NOT NULL,
    _LOADED_AT      TIMESTAMP_NTZ NOT NULL DEFAULT CURRENT_TIMESTAMP(),
    _SOURCE_FILE    VARCHAR
)
COMMENT = 'Point-in-time balance snapshots from Plaid /accounts/balance/get';

-- Cursor bookkeeping for /transactions/sync. The ingestion script reads
-- the last cursor per item and passes it back to Plaid so each run only
-- pulls new, modified, and removed transactions.
CREATE TABLE IF NOT EXISTS RAW.SYNC_STATE (
    ITEM_ID         VARCHAR       NOT NULL,
    INSTITUTION     VARCHAR,
    CURSOR          VARCHAR,
    LAST_SYNCED_AT  TIMESTAMP_NTZ NOT NULL DEFAULT CURRENT_TIMESTAMP()
)
COMMENT = 'Last successful sync cursor per Plaid Item';

-- ---------------------------------------------------------------------
-- 5. Transform role for dbt
-- ---------------------------------------------------------------------
-- Running dbt as a dedicated least-privilege role rather than
-- ACCOUNTADMIN is the production pattern and is worth practicing.
-- Replace <YOUR_SNOWFLAKE_USER> before running, or comment out the
-- final GRANT and assign the role in Snowsight.
-- ---------------------------------------------------------------------

CREATE ROLE IF NOT EXISTS PFIN_TRANSFORMER
    COMMENT = 'Role used by dbt to build staging and marts models';

GRANT USAGE ON WAREHOUSE PFIN_WH             TO ROLE PFIN_TRANSFORMER;
GRANT OPERATE ON WAREHOUSE PFIN_WH           TO ROLE PFIN_TRANSFORMER;

GRANT USAGE ON DATABASE PERSONAL_FINANCE     TO ROLE PFIN_TRANSFORMER;
GRANT CREATE SCHEMA ON DATABASE PERSONAL_FINANCE TO ROLE PFIN_TRANSFORMER;

GRANT USAGE ON SCHEMA PERSONAL_FINANCE.RAW   TO ROLE PFIN_TRANSFORMER;
GRANT SELECT ON ALL TABLES IN SCHEMA PERSONAL_FINANCE.RAW    TO ROLE PFIN_TRANSFORMER;
GRANT SELECT ON FUTURE TABLES IN SCHEMA PERSONAL_FINANCE.RAW TO ROLE PFIN_TRANSFORMER;

GRANT ALL ON SCHEMA PERSONAL_FINANCE.STAGING TO ROLE PFIN_TRANSFORMER;
GRANT ALL ON SCHEMA PERSONAL_FINANCE.MARTS   TO ROLE PFIN_TRANSFORMER;
GRANT USAGE ON SCHEMA PERSONAL_FINANCE.UTIL  TO ROLE PFIN_TRANSFORMER;

-- Uncomment and set your username to grant yourself the role:
-- GRANT ROLE PFIN_TRANSFORMER TO USER <YOUR_SNOWFLAKE_USER>;

-- ---------------------------------------------------------------------
-- 6. Verification
-- ---------------------------------------------------------------------

SELECT 'Infrastructure ready' AS status,
       CURRENT_ACCOUNT()      AS account,
       CURRENT_WAREHOUSE()    AS warehouse,
       CURRENT_DATABASE()     AS database;

SHOW SCHEMAS IN DATABASE PERSONAL_FINANCE;
SHOW TABLES IN SCHEMA PERSONAL_FINANCE.RAW;
