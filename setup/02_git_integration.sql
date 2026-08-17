-- =====================================================================
-- Personal Finance Analytics Platform :: GitHub integration
-- =====================================================================
-- Connects Snowflake to the project's GitHub repository so Snowsight
-- Workspaces and dbt Projects on Snowflake can pull (and, with a user
-- supplied PAT, push) the repo.
--
-- Idempotent. Safe to re-run.
--
-- Run with:
--   snow sql -f setup/02_git_integration.sql -c pfin
--
-- Contains no secret. The GitHub personal access token needed for
-- pushes from a workspace is entered interactively in Snowsight when
-- connecting the workspace, and lives only in Snowflake's secret store.
-- =====================================================================

USE ROLE ACCOUNTADMIN;
USE DATABASE PERSONAL_FINANCE;

-- ---------------------------------------------------------------------
-- 1. API integration for GitHub over HTTPS
-- ---------------------------------------------------------------------
-- Scoped to the single owner prefix rather than all of github.com, so
-- this integration cannot be pointed at arbitrary repositories.
-- ---------------------------------------------------------------------

CREATE API INTEGRATION IF NOT EXISTS PFIN_GITHUB
    API_PROVIDER          = GIT_HTTPS_API
    API_ALLOWED_PREFIXES  = ('https://github.com/YunlouTeng/')
    ENABLED               = TRUE
    COMMENT               = 'GitHub access for the personal-finance-analytics repo';

-- ---------------------------------------------------------------------
-- 2. Git repository object
-- ---------------------------------------------------------------------
-- Lives in UTIL alongside the other helper objects. Read-only clone of
-- the public repo; fetches are on demand (ALTER GIT REPOSITORY ... FETCH)
-- or driven by the workspace.
-- ---------------------------------------------------------------------

CREATE GIT REPOSITORY IF NOT EXISTS UTIL.PFIN_REPO
    API_INTEGRATION = PFIN_GITHUB
    ORIGIN          = 'https://github.com/YunlouTeng/personal-finance-analytics.git'
    COMMENT         = 'Source of truth for dbt Projects on Snowflake';

-- ---------------------------------------------------------------------
-- 3. Grants
-- ---------------------------------------------------------------------
-- The transformer role can read the repo object and create dbt project
-- objects in UTIL, so deploys do not require ACCOUNTADMIN.
-- ---------------------------------------------------------------------

GRANT READ ON GIT REPOSITORY UTIL.PFIN_REPO  TO ROLE PFIN_TRANSFORMER;
GRANT CREATE DBT PROJECT ON SCHEMA UTIL      TO ROLE PFIN_TRANSFORMER;

-- ---------------------------------------------------------------------
-- 4. Verification
-- ---------------------------------------------------------------------

SHOW GIT REPOSITORIES IN SCHEMA UTIL;
ALTER GIT REPOSITORY UTIL.PFIN_REPO FETCH;
SHOW GIT BRANCHES IN UTIL.PFIN_REPO;
