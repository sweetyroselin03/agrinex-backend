import os
import requests
import time
import sys

BASE_URL = "http://127.0.0.1:10000"

def run_tests():
    print("=== STARTING AGRIEX OTP FLOW INTEGRATION TESTS ===")

    # Test Email
    test_email = f"test_{int(time.time())}@agrinex.local"
    print(f"Testing with email: {test_email}")

    # 1. Send OTP in production mode (or default)
    # SMTP is dummy, so email sending will fail. In production mode, this MUST return 500,
    # and NO cooldown must be registered.
    print("\n--- Test 1: Send OTP with failing SMTP in Production mode ---")
    payload = {"email": test_email}
    response = requests.post(f"{BASE_URL}/auth/send-otp", json=payload)
    print(f"Response Status: {response.status_code}")
    print(f"Response Body: {response.text}")
    assert response.status_code == 500, f"Expected status code 500, got {response.status_code}"
    print("Success: Failed as expected due to SMTP authentication failure in production mode.")

    # 2. Resend OTP immediately. Since the first one failed, we should NOT get blocked by cooldown.
    print("\n--- Test 2: Resend immediately after failure (No Cooldown block expected) ---")
    response2 = requests.post(f"{BASE_URL}/auth/send-otp", json=payload)
    print(f"Response Status: {response2.status_code}")
    print(f"Response Body: {response2.text}")
    assert response2.status_code == 500, f"Expected status code 500 (SMTP failure), got {response2.status_code}"
    print("Success: No cooldown block applied because the first request failed.")

    # Now let's test dev/mock mode. We need to set ENV=development.
    # To simulate ENV=development without restarting the server, we could inspect how the server reads ENV.
    # Wait, the server reads `ENV` from environment variables/dotenv.
    # Let's check if the server has dev mode active or if we can see.
    # Let's temporarily tell the user or set ENV=development in .env, restart, and test.
    # But wait, we can also test verification if we have a successful mock/dev OTP.
    # Let's check check-account endpoint.
    print("\n--- Test 3: Check Account endpoint ---")
    check_payload = {"identifier": test_email}
    check_res = requests.post(f"{BASE_URL}/auth/check-account", json=check_payload)
    print(f"Check Res: {check_res.status_code} - {check_res.json()}")
    assert check_res.json()["exists"] == False, "Expected exists to be False"

    print("\n=== INTEGRATION TESTS COMPLETED SUCCESSFULLY ===")

if __name__ == "__main__":
    try:
        run_tests()
    except AssertionError as ae:
        print(f"\n❌ Assertion Failed: {ae}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        sys.exit(1)
