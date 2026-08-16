from bs4 import BeautifulSoup
import re

with open("product_sample.html", "r", encoding="utf-8") as f:
    html = f.read()

soup = BeautifulSoup(html, "html.parser")

avail_label = soup.find(string=re.compile(r"Available:"))
if avail_label:
    # Look at the parent's full text
    avail_parent = avail_label.parent.parent
    print("Avail full text:", repr(avail_parent.text.strip()))
    
    # Let's also check the next sibling
    print("Next sibling:", repr(avail_label.next_sibling))
    if avail_label.next_sibling:
        # maybe it's in a span
        if avail_label.next_sibling.name == 'span':
            print("Next sibling text:", avail_label.next_sibling.text)
        elif isinstance(avail_label.next_sibling, str):
            print("Next sibling string:", avail_label.next_sibling.strip())
