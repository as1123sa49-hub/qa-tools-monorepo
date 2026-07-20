import logging

logger = logging.getLogger(__name__)


class GameConfig:
    """Wrapper class for Game Configuration (YAML)."""

    def __init__(self, game_id: str, raw_data: dict):
        self.game_id = game_id
        self._data = raw_data
        self.name = raw_data.get("name", "Unknown Game")
        self.search_keyword = raw_data.get("search_keyword", "")

    @property
    def icon_offset_y(self) -> int:
        return self._data.get("icon_offset_y", 100)

    @property
    def spin_button_prompt(self) -> str:
        return self._data.get("spin_button", {}).get("prompt", "")

    @property
    def spin_button_idle_prompt(self) -> str:
        spin_data = self._data.get("spin_button", {})
        return spin_data.get("idle_prompt", spin_data.get("prompt", ""))

    @property
    def layout(self) -> str:
        resolved = self._data.get("_resolved_layout")
        if resolved in ("portrait", "landscape"):
            return resolved
        return self._data.get("layout", "landscape")

    @property
    def is_portrait(self) -> bool:
        return self.layout == "portrait"

    @property
    def spin_region(self) -> dict:
        return self._data.get("spin_button", {}).get(
            "region",
            {
                "x_start": 0.0,
                "x_end": 1.0,
                "y_start": 0.0,
                "y_end": 1.0,
            },
        )

    @property
    def balance_keywords(self) -> list:
        return self._data.get("balance_check", {}).get("keywords", ["balance"])

    def get_label_key(self) -> str:
        return f"{self.game_id}_label"

    def __repr__(self):
        return f"<GameConfig id={self.game_id} name='{self.name}'>"
