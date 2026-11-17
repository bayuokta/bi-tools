"""Tab Pengaturan (view pasif): sub-tab Kredensial dan Katalog & Database."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .job_runner import WindowSubmitter
from .settings import SETTINGS_SUB_TAB_KEY
from .settings_store import AppSettings
from .viewmodels.settings import SettingsState, SettingsViewModel
from .widgets import PathRow

if TYPE_CHECKING:
    from .main_window import MainWindow

CATALOG_MODE_OPTIONS = [
    ("Otomatis (admin lalu member)", "auto"),
    ("Admin (seluruh tenant)", "admin"),
    ("Member (workspace yang dapat diakses)", "member"),
]

SUB_TAB_CREDENTIALS = "credentials"
SUB_TAB_CATALOG = "catalog"
SUB_TAB_ORDER = (SUB_TAB_CREDENTIALS, SUB_TAB_CATALOG)


class SettingsTab(QWidget):
    """Kredensial, identitas RLS default, path, dan katalog dalam sub-tab."""

    def __init__(
        self,
        window: MainWindow,
        *,
        settings: AppSettings | None = None,
    ) -> None:
        super().__init__()
        self.window = window
        self._settings = settings or AppSettings()
        runner = getattr(window, "runner", None) or WindowSubmitter(window)
        self.vm = SettingsViewModel(self._settings, runner)

        self._build_ui(self.vm.build_state())

        self.vm.state_changed.connect(self.render)
        self.vm.log.connect(self.window.log)
        self.tenant.textChanged.connect(lambda text: self.vm.apply(tenant_id=text))
        self.client.textChanged.connect(lambda text: self.vm.apply(client_id=text))
        self.secret.textChanged.connect(
            lambda text: self.vm.apply(client_secret=text)
        )
        self.rls_username.textChanged.connect(
            lambda text: self.vm.apply(rls_username=text)
        )
        self.rls_roles.textChanged.connect(lambda text: self.vm.apply(rls_roles=text))
        self.db_path.edit.textChanged.connect(
            lambda text: self.vm.apply(database=text)
        )
        self.show_secret.toggled.connect(self._toggle_secret)
        self.save_button.clicked.connect(self.vm.save)
        self.test_button.clicked.connect(self.vm.test_connection)
        self.catalog_mode.currentIndexChanged.connect(self._on_catalog_mode)
        self.catalog_button.clicked.connect(self.vm.sync_catalog)
        self.scan_button.clicked.connect(self.vm.run_scan)
        self.full_scan.toggled.connect(self.vm.set_full_scan)
        self.include_personal.toggled.connect(self.vm.set_include_personal)
        self.vm.start()

    # -- UI ----------------------------------------------------------------
    def _build_ui(self, state: SettingsState) -> None:
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.addTab(self._build_credentials_page(state), "Kredensial")
        self.tabs.addTab(self._build_catalog_page(state), "Katalog & Database")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.tabs)

        self.tabs.currentChanged.connect(self._on_sub_tab_changed)
        self._restore_sub_tab()

    def _build_credentials_page(self, state: SettingsState) -> QWidget:
        self.tenant = QLineEdit(state.tenant_id)
        self.tenant.setPlaceholderText("Tenant ID (GUID atau domain tenant)")
        self.client = QLineEdit(state.client_id)
        self.client.setPlaceholderText("Application (client) ID")
        self.secret = QLineEdit(state.client_secret)
        self.secret.setEchoMode(QLineEdit.EchoMode.Password)
        self.show_secret = QCheckBox("Tampilkan secret")

        secret_row = QWidget()
        secret_layout = QVBoxLayout(secret_row)
        secret_layout.setContentsMargins(0, 0, 0, 0)
        secret_layout.addWidget(self.secret)
        secret_layout.addWidget(self.show_secret)

        self.status = QLabel(state.status_text)
        self.status.setStyleSheet(f"color: {state.status_color};")
        self.status.setWordWrap(True)
        self.save_button = QPushButton("Simpan kredensial")
        self.test_button = QPushButton("Tes koneksi")
        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.addWidget(self.save_button)
        buttons.addWidget(self.test_button)
        buttons.addStretch(1)
        buttons_widget = QWidget()
        buttons_widget.setLayout(buttons)

        warning = QLabel(
            "Client Secret disimpan sebagai teks biasa di QSettings (registry "
            "Windows) agar GUI tidak meminta ulang. Untuk lingkungan bersama, "
            "gunakan CLI dengan environment atau file .env."
        )
        warning.setWordWrap(True)
        warning.setStyleSheet("color: #a05000;")

        connection_form = QFormLayout()
        connection_form.addRow("Tenant ID:", self.tenant)
        connection_form.addRow("Client ID:", self.client)
        connection_form.addRow("Client Secret:", secret_row)
        connection_form.addRow("", self.status)
        connection_form.addRow("", buttons_widget)
        connection_form.addRow("", warning)
        connection_box = QGroupBox("Koneksi Power BI Service")
        connection_box.setLayout(connection_form)

        self.rls_username = QLineEdit(state.rls_username)
        self.rls_username.setPlaceholderText("mis. user@domain.com")
        self.rls_roles = QLineEdit(state.rls_roles)
        self.rls_roles.setPlaceholderText("mis. HO,Region")
        rls_form = QFormLayout()
        rls_form.addRow("Username:", self.rls_username)
        rls_form.addRow("Roles:", self.rls_roles)
        rls_note = QLabel(
            "Dipakai sebagai default screenshot TSD; tab Generate TSD tetap "
            "boleh mengisi nilai lain untuk satu kali capture."
        )
        rls_note.setWordWrap(True)
        rls_form.addRow("", rls_note)
        rls_box = QGroupBox("Identitas RLS default")
        rls_box.setLayout(rls_form)

        info = QLabel(
            "Satu service principal dipakai untuk Fabric API, Power BI REST, "
            "embed/Scanner, dan XMLA (token Power BI yang sama). Token hanya "
            "di memori proses; CLI memakai TENANT_ID / CLIENT_ID / "
            "CLIENT_SECRET dari environment atau .env."
        )
        info.setWordWrap(True)
        info_box = QGroupBox("Info")
        info_layout = QVBoxLayout(info_box)
        info_layout.addWidget(info)

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 6, 0, 0)
        layout.addWidget(connection_box)
        layout.addWidget(rls_box)
        layout.addWidget(info_box)
        layout.addStretch(1)
        return page

    def _build_catalog_page(self, state: SettingsState) -> QWidget:
        self.db_path = PathRow(
            state.database, file_filter="SQLite (*.db);;Semua file (*)"
        )
        path_form = QFormLayout()
        path_form.addRow("Database:", self.db_path)
        path_box = QGroupBox("Path")
        path_box.setLayout(path_form)

        self.catalog_mode = QComboBox()
        for label, key in CATALOG_MODE_OPTIONS:
            self.catalog_mode.addItem(label, key)
        self.full_scan = QCheckBox(
            "Full scan lineage (abaikan timestamp incremental)"
        )
        self.full_scan.setChecked(state.full_scan)
        self.full_scan.setToolTip(
            "Hanya berlaku untuk Scan lineage. Mode member selalu memindai "
            "seluruh workspace yang dapat diakses."
        )
        self.include_personal = QCheckBox("Sertakan My Workspace (personal)")
        self.include_personal.setChecked(state.include_personal)
        self.include_personal.setToolTip(
            "Scan lineage ikut memindai My Workspace semua user (hanya mode "
            "admin; aktivasi pertama memaksa full scan). Full scan pertama jauh "
            "lebih lama dan menambah isi database. Nama personal workspace "
            "memuat email pemilik."
        )
        self.catalog_button = QPushButton("Sinkronisasi katalog workspace")
        self.catalog_button.setToolTip(
            "Menarik daftar workspace (1-2 request) untuk picker Workspace."
        )
        self.scan_button = QPushButton("Scan lineage")
        self.scan_button.setToolTip(
            "Scan Scanner API: node, edge, dan datasource untuk tab Lineage."
        )
        sync_buttons = QHBoxLayout()
        sync_buttons.setContentsMargins(0, 0, 0, 0)
        sync_buttons.addWidget(self.catalog_button)
        sync_buttons.addWidget(self.scan_button)
        sync_buttons.addStretch(1)
        sync_buttons_widget = QWidget()
        sync_buttons_widget.setLayout(sync_buttons)

        self.sync_status = QLabel(state.sync_status)
        self.sync_status.setWordWrap(True)
        self.sync_status.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        sync_note = QLabel(
            "Kedua aksi memakai database yang sudah disimpan di grup Path dan "
            "kredensial dari sub-tab Kredensial. Mode dipakai bersama: katalog "
            "untuk picker Workspace, lineage untuk tab Lineage. Full scan hanya "
            "mengubah cara scan lineage memilih workspace. Sertakan My Workspace "
            "berlaku untuk scan lineage mode admin saja."
        )
        sync_note.setWordWrap(True)
        sync_form = QFormLayout()
        sync_form.addRow("Mode:", self.catalog_mode)
        sync_form.addRow("", self.full_scan)
        sync_form.addRow("", self.include_personal)
        sync_form.addRow("", sync_buttons_widget)
        sync_form.addRow("Status:", self.sync_status)
        sync_form.addRow("", sync_note)
        sync_box = QGroupBox("Sinkronisasi data")
        sync_box.setLayout(sync_form)

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 6, 0, 0)
        layout.addWidget(path_box)
        layout.addWidget(sync_box)
        layout.addStretch(1)
        return page

    # -- sub-tab aktif -----------------------------------------------------
    def _restore_sub_tab(self) -> None:
        saved = self._settings.value(SETTINGS_SUB_TAB_KEY, "", type=str)
        index = SUB_TAB_ORDER.index(saved) if saved in SUB_TAB_ORDER else 0
        self.tabs.blockSignals(True)
        self.tabs.setCurrentIndex(index)
        self.tabs.blockSignals(False)

    def _on_sub_tab_changed(self, index: int) -> None:
        if 0 <= index < len(SUB_TAB_ORDER):
            self._settings.set_value(SETTINGS_SUB_TAB_KEY, SUB_TAB_ORDER[index])

    @property
    def active_sub_tab(self) -> str:
        index = self.tabs.currentIndex()
        if 0 <= index < len(SUB_TAB_ORDER):
            return SUB_TAB_ORDER[index]
        return SUB_TAB_ORDER[0]

    # -- render ------------------------------------------------------------
    def render(self, state: SettingsState) -> None:
        self._set_text(self.tenant, state.tenant_id)
        self._set_text(self.client, state.client_id)
        self._set_text(self.secret, state.client_secret)
        self._set_text(self.rls_username, state.rls_username)
        self._set_text(self.rls_roles, state.rls_roles)
        if self.db_path.text() != state.database:
            self.db_path.set_text(state.database)
        self.status.setText(state.status_text)
        self.status.setStyleSheet(f"color: {state.status_color};")

        index = next(
            (
                position
                for position, (_label, key) in enumerate(CATALOG_MODE_OPTIONS)
                if key == state.catalog_mode
            ),
            -1,
        )
        if index >= 0 and self.catalog_mode.currentIndex() != index:
            self.catalog_mode.blockSignals(True)
            self.catalog_mode.setCurrentIndex(index)
            self.catalog_mode.blockSignals(False)
        if self.full_scan.isChecked() != state.full_scan:
            self.full_scan.blockSignals(True)
            self.full_scan.setChecked(state.full_scan)
            self.full_scan.blockSignals(False)
        if self.include_personal.isChecked() != state.include_personal:
            self.include_personal.blockSignals(True)
            self.include_personal.setChecked(state.include_personal)
            self.include_personal.blockSignals(False)
        self.sync_status.setText(state.sync_status)
        self.sync_status.setStyleSheet(
            f"color: {state.sync_status_color};"
            if state.sync_status_color
            else ""
        )

        for widget in (
            self.tenant,
            self.client,
            self.secret,
            self.show_secret,
            self.rls_username,
            self.rls_roles,
            self.db_path,
            self.save_button,
            self.test_button,
            self.catalog_mode,
            self.full_scan,
            self.include_personal,
            self.catalog_button,
            self.scan_button,
        ):
            widget.setEnabled(state.idle)

    @staticmethod
    def _set_text(widget: QLineEdit, value: str) -> None:
        if widget.text() == value:
            return
        widget.blockSignals(True)
        widget.setText(value)
        widget.blockSignals(False)

    # -- aksi --------------------------------------------------------------
    def _on_catalog_mode(self, _index: int) -> None:
        mode = self.catalog_mode.currentData()
        if mode:
            self.vm.set_catalog_mode(mode)

    def _toggle_secret(self, visible: bool) -> None:
        self.secret.setEchoMode(
            QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password
        )

    def set_busy(self, busy: bool) -> None:
        self.vm.set_busy(busy)
