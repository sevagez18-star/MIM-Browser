import sys
import os
import re
import json
import time
import shutil
import urllib.parse
import urllib.request
import subprocess
from pathlib import Path
from datetime import datetime

from PySide6.QtCore import (
    Qt, QUrl, QTimer, QThread, Signal, QStandardPaths
)
from PySide6.QtGui import QAction, QColor, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QLineEdit, QPushButton, QLabel, QListWidget,
    QListWidgetItem, QSplitter, QDialog, QFormLayout, QComboBox,
    QCheckBox, QColorDialog, QFileDialog, QMessageBox, QMenu,
    QInputDialog, QToolButton, QProgressBar, QSpinBox, QTextEdit,
    QGroupBox, QTableWidget, QTableWidgetItem, QHeaderView
)
from PySide6.QtWebEngineCore import (
    QWebEngineProfile, QWebEnginePage,
    QWebEngineUrlRequestInterceptor, QWebEngineDownloadRequest,
    QWebEngineSettings, QWebEngineScript
)
from PySide6.QtWebEngineWidgets import QWebEngineView

APP_NAME = "MIM Browser"
APP_VERSION = "1.0.3"
GITHUB_REPO = "sevagez18-star/mim-browser"
GITHUB_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"

ROOT = Path.home() / "MIMBrowser"
ROOT.mkdir(parents=True, exist_ok=True)

DEFAULT_DOWNLOADS = str(
    Path(QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.DownloadLocation
    ) or Path.home() / "Downloads")
)

DEFAULTS = {
    "homepage": "https://www.google.com/",
    "search_engine": "https://www.google.com/search?q={}",
    "theme": "dark",
    "accent": "#ff6b35",
    "sidebar": True,
    "adblock": True,
    "restore_tabs": True,
    "game_mode": False,
    "animations": True,
    "download_path": DEFAULT_DOWNLOADS,
    "last_tabs": [],
    "pinned_urls": [],
    "recent_sites": [],
    "window_width": 1400,
    "window_height": 900,
    "window_x": 80,
    "window_y": 60,
}


def read_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as file:
            return json.load(file)
    except (OSError, ValueError, TypeError):
        return default


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with open(temp, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
    temp.replace(path)


def version_tuple(value):
    try:
        return tuple(int(x) for x in value.lstrip("vV").split("."))
    except (ValueError, AttributeError):
        return (0,)


def safe_name(value):
    result = re.sub(r"[^a-zA-Z0-9_-]", "_", value)
    return result[:40] or "Default"


def get_profile_folder(name):
    folder = ROOT / "profiles" / safe_name(name)
    folder.mkdir(parents=True, exist_ok=True)
    return folder


class AdBlocker(QWebEngineUrlRequestInterceptor):
    DOMAINS = {
        "doubleclick.net",
        "googlesyndication.com",
        "googleadservices.com",
        "adnxs.com",
        "adform.net",
        "taboola.com",
        "outbrain.com",
        "popads.net",
        "propellerads.com",
    }

    def __init__(self):
        super().__init__()
        self.enabled = True
        self.blocked_count = 0

    def interceptRequest(self, info):
        if not self.enabled:
            return

        try:
            host = info.requestUrl().host().lower()
            if any(host == domain or host.endswith("." + domain)
                   for domain in self.DOMAINS):
                self.blocked_count += 1
                info.block(True)
        except Exception:
            pass


class UpdateWorker(QThread):
    found = Signal(object)
    failed = Signal(str)

    def run(self):
        try:
            request = urllib.request.Request(
                GITHUB_API,
                headers={
                    "User-Agent": "MIM-Browser-Updater",
                    "Accept": "application/vnd.github+json",
                },
            )
            with urllib.request.urlopen(request, timeout=15) as response:
                release = json.loads(response.read().decode("utf-8"))

            if release.get("draft") or release.get("prerelease"):
                self.found.emit(None)
                return

            version = str(release.get("tag_name", "")).lstrip("vV")
            if not re.fullmatch(r"\d+(?:\.\d+){1,3}", version):
                self.found.emit(None)
                return

            asset = next(
                (
                    item for item in release.get("assets", [])
                    if item.get("name") == "main.py"
                ),
                None,
            )

            if not asset:
                self.found.emit(None)
                return

            self.found.emit({
                "version": version,
                "url": asset["browser_download_url"],
                "release_url": release.get("html_url", ""),
            })
        except Exception as error:
            self.failed.emit(str(error))


class HomePage(QWidget):
    def __init__(self, browser):
        super().__init__()
        self.browser = browser
        self.setObjectName("homePage")

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setContentsMargins(45, 30, 45, 30)
        layout.setSpacing(16)

        title = QLabel("MIM Browser")
        title.setObjectName("homeTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        subtitle = QLabel(f"Версия {APP_VERSION} • Твой браузер")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitle)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Поиск или адрес сайта…")
        self.search.setMinimumHeight(46)
        self.search.returnPressed.connect(self.search_web)
        layout.addWidget(self.search)

        quick = QHBoxLayout()
        shortcuts = [
            ("YouTube", "https://www.youtube.com/"),
            ("Discord", "https://discord.com/app"),
            ("Spotify", "https://open.spotify.com/"),
            ("Google", "https://www.google.com/"),
        ]
        for name, url in shortcuts:
            button = QPushButton(name)
            button.clicked.connect(
                lambda checked=False, target=url: browser.navigate(target)
            )
            quick.addWidget(button)
        layout.addLayout(quick)

        layout.addSpacing(15)
        recent_title = QLabel("Недавно посещённые")
        recent_title.setObjectName("sectionTitle")
        layout.addWidget(recent_title)

        self.recent = QListWidget()
        self.recent.setMaximumHeight(150)
        self.recent.itemDoubleClicked.connect(self.open_recent)
        layout.addWidget(self.recent)
        self.refresh_recent()

        self.clock = QLabel()
        self.clock.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.clock)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_clock)
        self.timer.start(1000)
        self.update_clock()

    def search_web(self):
        text = self.search.text().strip()
        if text:
            self.browser.navigate(self.browser.make_url(text))

    def update_clock(self):
        self.clock.setText(datetime.now().strftime("%H:%M:%S  •  %d.%m.%Y"))

    def refresh_recent(self):
        self.recent.clear()
        for item in self.browser.settings.get("recent_sites", [])[:10]:
            row = QListWidgetItem(
                f'{item.get("title", item.get("url", ""))}\n'
                f'{item.get("url", "")}'
            )
            row.setData(Qt.ItemDataRole.UserRole, item.get("url", ""))
            self.recent.addItem(row)

    def open_recent(self, item):
        url = item.data(Qt.ItemDataRole.UserRole)
        if url:
            self.browser.navigate(url)


