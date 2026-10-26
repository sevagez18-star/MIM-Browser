
import sys
import os
import json
import base64
import hashlib
import secrets
import urllib.parse
from pathlib import Path
from datetime import datetime

from PySide6.QtCore import Qt, QUrl, QTimer, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QAction, QColor, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QLineEdit, QPushButton, QLabel, QListWidget,
    QListWidgetItem, QSplitter, QDialog, QFormLayout, QComboBox,
    QCheckBox, QColorDialog, QFileDialog, QMessageBox, QMenu,
    QInputDialog, QToolButton, QStackedWidget, QProgressBar
)
from PySide6.QtWebEngineCore import (
    QWebEngineProfile, QWebEnginePage, QWebEngineUrlRequestInterceptor,
    QWebEngineDownloadRequest, QWebEngineSettings
)
from PySide6.QtWebEngineWidgets import QWebEngineView

try:
    from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
    MULTIMEDIA_AVAILABLE = True
except ImportError:
    MULTIMEDIA_AVAILABLE = False

try:
    from cryptography.fernet import Fernet
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False


APP_NAME = "MIM Browser"
ROOT = Path.home() / "MIMBrowser"
ROOT.mkdir(parents=True, exist_ok=True)

DEFAULTS = {
    "homepage": "https://www.google.com/",
    "search_engine": "https://www.google.com/search?q={}",
    "theme": "dark",
    "accent": "#ff6b35",
    "sidebar": True,
    "game_mode": False,
    "animations": True,
    "adblock": True,
    "restore_tabs": True,
    "last_tabs": [],
    "pinned_urls": [],
    "download_path": str(Path.home() / "Downloads"),
    "active_profile": "Default",
}


def read_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError, TypeError):
        return default


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with open(temp, "w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
    temp.replace(path)


def profile_dir(name):
    safe = "".join(c for c in name if c.isalnum() or c in "-_ ")[:40].strip()
    safe = safe or "Default"
    folder = ROOT / "profiles" / safe
    folder.mkdir(parents=True, exist_ok=True)
    return folder


class AdBlocker(QWebEngineUrlRequestInterceptor):
    """Простой блокировщик известных рекламных доменов."""

    DOMAINS = (
        "doubleclick.net",
        "googlesyndication.com",
        "googleadservices.com",
        "adnxs.com",
        "adform.net",
        "taboola.com",
        "outbrain.com",
        "adsystem.com",
        "popads.net",
        "propellerads.com",
        "adsterra.com",
    )

    def __init__(self):
        super().__init__()
        self.enabled = True

    def interceptRequest(self, info):
        if not self.enabled:
            return
        try:
            host = info.requestUrl().host().lower()
            if any(host == domain or host.endswith("." + domain)
                   for domain in self.DOMAINS):
                info.block(True)
        except Exception:
            pass


class HomePage(QWidget):
    """Домашняя страница без локального фиктивного URL."""

    def __init__(self, browser):
        super().__init__()
        self.browser = browser
        self.setObjectName("homePage")
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setContentsMargins(40, 30, 40, 30)
        layout.setSpacing(16)

        title = QLabel("MIM Browser")
        title.setObjectName("homeTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        subtitle = QLabel("Твой браузер. Твои правила.")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitle)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Поиск в Google или ввод адреса…")
        self.search.setMinimumHeight(48)
        self.search.returnPressed.connect(self.search_web)
        layout.addWidget(self.search)

        links = QHBoxLayout()
        for label, url in [
            ("YouTube", "https://www.youtube.com/"),
            ("Discord", "https://discord.com/app"),
            ("Spotify", "https://open.spotify.com/"),
            ("Google", "https://www.google.com/"),
        ]:
            button = QPushButton(label)
            button.clicked.connect(lambda checked=False, u=url: browser.navigate(u))
            links.addWidget(button)
        layout.addLayout(links)

        self.clock = QLabel()
        self.clock.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.clock)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_clock)
        self.timer.start(1000)
        self.update_clock()

    def update_clock(self):
        self.clock.setText(datetime.now().strftime("%H:%M:%S  •  %d.%m.%Y"))

    def search_web(self):
        text = self.search.text().strip()
        if text:
            self.browser.navigate(self.browser.make_url(text))


