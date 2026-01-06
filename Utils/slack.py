import json

import requests


class SlackNotifier:
    def __init__(self, webhook_url=None):
        self.webhook_url = webhook_url

    def send(self, title, message):
        if not self.webhook_url:
            print(f"[Slack Skip] URL not set: {title}")
            return

        payload = {
            "blocks": [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": title, "emoji": True},
                },
                {"type": "section", "text": {"type": "mrkdwn", "text": message}},
                {"type": "divider"},
            ]
        }

        try:
            response = requests.post(
                self.webhook_url,
                data=json.dumps(payload),
                headers={"Content-Type": "application/json"},
            )
            if response.status_code != 200:
                print(
                    f"❌ Slack Failed to send: {response.status_code} - {response.text}"
                )
        except Exception as e:
            print(f"❌ Slack Connection error: {e}")
