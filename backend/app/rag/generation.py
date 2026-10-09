"""Answer generation from retrieved passages.

Two implementations share one interface:
  * LLMAnswerGenerator   - asks the configured chat model (Gemini) for a cited answer.
  * ExtractiveAnswerGenerator - demo mode: quotes the passage sentences that best match
    the question. No model, no API key, and it can only repeat what the documents say.
"""

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from functools import lru_cache

from app.core.config import get_settings
from app.rag.prompts import ABSTAIN_TOKEN, SYSTEM_PROMPT, build_user_prompt
from app.rag.providers.base import ChatMessage, ChatProvider
from app.rag.retrieval import RetrievedChunk
from app.rag.text import split_sentences, term_matches, terms

MAX_ANSWER_CHARS = 4000
_CITATION = re.compile(r"\[(\d{1,2})\]")
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


@dataclass
class GeneratedAnswer:
    text: str
    cited: list[int] = field(default_factory=list)  # 1-based source numbers, sorted
    abstained: bool = False


class AnswerGenerator(ABC):
    name: str
    model: str
    is_demo: bool = False

    @abstractmethod
    def generate(
        self, question: str, history: list[ChatMessage], sources: list[RetrievedChunk]
    ) -> GeneratedAnswer:
        """Raises ProviderError if the underlying model fails."""


def sanitize_output(text: str) -> str:
    """Remove control characters and cap the length of model output."""
    text = _CONTROL_CHARS.sub("", text).strip()
    if len(text) > MAX_ANSWER_CHARS:
        text = text[:MAX_ANSWER_CHARS].rsplit(" ", 1)[0] + "..."
    return text


def parse_answer(raw: str, source_count: int) -> GeneratedAnswer:
    """Detect abstention, keep only citations that point at a real source."""
    text = sanitize_output(raw)
    if not text or ABSTAIN_TOKEN in text:
        return GeneratedAnswer(text="", abstained=True)

    def keep_valid(match: re.Match[str]) -> str:
        number = int(match.group(1))
        return match.group(0) if 1 <= number <= source_count else ""

    text = _CITATION.sub(keep_valid, text)
    cited = sorted({int(n) for n in _CITATION.findall(text)})
    return GeneratedAnswer(text=text, cited=cited)


class LLMAnswerGenerator(AnswerGenerator):
    def __init__(self, chat: ChatProvider) -> None:
        self.chat = chat
        self.name = chat.name
        self.model = chat.model

    def generate(
        self, question: str, history: list[ChatMessage], sources: list[RetrievedChunk]
    ) -> GeneratedAnswer:
        messages = [*history, ChatMessage("user", build_user_prompt(question, sources))]
        raw = self.chat.generate(SYSTEM_PROMPT, messages)
        return parse_answer(raw, len(sources))


class ExtractiveAnswerGenerator(AnswerGenerator):
    """Demo mode: quote the part of the best passage that matches the question.

    Finds the sentence or line sharing the most key terms with the question, then quotes
    it together with the lines that follow (a heading plus its list, or a sentence plus
    its details), up to WINDOW_CHARS. It never writes anything that is not in a document.
    """

    name = "demo"
    model = "extractive-v1"
    is_demo = True

    WINDOW_CHARS = 450

    def generate(
        self, question: str, history: list[ChatMessage], sources: list[RetrievedChunk]
    ) -> GeneratedAnswer:
        question_terms = set(terms(question))
        if not question_terms or not sources:
            return GeneratedAnswer(text="", abstained=True)

        best: tuple[float, int, int, list[str]] | None = None
        for number, source in enumerate(sources, start=1):
            sentences = split_sentences(source.content)
            for position, sentence in enumerate(sentences):
                vocabulary = set(terms(sentence))
                matched = sum(1 for term in question_terms if term_matches(term, vocabulary))
                if matched == 0:
                    continue
                # More of the question covered wins; ties go to the better-ranked passage.
                score = matched / len(question_terms) + 0.25 * source.score
                if best is None or score > best[0]:
                    best = (score, number, position, sentences)
        if best is None:
            return GeneratedAnswer(text="", abstained=True)

        _, number, start, sentences = best
        window: list[str] = []
        length = 0
        for sentence in sentences[start:]:
            if window and length + len(sentence) > self.WINDOW_CHARS:
                break
            window.append(sentence)
            length += len(sentence)
        lines = "\n".join(f"- {sentence}" for sentence in window)
        text = f"Here is what our documentation says:\n\n{lines} [{number}]"
        return GeneratedAnswer(text=text, cited=[number])


@lru_cache
def get_answer_generator() -> AnswerGenerator:
    settings = get_settings()
    if settings.llm_provider == "demo":
        return ExtractiveAnswerGenerator()

    from app.rag.providers.gemini import GeminiChatProvider

    return LLMAnswerGenerator(GeminiChatProvider(settings))
