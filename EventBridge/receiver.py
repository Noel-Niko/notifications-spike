from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timezone
import json


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length)
        received_at = datetime.now(timezone.utc)

        try:
            event = json.loads(body)
            eb_time = event.get('time', '')
            detail = event.get('detail', {})
            event_body = detail.get('eventBody', {})
            conversation_id = event_body.get('conversationId', 'unknown')
            transcripts = event_body.get('transcripts', [])

            for t in transcripts:
                channel = t.get('channel', '?')
                for alt in t.get('alternatives', []):
                    text = alt.get('transcript', '')
                    confidence = alt.get('confidence', 0)
                    print(f"\n[RECEIVED {received_at.isoformat()}]")
                    print(f"  EB time:  {eb_time}")
                    print(f"  Conv:     {conversation_id}")
                    print(f"  Channel:  {channel}")
                    print(f"  Text:     \"{text}\"")
                    print(f"  Confidence: {confidence}")
        except Exception as e:
            print(f"\n[RAW EVENT {received_at.isoformat()}]")
            print(body.decode('utf-8', errors='replace'))

        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'OK')

    def log_message(self, format, *args):
        pass  # suppress default logging


print("Listening on port 8080...")
HTTPServer(('0.0.0.0', 8080), Handler).serve_forever()