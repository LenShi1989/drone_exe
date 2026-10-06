# 部署說明 — 無人機操作系統 (exe 版)

打包產出 `dist\DroneSystem\`:

| 檔案 | 說明 |
|---|---|
| `DroneServer.exe` | 後端 API + 模擬器 + WebSocket (主控台視窗,關閉即停止服務) |
| `DroneClient.exe` | 桌面操作介面 |
| `server.ini` | 後端設定 (資料庫、埠號、JWT、模擬器) |
| `client.ini` | 前端設定 (後端位址、地圖圖磚) |
| `init_postgreSQL.sql` | 建表 SQL (選用,後端啟動時也會自動建表) |

兩個 exe 都是單一檔案,可放在同一台或不同電腦;設定檔需與 exe 放在同一資料夾。

## 1. 資料庫 (PostgreSQL 14 以上)

```sql
-- 以 postgres 超級使用者執行一次
CREATE ROLE drone LOGIN PASSWORD 'drone_pass';
CREATE DATABASE drone_system OWNER drone;
```

`DroneServer.exe` 第一次啟動時會建立資料表並寫入示範資料;只在資料表為空時寫入,重複啟動不會重複灌入。
若想先手動建表:`psql -U drone -d drone_system -f init_postgreSQL.sql`。

也可以直接指向原 `drone_system` (ASP.NET 版) 的資料庫,結構相同,既有資料與帳號沿用。

## 2. 後端

編輯 `server.ini`,執行 `DroneServer.exe`。

```
DroneServer.exe              啟動服務 (預設 http://0.0.0.0:5080)
DroneServer.exe --port 6000  改埠號
DroneServer.exe --init-db    只建表 + 種子資料後結束
DroneServer.exe --sql        輸出建表 SQL
```

- 健康檢查:http://localhost:5080/health  · API 文件:http://localhost:5080/docs
- 其他電腦要連線時,Windows 防火牆需開放該埠 (TCP 5080)。
- 設定也可用環境變數覆蓋,例:`set DRONE_DATABASE__PASSWORD=xxx`。
- 想做成 Windows 服務可搭配 [NSSM](https://nssm.cc/):`nssm install DroneServer C:\DroneSystem\DroneServer.exe`。

## 3. 前端

編輯 `client.ini` 的 `[server] url` (例:`http://192.168.1.10:5080`),執行 `DroneClient.exe`。

- 地圖圖磚快取與記住的帳號存在 `%LOCALAPPDATA%\DroneOps\`。
- 沒有網路時 `[map] online = false`,地圖改為網格底圖,點位 / 航線 / 航跡照常顯示。
- 攝影機以內建 OpenCV 直接播放 `rtsp://` / `http://` 串流 (MJPEG 等)。
- 部署後檢查:`DroneClient.exe --selftest`,結果寫到同資料夾 `selftest.txt` (應為 `RESULT: PASS`)。

## 4. 重新打包

```powershell
powershell -ExecutionPolicy Bypass -File deploy\build.ps1 [-Clean] [-Python C:\Python310\python.exe]
```

需要 Python 3.10+;腳本會安裝 `requirements.txt` 與 PyInstaller,再依 `DroneServer.spec` / `DroneClient.spec` 建置。

## 疑難排解

| 狀況 | 處理 |
|---|---|
| 後端啟動即結束,訊息「資料庫初始化失敗」 | PostgreSQL 未啟動或 `server.ini` 帳密錯誤 |
| 前端登入顯示「無法連線到伺服器」 | `client.ini` 的 url 錯誤、後端未啟動或防火牆阻擋 |
| 側邊欄顯示「遙測未連線」 | WebSocket 被代理 / 防火牆擋住;畫面仍會以 REST 顯示最後快照 |
| 地圖只有網格 | 無法連線圖磚伺服器,檢查網路或改用內網圖磚 (`tile_url`) |
| 顯示比例過大 / 過小 | 依 Windows 顯示縮放自動調整;可設環境變數 `QT_SCALE_FACTOR=0.9` 微調 |
