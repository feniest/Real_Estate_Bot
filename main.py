import sys
import os
import shutil
import logging
import zipfile
import configparser
import psycopg2  # Драйвер для работы с PostgreSQL
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

# Если конфига нет — создаем шаблон с секциями для БД и FTP
if not os.path.exists(config_file):
    config['Database'] = {
        'host': '127.0.0.1',
        'port': '5432',
        'dbname': 'estate_db',
        'user': 'postgres',
        'password': 'your_password'
    }
    config['Server'] = {
        'host': '127.0.0.1',
        'port': '21',
        'username': 'operator',
        'password': 'op123',
        'use_sftp': 'False'
    }
    with open(config_file, 'w', encoding='utf-8') as f:
        config.write(f)
else:
    config.read(config_file, encoding='utf-8')

def get_db_connection():
    """Функция создания подключения к удаленной базе данных PostgreSQL"""
    return psycopg2.connect(
        host=config.get('Database', 'host', fallback='127.0.0.1'),
        port=config.getint('Database', 'port', fallback=5432),
        database=config.get('Database', 'dbname', fallback='estate_db'),
        user=config.get('Database', 'user', fallback='postgres'),
        password=config.get('Database', 'password', fallback='')
    )

def init_db():
    """Инициализация таблиц в удаленной базе данных PostgreSQL при первом запуске"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Таблица рабочей базы данных (РБД)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS ads (
                id SERIAL PRIMARY KEY,
                ad_number VARCHAR(50) UNIQUE NOT NULL,
                category VARCHAR(50) NOT NULL,
                property_type VARCHAR(50) NOT NULL,
                rooms VARCHAR(20) NOT NULL,
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
                id SERIAL PRIMARY KEY,
                ad_number VARCHAR(50) UNIQUE NOT NULL,
                category VARCHAR(50) NOT NULL,
                property_type VARCHAR(50) NOT NULL,
                rooms VARCHAR(20) NOT NULL,
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
                id SERIAL PRIMARY KEY,
                username VARCHAR(50) UNIQUE NOT NULL,
                password VARCHAR(100) NOT NULL,
                role VARCHAR(20) NOT NULL
            )
        ''')
        
        # Создаем админа и оператора по умолчанию, если таблица пользователей пуста
        cursor.execute("SELECT COUNT(*) FROM users")
        if cursor.fetchone()[0] == 0:
            cursor.execute("INSERT INTO users (username, password, role) VALUES (%s, %s, %s)", ("admin", "admin123", "admin"))
            cursor.execute("INSERT INTO users (username, password, role) VALUES (%s, %s, %s)", ("operator", "op123", "operator"))
            
        conn.commit()
        cursor.close()
        conn.close()
        logging.info("Подключение и инициализация структуры PostgreSQL выполнены успешно.")
    except Exception as e:
        logging.critical(f"Ошибка подключения к PostgreSQL: {e}")
        print(f"Критическая ошибка подключения к БД: {e}")

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
        
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT role FROM users WHERE username=%s AND password=%s", (username, password))
            res = cursor.fetchone()
            cursor.close()
            conn.close()
            
            if res:
                self.user_data = {"username": username, "role": res[0]}
                self.accept()
            else:
                QMessageBox.warning(self, "Ошибка", "Неверный логин или пароль!")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка сети", f"Не удалось подключиться к базе данных: {e}")

class MainWindow(QMainWindow):
    """Основное окно программы"""
    def __init__(self, user_info):
        super().__init__()
        self.user_info = user_info
        self.setWindowTitle(f"РБД Управление недвижимостью (Cloud) - Пользователь: {user_info['username']} ({user_info['role']})")
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
        
        # Добавляем стили для яркой и четкой подсветки активных вкладок
        self.setStyleSheet("""
            QTabBar::tab:selected {
                background-color: #0078d7;
                color: white;
                font-weight: bold;
                padding: 6px 12px;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
            }
            QTabBar::tab:!selected {
                background-color: #f0f0f0;
                color: #333333;
                padding: 6px 12px;
            }
            QTabWidget::pane {
                border: 1px solid #c8c6c4;
            }
        """)

        central_widget.setLayout(main_layout)
        self.setCentralWidget(central_widget)

    def setup_tools_tab(self, parent_tab):
        layout = QVBoxLayout()
        layout.addWidget(QLabel("<b>Панель расширенного администрирования (РБД / АБД / Логи / Пользователи)</b>"))
        
        btn_logs = QPushButton("Просмотреть системный журнал (actions.log)")
        btn_logs.clicked.connect(self.view_system_logs)
        layout.addWidget(btn_logs)
        
        btn_backup = QPushButton("Создать резервную копию базы данных (Backup PostgreSQL)")
        btn_backup.clicked.connect(self.backup_database)
        layout.addWidget(btn_backup)
        
        btn_clear_db = QPushButton("⚠️ Полная очистка базы данных (Сброс всех объявлений)")
        btn_clear_db.setStyleSheet("background-color: #ffcccc; color: #990000; font-weight: bold;")
        btn_clear_db.clicked.connect(self.clear_entire_database)
        layout.addWidget(btn_clear_db)
        
        btn_restore = QPushButton("Управление архивом (Восстановление записей и медиа из АБД)")
        btn_restore.clicked.connect(self.open_restore_dialog)
        layout.addWidget(btn_restore)
        
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
        
    def clear_entire_database(self):
        """Полная очистка таблиц ads и archive_ads сбросом автоинкремента ID"""
        reply = QMessageBox.question(
            self, 
            "Внимание: Очистка базы", 
            "Вы уверены, что хотите полностью удалить ВСЕ объявления и архивные записи?\nЭто действие необратимо!",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            try:
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute("TRUNCATE TABLE ads, archive_ads RESTART IDENTITY CASCADE;")
                conn.commit()
                cursor.close()
                conn.close()
                
                logging.info(f"Администратор {self.user_info['username']} полностью очистил базу данных (ads и archive_ads).")
                QMessageBox.information(self, "Успех", "База данных успешно очищена от всех записей!")
                self.load_table_data()
            except Exception as e:
                QMessageBox.critical(self, "Ошибка", f"Не удалось очистить базу данных: {e}")

    def view_system_logs(self):
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
        QMessageBox.information(self, "Резервная копия", "Для облачной PostgreSQL бэкапы выполняются на стороне сервера (через pg_dump или панель хостинга).")

    def load_users_table(self):
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT id, username, role FROM users")
            rows = cursor.fetchall()
            cursor.close()
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
        except Exception as e:
            logging.error(f"Ошибка загрузки пользователей: {e}")

    def add_user_dialog(self):
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
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute("SELECT id FROM users WHERE username=%s", (username,))
                if cursor.fetchone():
                    QMessageBox.warning(dlg, "Ошибка", f"Логин '{username}' уже занят!")
                    cursor.close()
                    conn.close()
                    return
                
                cursor.execute("INSERT INTO users (username, password, role) VALUES (%s, %s, %s)", (username, password, role))
                conn.commit()
                cursor.close()
                conn.close()
                
                logging.info(f"Администратор {self.user_info['username']} добавил пользователя {username}.")
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
        target_user = None
        for row in range(self.users_table.rowCount()):
            chk_widget = self.users_table.cellWidget(row, 3)
            if chk_widget and isinstance(chk_widget, QCheckBox) and chk_widget.isChecked():
                user_id = self.users_table.item(row, 0).text()
                username = self.users_table.item(row, 1).text()
                target_user = (user_id, username)
                break
                
        if not target_user:
            QMessageBox.warning(self, "Ошибка", "Выберите пользователя галочкой!")
            return
            
        user_id, username = target_user
        if username == "admin":
            QMessageBox.warning(self, "Ошибка", "Нельзя удалить главного администратора!")
            return
            
        reply = QMessageBox.question(self, "Удаление", f"Удалить пользователя '{username}'?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            try:
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute("DELETE FROM users WHERE id=%s", (user_id,))
                conn.commit()
                cursor.close()
                conn.close()
                
                logging.info(f"Администратор {self.user_info['username']} удалил пользователя {username}.")
                self.load_users_table()
            except Exception as e:
                QMessageBox.critical(self, "Ошибка", f"Не удалось удалить: {e}")

    def open_restore_dialog(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Восстановление записей из АБД")
        dlg.resize(900, 450)
        dlg_layout = QVBoxLayout()
        dlg_layout.addWidget(QLabel("<b>Архивные записи в PostgreSQL (АБД):</b>"))
        
        table = QTableWidget()
        table.setColumnCount(8)
        table.setHorizontalHeaderLabels(["Объявление №", "Категория", "Тип", "Комн.", "Район", "Цена", "Дата удаления", "Выбор"])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT ad_number, category, property_type, rooms, district, price, deleted_at FROM archive_ads")
            rows = cursor.fetchall()
            cursor.close()
            conn.close()
        except Exception:
            rows = []
            
        table.setRowCount(len(rows))
        for row_idx, row_data in enumerate(rows):
            for col_idx, val in enumerate(row_data):
                table.setItem(row_idx, col_idx, QTableWidgetItem(str(val)))
            table.setCellWidget(row_idx, 7, QCheckBox())
            
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
                QMessageBox.warning(dlg, "Ошибка", "Отметьте галочкой запись!")
                return
                
            try:
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute("SELECT category, property_type, rooms, district, landmark, area, floor, floors_total, price FROM archive_ads WHERE ad_number=%s", (selected_ad,))
                rec = cursor.fetchone()
                
                if rec:
                    cat, p_type, r_val, dist, land, area_v, floor_v, f_tot, price_v = rec
                    cursor.execute("SELECT id FROM ads WHERE ad_number=%s", (selected_ad,))
                    if cursor.fetchone():
                        cursor.execute('''
                            UPDATE ads 
                            SET category=%s, property_type=%s, rooms=%s, district=%s, landmark=%s, area=%s, floor=%s, floors_total=%s, price=%s, is_active=1
                            WHERE ad_number=%s
                        ''', (cat, p_type, r_val, dist, land, area_v, floor_v, f_tot, price_v, selected_ad))
                    else:
                        cursor.execute('''
                            INSERT INTO ads (ad_number, category, property_type, rooms, district, landmark, area, floor, floors_total, price, is_active)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1)
                        ''', (selected_ad, cat, p_type, r_val, dist, land, area_v, floor_v, f_tot, price_v))
                    
                    cursor.execute("DELETE FROM archive_ads WHERE ad_number=%s", (selected_ad,))
                    conn.commit()
                    cursor.close()
                    conn.close()
                    
                    QMessageBox.information(dlg, "Успех", f"Запись № {selected_ad} восстановлена!")
                    dlg.accept()
                    self.load_table_data()
            except Exception as e:
                QMessageBox.critical(dlg, "Ошибка", f"Не удалось восстановить: {e}")

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
            table.setColumnWidth(3, 50)
            table.setColumnWidth(4, 70)
            table.setColumnWidth(5, 75)
            table.setColumnWidth(8, 60)
            table.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeMode.Stretch)
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
        QMessageBox.information(self, "Редактирование", "Ячейки разблокированы.")

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

        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM ads WHERE ad_number=%s", (ad_num,))
            if cursor.fetchone():
                QMessageBox.critical(self, "Ошибка", f"Запись с номером ({ad_num}) уже существует!")
                cursor.close()
                conn.close()
                return

            floor_area_val = float(floor_area_str) if floor_area_str else 0.0
            floors_total_val = int(floors_total_str) if floors_total_str else 1
            price_val = float(price_str) if price_str else 0.0

            clean_rooms = rooms.replace("-room", "").replace("-комн.", "").strip()

            cursor.execute('''
                INSERT INTO ads (ad_number, category, property_type, rooms, district, landmark, floor, floors_total, price, is_active)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 1)
            ''', (ad_num, "Rent", "Apartments", clean_rooms, district, landmark, floor_area_val, floors_total_val, price_val))
            
            conn.commit()
            cursor.close()
            conn.close()
            
            logging.info(f"Оператор {self.user_info['username']} создал объявление № {ad_num}")
            QMessageBox.information(self, "Успех", "Данные успешно сохранены в облачную БД!")
            
            media_folder = os.path.join("Rent", "Apartments", f"{clean_rooms}-room", ad_num)
            os.makedirs(media_folder, exist_ok=True)
            
        except Exception as e:
            QMessageBox.critical(self, "Ошибка БД", f"Не удалось сохранить: {e}")
            
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
            QMessageBox.warning(self, "Ошибка", "Отметьте галочкой строку для прикрепления файлов!")
            return

        ad_num, cat, p_type, r = target_ad

        files, _ = QFileDialog.getOpenFileNames(self, f"Медиафайлы для № {ad_num}", "", "Медиа файлы (*.jpg *.png *.jpeg)")
        if not files:
            return
            
        progress = QProgressBar()
        progress.setWindowTitle("Загрузка медиафайлов в облако")
        progress.setRange(0, len(files))
        progress.show()
        
        saved_files_count = 0

        # Структурированная отправка на FTP-сервер из памяти
        try:
            from ftplib import FTP
            ftp = FTP()
            ftp.connect(config.get('Server', 'host'), config.getint('Server', 'port', fallback=21))
            ftp.login(config.get('Server', 'username'), config.get('Server', 'password'))

            def ftp_mkdir_p(ftp_client, remote_path):
                dirs = remote_path.strip("/").split("/")
                current = ""
                for d in dirs:
                    if d:
                        current += f"/{d}"
                        try:
                            ftp_client.cwd(current)
                        except Exception:
                            ftp_client.mkd(current)
                            ftp_client.cwd(current)

            remote_path = f"{cat}/{p_type}/{r}/{ad_num}"
            ftp_mkdir_p(ftp, remote_path)
            ftp.cwd(f"/{remote_path}")

            for i, file_path in enumerate(files):
                file_name = os.path.basename(file_path)
                with open(file_path, 'rb') as f_obj:
                    ftp.storbinary(f"STOR {file_name}", f_obj)
                saved_files_count += 1
                progress.setValue(i + 1)
                    
            ftp.quit()
            logging.info(f"Оператор {self.user_info['username']} отправил {saved_files_count} файлов на FTP в папку '{remote_path}'.")
        except Exception as e:
            logging.warning(f"Ошибка отправки на FTP: {e}")

        progress.close()
        if target_checkbox:
            target_checkbox.setChecked(False)
        
        QMessageBox.information(self, "Успех", f"Медиафайлы ({saved_files_count} шт.) успешно загружены в облачное хранилище!")
        self.load_table_data()

    def delete_records(self):
        rooms_list = ["1-room", "2-room", "3-room", "4-room", "5-room"]
        categories = [("Rent", "Apartments"), ("Rent", "Houses"), ("Sales", "Apartments"), ("Sales", "Houses")]
        
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
            QMessageBox.warning(self, "Ошибка", "Отметьте галочкой записи для удаления!")
            return

        reply = QMessageBox.question(self, "Удаление", "Удалить выбранные записи?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            try:
                conn = get_db_connection()
                cursor = conn.cursor()
                now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                for ad_num, cat, p_type, r in checked_ads:
                    cursor.execute("SELECT category, property_type, rooms, district, landmark, area, floor, floors_total, price FROM ads WHERE ad_number=%s", (ad_num,))
                    rec = cursor.fetchone()
                    
                    if rec:
                        c_val, pt_val, r_val, dist_v, land_v, area_v, floor_v, f_tot_v, price_v = rec
                        cursor.execute('''
                            INSERT INTO archive_ads (ad_number, category, property_type, rooms, district, landmark, area, floor, floors_total, price, deleted_at)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ''', (ad_num, c_val, pt_val, r_val, dist_v, land_v, area_v, floor_v, f_tot_v, price_v, now_str))
                    
                    cursor.execute("UPDATE ads SET is_active=0 WHERE ad_number=%s", (ad_num,))
                
                conn.commit()
                cursor.close()
                conn.close()
                QMessageBox.information(self, "Успех", "Записи перемещены в архив!")
                self.load_table_data()
            except Exception as e:
                QMessageBox.critical(self, "Ошибка", f"Не удалось удалить: {e}")

    def load_table_data(self):
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            rooms_list = ["1-room", "2-room", "3-room", "4-room", "5-room"]
            categories = [("Rent", "Apartments"), ("Rent", "Houses"), ("Sales", "Apartments"), ("Sales", "Houses")]
            
            # Подключаемся к FTP для проверки и скачивания превьюшек
            ftp = None
            try:
                from ftplib import FTP
                ftp = FTP()
                ftp.connect(config.get('Server', 'host'), config.getint('Server', 'port', fallback=21))
                ftp.login(config.get('Server', 'username'), config.get('Server', 'password'))
            except Exception as ftp_err:
                logging.warning(f"Не удалось подключиться к FTP при загрузке таблиц: {ftp_err}")

            for cat, p_type in categories:
                for r in rooms_list:
                    table = getattr(self, f"table_{cat}_{p_type}_{r}", None)
                    if table:
                        room_val = r.replace("-room", "").strip()
                        cursor.execute(
                            "SELECT ad_number, district, landmark, rooms, floor, floors_total, price FROM ads WHERE category=%s AND property_type=%s AND rooms=%s AND is_active=1",
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
                            
                            photos_count = 0
                            thumbnail_pixmap = None
                            
                            if ftp:
                                remote_path = f"{cat}/{p_type}/{r}/{ad_num}"
                                try:
                                    ftp.cwd(f"/{remote_path}")
                                    file_list = ftp.nlst()
                                    image_files = []
                                    
                                    for file_name in file_list:
                                        if file_name.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp')):
                                            photos_count += 1
                                            image_files.append(file_name)
                                        elif file_name.lower().endswith(('.mp4', '.avi')):
                                            photos_count += 1
                                            
                                    # Если есть картинки, скачиваем первую попавшуюся во временную память для превью
                                    if image_files:
                                        first_img = image_files[0]
                                        from io import BytesIO
                                        img_io = BytesIO()
                                        ftp.retrbinary(f"RETR {first_img}", img_io.write)
                                        img_io.seek(0)
                                        
                                        # Превращаем в QPixmap и сжимаем в миниатюру прямо в PyQt
                                        pixmap = QPixmap()
                                        pixmap.loadFromData(img_io.read())
                                        if not pixmap.isNull():
                                            thumbnail_pixmap = pixmap.scaled(45, 45, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)

                                    ftp.cwd("/")
                                except Exception:
                                    try:
                                        ftp.cwd("/")
                                    except:
                                        pass
                            
                            # Визуальное оформление ячейки медиа: Иконка + Текст
                            if thumbnail_pixmap:
                                img_label = QLabel()
                                img_label.setPixmap(thumbnail_pixmap)
                                media_layout.addWidget(img_label)
                                
                            text_lbl = QLabel(f"Фото: {photos_count}" if photos_count > 0 else "Нет фото")
                            media_layout.addWidget(text_lbl)
                            
                            table.setCellWidget(row_idx, 7, media_cell_widget)
                            table.setCellWidget(row_idx, 8, QCheckBox())
                            table.setRowHeight(row_idx, 60)
            
            if ftp:
                try:
                    ftp.quit()
                except:
                    pass

            cursor.close()
            conn.close()
        except Exception as e:
            logging.error(f"Ошибка загрузки таблиц из PostgreSQL: {e}")
if __name__ == "__main__":
    init_db()  # Инициализация таблиц в облаке при первом запуске
    app = QApplication(sys.argv)
    
    auth = AuthWindow()
    if auth.exec() == QDialog.DialogCode.Accepted and auth.user_data:
        window = MainWindow(auth.user_data)
        window.show()
        sys.exit(app.exec())