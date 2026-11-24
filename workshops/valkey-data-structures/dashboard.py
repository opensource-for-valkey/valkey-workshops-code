"""A read-only Textual dashboard for the five conference backend patterns."""

from textual.app import App, ComposeResult
from textual.widgets import DataTable, Footer, Header, Static

from common import LatencyTimer, key, text, timed
from valkey_client import ValkeyClientManager


class WorkshopDashboard(App):
    TITLE = "Valkey · Conference backend"
    BINDINGS = [("q", "quit", "Quit"), ("r", "refresh", "Refresh")]
    CSS = """
    Screen { background: #182330; }
    #status { height: 7; border: round #8faadc; padding: 1; }
    DataTable { height: 1fr; border: round #8faadc; }
    """

    def __init__(self, client):
        super().__init__()
        self.client = client

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("", id="status")
        yield DataTable(id="patterns")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one(DataTable).add_columns("Pattern", "Valkey latency (ms)", "Live observation", "Key")
        self.action_refresh()
        self.set_interval(1, self.action_refresh)

    def action_refresh(self) -> None:
        table = self.query_one(DataTable)
        table.clear()
        cache_key = key("cache", "product", "v1", "speaker")
        session = key("session", "demo-session")
        board = key("leaderboard", "conference")
        channel = key("events", "scores")
        ready = key("queue", "ready")
        # Each row times its own request; total refresh includes all six reads.
        with LatencyTimer() as refresh:
            observations = [
                ("Strings", cache_key, lambda: f"TTL {self.client.ttl(cache_key)} seconds"),
                ("Hashes", session, lambda: f"{self.client.hlen(session)} fields"),
                ("Sorted Sets", board, lambda: f"{self.client.zcard(board)} players"),
                ("Pub/Sub", channel, lambda: (
                    f"{self.client.pubsub_numsub([channel]).get(channel.encode(), 0)} live subscriptions"
                )),
                ("Lists", ready, lambda: f"{self.client.llen(ready)} ready jobs"),
            ]
            rows = []
            for pattern, name, operation in observations:
                observation, elapsed_ms = timed(operation)
                rows.append((pattern, f"{elapsed_ms:.3f}", observation, name))
            pong, ping_ms = timed(self.client.ping)
        for row in rows:
            table.add_row(*row)
        self.query_one("#status", Static).update(
            f"{text(pong)} · GLIDE · key prefix {key()}\n"
            f"PING: {ping_ms:.3f} ms · refresh: {refresh.elapsed_ms:.3f} ms\n"
            "Client-observed latency; this view refreshes each second."
        )


def main() -> None:
    with ValkeyClientManager() as client:
        WorkshopDashboard(client).run()


if __name__ == "__main__":
    main()
