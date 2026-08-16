import urllib.request
try:
    req = urllib.request.Request("https://www.oldies.com/", headers={"User-Agent": "Mozilla/5.0"})
    res = urllib.request.urlopen(req)
    print("Status:", res.status)
    print("Response length:", len(res.read()))
except Exception as e:
    print("Error:", e)
