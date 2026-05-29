import os
import requests
import time
import sys

BASE_URL = "http://127.0.0.1:10000"

def run_tests():
    print("=== STARTING AGRIEX DEV MODE OTP FLOW INTEGRATION TESTS ===")

    # Test Email
    test_email = f"test_dev_{int(time.time())}@agrinex.local"
    print(f"Testing with email: {test_email}")

    # 1. Send OTP in development mode
    # SMTP is dummy, so it will fail, but since ENV=development, it should fall back to returning the generated OTP.
    print("\n--- Test 1: Send OTP (Dev Fallback Mode) ---")
    payload = {"email": test_email}
    response = requests.post(f"{BASE_URL}/auth/send-otp", json=payload)
    print(f"Response Status: {response.status_code}")
    print(f"Response Body: {response.text}")
    assert response.status_code == 200, f"Expected status code 200, got {response.status_code}"
    
    res_data = response.json()
    assert "dev_otp" in res_data, "Expected dev_otp in response data"
    otp = res_data["dev_otp"]
    print(f"Success: OTP sent and returned as: {otp}")

    # 2. Resend OTP immediately. This MUST fail with 429 because the first request succeeded.
    print("\n--- Test 2: Resend immediately (Cooldown block expected) ---")
    response2 = requests.post(f"{BASE_URL}/auth/send-otp", json=payload)
    print(f"Response Status: {response2.status_code}")
    print(f"Response Body: {response2.text}")
    assert response2.status_code == 429, f"Expected status code 429, got {response2.status_code}"
    print("Success: Cooldown block successfully triggered.")

    # 3. Verify OTP with wrong code. Attempts should increment.
    print("\n--- Test 3: Verify OTP with incorrect code ---")
    verify_payload = {"email": test_email, "otp": "000000"}
    response3 = requests.post(f"{BASE_URL}/auth/verify-otp", json=verify_payload)
    print(f"Response Status: {response3.status_code}")
    print(f"Response Body: {response3.text}")
    assert response3.status_code == 400, f"Expected status code 400, got {response3.status_code}"
    print("Success: Incorrect verification failed with 400.")

    # 4. Verify OTP with correct code. Should succeed.
    print("\n--- Test 4: Verify OTP with correct code ---")
    verify_payload_correct = {"email": test_email, "otp": otp}
    response4 = requests.post(f"{BASE_URL}/auth/verify-otp", json=verify_payload_correct)
    print(f"Response Status: {response4.status_code}")
    print(f"Response Body: {response4.text}")
    assert response4.status_code == 200, f"Expected status code 200, got {response4.status_code}"
    print("Success: Verification succeeded with 200.")

    print("\n=== DEV MODE INTEGRATION TESTS COMPLETED SUCCESSFULLY ===")

if __name__ == "__main__":
    try:
        run_tests()
    except AssertionError as ae:
        print(f"\n❌ Assertion Failed: {ae}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        sys.exit(1)
