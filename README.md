# drone_exe — 無人機操作系統 (桌面版)

由 [`drone_system`](../drone_system) (Vue 3 + ASP.NET Core) 改寫:

| 層 | 原版 | 本版 |
|---|---|---|
| 前端 | Vue 3 + TypeScript (瀏覽器) | **Python PyQt5** 桌面程式 → `DroneClient.exe` |
| 後端 | ASP.NET Core 10 + EF Core | **FastAPI** + SQLAlchemy 2 → `DroneServer.exe` |
| 即時推播 | SignalR | WebSocket (`/ws/telemetry`) |
| 資料庫 | PostgreSQL | **PostgreSQL** (表結構與原版完全相同,可共用同一個資料庫) |
| 地圖 | Google Maps / OSM | 原生 Qt 地圖元件 + OSM 圖磚 (深色濾鏡、磁碟快取、離線網格底圖) |
| 圖表 | ECharts | matplotlib (嵌入 Qt,滑鼠移上顯示數值) |
| 攝影機 | Python OpenCV 串流閘道 + `<img>` | 用戶端直接以 OpenCV 拉 RTSP / HTTP 串流,不需另架閘道 |

功能與原版一一對應:即時監控、地圖編輯 / 歷史地圖、無人機設定 / 狀態、攝影機管理、
當前 / 歷史工單 / 工單模板、四種統計圖表、任務 / 登入紀錄、通知中心、帳號 / 角色管理 (側邊欄依角色權限開放)。
內建無人機模擬器 (飛行、耗電、低電量返航、充電、自動派工、巡航)。

---

## 快速開始 (使用打包好的 exe)

1. 準備 PostgreSQL,建立帳號與資料庫 (只需做一次):
   ```sql
   CREATE ROLE drone LOGIN PASSWORD 'drone_pass';
   CREATE DATABASE drone_system OWNER drone;
   ```
2. 編輯 `server.ini` 的 `[database]`,執行 **`DroneServer.exe`**
   — 第一次啟動會自動建表並寫入示範資料 (帳號、6 台無人機、航線、40+ 張工單…)。
3. 編輯 `client.ini` 的 `[server] url` 指向後端,執行 **`DroneClient.exe`**。

| 帳號 | 密碼 | 角色 |
|---|---|---|
| `admin` | `Admin@123` | 系統管理員 (全部權限) |
| `operator` | `Operator@123` | 操作員 |
| `viewer` | `Viewer@123` | 檢視者 (唯讀) |

部署細節見 [deploy/README.md](deploy/README.md)。

---

## 開發

```bash
pip install -r requirements.txt

# 後端 (預設讀 server.ini,沒有則用預設值 localhost:5432 drone/drone_pass)
python run_server.py              # http://localhost:5080 ,Swagger: /docs
python run_server.py --init-db    # 只建表 + 種子資料
python run_server.py --sql        # 輸出建表 SQL

# 前端
python run_client.py              # 讀 client.ini,或設定環境變數 DRONE_SERVER_URL
```

### 測試

```bash
python tests/api_smoke_test.py http://localhost:5080     # 76 項 API / 權限 / 狀態機檢查
python tests/gui_tour.py --server http://localhost:5080 --out screenshots --park   # 逐頁截圖
python tests/gui_dialogs.py --server http://localhost:5080 --out screenshots        # 對話框截圖
```

### 打包

```powershell
powershell -ExecutionPolicy Bypass -File deploy\build.ps1    # 產出 dist\DroneSystem\
```

---

## 專案結構

```
drone_exe/
├─ run_server.py          後端入口 (DroneServer.exe)
├─ run_client.py          前端入口 (DroneClient.exe)
├─ server/                FastAPI 後端
│  ├─ app.py              應用程式、錯誤格式、WebSocket
│  ├─ config.py           server.ini / 環境變數設定
│  ├─ models.py           SQLAlchemy ORM (與原 EF Core 表結構相同)
│  ├─ schemas.py          請求 / 回應模型 (JSON camelCase,與原 API 契約相同)
│  ├─ routers/            auth / drones / cameras / map / workorders / statistics / logs / system
│  ├─ simulator.py        無人機模擬器 (背景執行緒)
│  ├─ seeder.py           種子資料
│  └─ security.py         PBKDF2 (與原版相容) + JWT
├─ client/                PyQt5 前端
│  ├─ api.py              REST 用戶端 (自動 refresh token)
│  ├─ realtime.py         WebSocket 即時遙測 (自動重連)
│  ├─ theme.py            深色科技風 QSS
│  ├─ widgets/            地圖、圖表、攝影機、表格 / 對話框等共用元件
│  └─ views/              登入、主視窗與 18 個功能頁
├─ db/init_postgreSQL.sql 建表 SQL (由 ORM 產生)
├─ deploy/                PyInstaller spec、建置腳本、設定檔範本、部署說明
└─ tests/                 API 冒煙測試、GUI 截圖巡覽
```

## 與原版的相容性

- 表名、欄位、型別、索引名稱與原 EF Core 版相同,**可直接指向原本的 `drone_system` 資料庫**;
  密碼雜湊格式 (`PBKDF2$100000$salt$hash`) 也相同,既有帳號可直接登入。
- REST API 路徑與 JSON 欄位維持原契約 (camelCase、`{items,total,page,pageSize}` 分頁、`{message}` 錯誤)。
- 即時推播由 SignalR 改為原生 WebSocket:`ws://<host>:5080/ws/telemetry?access_token=<JWT>`,
  訊息格式 `{"type": "TelemetryUpdate" | "WorkOrderChanged" | "NotificationReceived", "data": ...}`。

## 正式部署前必改

1. `server.ini` 的 `[jwt] secret_key` 改成 ≥32 字元隨機字串。
2. 資料庫密碼改用環境變數 `DRONE_DATABASE__PASSWORD`。
3. 預設帳號密碼全部重設。
4. OSM 公用圖磚有[使用條款](https://operations.osmfoundation.org/policies/tiles/),正式上線建議改用自架或商用圖磚 (`client.ini` 的 `tile_url`)。
