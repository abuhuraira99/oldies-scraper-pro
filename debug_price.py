import urllib.request
from bs4 import BeautifulSoup
import re

urls = [
    "https://www.oldies.com/product-view/22725F.html", # Stranger things
    "https://www.oldies.com/product-view/78590K.html"  # Suspension
]

for url in urls:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    html = urllib.request.urlopen(req).read().decode("utf-8")
    soup = BeautifulSoup(html, "html.parser")
    
    print(f"\n--- {url} ---")
    
    # Let's find "Your Price:"
    your_price = soup.find(string=re.compile(r"Your Price:"))
    if your_price:
        parent = your_price.parent
        print("Your Price parent text:", repr(parent.text))
        print("Your Price parent HTML:", parent.encode_contents().decode('utf-8'))
        
        # also print next sibling if any
        grandparent = parent.parent
        print("Your Price grandparent HTML:", grandparent.encode_contents().decode('utf-8'))
    
