import os
from pyftpdlib.authorizers import DummyAuthorizer
from pyftpdlib.handlers import FTPHandler
from pyftpdlib.servers import FTPServer

def run_ftp_server():
    # Убедимся, что папка D:\TestFTP существует
    base_dir = r"D:\TestFTP"
    os.makedirs(base_dir, exist_ok=True)

    authorizer = DummyAuthorizer()
    
    # Создаем пользователя для тестов: логин 'operator', пароль 'op123'
    # Права: 'elradfmw' означают полный доступ (чтение, запись, удаление, создание папок и т.д.)
    authorizer.add_user("operator", "op123", base_dir, perm="elradfmw")

    handler = FTPHandler
    handler.authorizer = authorizer

    # Запускаем сервер на локальном хосте и порту 21
    server = FTPServer(("127.0.0.1", 21), handler)
    print(f"[*] Встроенный FTP-сервер запущен на 127.0.0.1:21")
    print(f"[*] Корневая папка сервера: {base_dir}")
    
    server.serve_forever()

if __name__ == "__main__":
    run_ftp_server()