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

st.set_page_config(page_title="Chat with Lord Ram", page_icon="🕉️")
st.title("🪔 Chat with Lord Ram")

# Display Lord Ram avatar at top
st.image("bcb77977-752f-4c46-ae2d-d236a0c7d62f.png", width=150)

# Auto Refresh every 5 seconds
st_autorefresh(interval=5 * 1000, key="chat_autorefresh")

# ------------------ Function to load chat history ------------------
def load_history(force_refresh=False):
    try:
        resp = requests.get(f"{BACKEND_URL}/messages", params={"user": st.session_state.user}, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if force_refresh or len(data) != len(st.session_state.messages) // 2:
                st.session_state.messages = []
                for item in data:
                    st.session_state.messages.append({"role": "user", "content": item["message"]})
                    if item.get("response") and item["response"].strip():
                        st.session_state.messages.append({"role": "assistant", "content": item["response"]})
    except Exception as e:
        st.error(f"Error loading history: {e}")

# ------------------ Refresh ------------------
if st.button("🔄 Refresh Chat"):
    load_history(force_refresh=True)
else:
    load_history()

# ------------------ Display messages ------------------
for msg in st.session_state.messages:
    if msg["role"] == "user":
        with st.chat_message("user"):
            st.markdown(msg["content"])
    else:
        with st.chat_message("assistant", avatar="bcb77977-752f-4c46-ae2d-d236a0c7d62f.png"):
            st.markdown(msg["content"])

# ------------------ Handle user input ------------------
if prompt := st.chat_input("Type your message..."):
    st.chat_message("user").markdown(prompt)
    st.session_state.messages.append({"role": "user", "content": prompt})

    try:
        resp = requests.post(
            f"{BACKEND_URL}/send",
            json={"user": st.session_state.user, "message": prompt},
            timeout=10
        )

        if resp.status_code == 200:
            st.chat_message("assistant", avatar="bcb77977-752f-4c46-ae2d-d236a0c7d62f.png").markdown("⏳ Awaiting Lord Ram’s guidance...")
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
                            st.chat_message("assistant", avatar="bcb77977-752f-4c46-ae2d-d236a0c7d62f.png").markdown(reply)
                            st.session_state.messages.append({"role": "assistant", "content": reply})
                            break
        else:
            st.chat_message("assistant").markdown(f"❌ Error: {resp.text}")

    except Exception as e:
        st.chat_message("assistant").markdown(f"⚠️ Error sending message: {e}")
