import requests

BASE_URL = "http://127.0.0.1:8000" # Localhost since we are on the same machine

def test_send_otp():
    print(f"Testing /auth/send-otp...")
    url = f"{BASE_URL}/auth/send-otp"
    payload = {"email": "sweetyroselin2005@gmail.com"}
    
    try:
        response = requests.post(url, json=payload)
        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.json()}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_send_otp()
