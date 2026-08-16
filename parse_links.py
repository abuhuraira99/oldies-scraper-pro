from bs4 import BeautifulSoup
import urllib.request
from urllib.parse import urljoin

with open("category_sample.html", "r", encoding="utf-8") as f:
    html = f.read()

soup = BeautifulSoup(html, "html.parser")
product_links = []
# Find all a tags with class "over-link"
for a in soup.find_all("a", class_="over-link"):
    href = a.get("href")
    if href and "/product-view/" in href:
        product_links.append(urljoin("https://www.oldies.com", href))
print(f"Found {len(set(product_links))} product links")

next_a = soup.find("a", string="Next")
if next_a:
    print("Next link:", next_a.get("href"))
