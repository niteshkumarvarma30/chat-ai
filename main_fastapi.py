from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
import aio_pika
import json
import redis
from supabase import create_client, Client
import os
from dotenv import load_dotenv
from datetime import datetime
import asyncio
import logging
import threading
import pika
import time

# ---------------- LOAD ENV ----------------
load_dotenv()

# ---------------- LOGGER ----------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("chat-backend")

app = FastAPI(title="Chat-AI Backend", description="FastAPI + Supabase + Redis + RabbitMQ")

# ---------------- CONFIG ----------------
RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@rabbitmq/")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

REDIS_HOST = os.getenv("REDIS_HOST", "chat-ai-redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))

# ---------------- INIT CONNECTIONS ----------------
try:
    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    r.ping()
    log.info(f"✅ Connected to Redis at {REDIS_HOST}:{REDIS_PORT}")
except Exception as e:
    log.error(f"❌ Redis connection failed: {e}")
    r = None

try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    log.info("✅ Connected to Supabase successfully")
except Exception as e:
    log.error(f"❌ Supabase connection failed: {e}")
    supabase = None

# ---------------- CORS ----------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------- ASYNC TASK: SEND TO RABBITMQ ----------------
async def publish_to_rabbitmq(username: str, message: str):
    """Publish user message to RabbitMQ queue for Gemini processing."""
    for attempt in range(3):
        try:
            connection = await aio_pika.connect_robust(RABBITMQ_URL)
            async with connection:
                channel = await connection.channel()
                queue = await channel.declare_queue("chat_queue", durable=True)
                await channel.default_exchange.publish(
                    aio_pika.Message(
                        body=json.dumps({"username": username, "message": message}).encode()
                    ),
                    routing_key=queue.name,
                )
            log.info(f"📨 Queued message from {username}")
            return
        except Exception as e:
            log.warning(f"⚠️ RabbitMQ publish failed (attempt {attempt+1}/3): {e}")
            await asyncio.sleep(2)
    log.error("❌ Failed to publish message to RabbitMQ after retries")

# ---------------- ROUTES ----------------
@app.post("/send")
async def send_message(req: Request, background_tasks: BackgroundTasks):
    """Receive user message → store in Supabase → queue for Gemini worker."""
    data = await req.json()
    username = data.get("user", "guest")
    message = data.get("message", "")

    try:
        supabase.table("chat_history").insert({
            "username": username,
            "message": message,
            "response": None,
            "created_at": datetime.utcnow().isoformat()
        }).execute()
        log.info(f"✅ Message saved to Supabase for user: {username}")
    except Exception as e:
        log.error(f"❌ Supabase insert failed: {e}")

    background_tasks.add_task(publish_to_rabbitmq, username, message)
    return {"status": "queued", "user": username, "message": message}


@app.get("/messages")
def get_messages(user: str):
    """Fetch chat history (cached in Redis)."""
    cache_key = f"chat:{user}"

    # Try cache first
    if r:
        cached_data = r.get(cache_key)
        if cached_data:
            log.info(f"⚡ Cache hit for {user}")
            return json.loads(cached_data)

    # If not cached, fetch from Supabase
    try:
        log.info(f"📥 Fetching chat history for {user}")
        response = supabase.table("chat_history").select("*").eq("username", user).order("created_at").execute()
        chats = response.data or []

        # Store in cache
        if r:
            r.set(cache_key, json.dumps(chats), ex=60)
            log.info(f"💾 Cached chat history for {user}")

        return chats
    except Exception as e:
        log.error(f"❌ Supabase fetch failed: {e}")
        return {"error": "Supabase fetch failed", "details": str(e)}


# ---------------- BACKGROUND CONSUMER ----------------
def connect_to_rabbitmq_with_retry(max_retries=10, delay=5):
    """Retry connecting to RabbitMQ until available."""
    for attempt in range(max_retries):
        try:
            connection = pika.BlockingConnection(pika.ConnectionParameters(host="rabbitmq"))
            print("✅ Connected to RabbitMQ for reply listener.")
            return connection
        except Exception as e:
            print(f"⚠️ RabbitMQ not ready yet (attempt {attempt+1}/{max_retries}): {e}")
            time.sleep(delay)
    raise Exception("❌ Could not connect to RabbitMQ after retries.")


def listen_for_replies():
    """Threaded listener for Gemini replies."""
    try:
        connection = connect_to_rabbitmq_with_retry()
        channel = connection.channel()
        channel.queue_declare(queue="reply_queue", durable=True)
        print("👂 Listening for Gemini replies...")

        def callback(ch, method, properties, body):
            try:
                data = json.loads(body)
                username = data.get("username", "guest")
                reply_text = data.get("response", "")
                timestamp = data.get("timestamp", datetime.utcnow().isoformat())

                print(f"💬 Received Gemini reply for {username}: {reply_text}")

                # Update Supabase response
                try:
                    supabase.table("chat_history").update({"response": reply_text}).eq("username", username).order("created_at", desc=True).limit(1).execute()
                    print("✅ Supabase updated with Gemini reply.")
                except Exception as e:
                    print(f"⚠️ Supabase update failed: {e}")

                # Update Redis cache
                try:
                    cache_key = f"chat:{username}"
                    cached_data = r.get(cache_key)
                    if cached_data:
                        chats = json.loads(cached_data)
                        for chat in chats:
                            if chat.get("response") is None:
                                chat["response"] = reply_text
                                break
                        r.set(cache_key, json.dumps(chats))
                        print("🧠 Updated Redis cache with Gemini reply.")
                except Exception as e:
                    print(f"⚠️ Redis cache update failed: {e}")

                ch.basic_ack(delivery_tag=method.delivery_tag)
            except Exception as e:
                print(f"❌ Error processing reply: {e}")
                ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

        channel.basic_consume(queue="reply_queue", on_message_callback=callback, auto_ack=False)
        channel.start_consuming()

    except Exception as e:
        print(f"❌ Reply listener error: {e}")


@app.on_event("startup")
async def startup_event():
    log.info("🚀 Chat backend started successfully")
    threading.Thread(target=listen_for_replies, daemon=True).start()
