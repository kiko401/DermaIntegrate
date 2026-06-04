import requests

url = "http://127.0.0.1:8000/upload"
file_path = r"D:\myProjects\DermaIntegrate.2\test.jpg"  # 测试图片路径

with open(file_path, "rb") as f:
    files = {"file": ("test.jpg", f, "image/jpeg")}
    response = requests.post(url, files=files)
    print("Status:", response.status_code)
    print("Response:", response.json())