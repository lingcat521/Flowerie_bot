"""Parse DuckDuckGo's HTML result cards with the standard HTML parser."""

from html.parser import HTMLParser


class DuckDuckGoResults(HTMLParser):
    def __init__(self, html: str):
        super().__init__()
        self.results: list[dict[str, str]] = []
        self._card: dict[str, str] | None = None
        self._div_depth = 0
        self._field = ""
        self._pieces: list[str] = []
        self.feed(html)
        self.close()

    def _finish_field(self) -> None:
        if self._card is not None and self._field:
            self._card[self._field] = " ".join(" ".join(self._pieces).split())
            self._field = ""
            self._pieces.clear()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = (attributes.get("class") or "").split()
        if tag == "div":
            if {"result", "results_links"}.issubset(classes):
                self._finish_field()
                self._card = {}
                self.results.append(self._card)
                self._div_depth = 0
            if self._card is not None:
                self._div_depth += 1
        if self._card is None or tag != "a":
            return
        if "result__a" in classes and attributes.get("href"):
            self._finish_field()
            self._card["href"] = attributes["href"]
            self._field = "title"
        elif "result__snippet" in classes:
            self._finish_field()
            self._field = "snippet"

    def handle_endtag(self, tag: str) -> None:
        if self._card is None:
            return
        if tag == "a":
            self._finish_field()
        elif tag == "div":
            self._div_depth -= 1
            if self._div_depth == 0:
                self._finish_field()
                self._card = None

    def handle_data(self, data: str) -> None:
        if self._field:
            self._pieces.append(data)