class BrowserTab(QWidget):
    def __init__(self, browser, profile, private=False):
        super().__init__()
        self.browser = browser
        self.private = private
        self.group = "Без группы"
        self.view = QWebEngineView(self)
        self.page = QWebEnginePage(profile, self.view)
        self.view.setPage(self.page)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view)

        self.view.urlChanged.connect(self.url_changed)
        self.view.titleChanged.connect(self.title_changed)
        self.view.loadFinished.connect(self.load_finished)
        self.view.loadProgress.connect(self.load_progress)

    def url_changed(self, url):
        if self.browser.current_tab() is self:
            self.browser.address.setText(url.toString())

    def title_changed(self, title):
        self.browser.update_tab_title(self)
        if self.browser.current_tab() is self:
            self.browser.setWindowTitle(
                (title or APP_NAME) +
                (" — Приватный режим" if self.private else "")
            )

    def load_finished(self, ok):
        if ok and not self.private:
            url = self.view.url().toString()
            if url and url != "about:blank":
                self.browser.add_history(url, self.view.title())

    def load_progress(self, progress):
        if self.browser.current_tab() is self:
            self.browser.progress.setValue(progress)
            self.browser.progress.setVisible(progress < 100)


class PasswordDialog(QDialog):
    """Локальное хранилище паролей с шифрованием Fernet."""

    def __init__(self, browser):
        super().__init__(browser)
        self.browser = browser
        self.setWindowTitle("Менеджер паролей")
        self.resize(620, 440)
        self.data_file = browser.folder / "passwords.enc"
        self.key_file = browser.folder / "password_key.key"
        self.key = None
        self.passwords = []

        layout = QVBoxLayout(self)
        self.status = QLabel(
            "Пароли хранятся локально в зашифрованном виде."
            if CRYPTO_AVAILABLE else
            "Для шифрования установи пакет cryptography."
        )
        layout.addWidget(self.status)

        self.list = QListWidget()
        layout.addWidget(self.list)

        buttons = QHBoxLayout()
        for label, callback in [
            ("Разблокировать", self.unlock),
            ("Добавить", self.add_password),
            ("Показать пароль", self.show_password),
            ("Удалить", self.delete_password),
        ]:
            b = QPushButton(label)
            b.clicked.connect(callback)
            buttons.addWidget(b)
        layout.addLayout(buttons)

        if self.key_file.exists() and CRYPTO_AVAILABLE:
            self.unlock()

    def unlock(self):
        if not CRYPTO_AVAILABLE:
            QMessageBox.warning(self, APP_NAME, "Установи cryptography.")
            return
        if not self.key_file.exists():
            key = Fernet.generate_key()
            self.key_file.write_bytes(key)
        else:
            key = self.key_file.read_bytes()
        self.key = Fernet(key)
        self.passwords = []
        if self.data_file.exists():
            try:
                raw = self.key.decrypt(self.data_file.read_bytes())
                self.passwords = json.loads(raw.decode("utf-8"))
            except Exception:
                QMessageBox.warning(
                    self, "Менеджер паролей",
                    "Не удалось прочитать хранилище."
                )
                return
        self.refresh()
        self.status.setText("Хранилище разблокировано.")

    def persist(self):
        if not self.key:
            return
        encrypted = self.key.encrypt(
            json.dumps(self.passwords, ensure_ascii=False).encode("utf-8")
        )
        self.data_file.write_bytes(encrypted)

    def refresh(self):
        self.list.clear()
        for item in self.passwords:
            self.list.addItem(item.get("site", "Сайт"))

    def add_password(self):
        if not self.key:
            QMessageBox.information(self, APP_NAME, "Сначала разблокируй хранилище.")
            return
        site, ok = QInputDialog.getText(self, "Новая запись", "Сайт:")
        if not ok or not site.strip():
            return
        username, ok = QInputDialog.getText(self, "Новая запись", "Логин:")
        if not ok:
            return
        password, ok = QInputDialog.getText(
            self, "Новая запись", "Пароль:", QLineEdit.EchoMode.Password
        )
        if not ok:
            return
        self.passwords.append({
            "site": site.strip(),
            "username": username,
            "password": password,
        })
        self.persist()
        self.refresh()

    def show_password(self):
        index = self.list.currentRow()
        if index < 0 or index >= len(self.passwords):
            return
        item = self.passwords[index]
        QMessageBox.information(
            self, item["site"],
            f'Логин: {item["username"]}\nПароль: {item["password"]}'
        )

    def delete_password(self):
        index = self.list.currentRow()
        if index < 0:
            return
        del self.passwords[index]
        self.persist()
        self.refresh()


