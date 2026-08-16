import urllib.request

urls = {
    "category": "https://www.oldies.com/collection-view/Clearance-DVDs.html",
    "product": "https://www.oldies.com/product-view/18955W.html"
}

def fetch_and_save(name, url):
    try:
        print(f"Fetching {name} from {url}...")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"})
        html = urllib.request.urlopen(req, timeout=10).read().decode("utf-8")
        with open(f"{name}_sample.html", "w", encoding="utf-8") as f:
            f.write(html)
        print(f"Saved {name}_sample.html successfully.")
    except Exception as e:
        print(f"Failed to fetch {name}: {e}")

fetch_and_save("category", urls["category"])
fetch_and_save("product", urls["product"])
