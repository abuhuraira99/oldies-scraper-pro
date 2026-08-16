# Oldies.com Scraper - Project Architecture & Explanation

## Overview
This is a high-performance, locally-hosted web application designed to scrape movie/DVD data from `oldies.com`. 
The system is built using a Python Flask backend and a vanilla HTML/JS frontend. It handles thousands of products by utilizing a multi-threaded background queue and a local SQLite database to persist state and prevent memory leaks.

## Tech Stack
- **Backend:** Python 3, Flask, SQLite3, BeautifulSoup4, threading, queue
- **Frontend:** HTML, CSS (Google Fonts, custom styling), JavaScript (DataTables.js, jQuery, DataTables export buttons)
- **Deployment:** Windows Batch files (`setup.bat` and `run.bat`) that automatically provision a virtual environment, install dependencies, and launch the server.

## Core Architecture
The backend is split into three main files:
1. **`server.py`**: The Flask web server. It handles API requests, serves the UI, initializes the SQLite database, and manages the background pipeline.
2. **`fetch_oldies.py`**: The core scraping logic. It contains functions to discover product links and extract 7 specific details (UPC, Sale Price, Availability, Shipping Days, Fast 'N Cheap Shipping, Shipping Price, Format) from individual product pages. It also contains the background worker thread logic.
3. **`index.html`**: The frontend UI that polls the backend via AJAX to display real-time progress and a data table.

## Execution Pipeline
When a user submits a URL via the UI, the backend executes a two-phase pipeline:
1. **Phase 1: Discovery (Sequential)**
   - The server navigates through pagination of the provided category URL.
   - It extracts all individual product links and inserts them into the `products` SQLite table with a status of `pending`.
2. **Phase 2: Extraction (Multi-threaded)**
   - Once all links are discovered, a Thread Pool (controlled by `WORKER_THREADS`) is spawned.
   - Workers pull `pending` product links from a thread-safe `Queue`.
   - Each worker fetches the product page, extracts the required data, and updates the SQLite database row for that product to `done`.
   - If an error occurs (e.g. rate limit or bad HTML), the row is marked as `error`.

## Key Design Decisions & Logic Rules for Future AI Agents
- **Local Database (SQLite):** Do not store scraped data in memory (e.g., Python lists or dictionaries). We use SQLite (`db.sqlite`) to prevent RAM bloat and allow users to pause/resume runs. 
- **Thread Safety:** The workers write to the SQLite DB. SQLite handles concurrent writes relatively well, but ensure database connections are opened *inside* the worker thread (`sqlite3.connect`), not shared across threads.
- **EXTREME Rate Limiting (CRITICAL):** Oldies.com has extremely strict anti-bot protections. A `threading.Lock()` is implemented around the HTTP request function in `fetch_oldies.py` to enforce an *absolute global rate limit* of 1 request every 3.5 seconds across all threads. It also randomizes the `User-Agent`. If you attempt to speed this up, the host IP will be instantly banned (HTTP 429).
- **UI Polling:** The UI updates by calling `/api/progress/<run_id>` and `/api/rows/<run_id>` every 2 seconds. The table uses DataTables.js server-side pagination to handle tens of thousands of rows without crashing the browser.

## Modifying the Scraper
If you are asked to add a new column to scrape:
1. Update `index.html` to add the column header (`<th>`) and adjust the DataTables `columns` array.
2. Update the SQLite `CREATE TABLE` schema in `server.py` to include the new column.
3. Update the `extract_product_details` function in `fetch_oldies.py` to scrape the new data point.
4. Update the SQLite `UPDATE` query inside `worker_process` in `fetch_oldies.py` to save the new data.
5. Update the export endpoints (`/api/export/<run_id>`) in `server.py` to include the new column in the Excel file.
