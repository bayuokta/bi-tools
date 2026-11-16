"""Kunci QSettings yang dipakai bersama oleh tab-tab GUI."""

from __future__ import annotations

SETTINGS_ORG = "2W-Dragon"
SETTINGS_APP = "BI Tools"

SETTINGS_INSTANCE_KEY = "model/last_catalog"
SETTINGS_SCOPE_KEY = "extraction/scope"
SETTINGS_SCOPE_LOCAL_KEY = "extraction/scope_local"
SETTINGS_SCOPE_SERVICE_KEY = "extraction/scope_service"
SETTINGS_ACTIVE_TAB_KEY = "extraction/active_tab"
SETTINGS_REPORT_SOURCE_KEY = "extraction/report_source"
SETTINGS_SERVICE_URL_KEY = "extraction/service_url"
SETTINGS_SERVICE_WORKSPACE_KEY = "extraction/service_workspace_id"
SETTINGS_SERVICE_REPORT_KEY = "extraction/service_report_id"
SETTINGS_CATALOG_MODE_KEY = "catalog/mode"
SETTINGS_SUB_TAB_KEY = "settings/active_tab"

SETTINGS_TSD_REPORT_KEY = "tsd/report_workbook"
SETTINGS_TSD_MODEL_KEY = "tsd/model_workbook"
SETTINGS_TSD_MANUAL_KEY = "tsd/manual_path"
SETTINGS_TSD_OUT_DIR_KEY = "tsd/out_dir"
SETTINGS_TSD_DRAFT_KEY = "tsd/draft"
SETTINGS_TSD_EXPAND_KEY = "tsd/expand_all"

# Screenshot Power BI Service untuk 2.2.7.1 (kredensial memakai auth/*).
SETTINGS_TSD_SHOTS_KEY = "tsd/screenshots_enabled"
SETTINGS_TSD_WORKSPACE_KEY = "tsd/workspace_id"
SETTINGS_TSD_REPORT_ID_KEY = "tsd/report_id"
SETTINGS_TSD_RLS_USER_KEY = "tsd/rls_username"
SETTINGS_TSD_RLS_ROLES_KEY = "tsd/rls_roles"
SETTINGS_TSD_SHOT_SCOPE_KEY = "tsd/screenshot_scope"
SETTINGS_TSD_SHOT_SCALE_KEY = "tsd/screenshot_scale"
SETTINGS_TSD_SHOT_MOBILE_KEY = "tsd/screenshot_mobile"
SETTINGS_TSD_DECORATIVE_KEY = "tsd/include_decorative"

LINEAGE_DB_KEY = "lineage/db_path"
LINEAGE_TENANT_KEY = "lineage/tenant_id"
LINEAGE_CLIENT_KEY = "lineage/client_id"
LINEAGE_SECRET_KEY = "lineage/client_secret"

# Kunci baru (Commit 2): satu sumber kredensial dan path.
AUTH_TENANT_KEY = "auth/tenant_id"
AUTH_CLIENT_KEY = "auth/client_id"
AUTH_SECRET_KEY = "auth/client_secret"
PATHS_LINEAGE_DB_KEY = "paths/lineage_db"
SETTINGS_MIGRATED_KEY = "settings/migrated_v1"

# Analisa Semantic Model (read-only).
SETTINGS_ANALYSIS_WORKSPACE_KEY = "analysis/workspace_id"
SETTINGS_ANALYSIS_DATASET_KEY = "analysis/dataset_id"
SETTINGS_ANALYSIS_OTHER_WS_KEY = "analysis/include_other_workspaces"
SETTINGS_ANALYSIS_PERSONAL_KEY = "analysis/include_personal"
SETTINGS_ANALYSIS_OBJECT_FILTER_KEY = "analysis/object_filter"
SETTINGS_ANALYSIS_SORT_COLUMN_KEY = "analysis/sort_column"
SETTINGS_ANALYSIS_SORT_DESC_KEY = "analysis/sort_desc"
SETTINGS_ANALYSIS_UNUSED_ONLY_KEY = "analysis/unused_only"
