import json
import os
import threading
from dataclasses import dataclass, asdict
from typing import Optional


@dataclass
class Prompt:
    name: str
    template: str
    description: str = ""
    category: str = "general"


class PromptStorage:
    def __init__(self, filepath: str = "prompts.json"):
        self.filepath = filepath
        self._lock = threading.Lock()
        self._data: dict = {"prompts": {}, "active": {}}
        self._load()

    def _load(self):
        if os.path.exists(self.filepath):
            with open(self.filepath, "r", encoding="utf-8") as f:
                self._data = json.load(f)
        if "prompts" not in self._data:
            self._data["prompts"] = {}
        if "active" not in self._data:
            self._data["active"] = {}

    def _save(self):
        with open(self.filepath, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    def add(self, prompt: Prompt) -> bool:
        with self._lock:
            self._data["prompts"][prompt.name] = asdict(prompt)
            self._save()
        return True

    def update(self, prompt: Prompt) -> bool:
        with self._lock:
            if prompt.name not in self._data["prompts"]:
                return False
            self._data["prompts"][prompt.name] = asdict(prompt)
            self._save()
        return True

    def get(self, name: str) -> Optional[Prompt]:
        data = self._data["prompts"].get(name)
        if not data:
            return None
        return Prompt(**data)

    def delete(self, name: str) -> bool:
        with self._lock:
            if name not in self._data["prompts"]:
                return False
            del self._data["prompts"][name]
            for uid, active in list(self._data["active"].items()):
                if active == name:
                    del self._data["active"][uid]
            self._save()
        return True

    def list_all(self) -> list[Prompt]:
        return [Prompt(**v) for v in self._data["prompts"].values()]

    def list_by_category(self, category: str) -> list[Prompt]:
        return [p for p in self.list_all() if p.category == category]

    def search(self, query: str) -> list[Prompt]:
        q = query.lower()
        return [
            p for p in self.list_all()
            if q in p.name.lower() or q in p.description.lower()
        ]

    def set_active(self, user_id: int, prompt_name: str):
        with self._lock:
            self._data["active"][str(user_id)] = prompt_name
            self._save()

    def get_active(self, user_id: int) -> Optional[Prompt]:
        name = self._data["active"].get(str(user_id))
        return self.get(name) if name else None

    def clear_active(self, user_id: int):
        with self._lock:
            self._data["active"].pop(str(user_id), None)
            self._save()

    def categories(self) -> list[str]:
        return list({p.category for p in self.list_all()})
