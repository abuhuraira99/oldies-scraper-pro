import urllib.request
from bs4 import BeautifulSoup
import re
import time
import sqlite3
import threading
from queue import Queue
from urllib.parse import urljoin

MAX_RETRIES = 3
WORKER_THREADS = 4

import random

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0"
]

request_lock = threading.Lock()

def get_page_html(url, headless=True):
    for attempt in range(MAX_RETRIES):
        try:
            with request_lock:
                # 3.5 seconds absolute rate limit
                time.sleep(3.5)
                req = urllib.request.Request(url, headers={"User-Agent": random.choice(USER_AGENTS)})
                html = urllib.request.urlopen(req, timeout=15).read().decode("utf-8")
            return html
        except Exception as e:
            # If we get blocked (e.g. HTTP 429), sleep for 30 seconds to let the ban lift automatically
            if "429" in str(e):
                print("Rate limit hit! Sleeping for 30 seconds...")
                time.sleep(30)
            else:
                time.sleep(3)
    return None

def fetch_all_products_from_url(start_url, headless=True):
    product_links = set()
    current_url = start_url
    base_url = "https://www.oldies.com"

    while current_url:
        print(f"Discovering links on: {current_url}")
        html = get_page_html(current_url, headless)
        if not html:
            print("Failed to fetch discovery page")
            break

        soup = BeautifulSoup(html, 'html.parser')

        # Find all product links on the current page
        for a in soup.find_all("a", class_="over-link"):
            href = a.get("href")
            if href and "/product-view/" in href:
                product_links.add(urljoin(base_url, href))

        # Check for next page
        next_a = soup.find("a", string="Next")
        if next_a and next_a.get("href"):
            current_url = urljoin(base_url, next_a.get("href"))
        else:
            current_url = None

    return list(product_links)

def extract_product_details(url, headless=True):
    html = get_page_html(url, headless)
    if not html:
        return {"error": "Failed to fetch page"}
        
    soup = BeautifulSoup(html, 'html.parser')
    
    # 1. UPC
    upc = "N/A"
    upc_meta = soup.find("meta", property="og:upc")
    if upc_meta and upc_meta.get("content"):
        upc = upc_meta["content"]
    
    if upc == "N/A":
        gtin = soup.find("meta", itemprop="gtin12")
        if gtin and gtin.get("content"):
            upc = gtin["content"]
            
    if upc == "N/A":
        product_id = soup.find("meta", itemprop="productID")
        if product_id and product_id.get("content"):
            content = product_id["content"]
            if content.startswith("upc:"):
                upc = content.replace("upc:", "")
    
    # 2. Sale Price
    # Look specifically for the main product price ID to avoid grabbing "Also released as" or related product prices
    price_elem = soup.find(id="product-price")
    if not price_elem:
        # Fallback to the first itemprop="price" which should be the main product's metadata
        price_elem = soup.find(itemprop="price")
        
    if price_elem:
        # Sometimes the price has a 'content' attribute without the $ sign, or we can just grab the text
        sale_price = price_elem.text.strip()
        if not sale_price and price_elem.has_attr("content"):
            sale_price = "$" + price_elem["content"]
    else:
        sale_price = "N/A"
    
    # 3 & 4. Availability & Shipping Days
    availability = "N/A"
    shipping_days = "N/A"
    avail_label = soup.find(string=re.compile(r"Available:"))
    if avail_label and avail_label.parent and avail_label.parent.parent:
        avail_parent_text = avail_label.parent.parent.text.strip()
        # avail_parent_text is typically 'Available:\n Usually ships in 1-3 business days'
        parts = avail_parent_text.split("Available:")
        if len(parts) > 1:
            availability = "Available:"
            shipping_days = parts[1].strip()
    
    # 5 & 6. Fast n Cheap Shipping & Shipping Price
    fast_cheap_shipping = "No"
    shipping_price = "N/A"
    fast_cheap = soup.find(string=re.compile(r"FAST 'N CHEAP"))
    if fast_cheap and fast_cheap.parent and fast_cheap.parent.parent:
        fast_cheap_shipping = "Yes"
        shipping_block_text = fast_cheap.parent.parent.text.strip()
        # Find price in the block
        match = re.search(r"\$\d+\.\d{2}", shipping_block_text)
        if match:
            shipping_price = match.group(0)

    # 7. Format
    format_val = "N/A"
    format_meta = soup.find("meta", itemprop="category")
    if format_meta:
        format_val = format_meta["content"]
    else:
        format_label = soup.find(string=re.compile(r"Format:"))
        if format_label and format_label.parent:
            # text is something like 'Format:\nDVD'
            f_parts = format_label.parent.text.split("Format:")
            if len(f_parts) > 1:
                format_val = f_parts[1].strip()

    return {
        "upc": upc,
        "sale_price": sale_price,
        "availability": availability,
        "shipping_days": shipping_days,
        "fast_cheap_shipping": fast_cheap_shipping,
        "shipping_price": shipping_price,
        "format": format_val,
        "error": None
    }


def worker_process(worker_id, q, db_path, headless):
    conn = sqlite3.connect(db_path)
    while True:
        job = q.get()
        if job is None:
            break
            
        row_id, product_url, run_id = job
        
        try:
            details = extract_product_details(product_url, headless)
            
            if details.get("error"):
                conn.execute("UPDATE products SET status = 'error', error = ? WHERE id = ?", (details["error"], row_id))
            else:
                conn.execute('''
                    UPDATE products 
                    SET upc = ?, sale_price = ?, availability = ?, shipping_days = ?, fast_cheap_shipping = ?, shipping_price = ?, format = ?, status = 'done'
                    WHERE id = ?
                ''', (
                    details["upc"],
                    details["sale_price"],
                    details["availability"],
                    details["shipping_days"],
                    details["fast_cheap_shipping"],
                    details["shipping_price"],
                    details["format"],
                    row_id
                ))
            conn.commit()
            
        except Exception as e:
            conn.execute("UPDATE products SET status = 'error', error = ? WHERE id = ?", (str(e), row_id))
            conn.commit()
        
        q.task_done()
    
    conn.close()

def start_extraction_workers(run_id, db_path, num_workers=WORKER_THREADS, headless=True):
    with sqlite3.connect(db_path) as conn:
        # Re-fetch pending rows for this run
        pending_rows = conn.execute("SELECT id, product_url FROM products WHERE run_id = ? AND status = 'pending'", (run_id,)).fetchall()
        
    q = Queue()
    for row in pending_rows:
        q.put((row[0], row[1], run_id))
        
    threads = []
    for i in range(num_workers):
        t = threading.Thread(target=worker_process, args=(i, q, db_path, headless))
        t.start()
        threads.append(t)
        
    q.join()
    
    for i in range(num_workers):
        q.put(None)
    for t in threads:
        t.join()
