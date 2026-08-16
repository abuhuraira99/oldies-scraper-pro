# Oldies Scraper Pro (Movies & DVDs)

A high-performance, locally-hosted web application designed to scrape detailed Movie and DVD data from Oldies.com. Built as a successor to the Hamilton Scraper, this project utilizes advanced rate-limiting logic to bypass strict anti-bot systems while extracting huge volumes of e-commerce data.

## Features
- **Anti-Bot Protection:** Implements a strict Global Thread Lock and randomized User-Agents to prevent IP bans (HTTP 429 Errors) common on strictly protected e-commerce sites.
- **State Persistence:** Uses SQLite3 to store jobs and statuses, completely avoiding RAM bloat and preventing data loss during crashes or pauses.
- **Modern UI:** Clean, glassmorphism-styled dashboard using vanilla HTML/JS, with DataTables server-side pagination to render thousands of rows smoothly.
- **Export to Excel:** Seamless one-click extraction to cleanly formatted `.xlsx` files using `openpyxl`. Extracts 7 specific fields: UPC, Sale Price, Availability, Shipping Days, Fast 'N Cheap Shipping, Shipping Price, and Format.
- **Portable Deployment:** Designed for non-technical users to deploy on a Windows Server (VPS) via a simple batch script (`setup.bat`).

## AI Handoff & Architecture
If you are an AI agent or a developer tasked with extending this project, please read:
- [Project Architecture & Logic](./project_architecture.md)
- [Conversation & Context History](./conversation_history.md)
- [Changelog](./CHANGELOG.md)

## Tech Stack
- **Backend:** Python 3, Flask, SQLite3, BeautifulSoup4
- **Frontend:** HTML, CSS, JavaScript (jQuery, DataTables.js)
