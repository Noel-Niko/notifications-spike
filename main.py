# app.py
"""
FastAPI + asyncio client for Genesys Cloud Notifications API that:
- Authenticates via OAuth client credentials
- Creates a notifications channel and subscribes to an agent's conversation feed
- Dynamically subscribes to each conversation's transcript topic
- Persists raw transcript events to per-conversation JSONL files

Run:
  pip install -r requirements.txt
  uvicorn app:app --host 0.0.0.0 --port 8000 --reload


"""
from __future__ import annotations
import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

import httpx
import websockets
from fastapi import FastAPI
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s %(message)s')
log = logging.getLogger("transcript-recorder")

REGION_API_BASE = os.environ.get("REGION_API_BASE")
REGION_LOGIN_BASE = os.environ.get("REGION_LOGIN_BASE")
CLIENT_ID = os.environ.get("CLIENT_ID")
CLIENT_SECRET = os.environ.get("CLIENT_SECRET")
AGENT_EMAILS_FILE = os.environ.get("AGENT_EMAILS_FILE", "agents.txt")
AGENT_TOPIC_TEMPLATE = os.environ.get("AGENT_TOPIC_TEMPLATE", "v2.users.{user_id}.conversations")
MAX_CONCURRENT_CONVERSATIONS = int(os.environ.get("MAX_CONVERSATIONS", "10"))
CONVERSATION_EVENT_DIR = os.environ.get("CONVERSATION_EVENT_DIR", "conversation_events")

if not all([REGION_API_BASE, REGION_LOGIN_BASE, CLIENT_ID, CLIENT_SECRET]):
    missing = [k for k, v in {
        "REGION_API_BASE": REGION_API_BASE,
        "REGION_LOGIN_BASE": REGION_LOGIN_BASE,
        "CLIENT_ID": CLIENT_ID,
        "CLIENT_SECRET": CLIENT_SECRET,
    }.items() if not v]
    if not AGENT_EMAILS_FILE:
        missing.append("AGENT_EMAILS_FILE")
    if "{user_id}" not in (AGENT_TOPIC_TEMPLATE or ""):
        missing.append("AGENT_TOPIC_TEMPLATE must include {user_id}")
    raise SystemExit(f"Missing required env vars: {', '.join(missing)}")

if MAX_CONCURRENT_CONVERSATIONS < 1:
    raise SystemExit("MAX_CONVERSATIONS must be >= 1")

AGENT_EMAILS_PATH = Path(AGENT_EMAILS_FILE)

def load_agent_emails(path: Path) -> List[str]:
    emails: List[str] = []
    if not path.exists():
        raise SystemExit(f"Agent email file not found: {path}")

    with path.open("r", encoding="utf-8") as handle:
        for raw in handle:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            emails.append(line)
    if not emails:
        raise SystemExit(f"Agent email file {path} contained no addresses")
    return emails


CONVERSATION_EVENT_PATH = Path(CONVERSATION_EVENT_DIR)
CONVERSATION_EVENT_PATH.mkdir(parents=True, exist_ok=True)

channel_id: Optional[str] = None
connect_uri: Optional[str] = None


@dataclass
class ActiveConversationState:
    topic: str
    file_path: str


active_conversations: Dict[str, ActiveConversationState] = {}
subscription_topics: Set[str] = set()
subscription_lock = asyncio.Lock()

def conversation_file_path(conv_id: str) -> Path:
    return CONVERSATION_EVENT_PATH / f"{conv_id}.jsonl"


async def activate_conversation(
    client: httpx.AsyncClient,
    token: str,
    chan_id: str,
    conv_id: str,
) -> bool:
    if conv_id in active_conversations:
        return True

    if len(active_conversations) >= MAX_CONCURRENT_CONVERSATIONS:
        log.info(
            "Skipping activation for %s; active=%s/%s",
            conv_id,
            len(active_conversations),
            MAX_CONCURRENT_CONVERSATIONS,
        )
        return False

    topic = f"v2.conversations.{conv_id}.transcription"
    await update_channel_topics(client, token, chan_id, add=[topic])
    file_path = conversation_file_path(conv_id)
    file_path.touch(exist_ok=True)
    active_conversations[conv_id] = ActiveConversationState(topic=topic, file_path=str(file_path))
    log.info(
        "Subscribed to transcripts for conversation %s (active=%s/%s)",
        conv_id,
        len(active_conversations),
        MAX_CONCURRENT_CONVERSATIONS,
    )
    return True

