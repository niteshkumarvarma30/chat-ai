from google import genai
import os

# Set your Gemini API key
os.environ["GOOGLE_API_KEY"] = "AIzaSyBE6sSHHMyNgIuY31-8_YgRwd6IxaBc4UQ"

# Initialize client
client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])

# List all available models
for model in client.models.list():
    print(model.name)
