import urllib.request
from bs4 import BeautifulSoup
import re
import time
import sqlite3
import threading
from queue import Queue
from urllib.parse import urljoin
import os

MAX_RETRIES = 3
WORKER_THREADS = 4

# Optional outbound proxy (e.g. "http://host:port"), only needed when testing from outside the US
PROXY = os.environ.get("OLDIES_PROXY")

DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"

request_lock = threading.Lock()

# Oldies.com sits behind AWS WAF, which answers non-browser clients with an empty
# "202 + x-amzn-waf-action: challenge" response. A real Chrome solves the JS challenge
# and receives an aws-waf-token cookie; we reuse that cookie (with the same User-Agent)
# for all plain HTTP requests and refresh it whenever the challenge comes back.
waf_session = {"user_agent": DEFAULT_USER_AGENT, "cookie": None}

if PROXY:
    _opener = urllib.request.build_opener(urllib.request.ProxyHandler({"http": PROXY, "https": PROXY}))
else:
    _opener = urllib.request.build_opener()


class WafChallenge(Exception):
    pass


def refresh_waf_token(url, headless=True):
    from playwright.sync_api import sync_playwright

    print("AWS WAF challenge detected, solving it with Chrome...")
    launch_args = {"headless": headless}
    if PROXY:
        launch_args["proxy"] = {"server": PROXY}

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="chrome", **launch_args)
        except Exception:
            # Google Chrome not installed; fall back to Playwright's bundled Chromium
            browser = p.chromium.launch(**launch_args)
        try:
            probe = browser.new_page()
            # Headless Chrome reports "HeadlessChrome", which the WAF blocks outright with 403
            user_agent = probe.evaluate("navigator.userAgent").replace("HeadlessChrome", "Chrome")
            probe.close()

            context = browser.new_context(user_agent=user_agent)
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=60000)

            token = None
            deadline = time.time() + 60
            while time.time() < deadline:
                cookies = context.cookies("https://www.oldies.com")
                if any(c["name"] == "aws-waf-token" for c in cookies):
                    token = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
                    break
                page.wait_for_timeout(1000)
        finally:
            browser.close()

    if not token:
        raise Exception("Could not obtain AWS WAF token from oldies.com")

    waf_session["user_agent"] = user_agent
    waf_session["cookie"] = token
    print("AWS WAF token obtained.")


def _fetch(url):
    headers = {
        "User-Agent": waf_session["user_agent"],
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    if waf_session["cookie"]:
        headers["Cookie"] = waf_session["cookie"]
    req = urllib.request.Request(url, headers=headers)
    with _opener.open(req, timeout=30) as resp:
        challenged = resp.status == 202 or resp.headers.get("x-amzn-waf-action")
        html = resp.read().decode("utf-8")
    return html, bool(challenged or not html.strip())

def get_page_html(url, headless=True):
    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            with request_lock:
                # 3.5 seconds absolute rate limit
                time.sleep(3.5)
                html, challenged = _fetch(url)
                if challenged:
                    # Solve while holding the lock so other workers wait for the new token
                    refresh_waf_token(url, headless)
                    html, challenged = _fetch(url)
                    if challenged:
                        raise WafChallenge("AWS WAF challenge persisted after refreshing the token")
            return html
        except WafChallenge as e:
            last_error = e
        except Exception as e:
            last_error = e
            print(f"Request failed ({url}): {e}")
            # If we get blocked (e.g. HTTP 429), sleep for 30 seconds to let the ban lift automatically
            if "429" in str(e):
                print("Rate limit hit! Sleeping for 30 seconds...")
                time.sleep(30)
            else:
                time.sleep(3)
    print(f"Giving up on {url}: {last_error}")
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
            if not product_links:
                raise Exception("Could not load the listing page from oldies.com (see server console for details)")
            break

        soup = BeautifulSoup(html, 'html.parser')

        for a in soup.find_all("a", class_="over-link"):
            href = a.get("href")
            if href and "/product-view/" in href:
                product_links.add(urljoin(base_url, href))

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

    price_elem = soup.find(id="product-price")
    if not price_elem:
        price_elem = soup.find(itemprop="price")

    if price_elem:
        sale_price = price_elem.text.strip()
        if not sale_price and price_elem.has_attr("content"):
            sale_price = "$" + price_elem["content"]
    else:
        sale_price = "N/A"

    availability = "N/A"
    shipping_days = "N/A"
    avail_label = soup.find(string=re.compile(r"Available:"))
    if avail_label and avail_label.parent and avail_label.parent.parent:
        avail_parent_text = avail_label.parent.parent.text.strip()
        parts = avail_parent_text.split("Available:")
        if len(parts) > 1:
            availability = "Available:"
            shipping_days = parts[1].strip()

    fast_cheap_shipping = "No"
    shipping_price = "N/A"
    fast_cheap = soup.find(string=re.compile(r"FAST 'N CHEAP"))
    if fast_cheap and fast_cheap.parent and fast_cheap.parent.parent:
        fast_cheap_shipping = "Yes"
        shipping_block_text = fast_cheap.parent.parent.text.strip()
        match = re.search(r"\$\d+\.\d{2}", shipping_block_text)
        if match:
            shipping_price = match.group(0)

    format_val = "N/A"
    format_meta = soup.find("meta", itemprop="category")
    if format_meta:
        format_val = format_meta["content"]
    else:
        format_label = soup.find(string=re.compile(r"Format:"))
        if format_label and format_label.parent:
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
