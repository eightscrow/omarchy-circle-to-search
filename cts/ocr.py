"""OCR (Tesseract), Ollama translation, caching."""

import hashlib
import json
import threading
from collections import OrderedDict
from urllib.request import Request, urlopen

import cts


class TranslationCache:
    def __init__(self, max_size=500):
        self._cache = OrderedDict()
        self.max_size = max_size
        self.lock = threading.Lock()

    def _hash_text(self, text):
        normalized = ' '.join(text.split()).lower()
        return hashlib.md5(normalized.encode()).hexdigest()

    def get(self, text):
        key = self._hash_text(text)
        with self.lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
        return None

    def set(self, text, translation):
        key = self._hash_text(text)
        with self.lock:
            if key in self._cache:
                self._cache.move_to_end(key)
            self._cache[key] = translation
            while len(self._cache) > self.max_size:
                self._cache.popitem(last=False)


class OllamaTranslator:
    OLLAMA_URL = "http://localhost:11434/api/generate"
    TIMEOUT = 120

    def __init__(self):
        self.model = cts.USER_CONFIG.get('ollama_model', 'qwen2.5:7b')
        self.target_lang = cts.USER_CONFIG.get('translation_target', 'English')
        self.available = self._check_availability()

    def _check_availability(self):
        try:
            req = Request("http://localhost:11434/api/tags")
            with urlopen(req, timeout=2) as resp:
                return resp.status == 200
        except Exception:
            return False

    def translate(self, text, target_lang=None):
        if not text.strip():
            return text

        target_lang = target_lang or self.target_lang

        prompt = (
            f"Translate to {target_lang}. Output only the translation.\n\n"
            f"Example:\n"
            f"Input: Привет, как дела?\n"
            f"Output: Hello, how are you?\n\n"
            f"Input: {text}\n"
            f"Output:"
        )

        try:
            data = json.dumps({
                "model": self.model,
                "prompt": prompt,
                "stream": True,
            }).encode()

            req = Request(self.OLLAMA_URL, data=data)
            req.add_header("Content-Type", "application/json")

            response_text = []
            with urlopen(req, timeout=self.TIMEOUT) as resp:
                for line in resp:
                    try:
                        chunk = json.loads(line.decode())
                        if chunk.get("response"):
                            response_text.append(chunk["response"])
                        if chunk.get("done"):
                            break
                    except json.JSONDecodeError:
                        continue

            response = ''.join(response_text).strip()
            if len(response) > 2 and response.startswith('"') and response.endswith('"'):
                response = response[1:-1]
            return response if response else None
        except Exception:
            return None
