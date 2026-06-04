import requests

url = "http://127.0.0.1:8000/upload"

file_path = r"D:\myProjects\DermaIntegrate.2\test.jpg"

with open(file_path, "rb") as f:
    files = {"file": f}
    response = requests.post(url, files=files)
    print(response.status_code)
    print(response.json())