class MusicDialog(QDialog):
    def __init__(self, browser):
        super().__init__(browser)
        self.setWindowTitle("Музыкальный плеер")
        self.resize(520, 160)
        self.player = None

        layout = QVBoxLayout(self)
        self.label = QLabel("Выбери локальный аудиофайл.")
        layout.addWidget(self.label)

        row = QHBoxLayout()
        open_button = QPushButton("Открыть аудио")
        open_button.clicked.connect(self.open_audio)
        row.addWidget(open_button)

        if MULTIMEDIA_AVAILABLE:
            self.audio = QAudioOutput(self)
            self.player = QMediaPlayer(self)
            self.player.setAudioOutput(self.audio)
            play_button = QPushButton("▶ / ⏸")
            play_button.clicked.connect(self.toggle_play)
            row.addWidget(play_button)

            stop_button = QPushButton("■ Стоп")
            stop_button.clicked.connect(self.player.stop)
            row.addWidget(stop_button)

            self.volume = QComboBox()
            self.volume.addItems(["25%", "50%", "75%", "100%"])
            self.volume.setCurrentText("100%")
            self.volume.currentTextChanged.connect(
                lambda value: self.audio.setVolume(int(value[:-1]) / 100)
            )
            row.addWidget(self.volume)
        else:
            self.label.setText(
                "Мультимедиа недоступна. Установи полный пакет PySide6."
            )
        layout.addLayout(row)

    def open_audio(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Открыть аудио", "",
            "Аудио (*.mp3 *.wav *.ogg *.flac *.m4a);;Все файлы (*)"
        )
        if path:
            self.label.setText(Path(path).name)
            if self.player:
                self.player.setSource(QUrl.fromLocalFile(path))
                self.player.play()

    def toggle_play(self):
        if not self.player:
            return
        if self.player.isPlaying():
            self.player.pause()
        else:
            self.player.play()


