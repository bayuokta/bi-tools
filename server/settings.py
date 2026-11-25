"""Kunci preferensi yang dipakai server web.

Nama kunci sengaja sama dengan GUI 0.3.x supaya migrasi dari QSettings tidak
perlu pemetaan tambahan. Sejak 0.4.0 modul ini menjadi satu-satunya sumber
kunci preferensi web.
"""

from __future__ import annotations

SETTINGS_ORG = "BITools"
SETTINGS_APP = "Metadata"

# Hanya untuk migrasi sekali dari organisasi lama.
LEGACY_SETTINGS_ORG = "2W-Dragon"
LEGACY_SETTINGS_APP = "BI Tools"

SETTINGS_INSTANCE_KEY = "model/last_catalog"
SETTINGS_SCOPE_KEY = "extraction/scope"
SETTINGS_SCOPE_LOCAL_KEY = "extraction/scope_local"
SETTINGS_SCOPE_SERVICE_KEY = "extraction/scope_service"
SETTINGS_ACTIVE_TAB_KEY = "extraction/active_tab"
SETTINGS_REPORT_SOURCE_KEY = "extraction/report_source"
SETTINGS_SERVICE_URL_KEY = "extraction/service_url"
SETTINGS_SERVICE_WORKSPACE_KEY = "extraction/service_workspace_id"
SETTINGS_SERVICE_REPORT_KEY = "extraction/service_report_id"
SETTINGS_OUT_DIR_KEY = "extraction/out_dir"
SETTINGS_CATALOG_MODE_KEY = "catalog/mode"
SETTINGS_CATALOG_INCLUDE_PERSONAL_KEY = "catalog/include_personal"

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
SETTINGS_TSD_AUTO_INSTALL_KEY = "tsd/auto_install_browser"

LINEAGE_DB_KEY = "lineage/db_path"
LINEAGE_TENANT_KEY = "lineage/tenant_id"
LINEAGE_CLIENT_KEY = "lineage/client_id"
LINEAGE_SECRET_KEY = "lineage/client_secret"

AUTH_TENANT_KEY = "auth/tenant_id"
AUTH_CLIENT_KEY = "auth/client_id"
AUTH_SECRET_KEY = "auth/client_secret"
AUTH_MODE_KEY = "auth/mode"
BACKUP_FOLDER_KEY = "backup/folder"
BACKUP_PREFIX_KEY = "backup/prefix"
AUTH_RLS_USER_KEY = "auth/rls_username"
AUTH_RLS_ROLES_KEY = "auth/rls_roles"
PATHS_LINEAGE_DB_KEY = "paths/lineage_db"
SHARED_DB_SOURCE_KEY = "shared_db/source"
SHARED_DB_LOCAL_KEY = "shared_db/local"
SHARED_DB_AUTO_KEY = "shared_db/auto_download"
SETTINGS_MIGRATED_KEY = "settings/migrated_v1"

# Analisa Semantic Model (read-only).
SETTINGS_ANALYSIS_WORKSPACE_KEY = "analysis/workspace_id"
SETTINGS_ANALYSIS_DATASET_KEY = "analysis/dataset_id"
SETTINGS_ANALYSIS_OTHER_WS_KEY = "analysis/include_other_workspaces"
SETTINGS_ANALYSIS_PERSONAL_KEY = "analysis/include_personal"
SETTINGS_ANALYSIS_REPORTS_KEY = "analysis/include_reports"
SETTINGS_ANALYSIS_OBJECT_FILTER_KEY = "analysis/object_filter"
SETTINGS_ANALYSIS_SORT_COLUMN_KEY = "analysis/sort_column"
SETTINGS_ANALYSIS_SORT_DESC_KEY = "analysis/sort_desc"
SETTINGS_ANALYSIS_UNUSED_ONLY_KEY = "analysis/unused_only"

# Tampilan web.
SETTINGS_UI_THEME_KEY = "ui/theme"
SETTINGS_UI_MOTION_KEY = "ui/motion"
SETTINGS_UI_CONSOLE_KEY = "ui/show_console"
SETTINGS_UI_LANGUAGE_KEY = "ui/language"

# Pilihan yang dikosongkan setiap aplikasi dibuka: sesi selalu mulai bersih.
# Preferensi (kredensial, RLS, path, cakupan, filter, sort, opsi TSD, tema)
# tetap tersimpan karena itu preferensi, bukan pilihan sesi.
SESSION_SELECTION_KEYS = (
    SETTINGS_SERVICE_WORKSPACE_KEY,
    SETTINGS_SERVICE_REPORT_KEY,
    SETTINGS_SERVICE_URL_KEY,
    SETTINGS_INSTANCE_KEY,
    SETTINGS_TSD_WORKSPACE_KEY,
    SETTINGS_TSD_REPORT_ID_KEY,
    SETTINGS_TSD_MANUAL_KEY,
    SETTINGS_ANALYSIS_WORKSPACE_KEY,
    SETTINGS_ANALYSIS_DATASET_KEY,
)

ACTIVE_TABS = ("local", "service", "tsd")
