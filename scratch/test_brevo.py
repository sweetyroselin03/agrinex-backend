import os
import sys
from dotenv import load_dotenv

# Add parent directory to path so app imports work
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import auth_utils

def test_brevo_integration():
    print("=== TESTING BREVO REST API INTEGRATION ===")
    
    # Load .env
    load_dotenv()
    
    api_key = os.getenv("BREVO_API_KEY")
    sender = os.getenv("BREVO_FROM")
    
    print(f"Loaded config from environment:")
    print(f"BREVO_API_KEY: {api_key[:10] if api_key else 'None'}... (len: {len(api_key) if api_key else 0})")
    print(f"BREVO_FROM: {sender}")
    
    if not api_key:
        print("\n[WARNING] BREVO_API_KEY is missing! Testing mock dev fallback...")
    
    test_email = "trasr2000@gmail.com"  # Using a standard Gmail to receive tests
    test_otp = "888999"
    
    print(f"\nSending test OTP {test_otp} to {test_email}...")
    success, is_mock = auth_utils.send_otp_email(test_email, test_otp)
    
    print(f"\nResult:")
    print(f"Success: {success}")
    print(f"Is Mock: {is_mock}")
    
    if success:
        if is_mock:
            print("\n[SUCCESS] Mock/Dev flow executed perfectly!")
        else:
            print("\n[SUCCESS] Real Brevo email sent successfully via Transactional REST API!")
    else:
        print("\n[FAILURE] Failed to send email via Brevo REST API. Inspect the error logs above.")

if __name__ == "__main__":
    test_brevo_integration()