class MIMBrowser(QMainWindow):
    def __init__(self, private=False, profile_name=None):
        super().__init__()
        self.private = private
        self.profile_name = profile_name or "Default"
        self.folder = profile_dir(self.profile_name)
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
        self.windows = []

        self.setWindowTitle(APP_NAME)
        self.resize(1400, 900)

        if private:
            self.profile = QWebEngineProfile(self)
        else:
            self.profile = QWebEngineProfile(
                "MIM_" + self.profile_name.replace(" ", "_"), self
            )
            self.profile.setPersistentStoragePath(str(self.folder / "webdata"))
            self.profile.setCachePath(str(self.folder / "cache"))
            self.profile.setPersistentCookiesPolicy(
                QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies
            )

        self.adblocker = AdBlocker()
        self.adblocker.enabled = self.settings.get("adblock", True)
        self.profile.setUrlRequestInterceptor(self.adblocker)
        self.profile.downloadRequested.connect(self.download_requested)

        self.build_ui()
        self.apply_settings()

        last_tabs = self.settings.get("last_tabs", []) if not private else []
        if last_tabs and self.settings.get("restore_tabs", True):
            for url in last_tabs:
                self.add_tab(url, switch=False)
            self.tabs.setCurrentIndex(0)
        else:
            self.add_tab("")

    def build_ui(self):
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(5)
        self.setCentralWidget(root)

        toolbar = QHBoxLayout()
        self.back_btn = QPushButton("←")
        self.back_btn.clicked.connect(self.go_back)
        toolbar.addWidget(self.back_btn)

        self.forward_btn = QPushButton("→")
        self.forward_btn.clicked.connect(self.go_forward)
        toolbar.addWidget(self.forward_btn)

        self.reload_btn = QPushButton("⟳")
        self.reload_btn.clicked.connect(self.reload_page)
        toolbar.addWidget(self.reload_btn)

        self.home_btn = QPushButton("⌂")
        self.home_btn.clicked.connect(self.go_home)
        toolbar.addWidget(self.home_btn)

        self.address = QLineEdit()
        self.address.setPlaceholderText("Поиск Google или адрес сайта…")
        self.address.returnPressed.connect(self.navigate_address)
        toolbar.addWidget(self.address, 1)

        self.go_btn = QPushButton("Перейти")
        self.go_btn.clicked.connect(self.navigate_address)
        toolbar.addWidget(self.go_btn)

        self.bookmark_btn = QPushButton("☆")
        self.bookmark_btn.clicked.connect(self.bookmark_current)
        toolbar.addWidget(self.bookmark_btn)

        self.progress = QProgressBar()
        self.progress.setMaximumWidth(110)
        self.progress.setVisible(False)
        toolbar.addWidget(self.progress)

        layout.addLayout(toolbar)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(self.splitter, 1)

        self.sidebar = QWidget()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(240)
        side = QVBoxLayout(self.sidebar)
        side.setContentsMargins(5, 5, 5, 5)

        brand = QLabel("MIM Browser")
        brand.setAlignment(Qt.AlignmentFlag.AlignCenter)
        brand.setObjectName("brand")
        side.addWidget(brand)

        self.profile_label = QLabel("Профиль: " + self.profile_name)
        self.profile_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        side.addWidget(self.profile_label)

        for label, callback in [
            ("🏠  Домашняя", self.go_home),
            ("☆  Закладки", self.show_bookmarks),
            ("◷  История", self.show_history),
            ("↓  Загрузки", self.show_downloads),
            ("🎵  Музыка", self.open_music),
            ("🎮  Игровой режим", self.toggle_game_mode),
            ("🌐  Перевести страницу", self.translate_page),
            ("🛡  Блокировщик рекламы", self.toggle_adblock),
            ("🔐  Менеджер паролей", self.open_passwords),
            ("👤  Профили", self.manage_profiles),
            ("🗂  Группы вкладок", self.manage_groups),
            ("⚙  Настройки", self.open_settings),
        ]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            side.addWidget(button)

        side.addStretch()
        side.addWidget(QLabel("Ширина панели: 240 px"))
        self.splitter.addWidget(self.sidebar)

        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.setDocumentMode(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self.on_tab_changed)
        self.tabs.tabBar().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tabs.tabBar().customContextMenuRequested.connect(self.tab_menu)
        self.splitter.addWidget(self.tabs)
        self.splitter.setSizes([240, 1160])
        self.splitter.setStretchFactor(1, 1)

        new_tab = QToolButton()
        new_tab.setText("+")
        new_tab.setToolTip("Новая вкладка (Ctrl+T)")
        new_tab.clicked.connect(lambda: self.add_tab(""))
        self.tabs.setCornerWidget(new_tab, Qt.Corner.TopRightCorner)

        self.create_shortcuts()

    def create_shortcuts(self):
        bindings = [
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
        for shortcut, callback in bindings:
            action = QAction(self)
            action.setShortcut(QKeySequence(shortcut))
            action.triggered.connect(callback)
            self.addAction(action)

    def current_tab(self):
        tab = self.tabs.currentWidget()
        return tab if isinstance(tab, BrowserTab) else None

    def add_tab(self, url="", switch=True):
        tab = BrowserTab(self, self.profile, self.private)
        index = self.tabs.addTab(tab, "Новая вкладка")
        if switch:
            self.tabs.setCurrentIndex(index)
        if url:
            tab.view.setUrl(QUrl(url))
        else:
            self.show_home_in_tab(tab)
        return tab

    def show_home_in_tab(self, tab):
        page = HomePage(self)
        index = self.tabs.indexOf(tab)
        if index < 0:
            return
        old_view = tab.view
        tab.view.hide()
        tab.layout().addWidget(page)
        tab.home_widget = page
        self.tabs.setTabText(index, "Домашняя")

    def close_tab(self, index):
        if index < 0 or index >= self.tabs.count():
            return
        tab = self.tabs.widget(index)
        if isinstance(tab, BrowserTab):
            url = tab.view.url().toString()
            if url and url != "about:blank":
                self.closed_tabs.append(url)
        self.tabs.removeTab(index)
        if self.tabs.count() == 0:
            self.add_tab("")
        self.save_last_tabs()

    def restore_closed(self):
        if self.closed_tabs:
            self.add_tab(self.closed_tabs.pop())

    def on_tab_changed(self, index):
        tab = self.current_tab()
        if tab:
            url = tab.view.url().toString()
            if url and url != "about:blank":
                self.address.setText(url)
        self.save_last_tabs()

    def update_tab_title(self, tab):
        index = self.tabs.indexOf(tab)
        if index < 0:
            return
        title = tab.view.title() or "Вкладка"
        if tab.view.url().toString() in self.settings.get("pinned_urls", []):
            title = "📌 " + title
        if tab.group != "Без группы":
            title = f"[{tab.group}] {title}"
        self.tabs.setTabText(index, title[:28])

    def tab_menu(self, position):
        index = self.tabs.tabBar().tabAt(position)
        if index < 0:
            return
        tab = self.tabs.widget(index)
        menu = QMenu(self)
        duplicate = menu.addAction("Дублировать вкладку")
        pin = menu.addAction("Закрепить / открепить")
        group = menu.addAction("Назначить группу")
        close = menu.addAction("Закрыть вкладку")
        chosen = menu.exec(self.tabs.tabBar().mapToGlobal(position))

        if chosen == duplicate:
            self.add_tab(tab.view.url().toString())
        elif chosen == pin:
            url = tab.view.url().toString()
            pinned = self.settings.setdefault("pinned_urls", [])
            if url in pinned:
                pinned.remove(url)
            else:
                pinned.append(url)
            self.save_settings()
            self.update_tab_title(tab)
        elif chosen == group:
            name, ok = QInputDialog.getItem(
                self, "Группа вкладок", "Группа:", self.groups, 0, True
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
        query = urllib.parse.quote_plus(text)
        return self.settings["search_engine"].replace("{}", query)

    def navigate_address(self):
        text = self.address.text().strip()
        if text:
            self.navigate(self.make_url(text))

    def navigate(self, url):
        tab = self.current_tab()
        if tab:
            tab.view.setUrl(QUrl(url))
            if hasattr(tab, "home_widget"):
                tab.home_widget.hide()
                tab.view.show()

    def go_back(self):
        tab = self.current_tab()
        if tab:
            tab.view.back()

    def go_forward(self):
        tab = self.current_tab()
        if tab:
            tab.view.forward()

    def reload_page(self):
        tab = self.current_tab()
        if tab:
            tab.view.reload()

    def go_home(self):
        tab = self.current_tab()
        if not tab:
            return
        tab.view.setUrl(QUrl(self.settings.get("homepage", "https://www.google.com/")))

    def bookmark_current(self):
        tab = self.current_tab()
        if not tab:
            return
        url = tab.view.url().toString()
        if not url or url == "about:blank":
            return
        if any(b.get("url") == url for b in self.bookmarks):
            QMessageBox.information(self, APP_NAME, "Эта страница уже в закладках.")
            return
        self.bookmarks.append({
            "title": tab.view.title() or url,
            "url": url,
            "folder": "Без папки",
        })
        self.save_bookmarks()
        self.bookmark_btn.setText("★")

    def save_settings(self):
        if not self.private:
            write_json(self.settings_file, self.settings)

    def save_bookmarks(self):
        if not self.private:
            write_json(self.bookmarks_file, self.bookmarks)

    def save_history(self):
        if not self.private:
            write_json(self.history_file, self.history)

    def save_downloads(self):
        if not self.private:
            write_json(self.downloads_file, self.downloads)

    def save_last_tabs(self):
        if self.private:
            return
        urls = []
        for i in range(self.tabs.count()):
            tab = self.tabs.widget(i)
            if isinstance(tab, BrowserTab):
                url = tab.view.url().toString()
                if url and url != "about:blank":
                    urls.append(url)
        self.settings["last_tabs"] = urls
        self.save_settings()

    def add_history(self, url, title):
        if self.private:
            return
        self.history.insert(0, {
            "url": url,
            "title": title or url,
            "time": datetime.now().strftime("%d.%m.%Y %H:%M"),
        })
        self.history = self.history[:2000]
        self.save_history()

    def show_bookmarks(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Закладки")
        dialog.resize(720, 450)
        layout = QVBoxLayout(dialog)
        listing = QListWidget()
        listing.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        layout.addWidget(listing)

        def refresh():
            listing.clear()
            for i, item in enumerate(self.bookmarks):
                row = QListWidgetItem(
                    f'[{item.get("folder", "Без папки")}] {item.get("title", "")}\n'
                    f'{item.get("url", "")}'
                )
                row.setData(Qt.ItemDataRole.UserRole, i)
                listing.addItem(row)

        def open_selected():
            row = listing.currentItem()
            if row:
                index = row.data(Qt.ItemDataRole.UserRole)
                self.navigate(self.bookmarks[index]["url"])
                dialog.accept()

        def delete_selected():
            row = listing.currentItem()
            if row:
                index = row.data(Qt.ItemDataRole.UserRole)
                del self.bookmarks[index]
                self.save_bookmarks()
                refresh()

        def rename_selected():
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
                self.save_bookmarks()
                refresh()

        listing.itemDoubleClicked.connect(lambda _: open_selected())
        listing.customContextMenuRequested.connect(
            lambda pos: self.bookmark_context_menu(
                listing, pos, open_selected, rename_selected, delete_selected
            )
        )

        buttons = QHBoxLayout()
        for label, callback in [
            ("Открыть", open_selected),
            ("Переименовать", rename_selected),
            ("Удалить", delete_selected),
        ]:
            b = QPushButton(label)
            b.clicked.connect(callback)
            buttons.addWidget(b)

        import_btn = QPushButton("Импорт")
        import_btn.clicked.connect(self.import_bookmarks)
        buttons.addWidget(import_btn)
        export_btn = QPushButton("Экспорт")
        export_btn.clicked.connect(self.export_bookmarks)
        buttons.addWidget(export_btn)

        layout.addLayout(buttons)
        refresh()
        dialog.exec()

    def bookmark_context_menu(self, listing, pos, open_cb, rename_cb, delete_cb):
        menu = QMenu(listing)
        a = menu.addAction("Открыть")
        b = menu.addAction("Переименовать")
        c = menu.addAction("Удалить закладку")
        selected = menu.exec(listing.mapToGlobal(pos))
        if selected == a:
            open_cb()
        elif selected == b:
            rename_cb()
        elif selected == c:
            delete_cb()

    def import_bookmarks(self):
        path, _ = QFileDialog.getOpenFileName(self, "Импорт", "", "JSON (*.json)")
        if not path:
            return
        data = read_json(Path(path), [])
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and item.get("url"):
                    if not any(b.get("url") == item["url"] for b in self.bookmarks):
                        self.bookmarks.append(item)
            self.save_bookmarks()

    def export_bookmarks(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Экспорт", "mim_bookmarks.json", "JSON (*.json)"
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
            for i, item in enumerate(self.history):
                row = QListWidgetItem(
                    f'{item.get("title", "")}\n{item.get("url", "")}\n{item.get("time", "")}'
                )
                row.setData(Qt.ItemDataRole.UserRole, i)
                listing.addItem(row)

        def open_selected():
            row = listing.currentItem()
            if row:
                index = row.data(Qt.ItemDataRole.UserRole)
                self.navigate(self.history[index]["url"])
                dialog.accept()

        def delete_selected():
            row = listing.currentItem()
            if row:
                del self.history[row.data(Qt.ItemDataRole.UserRole)]
                self.save_history()
                refresh()

        def clear_all():
            answer = QMessageBox.question(dialog, "Очистить", "Удалить всю историю?")
            if answer == QMessageBox.StandardButton.Yes:
                self.history.clear()
                self.save_history()
                refresh()

        listing.itemDoubleClicked.connect(lambda _: open_selected())
        buttons = QHBoxLayout()
        for label, callback in [
            ("Открыть", open_selected),
            ("Удалить выбранную", delete_selected),
            ("Очистить всё", clear_all),
        ]:
            b = QPushButton(label)
            b.clicked.connect(callback)
            buttons.addWidget(b)
        layout.addLayout(buttons)
        refresh()
        dialog.exec()

    def show_downloads(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Загрузки")
        dialog.resize(720, 420)
        layout = QVBoxLayout(dialog)
        listing = QListWidget()
        layout.addWidget(listing)

        def refresh():
            listing.clear()
            for item in self.downloads:
                listing.addItem(
                    f'{item.get("name", "")} — {item.get("status", "")}\n'
                    f'{item.get("path", "")}'
                )

        def open_file():
            index = listing.currentRow()
            if index >= 0:
                path = self.downloads[index].get("path", "")
                if path and Path(path).exists():
                    if sys.platform == "win32":
                        os.startfile(path)
                    else:
                        import subprocess
                        subprocess.Popen(["xdg-open", path])

        def remove():
            index = listing.currentRow()
            if index >= 0:
                del self.downloads[index]
                self.save_downloads()
                refresh()

        buttons = QHBoxLayout()
        for label, callback in [
            ("Открыть файл", open_file),
            ("Убрать из списка", remove),
        ]:
            b = QPushButton(label)
            b.clicked.connect(callback)
            buttons.addWidget(b)
        layout.addLayout(buttons)
        refresh()
        dialog.exec()

    def download_requested(self, download):
        folder = Path(self.settings.get("download_path", str(Path.home() / "Downloads")))
        folder.mkdir(parents=True, exist_ok=True)
        suggested = download.downloadFileName()
        path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить загрузку", str(folder / suggested)
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
        }
        if not self.private:
            self.downloads.insert(0, record)
            self.save_downloads()

        download.stateChanged.connect(
            lambda state, r=record: self.download_state(state, r)
        )
        download.accept()

    def download_state(self, state, record):
        if state == QWebEngineDownloadRequest.DownloadState.DownloadCompleted:
            record["status"] = "Завершено"
        elif state == QWebEngineDownloadRequest.DownloadState.DownloadCancelled:
            record["status"] = "Отменено"
        elif state == QWebEngineDownloadRequest.DownloadState.DownloadInterrupted:
            record["status"] = "Ошибка"
        self.save_downloads()

    def toggle_game_mode(self):
        self.settings["game_mode"] = not self.settings.get("game_mode", False)
        self.apply_settings()
        self.save_settings()
        QMessageBox.information(
            self, "Игровой режим",
            "Игровой режим включён." if self.settings["game_mode"]
            else "Игровой режим выключен."
        )

    def toggle_adblock(self):
        self.settings["adblock"] = not self.settings.get("adblock", True)
        self.adblocker.enabled = self.settings["adblock"]
        self.save_settings()
        QMessageBox.information(
            self, "Блокировщик рекламы",
            "Включён" if self.adblocker.enabled else "Выключен"
        )

    def translate_page(self):
        tab = self.current_tab()
        if not tab:
            return
        url = tab.view.url().toString()
        if not url or url == "about:blank":
            return
        translated = (
            "https://translate.google.com/translate?sl=auto&tl=ru&u="
            + urllib.parse.quote(url, safe="")
        )
        self.navigate(translated)

    def open_music(self):
        dialog = MusicDialog(self)
        dialog.exec()

    def open_passwords(self):
        PasswordDialog(self).exec()

    def open_private(self):
        window = MIMBrowser(private=True, profile_name="Private")
        self.windows.append(window)
        window.show()

    def manage_profiles(self):
        names = ["Default"]
        profiles = ROOT / "profiles"
        if profiles.exists():
            names.extend(
                p.name for p in profiles.iterdir()
                if p.is_dir() and p.name not in names
            )
        name, ok = QInputDialog.getItem(
            self, "Профили пользователей", "Выбери профиль:",
            names + ["+ Создать профиль"], 0, False
        )
        if not ok:
            return
        if name == "+ Создать профиль":
            name, ok = QInputDialog.getText(self, "Новый профиль", "Название:")
            if not ok or not name.strip():
                return
        name = name.strip()
        if name == self.profile_name:
            return
        window = MIMBrowser(profile_name=name)
        self.windows.append(window)
        window.show()

    def manage_groups(self):
        tab = self.current_tab()
        if not tab:
            return
        name, ok = QInputDialog.getItem(
            self, "Группы вкладок", "Выбери группу:",
            self.groups, 0, True
        )
        if ok and name.strip():
            if name not in self.groups:
                self.groups.append(name)
            tab.group = name
            self.update_tab_title(tab)

    def find_text(self):
        tab = self.current_tab()
        if not tab:
            return
        text, ok = QInputDialog.getText(self, "Поиск на странице", "Найти текст:")
        if ok and text:
            tab.page.findText(text)

    def open_settings(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Настройки MIM Browser")
        dialog.resize(520, 500)
        layout = QVBoxLayout(dialog)
        form = QFormLayout()

        homepage = QLineEdit(self.settings.get("homepage", "https://www.google.com/"))
        search = QLineEdit(self.settings.get("search_engine", "https://www.google.com/search?q={}"))
        theme = QComboBox()
        theme.addItems(["dark", "light", "blue", "purple"])
        theme.setCurrentText(self.settings.get("theme", "dark"))

        accent_row = QHBoxLayout()
        accent = QLineEdit(self.settings.get("accent", "#ff6b35"))
        accent.setReadOnly(True)
        color_btn = QPushButton("Выбрать")
        color_btn.clicked.connect(
            lambda: self.choose_accent(accent)
        )
        accent_row.addWidget(accent)
        accent_row.addWidget(color_btn)

        sidebar = QCheckBox("Показывать боковую панель")
        sidebar.setChecked(self.settings.get("sidebar", True))
        game = QCheckBox("Игровой режим")
        game.setChecked(self.settings.get("game_mode", False))
        animations = QCheckBox("Анимации интерфейса")
        animations.setChecked(self.settings.get("animations", True))
        adblock = QCheckBox("Блокировщик рекламы")
        adblock.setChecked(self.settings.get("adblock", True))
        restore = QCheckBox("Восстанавливать вкладки")
        restore.setChecked(self.settings.get("restore_tabs", True))

        download_path = QLineEdit(self.settings.get("download_path", str(Path.home() / "Downloads")))
        choose_folder = QPushButton("Выбрать папку загрузок")
        choose_folder.clicked.connect(
            lambda: self.choose_download_folder(download_path)
        )

        form.addRow("Домашняя страница:", homepage)
        form.addRow("Поисковая ссылка ({}):", search)
        form.addRow("Тема:", theme)
        form.addRow("Акцентный цвет:", accent_row)
        form.addRow(sidebar)
        form.addRow(game)
        form.addRow(animations)
        form.addRow(adblock)
        form.addRow(restore)
        form.addRow("Папка загрузок:", download_path)
        form.addRow(choose_folder)
        layout.addLayout(form)

        buttons = QHBoxLayout()
        save_btn = QPushButton("Сохранить")
        cancel_btn = QPushButton("Отмена")
        buttons.addWidget(save_btn)
        buttons.addWidget(cancel_btn)
        layout.addLayout(buttons)
        cancel_btn.clicked.connect(dialog.reject)

        def save():
            self.settings.update({
                "homepage": homepage.text().strip() or "https://www.google.com/",
                "search_engine": search.text().strip() or "https://www.google.com/search?q={}",
                "theme": theme.currentText(),
                "accent": accent.text(),
                "sidebar": sidebar.isChecked(),
                "game_mode": game.isChecked(),
                "animations": animations.isChecked(),
                "adblock": adblock.isChecked(),
                "restore_tabs": restore.isChecked(),
                "download_path": download_path.text().strip(),
            })
            self.adblocker.enabled = self.settings["adblock"]
            self.apply_settings()
            self.save_settings()
            dialog.accept()

        save_btn.clicked.connect(save)

        export_btn = QPushButton("Экспорт настроек")
        export_btn.clicked.connect(self.export_settings)
        form.addRow(export_btn)

        import_btn = QPushButton("Импорт настроек")
        import_btn.clicked.connect(self.import_settings)
        form.addRow(import_btn)

        dialog.exec()

    def choose_accent(self, line_edit):
        color = QColorDialog.getColor(QColor(line_edit.text()), self)
        if color.isValid():
            line_edit.setText(color.name())

    def choose_download_folder(self, line_edit):
        path = QFileDialog.getExistingDirectory(self, "Папка загрузок", line_edit.text())
        if path:
            line_edit.setText(path)

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
        imported = read_json(Path(path), None)
        if not isinstance(imported, dict):
            QMessageBox.warning(self, APP_NAME, "Некорректный файл настроек.")
            return
        for key in DEFAULTS:
            if key in imported:
                self.settings[key] = imported[key]
        self.apply_settings()
        self.save_settings()

    def apply_settings(self):
        theme = self.settings.get("theme", "dark")
        accent = self.settings.get("accent", "#ff6b35")
        themes = {
            "dark": ("#17191f", "#242630", "#f3f3f3", "#373b47"),
            "light": ("#f4f5f7", "#ffffff", "#202124", "#d7dbe0"),
            "blue": ("#101c2d", "#172b45", "#f2f7ff", "#244a73"),
            "purple": ("#20152e", "#302044", "#f8f0ff", "#49305e"),
        }
        bg, panel, fg, border = themes.get(theme, themes["dark"])

        self.setStyleSheet(f"""
            QMainWindow, QWidget {{
                background-color: {bg};
                color: {fg};
                font-size: 13px;
            }}
            QLineEdit, QListWidget, QComboBox {{
                background-color: {panel};
                color: {fg};
                border: 1px solid {border};
                border-radius: 7px;
                padding: 7px;
            }}
            QPushButton, QToolButton {{
                background-color: {panel};
                color: {fg};
                border: 1px solid {border};
                border-radius: 7px;
                padding: 7px;
            }}
            QPushButton:hover, QToolButton:hover {{
                border: 1px solid {accent};
            }}
            QTabWidget::pane {{ border: 1px solid {border}; }}
            QTabBar::tab {{
                background: {panel};
                color: {fg};
                padding: 9px 12px;
                border: 1px solid {border};
            }}
            QTabBar::tab:selected {{ border-bottom: 2px solid {accent}; }}
            QLabel#brand, QLabel#homeTitle {{
                font-size: 22px;
                font-weight: bold;
                color: {accent};
                padding: 10px;
            }}
            QProgressBar::chunk {{ background-color: {accent}; }}
        """)

        # Панель всегда имеет строго 240 px, даже после изменения настроек.
        self.sidebar.setFixedWidth(240)
        self.sidebar.setVisible(self.settings.get("sidebar", True))
        self.adblocker.enabled = self.settings.get("adblock", True)

        if self.settings.get("game_mode", False):
            for i in range(self.tabs.count()):
                tab = self.tabs.widget(i)
                if isinstance(tab, BrowserTab):
                    tab.view.settings().setAttribute(
                        QWebEngineSettings.WebAttribute.PlaybackRequiresUserGesture,
                        True
                    )
                    tab.view.settings().setAttribute(
                        QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows,
                        False
                    )
        else:
            for i in range(self.tabs.count()):
                tab = self.tabs.widget(i)
                if isinstance(tab, BrowserTab):
                    tab.view.settings().setAttribute(
                        QWebEngineSettings.WebAttribute.PlaybackRequiresUserGesture,
                        False
                    )
                    tab.view.settings().setAttribute(
                        QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows,
                        True
                    )

        if self.settings.get("animations", True):
            animation = QPropertyAnimation(self, b"windowOpacity", self)
            animation.setDuration(180)
            animation.setStartValue(0.85)
            animation.setEndValue(1.0)
            animation.setEasingCurve(QEasingCurve.Type.OutCubic)
            animation.start()
            self._animation = animation

    def closeEvent(self, event):
        if not self.private:
            self.save_last_tabs()
            self.save_bookmarks()
            self.save_history()
            self.save_downloads()
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    window = MIMBrowser()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
