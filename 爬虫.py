import requests
from bs4 import BeautifulSoup

URL = "https://kongyiqi-home.onrender.com"

headers = {
}

try:
    resp = requests.get(URL, headers=headers, timeout=10)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding

    soup = BeautifulSoup(resp.text, "html.parser")

    print("状态码:", resp.status_code)
    print("页面标题:", soup.title.string if soup.title else "无标题")
    print("页面长度:", len(resp.text), "字符")
    print("\n--- 页面上的链接 ---")
    for a in soup.find_all("a", href=True):
        print(a["href"], "|", a.get_text(strip=True)[:30])

except requests.exceptions.RequestException as e:
    print("请求失败:", e)