"""
後端啟動入口 (開發:python run_server.py;打包後即 DroneServer.exe)。

  DroneServer.exe              啟動 API 服務 (預設 http://0.0.0.0:5080)
  DroneServer.exe --init-db    只建表 + 灌種子資料後結束
  DroneServer.exe --sql        輸出建表 SQL (db/init_postgreSQL.sql 即由此產生)
"""
from __future__ import annotations

import argparse
import logging
import re
import sys


class _RedactTokenFilter(logging.Filter):
    """uvicorn 會把 WebSocket 完整網址寫進日誌,把 query 中的 JWT 遮掉避免外流。"""

    _pattern = re.compile(r"(access_token=)[^\s&\"']+")

    def filter(self, record: logging.LogRecord) -> bool:
        if record.args:
            record.args = tuple(self._pattern.sub(r"\1***", a) if isinstance(a, str) else a for a in record.args)
        if isinstance(record.msg, str):
            record.msg = self._pattern.sub(r"\1***", record.msg)
        return True


def _setup_logging(level: str) -> None:
    logging.basicConfig(level=level.upper(), format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                        datefmt="%H:%M:%S", stream=sys.stdout)
    for handler in logging.getLogger().handlers:
        handler.addFilter(_RedactTokenFilter())


def dump_sql() -> None:
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.schema import CreateIndex, CreateTable

    from server.models import Base

    sys.stdout.reconfigure(encoding="utf-8")  # 重導到檔案時固定 UTF-8,不受主控台字碼頁影響
    dialect = postgresql.dialect()
    print("-- 由 `DroneServer.exe --sql` (或 python run_server.py --sql) 依 ORM 定義產生,請勿手改。")
    print("-- 與原 EF Core 版結構相同;後端啟動時也會自動建立缺少的資料表。\n")
    print("BEGIN;\n")
    for table in Base.metadata.sorted_tables:
        ddl = str(CreateTable(table, if_not_exists=True).compile(dialect=dialect)).strip()
        print(ddl + ";\n")
        for index in sorted(table.indexes, key=lambda i: i.name):
            print(str(CreateIndex(index, if_not_exists=True).compile(dialect=dialect)).strip() + ";")
        print()
    print("COMMIT;")


def main() -> None:
    parser = argparse.ArgumentParser(description="無人機操作系統 API 服務")
    parser.add_argument("--init-db", action="store_true", help="建立資料表並寫入種子資料後結束")
    parser.add_argument("--sql", action="store_true", help="輸出建表 SQL 後結束")
    parser.add_argument("--host", help="覆蓋 server.ini 的 [server] host")
    parser.add_argument("--port", type=int, help="覆蓋 server.ini 的 [server] port")
    args = parser.parse_args()

    if args.sql:
        dump_sql()
        return

    from server.config import settings

    _setup_logging(settings.server.log_level)
    log = logging.getLogger("drone")
    log.info("設定來源:%s", settings.source)
    log.info("資料庫:%s@%s:%s/%s", settings.database.user, settings.database.host, settings.database.port,
             settings.database.name)

    if args.init_db:
        from server.app import init_database
        init_database()
        log.info("資料庫初始化完成")
        return

    import uvicorn

    from server.app import app

    uvicorn.run(app, host=args.host or settings.server.host, port=args.port or settings.server.port,
                log_level=settings.server.log_level.lower(), log_config=None, ws="websockets")


if __name__ == "__main__":
    main()
