# PyInstaller spec — 後端 (FastAPI + 模擬器),主控台程式,單一 exe。
# 建置:pyinstaller deploy/DroneServer.spec --distpath dist --workpath build
from PyInstaller.utils.hooks import collect_submodules

ROOT = SPECPATH + "/.."

hidden = (
    collect_submodules("uvicorn")
    + collect_submodules("websockets")
    + collect_submodules("server")
    + ["sqlalchemy.dialects.postgresql", "psycopg2", "psycopg2.extras", "jwt"]
)

a = Analysis(
    [ROOT + "/run_server.py"],
    pathex=[ROOT],
    hiddenimports=hidden,
    excludes=["PyQt5", "matplotlib", "cv2", "numpy", "tkinter", "client", "IPython", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    name="DroneServer",
    console=True,
    upx=False,
    icon=ROOT + "/deploy/assets/drone.ico",
)
