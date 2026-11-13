import sys
import os
import sqlite3
import shutil
import logging
import zipfile
import configparser
from datetime import datetime, timedelta
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QLineEdit, QPushButton, 
    QVBoxLayout, QHBoxLayout, QGridLayout, QTabWidget, QTableWidget, 
    QTableWidgetItem, QCheckBox, QMessageBox, QFileDialog, QProgressBar, 
    QDialog, QHeaderView, QTextEdit, QComboBox
)
from PyQt6.QtGui import QIcon, QKeySequence, QPixmap
from PyQt6.QtCore import Qt, QSize

# Настройка логирования
logging.basicConfig(
    filename='actions.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    encoding='utf-8'
)

# Загрузка конфигурации
config = configparser.ConfigParser()
config_file = 'config.ini'

if not os.path.exists(config_file):
    config['Server'] = {
        'host': 'ftp.yourserver.com',
        'port': '21',
        'username': 'admin',
        'password': 'password',
        'use_sftp': 'False'
    }
    with open(config_file, 'w', encoding='utf-8') as f:
        config.write(f)
else:
    config.read(config_file, encoding='utf-8')

DB_PATH = 'database.db'

def init_db():
    """Инициализация SQLite базы данных и создание таблиц"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Таблица рабочей базы данных (РБД)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS ads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ad_number TEXT UNIQUE NOT NULL,
            category TEXT NOT NULL,
            property_type TEXT NOT NULL,
            rooms TEXT NOT NULL,
            district TEXT NOT NULL,
            landmark TEXT NOT NULL,
            area REAL,
            floor INTEGER,
            floors_total INTEGER NOT NULL,
            price REAL NOT NULL,
            is_active INTEGER DEFAULT 1
        )
    ''')
    
    # Таблица архивной базы данных (АБД) для удаленных записей
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS archive_ads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ad_number TEXT UNIQUE NOT NULL,
            category TEXT NOT NULL,
            property_type TEXT NOT NULL,
            rooms TEXT NOT NULL,
            district TEXT NOT NULL,
            landmark TEXT NOT NULL,
            area REAL,
            floor INTEGER,
            floors_total INTEGER NOT NULL,
            price REAL NOT NULL,
            deleted_at TEXT NOT NULL
        )
    ''')

    # Таблица пользователей для авторизации
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL
        )
    ''')
    
    # Создаем админа и оператора по умолчанию, если таблица пуста
    cursor.execute("SELECT COUNT(*) FROM users")
    if cursor.fetchone()[0] == 0:
        cursor.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)", ("admin", "admin123", "admin"))
        cursor.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)", ("operator", "op123", "operator"))
        
    conn.commit()
    conn.close()

class AuthWindow(QDialog):
    """Окно авторизации"""
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Авторизация")
        self.setFixedSize(300, 180)
        
        if os.path.exists("app_icon.ico"):
            self.setWindowIcon(QIcon("app_icon.ico"))
        
        layout = QVBoxLayout()
        
        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("Логин")
        layout.addWidget(QLabel("Логин:"))
        layout.addWidget(self.username_input)
        
        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("Пароль")
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(QLabel("Пароль:"))
        layout.addWidget(self.password_input)
        
        self.login_btn = QPushButton("Войти")
        self.login_btn.clicked.connect(self.handle_login)
        layout.addWidget(self.login_btn)
        
        self.setLayout(layout)
        self.user_data = None

    def handle_login(self):
        username = self.username_input.text().strip()
        password = self.password_input.text().strip()
        
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT role FROM users WHERE username=? AND password=?", (username, password))
        res = cursor.fetchone()
        conn.close()
        
        if res:
            self.user_data = {"username": username, "role": res[0]}
            self.accept()
        else:
            QMessageBox.warning(self, "Ошибка", "Неверный логин или пароль!")

class MainWindow(QMainWindow):
    """Основное окно программы"""
    def __init__(self, user_info):
        super().__init__()
        self.user_info = user_info
        self.setWindowTitle(f"РБД Управление недвижимостью - Пользователь: {user_info['username']} ({user_info['role']})")
        self.resize(1150, 700)
        
        if os.path.exists("app_icon.ico"):
            self.setWindowIcon(QIcon("app_icon.ico"))
            
        self.init_ui()
        self.load_table_data()

    def init_ui(self):
        central_widget = QWidget()
        main_layout = QHBoxLayout()
        
        # --- ПРАВАЯ ПАНЕЛЬ ИНСТРУМЕНТОВ (ToolBox) ---
        tools_layout = QVBoxLayout()
        tools_layout.addWidget(QLabel("<b>Панель ввода данных</b>"))
        
        self.inputs = {}
        fields = [
            ("Объявление №", "ad_number"),
            ("Район", "district"),
            ("Ориентир", "landmark"),
            ("Комн.", "rooms"),
            ("Этаж / Площадь", "floor_area"),
            ("Этажность", "floors_total"),
            ("Цена", "price")
        ]
        
        for label_text, key in fields:
            tools_layout.addWidget(QLabel(label_text))
            line_edit = QLineEdit()
            line_edit.setEnabled(False)
            self.inputs[key] = line_edit
            tools_layout.addWidget(line_edit)
            
        self.btn_create = QPushButton("Создать")
        self.btn_edit = QPushButton("Изменить")
        self.btn_save = QPushButton("Сохранить")
        self.btn_media = QPushButton("М-Файлы")
        self.btn_delete = QPushButton("Удалить")
        
        for btn in [self.btn_create, self.btn_edit, self.btn_save, self.btn_media, self.btn_delete]:
            tools_layout.addWidget(btn)
            
        self.btn_create.clicked.connect(self.enable_creation)
        self.btn_edit.clicked.connect(self.enable_editing)
        self.btn_save.clicked.connect(self.save_data)
        self.btn_media.clicked.connect(self.upload_media)
        self.btn_delete.clicked.connect(self.delete_records)
        
        tools_layout.addStretch()
        
        # --- ЛЕВАЯ ПАНЕЛЬ ОТОБРАЖЕНИЯ (Вкладки) ---
        self.tabs_main = QTabWidget()
        
        self.tab_rent = QWidget()
        self.tab_sales = QWidget()
        
        self.tabs_main.addTab(self.tab_rent, "Аренда (Rent)")
        self.tabs_main.addTab(self.tab_sales, "Продажа (Sales)")
        
        self.setup_category_tabs(self.tab_rent, "Rent")
        self.setup_category_tabs(self.tab_sales, "Sales")
        
        # РАСШИРЕНИЕ ДЛЯ АДМИНИСТРАТОРА: Вкладка "Инструменты"
        if self.user_info['role'] == 'admin':
            self.tab_tools = QWidget()
            self.tabs_main.addTab(self.tab_tools, "Инструменты (Tools)")
            self.setup_tools_tab(self.tab_tools)
        
        main_layout.addWidget(self.tabs_main, stretch=4)
        main_layout.addLayout(tools_layout, stretch=1)
        
        central_widget.setLayout(main_layout)
        self.setCentralWidget(central_widget)

    def setup_tools_tab(self, parent_tab):
        """Интерфейс вкладки 'Инструменты' (реализация стр. 66-67 ТЗ для Администратора)"""
        layout = QVBoxLayout()
        
        layout.addWidget(QLabel("<b>Панель расширенного администрирования (РБД / АБД / Логи / Пользователи)</b>"))
        
        # 1. Просмотр логов
        btn_logs = QPushButton("Просмотреть системный журнал (actions.log)")
        btn_logs.clicked.connect(self.view_system_logs)
        layout.addWidget(btn_logs)
        
        # 2. Бэкап БД
        btn_backup = QPushButton("Создать резервную копию базы данных (Backup)")
        btn_backup.clicked.connect(self.backup_database)
        layout.addWidget(btn_backup)
        
        # 3. Восстановление из архива (АБД)
        btn_restore = QPushButton("Управление архивом (Восстановление записей и медиа из АБД)")
        btn_restore.clicked.connect(self.open_restore_dialog)
        layout.addWidget(btn_restore)
        
        # 4. Управление пользователями (Операторами)
        layout.addWidget(QLabel("<br><b>Управление учетными записями операторов</b>"))
        
        self.users_table = QTableWidget()
        self.load_users_table()
        layout.addWidget(self.users_table)
        
        user_btn_layout = QHBoxLayout()
        btn_add_user = QPushButton("Добавить оператора")
        btn_add_user.clicked.connect(self.add_user_dialog)
        btn_del_user = QPushButton("Удалить выбранного")
        btn_del_user.clicked.connect(self.delete_user)
        
        user_btn_layout.addWidget(btn_add_user)
        user_btn_layout.addWidget(btn_del_user)
        layout.addLayout(user_btn_layout)
        
        parent_tab.setLayout(layout)

    def view_system_logs(self):
        """Просмотр логов на отдельном экране внутри программы"""
        if os.path.exists("actions.log"):
            with open("actions.log", "r", encoding="utf-8") as f:
                logs_content = f.read()
            
            dlg = QDialog(self)
            dlg.setWindowTitle("Системный журнал действий (Actions Log)")
            dlg.resize(800, 500)
            dlg_layout = QVBoxLayout()
            
            text_edit = QTextEdit()
            text_edit.setPlainText(logs_content)
            text_edit.setReadOnly(True)
            dlg_layout.addWidget(text_edit)
            
            dlg.setLayout(dlg_layout)
            dlg.exec()
        else:
            QMessageBox.information(self, "Логи", "Файл логов actions.log еще не создан.")

    def backup_database(self):
        """Создание бэкапа базы данных с логированием"""
        try:
            backup_path, _ = QFileDialog.getSaveFileName(self, "Сохранить бэкап БД", "database_backup.db", "SQLite DB (*.db)")
            if backup_path:
                shutil.copyfile(DB_PATH, backup_path)
                QMessageBox.information(self, "Успех", f"Резервная копия успешно сохранена в:\n{backup_path}")
                logging.info(f"Администратор {self.user_info['username']} успешно создал резервную копию базы данных.")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось создать бэкап: {e}")

    def load_users_table(self):
        """Загрузка списка пользователей с добавлением колонки чекбоксов для выбора"""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT id, username, role FROM users")
        rows = cursor.fetchall()
        conn.close()
        
        self.users_table.setColumnCount(4)
        self.users_table.setHorizontalHeaderLabels(["ID", "Логин", "Роль", "Выбор"])
        self.users_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        
        self.users_table.setRowCount(len(rows))
        for row_idx, row_data in enumerate(rows):
            for col_idx, val in enumerate(row_data):
                self.users_table.setItem(row_idx, col_idx, QTableWidgetItem(str(val)))
            
            chk = QCheckBox()
            self.users_table.setCellWidget(row_idx, 3, chk)

    def add_user_dialog(self):
        """Диалоговое окно добавления нового оператора с защитой от блокировки БД"""
        dlg = QDialog(self)
        dlg.setWindowTitle("Добавить оператора")
        dlg.setFixedSize(300, 200)
        dlg_layout = QVBoxLayout()
        
        u_input = QLineEdit()
        u_input.setPlaceholderText("Логин")
        p_input = QLineEdit()
        p_input.setPlaceholderText("Пароль")
        p_input.setEchoMode(QLineEdit.EchoMode.Password)
        
        r_combo = QComboBox()
        r_combo.addItems(["operator", "admin"])
        
        dlg_layout.addWidget(QLabel("Логин:"))
        dlg_layout.addWidget(u_input)
        dlg_layout.addWidget(QLabel("Пароль:"))
        dlg_layout.addWidget(p_input)
        dlg_layout.addWidget(QLabel("Роль:"))
        dlg_layout.addWidget(r_combo)
        
        btn_save = QPushButton("Создать")
        
        def save_new_user():
            username = u_input.text().strip()
            password = p_input.text().strip()
            role = r_combo.currentText()
            
            if not username or not password:
                QMessageBox.warning(dlg, "Ошибка", "Заполните все поля!")
                return
                
            try:
                conn = sqlite3.connect(DB_PATH, timeout=5.0)
                cursor = conn.cursor()
                
                cursor.execute("SELECT id FROM users WHERE username=?", (username,))
                if cursor.fetchone():
                    QMessageBox.warning(dlg, "Ошибка", f"Логин '{username}' уже занят! Выберите другой.")
                    conn.close()
                    return
                
                cursor.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)", (username, password, role))
                conn.commit()
                conn.close()
                
                logging.info(f"Администратор {self.user_info['username']} добавил пользователя {username} с ролью {role}.")
                QMessageBox.information(dlg, "Успех", f"Пользователь '{username}' успешно добавлен!")
                dlg.accept()
                self.load_users_table()
                
            except Exception as e:
                QMessageBox.critical(dlg, "Ошибка БД", f"Не удалось добавить пользователя: {e}")
                
        btn_save.clicked.connect(save_new_user)
        dlg_layout.addWidget(btn_save)
        dlg.setLayout(dlg_layout)
        dlg.exec()

    def delete_user(self):
        """Удаление отмеченного галочкой оператора"""
        target_user = None
        
        for row in range(self.users_table.rowCount()):
            chk_widget = self.users_table.cellWidget(row, 3)
            if chk_widget and isinstance(chk_widget, QCheckBox) and chk_widget.isChecked():
                user_id = self.users_table.item(row, 0).text()
                username = self.users_table.item(row, 1).text()
                target_user = (user_id, username)
                break
                
        if not target_user:
            QMessageBox.warning(self, "Ошибка", "Вы не выбрали пользователя. Отметьте галочкой строку пользователя, которого необходимо удалить!")
            return
            
        user_id, username = target_user
        
        if username == "admin":
            QMessageBox.warning(self, "Ошибка", "Нельзя удалить главного администратора по умолчанию!")
            return
            
        reply = QMessageBox.question(
            self, "Удаление", f"Желаете ли Вы удалить пользователя '{username}'?", 
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute("DELETE FROM users WHERE id=?", (user_id,))
            conn.commit()
            conn.close()
            
            logging.info(f"Администратор {self.user_info['username']} удалил пользователя {username}.")
            QMessageBox.information(self, "Успех", f"Пользователь '{username}' успешно удален.")
            self.load_users_table()

    def open_restore_dialog(self):
        """Экран восстановления удаленных записей из АБД и ZIP-архивов медиафайлов"""
        dlg = QDialog(self)
        dlg.setWindowTitle("Восстановление записей и медиа из АБД (Архив)")
        dlg.resize(900, 450)
        dlg_layout = QVBoxLayout()
        
        dlg_layout.addWidget(QLabel("<b>Список записей в Архивйной базе данных (АБД) — хранение до 30 дней:</b>"))
        
        table = QTableWidget()
        table.setColumnCount(8)
        table.setHorizontalHeaderLabels(["Объявление №", "Категория", "Тип", "Комн.", "Район", "Цена", "Дата удаления", "Выбор"])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT ad_number, category, property_type, rooms, district, price, deleted_at FROM archive_ads")
        rows = cursor.fetchall()
        conn.close()
        
        table.setRowCount(len(rows))
        for row_idx, row_data in enumerate(rows):
            for col_idx, val in enumerate(row_data):
                table.setItem(row_idx, col_idx, QTableWidgetItem(str(val)))
            chk = QCheckBox()
            table.setCellWidget(row_idx, 7, chk)
            
        dlg_layout.addWidget(table)
        
        btn_restore_selected = QPushButton("Восстановить выбранную запись в РБД")
        
        def restore_action():
            selected_ad = None
            for row in range(table.rowCount()):
                chk_widget = table.cellWidget(row, 7)
                if chk_widget and chk_widget.isChecked():
                    ad_item = table.item(row, 0)
                    if ad_item:
                        selected_ad = ad_item.text()
                        break
            if not selected_ad:
                QMessageBox.warning(dlg, "Ошибка", "Отметьте галочкой запись для восстановления!")
                return
                
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute("SELECT category, property_type, rooms, district, landmark, area, floor, floors_total, price FROM archive_ads WHERE ad_number=?", (selected_ad,))
            rec = cursor.fetchone()
            
            if rec:
                cat, p_type, r_val, dist, land, area_v, floor_v, f_tot, price_v = rec
                try:
                    cursor.execute("SELECT id FROM ads WHERE ad_number=?", (selected_ad,))
                    existing = cursor.fetchone()
                    
                    if existing:
                        cursor.execute('''
                            UPDATE ads 
                            SET category=?, property_type=?, rooms=?, district=?, landmark=?, area=?, floor=?, floors_total=?, price=?, is_active=1
                            WHERE ad_number=?
                        ''', (cat, p_type, r_val, dist, land, area_v, floor_v, f_tot, price_v, selected_ad))
                    else:
                        cursor.execute('''
                            INSERT INTO ads (ad_number, category, property_type, rooms, district, landmark, area, floor, floors_total, price, is_active)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                        ''', (selected_ad, cat, p_type, r_val, dist, land, area_v, floor_v, f_tot, price_v))
                    
                    cursor.execute("DELETE FROM archive_ads WHERE ad_number=?", (selected_ad,))
                    conn.commit()
                    
                    archive_zip_path = os.path.join("Archive", cat, p_type, f"{r_val}-room", f"{selected_ad}.zip")
                    target_media_dir = os.path.join(cat, p_type, f"{r_val}-room", selected_ad)
                    
                    if os.path.exists(archive_zip_path):
                        os.makedirs(target_media_dir, exist_ok=True)
                        with zipfile.ZipFile(archive_zip_path, 'r') as zip_ref:
                            zip_ref.extractall(target_media_dir)
                        os.remove(archive_zip_path)
                        
                    logging.info(f"Администратор {self.user_info['username']} восстановил объявление № {selected_ad} из АБД в РБД.")
                    QMessageBox.information(dlg, "Успех", f"Запись № {selected_ad} и её медиафайлы успешно восстановлены!")
                    dlg.accept()
                    self.load_table_data()
                except Exception as e:
                    QMessageBox.critical(dlg, "Ошибка", f"Не удалось восстановить запись: {e}")
            conn.close()

        btn_restore_selected.clicked.connect(restore_action)
        dlg_layout.addWidget(btn_restore_selected)
        
        dlg.setLayout(dlg_layout)
        dlg.exec()

    def setup_category_tabs(self, parent_tab, category_name):
        layout = QVBoxLayout()
        sub_tabs = QTabWidget()
        
        apartments_widget = QWidget()
        houses_widget = QWidget()
        
        sub_tabs.addTab(apartments_widget, "Квартиры (Apartments)")
        sub_tabs.addTab(houses_widget, "Дома (Houses)")
        
        self.setup_rooms_tabs(apartments_widget, category_name, "Apartments")
        self.setup_rooms_tabs(houses_widget, category_name, "Houses")
        
        layout.addWidget(sub_tabs)
        parent_tab.setLayout(layout)

    def setup_rooms_tabs(self, parent_widget, category, prop_type):
        layout = QVBoxLayout()
        rooms_tabs = QTabWidget()
        
        rooms_list = ["1-room", "2-room", "3-room", "4-room", "5-room"]
        for r in rooms_list:
            room_tab = QWidget()
            room_layout = QVBoxLayout()
            
            table = QTableWidget()
            table.setColumnCount(9)
            headers = ["Объявление №", "Район", "Ориентир", "Комн.", "Этаж", "Этажность", "Цена", "Медиа", "Выбор"]
            if prop_type == "Houses":
                headers[4] = "Площадь"
            table.setHorizontalHeaderLabels(headers)
            
            header = table.horizontalHeader()
            header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
            header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
            header.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
            header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
            header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
            header.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
            header.setSectionResizeMode(6, QHeaderView.ResizeMode.Interactive)
            header.setSectionResizeMode(8, QHeaderView.ResizeMode.Fixed)
            
            table.setColumnWidth(3, 50)
            table.setColumnWidth(4, 70)
            table.setColumnWidth(5, 75)
            table.setColumnWidth(8, 60)
            
            header.setSectionResizeMode(7, QHeaderView.ResizeMode.Stretch)
            table.setIconSize(QSize(50, 50))
            
            room_layout.addWidget(table)
            room_tab.setLayout(room_layout)
            rooms_tabs.addTab(room_tab, r.replace("-room", "-комн."))
            
            setattr(self, f"table_{category}_{prop_type}_{r}", table)
            
        layout.addWidget(rooms_tabs)
        parent_widget.setLayout(layout)

    def enable_creation(self):
        for field in self.inputs.values():
            field.setEnabled(True)
            field.clear()
        QMessageBox.information(self, "Создание", "Ячейки активированы. Введите данные или вставьте из Excel (Ctrl+C / Ctrl+V).")

    def keyPressEvent(self, event):
        fields_active = list(self.inputs.values())[0].isEnabled()
        is_ctrl_pressed = event.modifiers() & Qt.KeyboardModifier.ControlModifier
        if is_ctrl_pressed and event.key() == Qt.Key.Key_V and fields_active:
            clipboard = QApplication.clipboard()
            text = clipboard.text().strip()
            
            if text:
                row_data = text.split('\n')[0].split('\t')
                keys = ["ad_number", "district", "landmark", "rooms", "floor_area", "floors_total", "price"]
                
                for i, key in enumerate(keys):
                    if i < len(row_data):
                        clean_val = row_data[i].strip()
                        if key in self.inputs:
                            self.inputs[key].setText(clean_val)
                
                event.accept()
                return
                
        super().keyPressEvent(event)

    def enable_editing(self):
        for field in self.inputs.values():
            field.setEnabled(True)
        QMessageBox.information(self, "Редактирование", "Ячейки разблокированы для изменения выбранной записи.")

    def save_data(self):
        ad_num = self.inputs["ad_number"].text().strip()
        rooms = self.inputs["rooms"].text().strip()
        district = self.inputs["district"].text().strip()
        landmark = self.inputs["landmark"].text().strip()
        
        floor_area_str = self.inputs["floor_area"].text().strip().replace(" ", "").replace(",", ".")
        floors_total_str = self.inputs["floors_total"].text().strip().replace(" ", "")
        price_str = self.inputs["price"].text().strip().replace(" ", "").replace(",", ".")

        if not ad_num:
            QMessageBox.warning(self, "Ошибка", "Поле 'Объявление №' должно быть заполнено!")
            return

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("SELECT id FROM ads WHERE ad_number=?", (ad_num,))
        if cursor.fetchone():
            QMessageBox.critical(self, "Ошибка", f"Ошибка! Запись с таким номером ({ad_num}) уже существует! Исправьте №")
            conn.close()
            return

        try:
            floor_area_val = float(floor_area_str) if floor_area_str else 0.0
            floors_total_val = int(floors_total_str) if floors_total_str else 1
            price_val = float(price_str) if price_str else 0.0
        except ValueError:
            QMessageBox.critical(self, "Ошибка ввода", "Поля 'Этаж/Площадь', 'Этажность' и 'Цена' должны содержать только числовые значения!")
            conn.close()
            return

        try:
            clean_rooms = rooms.replace("-room", "").replace("-комн.", "").strip()

            cursor.execute('''
                INSERT INTO ads (ad_number, category, property_type, rooms, district, landmark, floor, floors_total, price, is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            ''', (ad_num, "Rent", "Apartments", clean_rooms, district, landmark, floor_area_val, floors_total_val, price_val))
            
            conn.commit()
            logging.info(f"Оператор {self.user_info['username']} создал объявление № {ad_num} в разделе [Rent/Apartments/{clean_rooms}-room]")
            QMessageBox.information(self, "Успех", "Данные успешно сохранены в РБД!")
            
            media_folder = os.path.join("Rent", "Apartments", f"{clean_rooms}-room", ad_num)
            os.makedirs(media_folder, exist_ok=True)
            
        except Exception as e:
            QMessageBox.critical(self, "Ошибка БД", f"Не удалось сохранить: {e}")
        finally:
            conn.close()
            
        self.load_table_data()
        for field in self.inputs.values():
            field.clear()
            field.setEnabled(False)

    def upload_media(self):
        rooms_list = ["1-room", "2-room", "3-room", "4-room", "5-room"]
        categories = [("Rent", "Apartments"), ("Rent", "Houses"), ("Sales", "Apartments"), ("Sales", "Houses")]
        
        target_ad = None
        target_checkbox = None
        
        for cat, p_type in categories:
            for r in rooms_list:
                table = getattr(self, f"table_{cat}_{p_type}_{r}", None)
                if table:
                    for row in range(table.rowCount()):
                        chk_widget = table.cellWidget(row, 8)
                        if chk_widget and isinstance(chk_widget, QCheckBox) and chk_widget.isChecked():
                            ad_num_item = table.item(row, 0)
                            if ad_num_item:
                                target_ad = (ad_num_item.text(), cat, p_type, r)
                                target_checkbox = chk_widget
                                break
                    if target_ad:
                        break
            if target_ad:
                break

        if not target_ad:
            QMessageBox.warning(self, "Ошибка", "Вы не выбрали строку. Отметьте галочкой строку, к которой необходимо прикрепить М-Файлы!")
            return

        ad_num, cat, p_type, r = target_ad
        section_path = f"{cat}/{p_type}/{r}"

        files, _ = QFileDialog.getOpenFileNames(
            self, f"Выберите медиафайлы для объявления № {ad_num}", "", 
            "Медиа файлы (*.jpg *.jpeg *.png *.bmp *.mp4 *.avi *.mkv *.mov)"
        )
        if not files:
            return
            
        progress = QProgressBar()
        progress.setWindowTitle("Загрузка медиафайлов")
        progress.setRange(0, len(files))
        progress.show()
        
        saved_files_count = 0
        local_copied_files = [] # Сюда будем собирать пути успешно сохраненных файлов
        
        base_work_dir = r"D:\JOB"
        media_folder = os.path.join(base_work_dir, cat, p_type, r, ad_num)
        os.makedirs(media_folder, exist_ok=True)

        for i, file_path in enumerate(files):
            file_size = os.path.getsize(file_path)
            if file_size > 50 * 1024 * 1024:
                QMessageBox.warning(self, "Предупреждение", f"Файл {os.path.basename(file_path)} превышает 50 МБ и был пропущен.")
                continue
            
            file_name = os.path.basename(file_path)
            dest_path = os.path.join(media_folder, file_name)
            
            with open(file_path, 'rb') as f_src, open(dest_path, 'wb') as f_dst:
                f_dst.write(f_src.read())
                
            local_copied_files.append(dest_path) # Запоминаем путь
            saved_files_count += 1
            progress.setValue(i + 1)
            
        progress.close()

        # =========================================================================
        # СЮДА ВСТАВЛЯЕМ ВАШ БЛОК ОТПРАВКИ НА ВСТРОЕННЫЙ PYTHON FTP-СЕРВЕР:
        # =========================================================================
        try:
            from ftplib import FTP
            ftp = FTP()
            ftp.connect('127.0.0.1', 21)
            ftp.login('operator', 'op123')

            for local_p in local_copied_files:
                f_name = os.path.basename(local_p)
                with open(local_p, 'rb') as f_obj:
                    ftp.storbinary(f"STOR {f_name}", f_obj)
            ftp.quit()
            
            logging.info(f"Оператор {self.user_info['username']} успешно отправил {saved_files_count} файлов на FTP-сервер.")
        except Exception as e:
            logging.error(f"Ошибка отправки файлов на FTP-сервер: {e}")
            QMessageBox.warning(self, "Сеть", f"Файлы сохранены локально, но не удалось отправить на FTP-сервер:\n{e}")
        # =========================================================================

        logging.info(f"Пользователь {self.user_info['username']} загрузил {saved_files_count} медиафайлов для объявления № {ad_num} в раздел [{section_path}]")
        
        if target_checkbox:
            target_checkbox.setChecked(False)
        
        QMessageBox.information(self, "Успех", f"Медиафайлы ({saved_files_count} шт.) успешно отправлены!")
        self.load_table_data()

    def delete_records(self):
        deleted_count = 0
        rooms_list = ["1-room", "2-room", "3-room", "4-room", "5-room"]
        categories = [("Rent", "Apartments"), ("Rent", "Houses"), ("Sales", "Apartments"), ("Sales", "Houses")]
        
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        checked_ads = []

        for cat, p_type in categories:
            for r in rooms_list:
                table = getattr(self, f"table_{cat}_{p_type}_{r}", None)
                if table:
                    for row in range(table.rowCount()):
                        chk_widget = table.cellWidget(row, 8)
                        if chk_widget and isinstance(chk_widget, QCheckBox) and chk_widget.isChecked():
                            ad_num_item = table.item(row, 0)
                            if ad_num_item:
                                checked_ads.append((ad_num_item.text(), cat, p_type, r))

        if not checked_ads:
            QMessageBox.warning(self, "Ошибка", "Вы не выбрали строку. Отметьте галочкой строку, которую необходимо Удалить!")
            conn.close()
            return

        msg = "Желаете ли Вы удалить выбранные записи?" if len(checked_ads) > 1 else "Желаете ли Вы удалить эту запись?"
        reply = QMessageBox.question(
            self, "Удаление", msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            for ad_num, cat, p_type, r in checked_ads:
                cursor.execute("SELECT category, property_type, rooms, district, landmark, area, floor, floors_total, price FROM ads WHERE ad_number=?", (ad_num,))
                rec = cursor.fetchone()
                
                if rec:
                    c_val, pt_val, r_val, dist_v, land_v, area_v, floor_v, f_tot_v, price_v = rec
                    cursor.execute('''
                        INSERT INTO archive_ads (ad_number, category, property_type, rooms, district, landmark, area, floor, floors_total, price, deleted_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (ad_num, c_val, pt_val, r_val, dist_v, land_v, area_v, floor_v, f_tot_v, price_v, now_str))
                
                cursor.execute("UPDATE ads SET is_active=0 WHERE ad_number=?", (ad_num,))
                
                media_dir = os.path.join(cat, p_type, r, ad_num)
                archive_dir = os.path.join("Archive", cat, p_type, r)
                
                if os.path.exists(media_dir) and os.listdir(media_dir):
                    os.makedirs(archive_dir, exist_ok=True)
                    zip_path = os.path.join(archive_dir, f"{ad_num}.zip")
                    
                    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                        for root, dirs, files in os.walk(media_dir):
                            for file in files:
                                file_path = os.path.join(root, file)
                                arcname = os.path.relpath(file_path, media_dir)
                                zipf.write(file_path, arcname)
                    
                    shutil.rmtree(media_dir)
                
                deleted_count += 1
                section_path = f"{cat}/{p_type}/{r}"
                logging.info(f"Пользователь {self.user_info['username']} удалил объявление № {ad_num} из раздела [{section_path}] (перенесено в АБД).")

            conn.commit()
            conn.close()
            
            QMessageBox.information(self, "Успех", f"Запись(и) ({deleted_count} шт.) успешно перенесена в АБД, файлы заархивированы в ZIP.")
            self.load_table_data()
        else:
            conn.close()

    def load_table_data(self):
        """Загрузка данных из БД, вывод миниатюр и счетчика файлов по типам во всех таблицах"""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        rooms_list = ["1-room", "2-room", "3-room", "4-room", "5-room"]
        categories = [("Rent", "Apartments"), ("Rent", "Houses"), ("Sales", "Apartments"), ("Sales", "Houses")]
        
        for cat, p_type in categories:
            for r in rooms_list:
                table = getattr(self, f"table_{cat}_{p_type}_{r}", None)
                if table:
                    room_val = r.replace("-room", "").strip()
                    cursor.execute(
                        "SELECT ad_number, district, landmark, rooms, floor, floors_total, price FROM ads WHERE category=? AND property_type=? AND rooms=? AND is_active=1",
                        (cat, p_type, room_val)
                    )
                    rows = cursor.fetchall()
                    table.setRowCount(len(rows))
                    
                    for row_idx, row_data in enumerate(rows):
                        ad_num = row_data[0]
                        
                        for col_idx, val in enumerate(row_data):
                            table.setItem(row_idx, col_idx, QTableWidgetItem(str(val)))
                        
                        media_cell_widget = QWidget()
                        media_layout = QHBoxLayout(media_cell_widget)
                        media_layout.setContentsMargins(4, 4, 4, 4)
                        media_layout.setSpacing(6)
                        
                        media_dir = os.path.join(cat, p_type, r, str(ad_num))
                        
                        photos_count = 0
                        videos_count = 0
                        other_count = 0
                        image_paths = []
                        
                        if os.path.exists(media_dir):
                            for file_name in os.listdir(media_dir):
                                f_lower = file_name.lower()
                                file_path = os.path.join(media_dir, file_name)
                                
                                if os.path.isfile(file_path):
                                    if f_lower.endswith(('.png', '.jpg', '.jpeg', '.bmp', '.webp')):
                                        photos_count += 1
                                        if len(image_paths) < 3:
                                            image_paths.append(file_path)
                                    elif f_lower.endswith(('.mp4', '.avi', '.mkv', '.mov', '.wmv')):
                                        videos_count += 1
                                    else:
                                        other_count += 1
                        
                        thumbnails_layout = QHBoxLayout()
                        thumbnails_layout.setSpacing(3)
                        
                        if image_paths:
                            for img_path in image_paths:
                                thumb_label = QLabel()
                                thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                                pixmap = QPixmap(img_path)
                                if not pixmap.isNull():
                                    scaled_pixmap = pixmap.scaled(40, 40, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                                    thumb_label.setPixmap(scaled_pixmap)
                                    thumb_label.setToolTip(os.path.basename(img_path))
                                    thumbnails_layout.addWidget(thumb_label)
                        else:
                            no_img_label = QLabel("Нет фото")
                            no_img_label.setStyleSheet("color: gray; font-size: 10px;")
                            thumbnails_layout.addWidget(no_img_label)
                            
                        media_layout.addLayout(thumbnails_layout)
                        
                        info_layout = QVBoxLayout()
                        info_layout.setSpacing(2)
                        
                        total_files = photos_count + videos_count + other_count
                        if total_files > 0:
                            info_text = f"Всего: {total_files}"
                            details = []
                            if photos_count > 0:
                                details.append(f"📸 Фото: {photos_count}")
                            if videos_count > 0:
                                details.append(f"🎬 Видео: {videos_count}")
                            if other_count > 0:
                                details.append(f"📁 Прочее: {other_count}")
                                
                            counter_label = QLabel(info_text)
                            counter_label.setStyleSheet("font-weight: bold; font-size: 11px; color: #0078D7;")
                            info_layout.addWidget(counter_label)
                            
                            details_label = QLabel(" | ".join(details))
                            details_label.setStyleSheet("font-size: 9px; color: #555555;")
                            info_layout.addWidget(details_label)
                        else:
                            empty_label = QLabel("Файлы отсутствуют")
                            empty_label.setStyleSheet("color: #888888; font-size: 10px; font-style: italic;")
                            info_layout.addWidget(empty_label)
                            
                        media_layout.addLayout(info_layout)
                        media_layout.addStretch()
                        
                        table.setCellWidget(row_idx, 7, media_cell_widget)
                        
                        chk = QCheckBox()
                        table.setCellWidget(row_idx, 8, chk)
                        
                        table.setRowHeight(row_idx, 60)
                        
        conn.close()

if __name__ == "__main__":
    init_db()
    app = QApplication(sys.argv)
    
    app_stylesheet = """
    QTabBar::tab {
        background: #e0e0e0;
        color: #333333;
        padding: 8px 16px;
        margin: 2px;
        border-radius: 4px;
    }
    QTabBar::tab:selected {
        background: #0078D7;
        color: #FFFFFF;
        font-weight: bold;
    }
    QTabBar::tab:hover {
        background: #c8c8c8;
    }
    """
    app.setStyleSheet(app_stylesheet)
    
    auth = AuthWindow()
    if auth.exec() == QDialog.DialogCode.Accepted and auth.user_data:
        window = MainWindow(auth.user_data)
        window.show()
        sys.exit(app.exec())