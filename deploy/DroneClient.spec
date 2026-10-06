# PyInstaller spec — 前端 (PyQt5),視窗程式,單一 exe。
# 建置:pyinstaller deploy/DroneClient.spec --distpath dist --workpath build
from PyInstaller.utils.hooks import collect_submodules

ROOT = SPECPATH + "/.."

a = Analysis(
    [ROOT + "/run_client.py"],
    pathex=[ROOT],
    hiddenimports=collect_submodules("client") + ["PyQt5.QtWebSockets", "matplotlib.backends.backend_qt5agg"],
    # 不需要的大型套件排除掉以縮小體積
    excludes=["fastapi", "uvicorn", "starlette", "sqlalchemy", "psycopg2", "server", "tkinter", "IPython",
              "pytest", "PyQt5.QtWebEngineWidgets", "PyQt5.QtWebEngineCore", "PyQt5.QtQml", "PyQt5.QtQuick",
              "PyQt5.Qt3DCore", "PyQt5.QtMultimedia", "PyQt5.QtBluetooth", "PyQt5.QtSql", "PyQt5.QtTest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    name="DroneClient",
    console=False,
    upx=False,
    icon=ROOT + "/deploy/assets/drone.ico",
)
