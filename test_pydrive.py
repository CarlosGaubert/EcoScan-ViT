from pydrive.auth import GoogleAuth
from pydrive.drive import GoogleDrive
import os

print("--- PyDrive Diagnostic and Authentication Tool ---")

# Setup PyDrive configuration
gauth = GoogleAuth()

# Check if client_secrets.json exists
if not os.path.exists("client_secrets.json"):
    print("ERROR: client_secrets.json not found in this folder!")
    exit(1)

# Check if the JSON is configured as web or installed
import json
with open("client_secrets.json", "r") as f:
    config = json.load(f)
    if "web" in config:
        print("WARNING: Your client_secrets.json is configured as a 'Web application'.")
        print("For local scripts and desktop tools, Google requires a 'Desktop app' (Aplicación de escritorio) credential.")
        print("If you get a 'Failed to start a local web server' or redirect mismatch error, please create a 'Desktop app' credential instead.")
    elif "installed" in config:
        print("SUCCESS: client_secrets.json is correctly configured as an 'Installed application' (Desktop app).")

print("\nStarting authentication flow...")
try:
    gauth.LoadCredentialsFile("mycreds.txt")
    if gauth.credentials is None:
        # Start local webserver to authenticate
        gauth.LocalWebserverAuth()
    elif gauth.access_token_expired:
        gauth.Refresh()
    else:
        gauth.Authorize()
        
    gauth.SaveCredentialsFile("mycreds.txt")
    print("\nSUCCESS: Authenticated successfully! Credentials saved to 'mycreds.txt'.")
    
    drive = GoogleDrive(gauth)
    print("Testing Google Drive list API...")
    file_list = drive.ListFile({'max_results': 1}).GetList()
    print("Connection test successful!")
    
except Exception as e:
    print(f"\nERROR during authentication: {e}")
    print("\nTroubleshooting Tips:")
    print("1. If it says 'Failed to start a local web server', make sure no other program is using port 8080.")
    print("2. If it says 'Access blocked: Authorization error', make sure to add your email to the 'Test users' list in the Google Cloud Console (under 'OAuth consent screen').")
    print("3. Alternatively, make sure you created the OAuth Client ID as a 'Desktop app' (Aplicación de escritorio) in Google Cloud Console.")