class BrowserTab(QWidget):
    def __init__(self, browser, profile, private=False):
        super().__init__()
        self.browser = browser
        self.private = private
        self.group = "Без группы"
        self.is_home = True

        self.view = QWebEngineView(self)
        self.page = QWebEnginePage(profile, self.view)
        self.view.setPage(self.page)

        self.home = HomePage(browser)

        self.stack_layout = QVBoxLayout(self)
        self.stack_layout.setContentsMargins(0, 0, 0, 0)
        self.stack_layout.addWidget(self.home)
        self.stack_layout.addWidget(self.view)

        self.view.hide()

        self.view.urlChanged.connect(self.url_changed)
        self.view.titleChanged.connect(self.title_changed)
        self.view.loadProgress.connect(self.load_progress)
        self.view.loadFinished.connect(self.load_finished)

    def open_url(self, url):
        self.is_home = False
        self.home.hide()
        self.view.show()
        self.view.setUrl(QUrl(url))

    def show_home(self):
        self.is_home = True
        self.view.hide()
        self.home.show()
        self.browser.address.clear()
        self.browser.setWindowTitle(APP_NAME)

    def url_changed(self, url):
        if self.browser.current_tab() is self:
            self.browser.address.setText(url.toString())

    def title_changed(self, title):
        self.browser.update_tab_title(self)
        if self.browser.current_tab() is self:
            self.browser.setWindowTitle((title or APP_NAME) + (
                " — Приватный режим" if self.private else ""
            ))

    def load_progress(self, value):
        if self.browser.current_tab() is self:
            self.browser.progress.setValue(value)
            self.browser.progress.setVisible(value < 100)

    def load_finished(self, ok):
        if not ok or self.private:
            return
        url = self.view.url().toString()
        if not url or url == "about:blank":
            return
        self.browser.add_history(url, self.view.title())
        self.browser.add_recent(url, self.view.title())


class ScriptsDialog(QDialog):
    """Менеджер локальных пользовательских JavaScript-скриптов."""

    def __init__(self, browser):
        super().__init__(browser)
        self.browser = browser
        self.folder = browser.folder / "scripts"
        self.folder.mkdir(parents=True, exist_ok=True)

        self.setWindowTitle("Менеджер пользовательских скриптов")
        self.resize(650, 420)
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel(
            "Локальные JavaScript-скрипты. Загружай только код, которому доверяешь."
        ))

        self.list = QListWidget()
        layout.addWidget(self.list)

        row = QHBoxLayout()
        for title, callback in [
            ("Добавить скрипт", self.add_script),
            ("Удалить", self.delete_script),
            ("Обновить список", self.refresh),
        ]:
            button = QPushButton(title)
            button.clicked.connect(callback)
            row.addWidget(button)
        layout.addLayout(row)
        self.refresh()

    def refresh(self):
        self.list.clear()
        for path in sorted(self.folder.glob("*.js")):
            self.list.addItem(path.name)

    def add_script(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Выбрать JavaScript", "",
            "JavaScript (*.js);;Все файлы (*)"
        )
        if not path:
            return

        source = Path(path).read_text(encoding="utf-8")
        if len(source) > 1_000_000:
            QMessageBox.warning(self, APP_NAME, "Файл слишком большой.")
            return

        target = self.folder / Path(path).name
        shutil.copy2(path, target)
        self.install_script(target)
        self.refresh()

    def install_script(self, path):
        source = path.read_text(encoding="utf-8")
        script = QWebEngineScript()
        script.setName(path.name)
        script.setSourceCode(source)
        script.setInjectionPoint(
            QWebEngineScript.InjectionPoint.DocumentReady
        )
        script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        script.setRunsOnSubFrames(False)

        tab = self.browser.current_tab()
        if tab:
            tab.page.scripts().insert(script)

    def delete_script(self):
        item = self.list.currentItem()
        if not item:
            return
        path = self.folder / item.text()
        answer = QMessageBox.question(
            self, "Удалить скрипт", f"Удалить {item.text()}?"
        )
        if answer == QMessageBox.StandardButton.Yes:
            try:
                path.unlink(missing_ok=True)
            except OSError as error:
                QMessageBox.warning(self, APP_NAME, str(error))
            self.refresh()


