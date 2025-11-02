import os
import json
import time
import redis
import pika
import google.generativeai as genai
from supabase import create_client
from dotenv import load_dotenv
from datetime import datetime

# ---------------- LOAD ENV ----------------
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "rabbitmq")

# ---------------- INIT SERVICES ----------------
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Redis
try:
    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=0, decode_responses=True)
    r.ping()
    print("✅ Connected to Redis")
except Exception as e:
    print(f"❌ Redis connection failed: {e}")
    r = None

# Gemini setup
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("models/gemini-2.5-flash")
print("✅ Gemini client ready")

# Lord Ram system prompt
system_prompt = """
🪔 You are Lord Ram, the virtuous prince of Ayodhya.
Speak with serenity, compassion, and dharmic truth.
Use a poetic, calm, and wise tone inspired by the Ramayana.
Offer guidance with humility and divine insight.
"""

# ---------------- CONNECT TO RABBITMQ ----------------
while True:
    try:
        connection = pika.BlockingConnection(pika.ConnectionParameters(host=RABBITMQ_HOST))
        channel = connection.channel()
        channel.queue_declare(queue="chat_queue", durable=True)
        channel.queue_declare(queue="reply_queue", durable=True)
        print("✅ Connected to RabbitMQ and queues declared.")
        break
    except Exception as e:
        print(f"❌ RabbitMQ not ready: {e}. Retrying in 5s...")
        time.sleep(5)

print("🚀 Gemini Worker (Lord Ram persona) is now active...")

# ---------------- CALLBACK ----------------
def callback(ch, method, properties, body):
    try:
        data = json.loads(body)
        username = data.get("username", "guest")
        user_message = data.get("message", "").strip()
        print(f"📩 Message from {username}: {user_message}")

        # Combine system prompt + user message
        prompt = f"{system_prompt}\n\nUser: {user_message}\nLord Ram:"

        try:
            response = model.generate_content(prompt)
            reply_text = response.text.strip() if hasattr(response, "text") else "(No response)"
        except Exception as e:
            reply_text = f"⚠️ Gemini API error: {e}"
            print(reply_text)

        # Send reply back
        reply_payload = {
            "username": username,
            "response": reply_text,
            "timestamp": datetime.utcnow().isoformat(),
        }

        channel.basic_publish(
            exchange="",
            routing_key="reply_queue",
            body=json.dumps(reply_payload),
            properties=pika.BasicProperties(delivery_mode=2),
        )
        print("📤 Sent reply to reply_queue.")

        # Update Supabase
        try:
            result = supabase.table("chat_history") \
                .select("id") \
                .eq("username", username) \
                .eq("message", user_message) \
                .order("created_at", desc=True) \
                .limit(1) \
                .execute()

            if result.data:
                last_id = result.data[0]["id"]
                supabase.table("chat_history") \
                    .update({"response": reply_text}) \
                    .eq("id", last_id) \
                    .execute()
                print(f"✅ Supabase updated for message ID {last_id}")
            else:
                supabase.table("chat_history").insert({
                    "username": username,
                    "message": user_message,
                    "response": reply_text,
                    "created_at": datetime.utcnow().isoformat()
                }).execute()
                print("🆕 Inserted new chat in Supabase.")
        except Exception as e:
            print(f"❌ Supabase update failed: {e}")

        # Redis update
        try:
            if r:
                cache_key = f"chat:{username}"
                cached_data = r.get(cache_key)
                if cached_data:
                    chats = json.loads(cached_data)
                    for chat in chats:
                        if chat.get("message") == user_message:
                            chat["response"] = reply_text
                    r.set(cache_key, json.dumps(chats), ex=60)
                    print("🧠 Updated Redis cache.")
        except Exception as e:
            print(f"⚠️ Redis cache update failed: {e}")

        ch.basic_ack(delivery_tag=method.delivery_tag)

    except Exception as e:
        print(f"❌ Error processing message: {e}")
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

# ---------------- START CONSUMING ----------------
channel.basic_qos(prefetch_count=1)
channel.basic_consume(queue="chat_queue", on_message_callback=callback)

try:
    channel.start_consuming()
except KeyboardInterrupt:
    print("\n🛑 Stopped by user")
    channel.stop_consuming()
    connection.close()
