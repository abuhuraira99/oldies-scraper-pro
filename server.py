import os
import json
import sqlite3
import threading
import time
import tempfile
import uuid
from pathlib import Path
from flask import Flask, jsonify, request, send_from_directory, send_file
from openpyxl import Workbook
import psutil

from fetch_oldies import fetch_all_products_from_url, start_extraction_workers

app = Flask(__name__, static_folder='.', static_url_path='')

PROJECT_ROOT = Path(__file__).resolve().parent
DB_PATH = PROJECT_ROOT / "db.sqlite"
# Finished runs are saved here automatically so data is never lost if nobody clicks Download
EXPORTS_DIR = PROJECT_ROOT / "exports"

# Create Database tables
def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY,
                url TEXT,
                status TEXT,
                workers INTEGER,
                headless BOOLEAN,
                total_items INTEGER DEFAULT 0,
                completed_items INTEGER DEFAULT 0,
                created_at REAL,
                completed_at REAL,
                error TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT,
                product_url TEXT,
                upc TEXT,
                sale_price TEXT,
                availability TEXT,
                shipping_days TEXT,
                fast_cheap_shipping TEXT,
                shipping_price TEXT,
                format TEXT,
                status TEXT DEFAULT 'pending',
                error TEXT,
                FOREIGN KEY(run_id) REFERENCES runs(id)
            )
        """)
        conn.commit()

init_db()

def _parse_bool(value, default=False):
    if value is None: return default
    if isinstance(value, bool): return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}

@app.route('/')
def index():
    return send_from_directory(app.static_folder or ".", 'index.html')

@app.route('/api/run', methods=['POST'])
def api_run():
    data = request.json or request.form
    url = data.get('url')
    if not url:
        return jsonify({"error": "url is required"}), 400

    workers = int(data.get('workers', 4))
    headless = _parse_bool(data.get('headless', False))
    run_id = str(uuid.uuid4())

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO runs (id, url, status, workers, headless, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (run_id, url, "discovering", workers, headless, time.time())
        )
        conn.commit()

    # Start background thread for Phase 1 (Discovery) and Phase 2 (Extraction)
    threading.Thread(target=run_pipeline, args=(run_id, url, workers, headless), daemon=True).start()

    return jsonify({"run_id": run_id, "status": "discovering", "workers": workers})

def run_pipeline(run_id, url, workers, headless):
    try:
        # Phase 1: Discover all product links from the listing URL
        product_links = fetch_all_products_from_url(url, headless)
        
        with sqlite3.connect(DB_PATH) as conn:
            # Insert all links into products
            for link in product_links:
                conn.execute(
                    "INSERT INTO products (run_id, product_url, status) VALUES (?, ?, 'pending')",
                    (run_id, link)
                )
            conn.execute("UPDATE runs SET status = 'extracting', total_items = ? WHERE id = ?", (len(product_links), run_id))
            conn.commit()

        # Phase 2: Start workers to process pending products
        finish_extraction(run_id, workers, headless)

    except Exception as e:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("UPDATE runs SET status = 'error', error = ? WHERE id = ?", (str(e), run_id))
            conn.commit()

def finish_extraction(run_id, workers, headless):
    start_extraction_workers(run_id, DB_PATH, workers, headless)

    # Save the Excel file before marking the run done, so the UI sees it immediately
    try:
        out_path = auto_export_path(run_id)
        EXPORTS_DIR.mkdir(exist_ok=True)
        write_export(run_id, out_path)
        print(f"Results saved automatically to: {out_path}")
    except Exception as e:
        print(f"Automatic Excel save failed: {e}")

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("UPDATE runs SET status = 'done', completed_at = ? WHERE id = ?", (time.time(), run_id))
        conn.commit()

def resume_pipeline(run_id, workers, headless):
    try:
        finish_extraction(run_id, workers, headless)
    except Exception as e:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("UPDATE runs SET status = 'error', error = ? WHERE id = ?", (str(e), run_id))
            conn.commit()

def auto_export_path(run_id):
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute("SELECT created_at FROM runs WHERE id = ?", (run_id,)).fetchone()
    stamp = time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime(row[0] if row and row[0] else time.time()))
    return EXPORTS_DIR / f"oldies_export_{stamp}_{run_id[:8]}.xlsx"

def write_export(run_id, out_path):
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute("SELECT upc, sale_price, availability, shipping_days, fast_cheap_shipping, shipping_price, format, product_url FROM products WHERE run_id = ?", (run_id,)).fetchall()

    wb = Workbook()
    ws = wb.active
    ws.title = "Extracted Data"
    ws.append(["UPC", "Sale Price", "Availability", "Shipping Days", "Fast N Cheap", "Shipping Price", "Format", "URL"])
    for row in rows:
        ws.append(row)
    wb.save(out_path)


@app.route('/api/progress/<run_id>', methods=['GET'])
def api_progress(run_id):
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        run = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if not run:
            return jsonify({"error": "run not found"}), 404
        
        # Count done vs pending
        row_counts = conn.execute(
            "SELECT status, COUNT(*) FROM products WHERE run_id = ? GROUP BY status", (run_id,)
        ).fetchall()
        
        counts = {"pending": 0, "done": 0, "error": 0}
        total = run['total_items']
        completed = 0

        for status, count in row_counts:
            counts[status] = count
            if status in ('done', 'error'):
                completed += count

        # Calculate elapsed and ETA
        elapsed = time.time() - run['created_at'] if run['created_at'] else 0
        eta = 0
        if completed > 0 and run['status'] == 'extracting':
            rate = completed / elapsed
            eta = (total - completed) / rate if rate > 0 else 0

        saved_file = auto_export_path(run_id)

        # Sync completed items in runs table
        conn.execute("UPDATE runs SET completed_items = ? WHERE id = ?", (completed, run_id))
        conn.commit()

        return jsonify({
            "status": run['status'],
            "total": total,
            "done": completed,
            "counts": counts,
            "elapsed": elapsed if run['status'] != 'done' else (run['completed_at'] - run['created_at']),
            "eta": eta,
            "error": run['error'],
            "auto_saved_file": saved_file.name if saved_file.exists() else None
        })

@app.route('/api/rows/<run_id>', methods=['GET'])
def api_rows(run_id):
    try:
        start = int(request.args.get("start", 0))
        length = int(request.args.get("length", 25))
    except ValueError:
        start, length = 0, 25

    with sqlite3.connect(DB_PATH) as conn:
        total = conn.execute("SELECT COUNT(*) FROM products WHERE run_id = ?", (run_id,)).fetchone()[0]
        rows = conn.execute(
            "SELECT upc, sale_price, availability, shipping_days, fast_cheap_shipping, shipping_price, format, status, product_url, error FROM products WHERE run_id = ? LIMIT ? OFFSET ?",
            (run_id, length, start)
        ).fetchall()

    return jsonify({
        "data": rows,
        "recordsTotal": total,
        "recordsFiltered": total,
    })

@app.route('/api/export/<run_id>', methods=['GET'])
def api_export(run_id):
    temp_dir = Path(tempfile.gettempdir())
    out_path = temp_dir / f"export_{run_id}.xlsx"
    write_export(run_id, out_path)
    
    return send_file(out_path, as_attachment=True, download_name="extracted_products.xlsx")

@app.route('/api/latest', methods=['GET'])
def api_latest():
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        run = conn.execute("SELECT id FROM runs ORDER BY created_at DESC LIMIT 1").fetchone()
        if not run:
            return jsonify({"error": "no runs"}), 404
        return jsonify({"run_id": run['id']})

@app.route('/api/cancel/<run_id>', methods=['POST'])
def api_cancel(run_id):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("UPDATE runs SET status = 'cancelled' WHERE id = ?", (run_id,))
        conn.commit()
    return jsonify({"status": "cancelled"})

# Resume endpoint for crashed/paused runs
@app.route('/api/resume/<run_id>', methods=['POST'])
def api_resume(run_id):
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        run = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if not run:
            return jsonify({"error": "run not found"}), 404
            
        conn.execute("UPDATE runs SET status = 'extracting' WHERE id = ?", (run_id,))
        conn.commit()
        
    threading.Thread(target=resume_pipeline, args=(run_id, run['workers'], run['headless']), daemon=True).start()
    return jsonify({"status": "resumed"})

@app.route('/api/clear_db', methods=['POST'])
def api_clear_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM products")
        conn.execute("DELETE FROM runs")
        conn.commit()
    return jsonify({"status": "cleared"})

if __name__ == '__main__':
    # On startup, mark any 'extracting' or 'discovering' runs as 'paused' so the user can manually resume
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("UPDATE runs SET status = 'paused' WHERE status IN ('extracting', 'discovering')")
        conn.commit()
    app.run(port=5000, debug=False, host='0.0.0.0')