class MIMBrowser(QMainWindow):
    def __init__(self, private=False, profile_name="Default"):
        super().__init__()
        self.private = private
        self.profile_name = profile_name
        self.folder = get_profile_folder(profile_name)

        self.settings_file = self.folder / "settings.json"
        self.bookmarks_file = self.folder / "bookmarks.json"
        self.history_file = self.folder / "history.json"
        self.downloads_file = self.folder / "downloads.json"

        self.settings = read_json(self.settings_file, DEFAULTS.copy())
        for key, value in DEFAULTS.items():
            self.settings.setdefault(key, value)

        self.bookmarks = [] if private else read_json(self.bookmarks_file, [])
        self.history = [] if private else read_json(self.history_file, [])
        self.downloads = [] if private else read_json(self.downloads_file, [])
        self.closed_tabs = []
        self.groups = ["Без группы", "Работа", "Игры", "Музыка"]
        self.extra_windows = []

        self.setWindowTitle(APP_NAME)
        self.resize(
            self.settings.get("window_width", 1400),
            self.settings.get("window_height", 900)
        )
        self.move(
            self.settings.get("window_x", 80),
            self.settings.get("window_y", 60)
        )

        if private:
            self.profile = QWebEngineProfile(self)
        else:
            name = "MIM_" + safe_name(profile_name)
            self.profile = QWebEngineProfile(name, self)
            self.profile.setPersistentStoragePath(str(self.folder / "webdata"))
            self.profile.setCachePath(str(self.folder / "cache"))
            self.profile.setPersistentCookiesPolicy(
                QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies
            )

        self.adblocker = AdBlocker()
        self.adblocker.enabled = self.settings["adblock"]
        self.profile.setUrlRequestInterceptor(self.adblocker)
        self.profile.downloadRequested.connect(self.download_requested)

        self.build_ui()
        self.apply_settings()

        if not private and self.settings.get("restore_tabs", True):
            urls = self.settings.get("last_tabs", [])
            if urls:
                for url in urls:
                    self.add_tab(url, switch=False)
                self.tabs.setCurrentIndex(0)
            else:
                self.add_tab("")
        else:
            self.add_tab("")

        if not private:
            QTimer.singleShot(2500, self.check_updates)

    def build_ui(self):
        central = QWidget()
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(6, 6, 6, 6)
        main_layout.setSpacing(5)
        self.setCentralWidget(central)

        toolbar = QHBoxLayout()

        for title, callback in [
            ("←", self.go_back),
            ("→", self.go_forward),
            ("⟳", self.reload_page),
            ("⌂", self.go_home),
        ]:
            button = QPushButton(title)
            button.clicked.connect(callback)
            toolbar.addWidget(button)

        self.address = QLineEdit()
        self.address.setPlaceholderText("Поиск или адрес сайта…")
        self.address.returnPressed.connect(self.navigate_address)
        toolbar.addWidget(self.address, 1)

        go = QPushButton("Перейти")
        go.clicked.connect(self.navigate_address)
        toolbar.addWidget(go)

        self.bookmark_button = QPushButton("☆")
        self.bookmark_button.clicked.connect(self.bookmark_current)
        toolbar.addWidget(self.bookmark_button)

        self.progress = QProgressBar()
        self.progress.setMaximumWidth(100)
        self.progress.setVisible(False)
        toolbar.addWidget(self.progress)
        main_layout.addLayout(toolbar)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(self.splitter, 1)

        self.sidebar = QWidget()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(240)
        side = QVBoxLayout(self.sidebar)

        brand = QLabel("MIM Browser")
        brand.setObjectName("brand")
        brand.setAlignment(Qt.AlignmentFlag.AlignCenter)
        side.addWidget(brand)

        self.profile_label = QLabel(f"Профиль: {profile_name}")
        self.profile_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        side.addWidget(self.profile_label)

        sidebar_actions = [
            ("⌂  Домашняя", self.go_home),
            ("☆  Закладки", self.show_bookmarks),
            ("◷  История", self.show_history),
            ("↓  Загрузки", self.show_downloads),
            ("🛡  Центр приватности", self.privacy_center),
            ("🧩  Скрипты", self.open_scripts),
            ("🎵  Музыка", self.open_music),
            ("👤  Профили", self.manage_profiles),
            ("🗂  Группы вкладок", self.manage_groups),
            ("🎮  Игровой режим", self.toggle_game_mode),
            ("🌐  Перевести страницу", self.translate_page),
            ("🛡  Блокировщик рекламы", self.toggle_adblock),
            ("⚙  Настройки", self.open_settings),
            ("↻  Проверить обновления", self.check_updates),
        ]

        for title, callback in sidebar_actions:
            button = QPushButton(title)
            button.clicked.connect(callback)
            side.addWidget(button)

        side.addStretch()
        side.addWidget(QLabel(f"Версия {APP_VERSION}"))
        self.splitter.addWidget(self.sidebar)

        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.setDocumentMode(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self.on_tab_changed)
        self.tabs.tabBar().setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self.tabs.tabBar().customContextMenuRequested.connect(self.tab_menu)
        self.splitter.addWidget(self.tabs)
        self.splitter.setSizes([240, 1160])

        new_button = QToolButton()
        new_button.setText("+")
        new_button.setToolTip("Новая вкладка — Ctrl+T")
        new_button.clicked.connect(lambda: self.add_tab(""))
        self.tabs.setCornerWidget(new_button, Qt.Corner.TopRightCorner)

        self.create_shortcuts()

    def create_shortcuts(self):
        shortcuts = [
            ("Ctrl+T", lambda: self.add_tab("")),
            ("Ctrl+W", lambda: self.close_tab(self.tabs.currentIndex())),
            ("Ctrl+L", self.address.setFocus),
            ("Ctrl+R", self.reload_page),
            ("Alt+Left", self.go_back),
            ("Alt+Right", self.go_forward),
            ("Ctrl+H", self.show_history),
            ("Ctrl+D", self.bookmark_current),
            ("Ctrl+J", self.show_downloads),
            ("Ctrl+F", self.find_text),
            ("Ctrl+Shift+N", self.open_private),
            ("Ctrl+Shift+T", self.restore_closed),
        ]
        for shortcut, callback in shortcuts:
            action = QAction(self)
            action.setShortcut(QKeySequence(shortcut))
            action.triggered.connect(callback)
            self.addAction(action)

    def current_tab(self):
        widget = self.tabs.currentWidget()
        return widget if isinstance(widget, BrowserTab) else None

    def add_tab(self, url="", switch=True):
        tab = BrowserTab(self, self.profile, self.private)
        index = self.tabs.addTab(tab, "Домашняя")
        if switch:
            self.tabs.setCurrentIndex(index)

        if url:
            tab.open_url(url)
        return tab

    def close_tab(self, index):
        if index < 0 or index >= self.tabs.count():
            return
        tab = self.tabs.widget(index)
        if isinstance(tab, BrowserTab) and not tab.is_home:
            url = tab.view.url().toString()
            if url:
                self.closed_tabs.append(url)
        self.tabs.removeTab(index)
        tab.deleteLater()
        if self.tabs.count() == 0:
            self.add_tab("")
        self.save_last_tabs()

    def restore_closed(self):
        if self.closed_tabs:
            self.add_tab(self.closed_tabs.pop())

    def on_tab_changed(self, index):
        tab = self.current_tab()
        if tab:
            if tab.is_home:
                self.address.clear()
            else:
                self.address.setText(tab.view.url().toString())
        self.save_last_tabs()

    def update_tab_title(self, tab):
        index = self.tabs.indexOf(tab)
        if index < 0:
            return
        title = "Домашняя" if tab.is_home else (
            tab.view.title() or "Вкладка"
        )
        if tab.group != "Без группы":
            title = f"[{tab.group}] {title}"
        if tab.view.url().toString() in self.settings.get("pinned_urls", []):
            title = "📌 " + title
        self.tabs.setTabText(index, title[:30])

    def tab_menu(self, position):
        index = self.tabs.tabBar().tabAt(position)
        if index < 0:
            return
        tab = self.tabs.widget(index)

        menu = QMenu(self)
        duplicate = menu.addAction("Дублировать")
        pin = menu.addAction("Закрепить / открепить")
        group = menu.addAction("Назначить группу")
        close = menu.addAction("Закрыть")
        chosen = menu.exec(self.tabs.tabBar().mapToGlobal(position))

        if chosen == duplicate:
            self.add_tab(
                "" if tab.is_home else tab.view.url().toString()
            )
        elif chosen == pin:
            url = tab.view.url().toString()
            pinned = self.settings.setdefault("pinned_urls", [])
            if url in pinned:
                pinned.remove(url)
            elif url:
                pinned.append(url)
            self.save_settings()
            self.update_tab_title(tab)
        elif chosen == group:
            name, ok = QInputDialog.getItem(
                self, "Группа", "Выбери группу:",
                self.groups, 0, True
            )
            if ok and name.strip():
                if name not in self.groups:
                    self.groups.append(name)
                tab.group = name
                self.update_tab_title(tab)
        elif chosen == close:
            self.close_tab(index)

    def make_url(self, text):
        text = text.strip()
        if not text:
            return self.settings["homepage"]
        if "://" in text:
            return text
        if " " not in text and "." in text:
            return "https://" + text
        return self.settings["search_engine"].replace(
            "{}", urllib.parse.quote_plus(text)
        )

    def navigate_address(self):
        text = self.address.text().strip()
        if text:
            self.navigate(self.make_url(text))

    def navigate(self, url):
        tab = self.current_tab()
        if tab:
            tab.open_url(url)

    def go_home(self):
        tab = self.current_tab()
        if tab:
            tab.show_home()

    def go_back(self):
        tab = self.current_tab()
        if tab and not tab.is_home:
            tab.view.back()

    def go_forward(self):
        tab = self.current_tab()
        if tab and not tab.is_home:
            tab.view.forward()

    def reload_page(self):
        tab = self.current_tab()
        if tab and not tab.is_home:
            tab.view.reload()

    def add_recent(self, url, title):
        if self.private:
            return
        recent = self.settings.setdefault("recent_sites", [])
        recent = [item for item in recent if item.get("url") != url]
        recent.insert(0, {"url": url, "title": title or url})
        self.settings["recent_sites"] = recent[:20]
        self.save_settings()

    def add_history(self, url, title):
        if self.private:
            return
        self.history.insert(0, {
            "url": url,
            "title": title or url,
            "time": datetime.now().strftime("%d.%m.%Y %H:%M:%S"),
        })
        self.history = self.history[:3000]
        write_json(self.history_file, self.history)

    def bookmark_current(self):
        tab = self.current_tab()
        if not tab or tab.is_home:
            return
        url = tab.view.url().toString()
        if not url:
            return
        if any(item.get("url") == url for item in self.bookmarks):
            QMessageBox.information(self, APP_NAME, "Уже добавлено в закладки.")
            return
        self.bookmarks.append({
            "url": url,
            "title": tab.view.title() or url,
            "folder": "Без папки",
        })
        write_json(self.bookmarks_file, self.bookmarks)
        self.bookmark_button.setText("★")

    def show_bookmarks(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Закладки")
        dialog.resize(720, 450)
        layout = QVBoxLayout(dialog)
        listing = QListWidget()
        layout.addWidget(listing)

        def refresh():
            listing.clear()
            for index, item in enumerate(self.bookmarks):
                row = QListWidgetItem(
                    f'{item.get("title", "")}\n{item.get("url", "")}'
                )
                row.setData(Qt.ItemDataRole.UserRole, index)
                listing.addItem(row)

        def open_item():
            row = listing.currentItem()
            if row:
                index = row.data(Qt.ItemDataRole.UserRole)
                self.navigate(self.bookmarks[index]["url"])
                dialog.accept()

        def rename_item():
            row = listing.currentItem()
            if not row:
                return
            index = row.data(Qt.ItemDataRole.UserRole)
            title, ok = QInputDialog.getText(
                dialog, "Переименовать", "Название:",
                text=self.bookmarks[index].get("title", "")
            )
            if ok and title.strip():
                self.bookmarks[index]["title"] = title.strip()
                write_json(self.bookmarks_file, self.bookmarks)
                refresh()

        def delete_item():
            row = listing.currentItem()
            if row:
                index = row.data(Qt.ItemDataRole.UserRole)
                del self.bookmarks[index]
                write_json(self.bookmarks_file, self.bookmarks)
                refresh()

        listing.itemDoubleClicked.connect(lambda _: open_item())

        buttons = QHBoxLayout()
        for title, callback in [
            ("Открыть", open_item),
            ("Переименовать", rename_item),
            ("Удалить", delete_item),
            ("Импорт", self.import_bookmarks),
            ("Экспорт", self.export_bookmarks),
        ]:
            button = QPushButton(title)
            button.clicked.connect(callback)
            buttons.addWidget(button)
        layout.addLayout(buttons)
        refresh()
        dialog.exec()

    def import_bookmarks(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Импорт закладок", "", "JSON (*.json)"
        )
        if not path:
            return
        imported = read_json(Path(path), [])
        if not isinstance(imported, list):
            QMessageBox.warning(self, APP_NAME, "Неверный файл.")
            return
        for item in imported:
            if isinstance(item, dict) and item.get("url"):
                if not any(b.get("url") == item["url"] for b in self.bookmarks):
                    self.bookmarks.append(item)
        write_json(self.bookmarks_file, self.bookmarks)

    def export_bookmarks(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Экспорт закладок", "mim_bookmarks.json", "JSON (*.json)"
        )
        if path:
            write_json(Path(path), self.bookmarks)

    def show_history(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("История")
        dialog.resize(750, 450)
        layout = QVBoxLayout(dialog)
        listing = QListWidget()
        layout.addWidget(listing)

        def refresh():
            listing.clear()
            for index, item in enumerate(self.history):
                row = QListWidgetItem(
                    f'{item.get("title", "")}\n{item.get("url", "")}\n'
                    f'{item.get("time", "")}'
                )
                row.setData(Qt.ItemDataRole.UserRole, index)
                listing.addItem(row)

        def open_item():
            row = listing.currentItem()
            if row:
                index = row.data(Qt.ItemDataRole.UserRole)
                self.navigate(self.history[index]["url"])
                dialog.accept()

        def delete_item():
            row = listing.currentItem()
            if row:
                del self.history[row.data(Qt.ItemDataRole.UserRole)]
                write_json(self.history_file, self.history)
                refresh()

        def clear_all():
            answer = QMessageBox.question(
                dialog, "Очистить историю", "Удалить всю историю?"
            )
            if answer == QMessageBox.StandardButton.Yes:
                self.history.clear()
                write_json(self.history_file, [])
                refresh()

        listing.itemDoubleClicked.connect(lambda _: open_item())
        buttons = QHBoxLayout()
        for title, callback in [
            ("Открыть", open_item),
            ("Удалить выбранную", delete_item),
            ("Очистить всё", clear_all),
        ]:
            button = QPushButton(title)
            button.clicked.connect(callback)
            buttons.addWidget(button)
        layout.addLayout(buttons)
        refresh()
        dialog.exec()

    def download_requested(self, download):
        folder = Path(self.settings.get("download_path", DEFAULT_DOWNLOADS))
        folder.mkdir(parents=True, exist_ok=True)
        filename = download.downloadFileName() or "download"
        path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить файл", str(folder / filename)
        )
        if not path:
            download.cancel()
            return

        download.setDownloadDirectory(str(Path(path).parent))
        download.setDownloadFileName(Path(path).name)

        record = {
            "name": Path(path).name,
            "path": path,
            "url": download.url().toString(),
            "status": "Загружается",
            "time": datetime.now().strftime("%d.%m.%Y %H:%M"),
        }

        if not self.private:
            self.downloads.insert(0, record)
            write_json(self.downloads_file, self.downloads)

        download.stateChanged.connect(
            lambda state, item=record: self.download_state(state, item)
        )
        download.accept()

    def download_state(self, state, record):
        states = QWebEngineDownloadRequest.DownloadState
        if state == states.DownloadCompleted:
            record["status"] = "Завершено"
        elif state == states.DownloadCancelled:
            record["status"] = "Отменено"
        elif state == states.DownloadInterrupted:
            record["status"] = "Ошибка"
        if not self.private:
            write_json(self.downloads_file, self.downloads)

    def show_downloads(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Менеджер загрузок")
        dialog.resize(800, 430)
        layout = QVBoxLayout(dialog)

        table = QTableWidget(0, 4)
        table.setHorizontalHeaderLabels(
            ["Файл", "Статус", "Путь", "Дата"]
        )
        table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        layout.addWidget(table)

        for record in self.downloads:
            row = table.rowCount()
            table.insertRow(row)
            for col, key in enumerate(["name", "status", "path", "time"]):
                table.setItem(
                    row, col,
                    QTableWidgetItem(str(record.get(key, "")))
                )

        buttons = QHBoxLayout()
        open_button = QPushButton("Открыть файл")
        folder_button = QPushButton("Открыть папку")
        remove_button = QPushButton("Убрать из списка")
        buttons.addWidget(open_button)
        buttons.addWidget(folder_button)
        buttons.addWidget(remove_button)
        layout.addLayout(buttons)

        def selected_path():
            row = table.currentRow()
            if row < 0:
                return ""
            item = table.item(row, 2)
            return item.text() if item else ""

        def open_file():
            path = selected_path()
            if path and Path(path).exists():
                self.open_local_path(path)

        def open_folder():
            path = selected_path()
            if path:
                target = str(Path(path).parent)
                self.open_local_path(target)

        def remove_record():
            row = table.currentRow()
            if row >= 0:
                del self.downloads[row]
                write_json(self.downloads_file, self.downloads)
                table.removeRow(row)

        open_button.clicked.connect(open_file)
        folder_button.clicked.connect(open_folder)
        remove_button.clicked.connect(remove_record)
        dialog.exec()

    def open_local_path(self, path):
        try:
            if sys.platform == "win32":
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as error:
            QMessageBox.warning(self, APP_NAME, str(error))

    def privacy_center(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Центр приватности")
        dialog.resize(520, 340)
        layout = QVBoxLayout(dialog)

        layout.addWidget(QLabel(
            "Управление локальными данными профиля и настройками приватности."
        ))

        info = QLabel(
            f"Блокировщик рекламы: "
            f"{'включён' if self.adblocker.enabled else 'выключен'}\n"
            f"Заблокировано запросов за сессию: {self.adblocker.blocked_count}"
        )
        layout.addWidget(info)

        clear_history = QPushButton("Очистить историю")
        clear_cache = QPushButton("Очистить кэш браузера")
        clear_cookies = QPushButton("Удалить cookies")
        clear_all = QPushButton("Очистить историю, кэш и cookies")

        for button in [clear_history, clear_cache, clear_cookies, clear_all]:
            layout.addWidget(button)

        def history_clear():
            answer = QMessageBox.question(
                dialog, "Очистить", "Удалить сохранённую историю?"
            )
            if answer == QMessageBox.StandardButton.Yes:
                self.history.clear()
                write_json(self.history_file, [])

        def cache_clear():
            self.profile.clearHttpCache()
            QMessageBox.information(self, APP_NAME, "Команда очистки кэша отправлена.")

        def cookies_clear():
            self.profile.cookieStore().deleteAllCookies()
            QMessageBox.information(
                self, APP_NAME,
                "Команда удаления cookies отправлена. Некоторые сайты могут выйти из аккаунта."
            )

        def all_clear():
            history_clear()
            cache_clear()
            cookies_clear()

        clear_history.clicked.connect(history_clear)
        clear_cache.clicked.connect(cache_clear)
        clear_cookies.clicked.connect(cookies_clear)
        clear_all.clicked.connect(all_clear)

        dialog.exec()

    def toggle_game_mode(self):
        self.settings["game_mode"] = not self.settings.get("game_mode", False)
        self.apply_settings()
        self.save_settings()
        QMessageBox.information(
            self, APP_NAME,
            "Игровой режим включён." if self.settings["game_mode"]
            else "Игровой режим выключен."
        )

    def toggle_adblock(self):
        self.settings["adblock"] = not self.settings.get("adblock", True)
        self.adblocker.enabled = self.settings["adblock"]
        self.save_settings()
        QMessageBox.information(
            self, APP_NAME,
            "Блокировщик рекламы включён."
            if self.adblocker.enabled else "Блокировщик рекламы выключен."
        )

    def translate_page(self):
        tab = self.current_tab()
        if not tab or tab.is_home:
            return
        url = tab.view.url().toString()
        translated = (
            "https://translate.google.com/translate?sl=auto&tl=ru&u="
            + urllib.parse.quote(url, safe="")
        )
        self.navigate(translated)

    def find_text(self):
        tab = self.current_tab()
        if not tab or tab.is_home:
            return
        text, ok = QInputDialog.getText(self, "Поиск на странице", "Найти:")
        if ok and text:
            tab.page.findText(text)

    def open_scripts(self):
        dialog = ScriptsDialog(self)
        dialog.exec()

    def open_music(self):
        QMessageBox.information(
            self, APP_NAME,
            "Для встроенного аудиоплеера можно добавить Qt Multimedia. "
            "Пока музыка открывается на музыкальных сайтах, например Spotify."
        )
        self.navigate("https://open.spotify.com/")

    def open_private(self):
        window = MIMBrowser(private=True, profile_name="Private")
        self.extra_windows.append(window)
        window.show()

    def manage_profiles(self):
        folder = ROOT / "profiles"
        folder.mkdir(exist_ok=True)
        names = ["Default"]
        names.extend(
            item.name for item in folder.iterdir()
            if item.is_dir() and item.name not in names
        )

        options = names + ["+ Создать профиль"]
        choice, ok = QInputDialog.getItem(
            self, "Профили", "Выбери профиль:", options, 0, False
        )
        if not ok:
            return

        if choice == "+ Создать профиль":
            choice, ok = QInputDialog.getText(
                self, "Новый профиль", "Название профиля:"
            )
            if not ok or not choice.strip():
                return

        window = MIMBrowser(profile_name=choice.strip())
        self.extra_windows.append(window)
        window.show()

    def manage_groups(self):
        tab = self.current_tab()
        if not tab:
            return
        name, ok = QInputDialog.getItem(
            self, "Группы вкладок", "Название группы:",
            self.groups, 0, True
        )
        if ok and name.strip():
            if name not in self.groups:
                self.groups.append(name)
            tab.group = name
            self.update_tab_title(tab)

    def open_settings(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Настройки MIM Browser")
        dialog.resize(550, 590)
        layout = QVBoxLayout(dialog)
        form = QFormLayout()

        homepage = QLineEdit(self.settings["homepage"])
        search_engine = QLineEdit(self.settings["search_engine"])

        theme = QComboBox()
        theme.addItems(["dark", "light", "blue", "purple"])
        theme.setCurrentText(self.settings.get("theme", "dark"))

        accent = QLineEdit(self.settings.get("accent", "#ff6b35"))
        accent.setReadOnly(True)
        color_button = QPushButton("Выбрать цвет")
        color_button.clicked.connect(
            lambda: self.choose_accent(accent)
        )
        accent_row = QHBoxLayout()
        accent_row.addWidget(accent)
        accent_row.addWidget(color_button)

        sidebar = QCheckBox("Показывать боковую панель")
        sidebar.setChecked(self.settings["sidebar"])

        adblock = QCheckBox("Блокировать рекламные домены")
        adblock.setChecked(self.settings["adblock"])

        restore = QCheckBox("Восстанавливать вкладки при запуске")
        restore.setChecked(self.settings["restore_tabs"])

        game = QCheckBox("Игровой режим")
        game.setChecked(self.settings["game_mode"])

        animations = QCheckBox("Анимации интерфейса")
        animations.setChecked(self.settings["animations"])

        download_path = QLineEdit(self.settings["download_path"])
        choose_folder = QPushButton("Выбрать папку")
        choose_folder.clicked.connect(
            lambda: self.choose_download_folder(download_path)
        )

        folder_row = QHBoxLayout()
        folder_row.addWidget(download_path)
        folder_row.addWidget(choose_folder)

        form.addRow("Домашняя страница:", homepage)
        form.addRow("Поисковая ссылка с {}:", search_engine)
        form.addRow("Тема:", theme)
        form.addRow("Акцентный цвет:", accent_row)
        form.addRow(sidebar)
        form.addRow(adblock)
        form.addRow(restore)
        form.addRow(game)
        form.addRow(animations)
        form.addRow("Загрузки:", folder_row)
        layout.addLayout(form)

        buttons = QHBoxLayout()
        save_button = QPushButton("Сохранить")
        cancel_button = QPushButton("Отмена")
        buttons.addWidget(save_button)
        buttons.addWidget(cancel_button)
        layout.addLayout(buttons)

        export_button = QPushButton("Экспорт настроек")
        import_button = QPushButton("Импорт настроек")
        layout.addWidget(export_button)
        layout.addWidget(import_button)

        cancel_button.clicked.connect(dialog.reject)
        export_button.clicked.connect(self.export_settings)
        import_button.clicked.connect(self.import_settings)

        def save():
            self.settings.update({
                "homepage": homepage.text().strip() or DEFAULTS["homepage"],
                "search_engine": search_engine.text().strip()
                or DEFAULTS["search_engine"],
                "theme": theme.currentText(),
                "accent": accent.text(),
                "sidebar": sidebar.isChecked(),
                "adblock": adblock.isChecked(),
                "restore_tabs": restore.isChecked(),
                "game_mode": game.isChecked(),
                "animations": animations.isChecked(),
                "download_path": download_path.text().strip() or DEFAULT_DOWNLOADS,
            })
            self.apply_settings()
            self.save_settings()
            dialog.accept()

        save_button.clicked.connect(save)
        dialog.exec()

    def choose_accent(self, field):
        color = QColorDialog.getColor(QColor(field.text()), self)
        if color.isValid():
            field.setText(color.name())

    def choose_download_folder(self, field):
        path = QFileDialog.getExistingDirectory(
            self, "Выбрать папку", field.text()
        )
        if path:
            field.setText(path)

    def export_settings(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Экспорт настроек", "mim_settings.json", "JSON (*.json)"
        )
        if path:
            write_json(Path(path), self.settings)

    def import_settings(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Импорт настроек", "", "JSON (*.json)"
        )
        if not path:
            return
        data = read_json(Path(path), None)
        if not isinstance(data, dict):
            QMessageBox.warning(self, APP_NAME, "Файл настроек некорректен.")
            return
        for key in DEFAULTS:
            if key in data:
                self.settings[key] = data[key]
        self.apply_settings()
        self.save_settings()

    def save_settings(self):
        if not self.private:
            write_json(self.settings_file, self.settings)

    def save_last_tabs(self):
        if self.private:
            return
        urls = []
        for i in range(self.tabs.count()):
            tab = self.tabs.widget(i)
            if isinstance(tab, BrowserTab) and not tab.is_home:
                url = tab.view.url().toString()
                if url and url != "about:blank":
                    urls.append(url)
        self.settings["last_tabs"] = urls
        self.save_settings()

    def apply_settings(self):
        themes = {
            "dark": ("#17191f", "#242630", "#f4f4f4", "#373b47"),
            "light": ("#f4f5f7", "#ffffff", "#202124", "#d7dbe0"),
            "blue": ("#101c2d", "#172b45", "#f2f7ff", "#244a73"),
            "purple": ("#20152e", "#302044", "#f8f0ff", "#49305e"),
        }
        bg, panel, fg, border = themes.get(
            self.settings.get("theme", "dark"), themes["dark"]
        )
        accent = self.settings.get("accent", "#ff6b35")

        self.setStyleSheet(f"""
            QMainWindow, QWidget {{
                background: {bg};
                color: {fg};
                font-size: 13px;
            }}
            QLineEdit, QListWidget, QComboBox, QTextEdit {{
                background: {panel};
                color: {fg};
                border: 1px solid {border};
                border-radius: 7px;
                padding: 7px;
            }}
            QPushButton, QToolButton {{
                background: {panel};
                color: {fg};
                border: 1px solid {border};
                border-radius: 7px;
                padding: 7px;
            }}
            QPushButton:hover, QToolButton:hover {{
                border: 1px solid {accent};
            }}
            QTabWidget::pane {{
                border: 1px solid {border};
            }}
            QTabBar::tab {{
                background: {panel};
                color: {fg};
                padding: 9px 12px;
                border: 1px solid {border};
            }}
            QTabBar::tab:selected {{
                border-bottom: 2px solid {accent};
            }}
            QLabel#brand, QLabel#homeTitle {{
                color: {accent};
                font-size: 23px;
                font-weight: bold;
                padding: 10px;
            }}
            QLabel#sectionTitle {{
                color: {accent};
                font-size: 16px;
                font-weight: bold;
            }}
            QProgressBar::chunk {{
                background: {accent};
            }}
        """)

        self.sidebar.setVisible(self.settings.get("sidebar", True))
        self.adblocker.enabled = self.settings.get("adblock", True)

        for index in range(self.tabs.count()):
            tab = self.tabs.widget(index)
            if isinstance(tab, BrowserTab):
                settings = tab.view.settings()
                game = self.settings.get("game_mode", False)
                settings.setAttribute(
                    QWebEngineSettings.WebAttribute.PlaybackRequiresUserGesture,
                    game,
                )
                settings.setAttribute(
                    QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows,
                    not game,
                )

    def check_updates(self):
        if self.private:
            return
        if hasattr(self, "update_worker") and self.update_worker.isRunning():
            return
        self.update_worker = UpdateWorker(self)
        self.update_worker.found.connect(self.update_found)
        self.update_worker.failed.connect(self.update_failed)
        self.update_worker.start()

    def update_failed(self, error):
        print("MIM Browser: не удалось проверить обновления:", error)

    def update_found(self, release):
        if not release:
            QMessageBox.information(
                self, APP_NAME,
                "Не найден опубликованный Release с файлом main.py."
            )
            return

        if version_tuple(release["version"]) <= version_tuple(APP_VERSION):
            QMessageBox.information(
                self, APP_NAME,
                f"Установлена последняя версия: {APP_VERSION}."
            )
            return

        answer = QMessageBox.question(
            self, "Обновление MIM Browser",
            f"Доступна версия {release['version']}.\n"
            f"Текущая версия: {APP_VERSION}.\n\n"
            "Скачать и установить?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.install_update(release["url"])

    def install_update(self, url):
        try:
            script = Path(__file__).resolve()
            if script.name.lower() != "main.py":
                raise RuntimeError("Файл программы должен называться main.py.")

            request = urllib.request.Request(
                url, headers={"User-Agent": "MIM-Browser-Updater"}
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                new_code = response.read()

            source = new_code.decode("utf-8-sig")
            compile(source, "main.py", "exec")

            update_path = script.with_name("main.py.update")
            update_path.write_bytes(source.encode("utf-8"))

            updater_path = script.with_name("mim_updater.py")
            updater_code = r'''
import os
import sys
import time
import shutil
import subprocess
from pathlib import Path

def main():
    pid = int(sys.argv[1])
    script = Path(sys.argv[2]).resolve()
    update = Path(sys.argv[3]).resolve()
    backup = script.with_name("main.py.backup")

    while True:
        try:
            os.kill(pid, 0)
        except OSError:
            break
        time.sleep(0.5)

    if not script.exists() or not update.exists():
        return 2

    shutil.copy2(script, backup)
    try:
        os.replace(update, script)
        subprocess.Popen([sys.executable, str(script)], cwd=str(script.parent))
    except Exception:
        shutil.copy2(backup, script)
        return 3
    return 0

if __name__ == "__main__":
    sys.exit(main())
'''
            updater_path.write_text(updater_code, encoding="utf-8")

            QMessageBox.information(
                self, APP_NAME,
                "Обновление скачано. Браузер закроется и запустится заново."
            )
            subprocess.Popen([
                sys.executable, str(updater_path), str(os.getpid()),
                str(script), str(update_path)
            ], cwd=str(script.parent))
            QApplication.quit()

        except Exception as error:
            QMessageBox.critical(
                self, "Ошибка обновления",
                f"Не удалось установить обновление:\n{error}"
            )

    def closeEvent(self, event):
        if not self.private:
            self.save_last_tabs()
            self.settings["window_width"] = self.width()
            self.settings["window_height"] = self.height()
            self.settings["window_x"] = self.x()
            self.settings["window_y"] = self.y()
            self.save_settings()
            write_json(self.bookmarks_file, self.bookmarks)
            write_json(self.history_file, self.history)
            write_json(self.downloads_file, self.downloads)
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("MIM")

    window = MIMBrowser()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()