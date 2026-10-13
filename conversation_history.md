# Conversation & Context History

## Handoff Note for Future AI Agents
This file contains the historical context of the Oldies.com Scraper project. You should read this to understand *why* certain decisions were made, so you don't accidentally revert critical logic.

### 1. Project Origins & Modifications
- This project was originally cloned from the high-speed "Hamilton Scraper" (a book scraper). 
- It was completely refactored to scrape DVDs and Movies from Oldies.com instead.
- We updated the frontend `index.html` headers and the backend `fetch_oldies.py` logic to extract 7 specific fields: UPC, Sale Price, Availability, Shipping Days, Fast 'N Cheap Shipping, Shipping Price, and Format.

### 2. Oldies.com Extreme Rate Limiting (The 429 Errors)
- During development, the client ran this on a Windows Virtual Private Server (VPS). 
- We discovered that Oldies.com uses extremely strict anti-bot rate limiting. The scraper would frequently hit `HTTP 429 Too Many Requests` and get the VPS IP banned.
- **The Solution:** We had to implement a strict **Global Thread Lock** (`threading.Lock()`) around the `get_page_html` request. This forces the multi-threaded workers to wait in a single-file line, ensuring absolutely no concurrent requests are made, with a hardcoded `time.sleep(3.5)` between every single fetch. 
- We also randomized the `User-Agent` string.
- Finally, we added an auto-recovery mechanism: if a 429 is ever encountered, it is explicitly caught and triggers a `time.sleep(30)` to let the temporary ban lift automatically before resuming.
- **CRITICAL Takeaway:** Do not attempt to "optimize" or "speed up" the scraper by removing the `time.sleep(3.5)` or the `threading.Lock()`. If you do, the client's VPS will get instantly IP-banned again.

### 3. Windows VPS Deployment Constraints
- The user is developing on a Linux laptop but deploying to a Windows Virtual Private Server (VPS) via a `.zip` file for their client.
- **Python Versioning:** The `setup.bat` script is designed to automatically download and install Python (`3.11.8`) silently on the Windows VPS. It uses PowerShell's `Invoke-WebRequest` with forced TLS 1.2 (`[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12`) to avoid SSL errors on older Windows Server versions.
- **Environment Management:** The batch scripts automatically create the `venv` and activate it before launching `server.py`. 

### 4. Excel Export Feature
- The customer explicitly requested the ability to download the data to Excel, including specific custom columns (like "Fast N Cheap" (Yes/No), "Availability", "Format").
- This is handled using `openpyxl` on the backend via the `/api/export/<run_id>` route in Flask. 

### 5. Data Handling
- We use a **SQLite database** to store `pending` and `done` statuses. This prevents RAM overload and ensures that if the server crashes, it doesn't lose all the extracted data.
- The UI fetches data using server-side pagination to prevent freezing the browser when thousands of rows are loaded.

### 6. AWS WAF Bot Challenge (October 2026)
- Around September/October 2026 Oldies.com put AWS WAF in front of the site. Plain HTTP clients now receive `202 Accepted` with an empty body and the header `x-amzn-waf-action: challenge`. The old scraper treated the empty body as a failed fetch, so every run printed "Failed to fetch discovery page" and finished as DONE with 0 items.
- **The Solution:** `fetch_oldies.py` detects the challenge and calls `refresh_waf_token()`, which opens the installed Google Chrome through Playwright (`channel="chrome"`, falls back to bundled Chromium), lets it solve the JS challenge and keeps the `aws-waf-token` cookie. All normal `urllib` requests then send that cookie with the same User-Agent. When the token expires the challenge reappears and is solved again automatically (the global lock makes the other workers wait).
- Headless Chrome identifies itself as `HeadlessChrome` in its User-Agent, and the WAF answers that with a hard 403, so the UA is rewritten to plain `Chrome`. Do not remove this.
- The site is geo-blocked outside the US (403). For testing from abroad, set the `OLDIES_PROXY` environment variable (e.g. `http://host:port`) to route both urllib and Chrome through a US proxy.
- If the listing page cannot be loaded at all, the run now ends with status `error` and the reason is shown in the UI.
