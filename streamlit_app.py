import streamlit as st
import requests
import os
import time
from dotenv import load_dotenv
from streamlit_autorefresh import st_autorefresh

# ------------------ Load environment ------------------
load_dotenv()
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")

# ------------------ Initialize session state ------------------
if "messages" not in st.session_state:
    st.session_state.messages = []
if "user" not in st.session_state:
    st.session_state.user = "guest"

st.title("💬 Gemini AI Chat")

# ------------------ Auto Refresh every 5 seconds ------------------
# This triggers rerun every 5 seconds to keep chat live
st_autorefresh(interval=5 * 1000, key="chat_autorefresh")

# ------------------ Function to load full chat history ------------------
def load_history(force_refresh=False):
    """Fetch chat messages from backend and update UI state."""
    try:
        resp = requests.get(f"{BACKEND_URL}/messages", params={"user": st.session_state.user}, timeout=10)
        if resp.status_code == 200:
            data = resp.json()

            # Only update if new data differs or refresh is requested
            if force_refresh or len(data) != len(st.session_state.messages) // 2:
                st.session_state.messages = []
                for item in data:
                    st.session_state.messages.append({"role": "user", "content": item["message"]})
                    if item.get("response") and item["response"].strip():
                        st.session_state.messages.append({"role": "assistant", "content": item["response"]})
        else:
            st.warning("⚠️ Could not fetch chat history.")
    except Exception as e:
        st.error(f"Error loading history: {e}")

# ------------------ Refresh Button ------------------
if st.button("🔄 Refresh Chat History"):
    load_history(force_refresh=True)
else:
    # Regular refresh every auto-refresh cycle
    load_history()

# ------------------ Display messages ------------------
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# ------------------ Handle user input ------------------
if prompt := st.chat_input("Type your message..."):
    # Show user message immediately
    st.chat_message("user").markdown(prompt)
    st.session_state.messages.append({"role": "user", "content": prompt})

    try:
        # Send to backend
        resp = requests.post(
            f"{BACKEND_URL}/send",
            json={"user": st.session_state.user, "message": prompt},
            timeout=10
        )

        if resp.status_code == 200:
            st.chat_message("assistant").markdown("⏳ Waiting for Gemini response...")
            st.session_state.messages.append({"role": "assistant", "content": "⏳ Waiting for Gemini response..."})

            # Poll for Gemini's reply (every 2s for 20s)
            for _ in range(10):
                time.sleep(2)
                refreshed = requests.get(
                    f"{BACKEND_URL}/messages",
                    params={"user": st.session_state.user},
                    timeout=10
                )
                if refreshed.status_code == 200:
                    data = refreshed.json()
                    if data and data[-1].get("response"):
                        reply = data[-1]["response"]
                        if reply and reply.strip():
                            st.chat_message("assistant").markdown(reply)
                            st.session_state.messages.append({"role": "assistant", "content": reply})
                            break
            else:
                st.chat_message("assistant").markdown("⌛ Still waiting for Gemini response...")

        else:
            st.chat_message("assistant").markdown(f"❌ Error: {resp.text}")

    except Exception as e:
        st.chat_message("assistant").markdown(f"⚠️ Error sending message: {e}")