async def deactivate_conversation(
    client: httpx.AsyncClient,
    token: str,
    chan_id: str,
    conv_id: str,
):
    state = active_conversations.pop(conv_id, None)
    if state is None:
        return

    await update_channel_topics(client, token, chan_id, remove=[state.topic])
    log.info(
        "Stopped tracking conversation %s (active=%s/%s)",
        conv_id,
        len(active_conversations),
        MAX_CONCURRENT_CONVERSATIONS,
    )


async def schedule_conversation(
    client: httpx.AsyncClient,
    token: str,
    chan_id: str,
    conv_id: str,
):
    if conv_id in active_conversations:
        return
    if len(active_conversations) >= MAX_CONCURRENT_CONVERSATIONS:
        log.info(
            "Capacity full; ignoring conversation %s (active=%s/%s)",
            conv_id,
            len(active_conversations),
            MAX_CONCURRENT_CONVERSATIONS,
        )
        return
    await activate_conversation(client, token, chan_id, conv_id)


# ------------ OAuth + Subscriptions -------------
async def get_token(client: httpx.AsyncClient) -> str:
    data = {"grant_type": "client_credentials"}
    resp = await client.post(
        f"{REGION_LOGIN_BASE}/oauth/token",
        data=data,
        auth=(CLIENT_ID, CLIENT_SECRET),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    resp.raise_for_status()
    tok = resp.json()["access_token"]
    return tok

async def create_channel(client: httpx.AsyncClient, token: str) -> Dict[str, Any]:
    resp = await client.post(
        f"{REGION_API_BASE}/api/v2/notifications/channels",
        headers={"Authorization": f"Bearer {token}"},
    )
    resp.raise_for_status()
    return resp.json()  # { id, connectUri }

async def subscribe_topics(client: httpx.AsyncClient, token: str, chan_id: str, topics: List[str]):
    body = [{"id": t} for t in topics]
    log.info("Subscribing channel %s to topics: %s", chan_id, topics)
    resp = await client.put(
        f"{REGION_API_BASE}/api/v2/notifications/channels/{chan_id}/subscriptions",
        json=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    resp.raise_for_status()
    return resp.json()


async def update_channel_topics(
    client: httpx.AsyncClient,
    token: str,
    chan_id: str,
    *,
    add: Iterable[str] = (),
    remove: Iterable[str] = (),
) -> Set[str]:
    async with subscription_lock:
        current = set(subscription_topics)
        updated = set(current)
        changed = False
        for topic in add:
            if topic not in updated:
                updated.add(topic)
                changed = True
        for topic in remove:
            if topic in updated:
                updated.remove(topic)
                changed = True
        if not changed:
            return current

        topics_list = sorted(updated)
        await subscribe_topics(client, token, chan_id, topics_list)
        subscription_topics.clear()
        subscription_topics.update(topics_list)
        return set(subscription_topics)


def _read_error_detail(resp: httpx.Response) -> str:
    try:
        payload = resp.json()
        return json.dumps(payload)
    except Exception:
        try:
            return resp.text
        except Exception:
            return "<unable to read error body>"


async def resolve_agent_user_id(client: httpx.AsyncClient, token: str, email: str) -> str:
    body = {
        "pageSize": 1,
        "query": [
            {
                "type": "TERM",
                "fields": ["email"],
                "value": email,
            }
        ],
    }
    resp = await client.post(
        f"{REGION_API_BASE}/api/v2/users/search",
        json=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    resp.raise_for_status()
    data = resp.json()
    results = data.get("results") or data.get("entities") or []
    if not results:
        raise SystemExit(f"No Genesys user found for email {email}")
    agent = results[0]
    agent_id = agent.get("id")
    if not agent_id:
        raise SystemExit(f"Genesys user lookup for {email} returned no id")
    log.info(f"Resolved agent email {email} to id {agent_id}")
    return agent_id


async def resolve_agent_user_ids(client: httpx.AsyncClient, token: str, emails: List[str]) -> Dict[str, str]:
    resolved: Dict[str, str] = {}
    for email in emails:
        normalized = email.strip()
        if not normalized:
            continue
        if normalized in resolved:
            continue
        resolved[normalized] = await resolve_agent_user_id(client, token, normalized)
    return resolved


async def fetch_available_topics(client: httpx.AsyncClient, token: str) -> List[str]:
    resp = await client.get(
        f"{REGION_API_BASE}/api/v2/notifications/availabletopics",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        },
    )
    resp.raise_for_status()
    payload = resp.json()
    entities = payload.get("entities") or payload.get("topics") or []
    out: List[str] = []
    for ent in entities:
        if isinstance(ent, dict):
            tid = ent.get("id")
            if tid:
                out.append(tid)
        elif isinstance(ent, str):
            out.append(ent)
    return out


def _build_agent_topic(user_id: str) -> str:
    try:
        return (AGENT_TOPIC_TEMPLATE or "v2.users.{user_id}.conversations").format(user_id=user_id)
    except KeyError as exc:
        raise SystemExit(f"AGENT_TOPIC_TEMPLATE contains unsupported placeholder {exc}") from exc


async def subscribe_agent_topics(
    client: httpx.AsyncClient,
    token: str,
    chan_id: str,
    agent_user_id: str,
) -> str:
    primary_topic = _build_agent_topic(agent_user_id)
    fallbacks: List[str] = []
    summary_topic = f"v2.users.{agent_user_id}.conversationsummary"
    if primary_topic != summary_topic:
        fallbacks.append(summary_topic)

    attempts = [primary_topic] + fallbacks
    last_error: Optional[httpx.HTTPStatusError] = None
    for topic in attempts:
        try:
            await update_channel_topics(client, token, chan_id, add=[topic])
            log.info("Subscribed channel %s to agent topic %s", chan_id, topic)
            return topic
        except httpx.HTTPStatusError as exc:
            detail = _read_error_detail(exc.response)
            log.warning(
                "Subscription attempt failed for topic %s (status %s): %s",
                topic,
                exc.response.status_code,
                detail,
            )
            last_error = exc
            if exc.response.status_code not in (400, 404):
                raise

    try:
        available = await fetch_available_topics(client, token)
    except Exception as fetch_err:
        log.warning("Could not retrieve available topics: %s", fetch_err)
        available = []

    user_topics = [t for t in available if agent_user_id in t]
    log.error(
        "Unable to subscribe channel %s to any agent topics for %s. Available user topics: %s",
        chan_id,
        agent_user_id,
        user_topics[:5],
    )
    if last_error is not None:
        raise last_error
    raise RuntimeError("Failed to subscribe to agent topics; see logs for details")


# ------------ Active Conversation Recovery -------------

def extract_active_conversation_ids(
    conversations: List[Dict[str, Any]],
    agent_user_ids: Set[str],
) -> Set[str]:
    """Return conversation IDs where a monitored agent is connected and not ended.

    Pure function — no side effects, no dependency on global state.

    Args:
        conversations: List of conversation dicts from Genesys
            ``GET /api/v2/conversations`` (the ``entities`` array).
        agent_user_ids: Set of Genesys user IDs we are monitoring.

    Returns:
        Set of conversation IDs that should be subscribed to.
    """
    active: Set[str] = set()
    for conv in conversations:
        conv_id = conv.get("id")
        if not conv_id:
            continue
        for part in conv.get("participants") or []:
            if not isinstance(part, dict):
                continue
            purpose = part.get("purpose")
            if not isinstance(purpose, str) or purpose.lower() != "agent":
                continue
            if part.get("userId") not in agent_user_ids:
                continue
            if part.get("connectedTime") and not part.get("endTime"):
                active.add(conv_id)
                break
    return active


async def recover_active_conversations(
    client: httpx.AsyncClient,
    token: str,
    chan_id: str,
    agent_user_ids: Set[str],
) -> int:
    """Poll Genesys for in-progress conversations and subscribe to them.

    Called once after the WebSocket connects to catch any conversations that
    started during the startup window.

    Returns:
        Number of conversations recovered.
    """
    resp = await client.get(
        f"{REGION_API_BASE}/api/v2/conversations",
        headers={"Authorization": f"Bearer {token}"},
    )
    resp.raise_for_status()
    conversations = resp.json().get("entities") or []

    conv_ids = extract_active_conversation_ids(conversations, agent_user_ids)
    recovered = 0
    for conv_id in conv_ids:
        if conv_id not in active_conversations:
            activated = await activate_conversation(client, token, chan_id, conv_id)
            if activated:
                recovered += 1
                log.info("Recovered in-progress conversation %s", conv_id)
    if recovered:
        log.info("Recovered %d in-progress conversation(s) from startup window", recovered)
    else:
        log.info("No in-progress conversations to recover")
    return recovered


# ------------ Transcript Handling -------------
def _conversation_times(event_body: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    participants = event_body.get("participants")
    if not isinstance(participants, list):
        return None, None

    best_start: Optional[str] = None
    best_end: Optional[str] = None
    best_is_active = False

    for part in participants:
        if not isinstance(part, dict):
            continue
        purpose = part.get("purpose")
        if not isinstance(purpose, str) or purpose.lower() != "agent":
            continue

        connected = part.get("connectedTime")
        if not connected:
            continue

        ended = part.get("endTime")
        is_active = ended is None

        if best_start is None or (is_active and not best_is_active) or (
            is_active == best_is_active and connected > best_start
        ):
            best_start = connected
            best_end = ended
            best_is_active = is_active

    return best_start, best_end


async def handle_transcript_event(conv_id: str, transcript: Dict[str, Any]) -> bool:
    # transcript: { channel: 'INTERNAL'|'EXTERNAL', isFinal: bool, alternatives: [{ transcript, offsetMs, durationMs }] }
    state = active_conversations.get(conv_id)
    if state:
        record = {
            "conversationId": conv_id,
            "receivedAt": time.time(),
            "transcript": transcript,
        }
        with open(state.file_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record))
            handle.write("\n")

    return False

# ------------ WebSocket loop -------------
async def ws_loop():
    global channel_id, connect_uri
    async with httpx.AsyncClient(timeout=30) as client:
        token = await get_token(client)
        ch = await create_channel(client, token)
        channel_id = ch["id"]
        connect_uri = ch["connectUri"]
        log.info(f"Channel created id={channel_id}")

        agent_emails = load_agent_emails(AGENT_EMAILS_PATH)
        email_to_user_id = await resolve_agent_user_ids(client, token, agent_emails)
        if not email_to_user_id:
            raise SystemExit("No agent user ids resolved; cannot subscribe to conversation feeds")

        for email, agent_user_id in email_to_user_id.items():
            subscribed_topic = await subscribe_agent_topics(client, token, channel_id, agent_user_id)
            log.info("Subscribed to agent %s via topic %s", email, subscribed_topic)

        # Connect WS and handle messages
        while True:
            try:
                async with websockets.connect(connect_uri, ping_interval=20, ping_timeout=20) as ws:
                    log.info(
                        "WebSocket connected (agents=%s, max_concurrent_conversations=%s)",
                        len(email_to_user_id),
                        MAX_CONCURRENT_CONVERSATIONS,
                    )
                    # Recover conversations that started during startup
                    try:
                        await recover_active_conversations(
                            client, token, channel_id,
                            set(email_to_user_id.values()),
                        )
                    except Exception as e:
                        log.warning("Failed to recover active conversations: %s", e)

                    async for raw in ws:
                        try:
                            msg = json.loads(raw)
                        except Exception:
                            continue
                        topic = msg.get("topicName")
                        if topic == "channel.metadata":
                            continue

                        event_body = msg.get("eventBody") or {}

                        # user conversation updates -> enqueue conversation for transcription
                        if topic and topic.startswith("v2.users.") and event_body.get("id"):
                            conv_id = event_body["id"]
                            call_start, call_end = _conversation_times(event_body)
                            log.info(
                                "Conversation %s agent state: connected=%s ended=%s",
                                conv_id,
                                bool(call_start),
                                bool(call_end),
                            )
                            if call_start and not call_end:
                                await schedule_conversation(client, token, channel_id, conv_id)
                            elif call_end:
                                if conv_id in active_conversations:
                                    await deactivate_conversation(client, token, channel_id, conv_id)
                            
                        # transcript events
                        if topic and topic.startswith("v2.conversations.") and event_body.get("transcripts"):
                            parts = topic.split(".")
                            if len(parts) >= 3:
                                conv_id = parts[2]
                                for tr in event_body.get("transcripts") or []:
                                    await handle_transcript_event(conv_id, tr)
            except Exception as e:
                log.warning(f"WS loop error: {e}; reconnecting in 3s")
                await asyncio.sleep(3)

# ------------ FastAPI app -------------
app = FastAPI(title="Genesys Transcript Recorder (FastAPI)", version="0.1.0")

@app.on_event("startup")
async def _startup():
    asyncio.create_task(ws_loop())

@app.get("/health")
async def health():
    return {"ok": True, "active_conversations": len(active_conversations)}

# ------------- requirements.txt (for reference) -------------
# fastapi
# uvicorn[standard]
# httpx
# websockets
# python-dotenv
# pydantic
