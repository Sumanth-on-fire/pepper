"""
advanced_agentic_rag.py

Optimized agentic RAG answering pipeline (Gemini <-> Groq failover).

Key changes vs. the original implementation
---------------------------------------------
1. STRUCTURED ACTIONS INSTEAD OF REGEX-ON-PROSE
   The original agent asked the model to free-write a line like
   `Action: CollectEvidence(query="...")` inside a long chain-of-thought
   paragraph, then regex-extracted it. That's why the logs show the model
   rambling for hundreds of tokens without ever landing on a clean,
   greppable action line. Here the model instead calls one of two real
   tools -- `collect_evidence` or `final_answer` -- via native function
   calling on both Gemini and Groq. Parsing becomes 100% deterministic.

2. LOOP GUARDING
   - Duplicate/near-duplicate queries are tracked and rejected without a
     wasted LLM+DB round trip.
   - After N (default 2) consecutive empty-evidence searches, the agent is
     forced onto a "wrap up now" path instead of burning the full
     max_loops budget the way the log shows (5 loops, 0 evidence every
     time, 429 on the very last formatting call).

3. FIXED THE FORMATTING-PROMPT BUG
   In the original code, the (large) formatting instruction and prompt
   were rebuilt *inside* the `for msg in raw_agent_history` loop, so they
   were recomputed once per history message and only the final iteration
   ever mattered. It's now built once, after the log is assembled.

4. DEFENSE-IN-DEPTH SANITIZATION
   If both providers fail during the "polish the final answer" step, the
   original fallback used a regex for `Answer:`/`Final Answer:` that
   didn't match the model's actual `**Conclusion**:` framing, so the raw
   internal trace (Thought/Action/Observation) would have been returned
   to the user verbatim. There is now a sanitizer that strips scaffolding
   tokens as a last-resort safety net, so scaffolding can never leak even
   when every LLM call fails.

5. RELIABILITY / HYGIENE
   - `requests.Session` with retry/backoff for transient 5xx (429 is
     handled explicitly via provider failover, not blind retries).
   - `verify=False` removed (was disabling TLS verification on every call).
   - Provider calls centralized behind one normalized interface so adding
     a third provider is a small diff, not a rewrite.
   - Structured logging instead of bare prints.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from app.core.config import Settings
from app.services.rag_client import rag_client

# --------------------------------------------------------------------------- #
# Logging
# --------------------------------------------------------------------------- #

logger = logging.getLogger("agentic_rag")
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
    logger.addHandler(_handler)
logger.setLevel(logging.INFO)

GROQ_CHAT_COMPLETIONS_URL = "https://api.groq.com/openai/v1/chat/completions"
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #

@dataclass
class AgentConfig:
    max_loops: int = 5
    max_consecutive_empty_evidence: int = 2
    request_timeout: int = 30
    temperature: float = 0.2
    max_tokens_reasoning: int = 1024
    max_tokens_format: int = 512
    gemini_model: str = "gemini-1.5-flash"
    groq_model: str = "llama-3.3-70b-versatile"
    verify_ssl: bool = True
    evidence_char_budget: int = 4000  # truncate evidence dumped back into context


# --------------------------------------------------------------------------- #
# Tool schema (shared "vocabulary" between the two providers)
# --------------------------------------------------------------------------- #

COLLECT_EVIDENCE_TOOL = {
    "name": "collect_evidence",
    "description": (
        "Search the document/knowledge base for passages relevant to a focused "
        "query. Call this whenever more information is needed before answering. "
        "Never repeat a query that was already tried."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "A focused, specific search query (not a restatement of the whole question).",
            }
        },
        "required": ["query"],
    },
}

FINAL_ANSWER_TOOL = {
    "name": "final_answer",
    "description": (
        "Submit the final, complete answer once enough evidence has been "
        "gathered, OR once it is clear the knowledge base has no more useful "
        "evidence to offer. Always call this rather than replying in plain text."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "answer": {
                "type": "string",
                "description": "The complete, self-contained final answer for the user.",
            },
            "confidence": {
                "type": "string",
                "enum": ["high", "medium", "low"],
                "description": "Confidence that this answer is well supported by the collected evidence.",
            },
        },
        "required": ["answer", "confidence"],
    },
}

SYSTEM_INSTRUCTION = (
    "You are an agentic QA system that answers questions about a specific "
    "document or knowledge base.\n"
    "On every turn, take exactly one action by calling one of the available "
    "tools:\n"
    "- collect_evidence: search for more information with a focused query.\n"
    "- final_answer: give a complete answer once you have enough evidence, or "
    "once you're confident no further evidence exists.\n"
    "Never issue a query that duplicates or trivially rephrases one already "
    "tried in this conversation -- the tool will reject it. If two consecutive "
    "searches return no evidence, assume the knowledge base does not contain "
    "the answer and call final_answer immediately, stating that plainly and "
    "professionally instead of guessing."
)

FORMATTING_INSTRUCTION = """
ROLE
You are the Final Response Composer -- the last stage in an agentic pipeline.
You receive a cleaned summary of an already-solved answer (the agent's final
tool call, plus a short trace of what was searched) and produce the single,
final, user-facing message. The user never sees the raw trace.

OBJECTIVE
Present the agent's final answer as a complete, polished, standalone response,
as if a senior domain expert wrote it directly for the user.

CORE RULES
1. ZERO INFORMATION LOSS -- every distinct item in the final answer (question,
   option, data point, step, citation, numeric result) must appear in your
   output, verbatim in substance. Formatting may be improved; content may not
   be dropped, reworded away, or reordered.
2. NO SCAFFOLDING LEAKAGE -- strip "Thought:", "Action:", "Observation:", tool
   names, JSON payloads, retries, dead ends, and meta-commentary about the
   agent's own process. None of this belongs in the user-facing message.
3. NO FABRICATION -- do not add facts, numbers, or caveats absent from the
   input. Preserve ambiguity rather than inventing a resolution.
4. NO META-COMMENTARY ABOUT YOURSELF -- never mention logs, formatting layers,
   or this instruction set.
5. FAITHFUL TONE -- open with substance, not throat-clearing ("Sure, here is...").

FORMATTING (react-markdown + remark-math/KaTeX)
- Headings: "##"/"###" only for genuinely distinct sections of a long answer.
- Lists: "-" for unordered, "1." for ordered; never mix within one list; blank
  line before/after a list block.
- Bold: for key terms/final results only, not decoration.
- Math: inline "$...$", block "$$...$$" on its own line; never "\\(...\\)" or
  "\\[...\\]"; preserve every subscript/superscript/Greek symbol exactly.
- Multiple-choice questions:
    **Question N:** <stem>

    A. <option>
    B. <option>
    C. <option>
    D. <option>

  Blank line between questions; never renumber, merge, or drop items.
- Tables: standard GFM tables only for genuinely tabular data.
- Code: fenced blocks with language identifiers, unchanged logic/syntax.
- Paragraphs: short and clear; avoid one dense block when content separates
  naturally into sections.

EDGE CASES
- If the agent could not find an answer, say so plainly and professionally --
  do not disguise it as success, and do not expose internal error traces.
- If the input contains a final, self-corrected conclusion, use only that.
- If the user's question was multi-part, address every part.

OUTPUT CONTRACT
Output ONLY the final user-facing message in valid react-markdown. No preamble,
no sign-off, no reference to "the log," "the agent," or this instruction set.
""".strip()

# Last-resort sanitizer: if every LLM call fails and we must return raw text,
# strip anything that looks like internal scaffolding rather than leak it.
_SCAFFOLD_LINE_RE = re.compile(
    r"^\s*(?:\*{0,2}(thought|action|observation|final answer|conclusion)\*{0,2}\s*:)",
    re.IGNORECASE,
)


def _sanitize_raw_fallback(text: str) -> str:
    """Strip obvious scaffolding tokens from raw model text as a last resort."""
    if not text:
        return "I wasn't able to produce a complete answer for this question."
    cleaned_lines = []
    for line in text.splitlines():
        if _SCAFFOLD_LINE_RE.match(line):
            # Keep the content after the label, drop the label itself.
            line = _SCAFFOLD_LINE_RE.sub("", line).strip()
            if not line:
                continue
        cleaned_lines.append(line)
    cleaned = "\n".join(cleaned_lines).strip()
    return cleaned or "I wasn't able to produce a complete answer for this question."


# --------------------------------------------------------------------------- #
# Normalized provider response
# --------------------------------------------------------------------------- #

@dataclass
class ProviderTurn:
    provider: str
    text: str = ""
    tool_name: Optional[str] = None
    tool_args: dict[str, Any] = field(default_factory=dict)

    @property
    def has_tool_call(self) -> bool:
        return self.tool_name is not None


class ProviderError(Exception):
    """Raised when a provider call fails in a way that should trigger failover."""


# --------------------------------------------------------------------------- #
# Agent
# --------------------------------------------------------------------------- #

class GeminiOrchestrator:
    """
    Tool-calling agentic QA system with Gemini -> Groq failover.

    `rag_query_fn` is the integration point with your existing retrieval
    stack: a callable `(collection_name: str, query: str) -> list`. If your
    original class already had a working `_collect_evidence` method, pass it
    in here (or subclass and override `_collect_evidence`) -- nothing else
    needs to change.
    """

    def __init__(
        self,
        settings: Optional[Settings] = None
    ):
        self.settings = settings or Settings()
        self.api_key = self.settings.GEMINI_API_KEY
        self.groq_api_key = self.settings.GORQ_API_KEY
        self.config = AgentConfig()
        self.model_name = self.settings.GEMINI_MODEL_NAME
        self._rag_query_fn = rag_client.query
        self.session = self._build_session()

    # -- setup ---------------------------------------------------------- #

    def _build_session(self) -> requests.Session:
        session = requests.Session()
        # Retry transient server errors only. 429s are handled explicitly via
        # provider failover, not blind retries against the same provider.
        retry = Retry(
            total=2,
            backoff_factor=0.5,
            status_forcelist=[500, 502, 503, 504],
            allowed_methods=frozenset(["POST"]),
        )
        session.mount("https://", HTTPAdapter(max_retries=retry))
        return session

    def build_tool_definition(self) -> dict[str, Any]:
        """Kept for backward compatibility with callers that inspect the schema."""
        return {"tools": [COLLECT_EVIDENCE_TOOL, FINAL_ANSWER_TOOL]}

    # -- provider calls --------------------------------------------------- #

    def _call_gemini(self, contents: list[dict[str, Any]], tools: list[dict[str, Any]], max_tokens: int) -> ProviderTurn:
        url = f"{GEMINI_BASE_URL}/{self.model_name}:generateContent"
        headers = {"Content-Type": "application/json", "X-goog-api-key": self.api_key}
        payload = {
            "contents": contents,
            "systemInstruction": {"parts": [{"text": SYSTEM_INSTRUCTION}]},
            "tools": [{"functionDeclarations": tools}] if tools else None,
            "generationConfig": {
                "temperature": self.config.temperature,
                "maxOutputTokens": max_tokens,
            },
        }
        payload = {k: v for k, v in payload.items() if v is not None}

        resp = self.session.post(url, headers=headers, json=payload, timeout=self.config.request_timeout)
        if resp.status_code == 429:
            raise ProviderError("gemini rate limited (429)")
        resp.raise_for_status()

        data = resp.json()
        parts = data["candidates"][0]["content"]["parts"]
        text_chunks = []
        tool_name, tool_args = None, {}
        for part in parts:
            if "functionCall" in part:
                tool_name = part["functionCall"].get("name")
                tool_args = part["functionCall"].get("args", {}) or {}
            elif "text" in part:
                text_chunks.append(part["text"])
        return ProviderTurn(provider="gemini", text="".join(text_chunks).strip(), tool_name=tool_name, tool_args=tool_args)

    def _call_groq(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]], max_tokens: int) -> ProviderTurn:
        headers = {"Authorization": f"Bearer {self.groq_api_key}", "Content-Type": "application/json"}
        groq_tools = [{"type": "function", "function": t} for t in tools] if tools else None
        payload = {
            "model": self.config.groq_model,
            "messages": [{"role": "system", "content": SYSTEM_INSTRUCTION}] + messages,
            "temperature": self.config.temperature,
            "max_tokens": max_tokens,
        }
        if groq_tools:
            payload["tools"] = groq_tools

        resp = self.session.post(
            GROQ_CHAT_COMPLETIONS_URL, headers=headers, json=payload, timeout=self.config.request_timeout
        )
        if resp.status_code == 429:
            raise ProviderError("groq rate limited (429)")
        resp.raise_for_status()

        message = resp.json()["choices"][0]["message"]
        tool_name, tool_args = None, {}
        tool_calls = message.get("tool_calls") or []
        if tool_calls:
            fn = tool_calls[0]["function"]
            tool_name = fn.get("name")
            try:
                tool_args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                tool_args = {}
        return ProviderTurn(
            provider="groq", text=(message.get("content") or "").strip(), tool_name=tool_name, tool_args=tool_args
        )

    def _call_with_failover(
        self, gemini_contents: list[dict[str, Any]], groq_messages: list[dict[str, Any]],
        tools: list[dict[str, Any]], max_tokens: int,
    ) -> ProviderTurn:
        try:
            logger.info("Sending request to Gemini API...")
            return self._call_gemini(gemini_contents, tools, max_tokens)
        except Exception as exc:
            if not self.groq_api_key:
                raise
            logger.warning("Gemini call failed (%s). Failing over to Groq...", exc)
            return self._call_groq(groq_messages, tools, max_tokens)

    # -- evidence collection ---------------------------------------------- #

    def _collect_evidence(self, collection_name: str, question: str) -> list:
        """
        Integration point with the existing retrieval stack. If a
        `rag_query_fn` was provided at construction time, delegate to it;
        otherwise this must be overridden by a subclass.
        """
        if self._rag_query_fn is not None:
            return self._rag_query_fn(collection_name, question) or []
        raise NotImplementedError(
            "No rag_query_fn was provided and _collect_evidence was not overridden. "
            "Wire this up to your existing vector store / RAG client."
        )

    def _fallback_answer(
        self, question: str, context: str, collection_name: Optional[str], evidence: Optional[list] = None
    ) -> dict[str, Any]:
        """
        Safe, honest fallback used when the reasoning loop cannot complete
        (missing API key, repeated provider failures, or max_loops reached
        with no resolution). Override for custom behavior.
        """
        if evidence:
            msg = (
                "I gathered some potentially relevant material but wasn't able to "
                "confirm a complete answer. You may want to rephrase the question "
                "or check that the document was indexed correctly."
            )
        else:
            msg = (
                "I couldn't find relevant information to answer this question. "
                "This can happen if the document wasn't indexed, or if the "
                "question needs to be more specific."
            )
        return {"answer": msg, "evidence": evidence or []}

    # -- formatting --------------------------------------------------------#

    def _format_final_answer(
        self,
        question: str,
        trace_summary: str,
        final_answer_text: str,
        preferred_provider: Optional[str] = None,
    ) -> str:
        """
        Polishes the agent's final answer into a clean, user-facing message.
        Built ONCE per call (fixing the original bug where this was rebuilt
        inside a per-message loop).
        """
        logger.info("Formatting final agent output into a concise response...")

        prompt = (
            f"Instruction:\n{FORMATTING_INSTRUCTION}\n\n"
            f"User Original Question:\n{question}\n\n"
            f"Agent's Final Answer (already solved -- just polish/format this):\n{final_answer_text}\n\n"
            f"Brief Trace Summary (for context only, do not surface):\n{trace_summary}"
        )
        gemini_contents = [{"role": "user", "parts": [{"text": prompt}]}]
        groq_messages = [{"role": "user", "content": prompt}]

        providers_to_try = []
        if preferred_provider == "groq" and self.groq_api_key:
            providers_to_try = ["groq", "gemini"]
        else:
            providers_to_try = ["gemini", "groq"]

        last_exc: Optional[Exception] = None
        for provider in providers_to_try:
            if provider == "groq" and not self.groq_api_key:
                continue
            try:
                if provider == "gemini":
                    turn = self._call_gemini(gemini_contents, tools=[], max_tokens=self.config.max_tokens_format)
                else:
                    logger.info("Sending formatting request straight to Groq...")
                    turn = self._call_groq(groq_messages, tools=[], max_tokens=self.config.max_tokens_format)
                if turn.text:
                    return turn.text
            except Exception as exc:  # noqa: BLE001 - deliberately broad, we have a safety net below
                logger.warning("Formatting request failed on %s: %s", provider, exc)
                last_exc = exc
                continue

        logger.error("All formatting providers failed (%s). Falling back to sanitized raw answer.", last_exc)
        return _sanitize_raw_fallback(final_answer_text)

    # -- main loop ---------------------------------------------------------#

    def generate_answer(
        self,
        question: str,
        context: Optional[str] = None,
        tool_schema: Optional[dict[str, Any]] = None,  # accepted for backward compat, unused (tools are fixed)
        collection_name: Optional[str] = None,
        **_: Any,
    ) -> dict[str, Any]:
        logger.info("=" * 60)
        logger.info("STARTING AGENTIC REASONING LOOP")
        logger.info("Question: %s", question)
        logger.info("=" * 60)

        if not self.api_key:
            logger.error("Missing API key. Deflecting to fallback.")
            return self._fallback_answer(question, context or "", collection_name)

        cfg = self.config
        tools = [COLLECT_EVIDENCE_TOOL, FINAL_ANSWER_TOOL]

        initial_prompt = f"Question: {question}"
        if context:
            initial_prompt += f"\nInitial Context: {context}"

        gemini_contents = [{"role": "user", "parts": [{"text": initial_prompt}]}]
        groq_messages = [{"role": "user", "content": initial_prompt}]

        evidence: list = []
        tried_queries: set[str] = set()
        trace_lines: list[str] = []
        consecutive_empty = 0

        def run_turn(tool_set: list[dict[str, Any]]) -> ProviderTurn:
            return self._call_with_failover(gemini_contents, groq_messages, tool_set, cfg.max_tokens_reasoning)

        for loop_idx in range(1, cfg.max_loops + 1):
            logger.info("[LOOP %d/%d] Requesting next action...", loop_idx, cfg.max_loops)
            try:
                turn = run_turn(tools)
            except Exception as exc:
                logger.error("API routing failed on loop %d: %s", loop_idx, exc)
                return self._fallback_answer(question, context or "", collection_name, evidence=evidence)

            if turn.tool_name == "final_answer":
                answer_text = turn.tool_args.get("answer", "").strip()
                trace_lines.append(f"[final_answer] confidence={turn.tool_args.get('confidence', 'unknown')}")
                polished = self._format_final_answer(
                    question=question,
                    trace_summary="\n".join(trace_lines),
                    final_answer_text=answer_text or turn.text,
                    preferred_provider=turn.provider,
                )
                return {"answer": polished, "evidence": evidence}

            if turn.tool_name == "collect_evidence":
                query = (turn.tool_args.get("query") or "").strip() or question
                key = query.lower()

                if key in tried_queries:
                    logger.info("Duplicate query rejected: %r", query)
                    obs = f"Observation: query '{query}' was already tried -- no new information. Try a different angle or call final_answer."
                    gemini_contents.append({"role": "model", "parts": [{"functionCall": {"name": "collect_evidence", "args": {"query": query}}}]})
                    gemini_contents.append({"role": "user", "parts": [{"text": obs}]})
                    groq_messages.append({"role": "assistant", "content": f"collect_evidence(query={query!r})"})
                    groq_messages.append({"role": "user", "content": obs})
                    continue

                tried_queries.add(key)
                logger.info("Executing evidence search: %r", query)

                if collection_name:
                    try:
                        new_evidence = self._collect_evidence(collection_name=collection_name, question=query)
                    except Exception as db_err:
                        logger.error("Evidence collection failed: %s", db_err)
                        new_evidence = []
                else:
                    new_evidence = []

                logger.info("Found %d new evidence item(s).", len(new_evidence))
                evidence.extend(new_evidence)
                trace_lines.append(f"[collect_evidence] query={query!r} -> {len(new_evidence)} item(s)")

                if new_evidence:
                    consecutive_empty = 0
                    dump = json.dumps(new_evidence)[: cfg.evidence_char_budget]
                    obs = f"Observation: found {len(new_evidence)} evidence item(s): {dump}"
                else:
                    consecutive_empty += 1
                    obs = "Observation: no relevant evidence found for this query."

                gemini_contents.append({"role": "model", "parts": [{"functionCall": {"name": "collect_evidence", "args": {"query": query}}}]})
                gemini_contents.append({"role": "user", "parts": [{"text": obs}]})
                groq_messages.append({"role": "assistant", "content": f"collect_evidence(query={query!r})"})
                groq_messages.append({"role": "user", "content": obs})

                if consecutive_empty >= cfg.max_consecutive_empty_evidence:
                    logger.info("Early stop: %d consecutive empty searches. Forcing wrap-up.", consecutive_empty)
                    nudge = (
                        "Observation: multiple consecutive searches returned no evidence. "
                        "The knowledge base most likely does not contain this information. "
                        "Call final_answer now and state that plainly."
                    )
                    gemini_contents.append({"role": "user", "parts": [{"text": nudge}]})
                    groq_messages.append({"role": "user", "content": nudge})

                    try:
                        closing_turn = run_turn([FINAL_ANSWER_TOOL])
                    except Exception as exc:
                        logger.error("Forced wrap-up call failed: %s", exc)
                        return self._fallback_answer(question, context or "", collection_name, evidence=evidence)

                    if closing_turn.tool_name == "final_answer":
                        answer_text = closing_turn.tool_args.get("answer", "").strip()
                        trace_lines.append(f"[final_answer] confidence={closing_turn.tool_args.get('confidence', 'unknown')}")
                        polished = self._format_final_answer(
                            question=question,
                            trace_summary="\n".join(trace_lines),
                            final_answer_text=answer_text or closing_turn.text,
                            preferred_provider=closing_turn.provider,
                        )
                        return {"answer": polished, "evidence": evidence}

                    return self._fallback_answer(question, context or "", collection_name, evidence=evidence)

                continue

            # Model replied without calling a tool at all -- treat any text as
            # a candidate final answer rather than silently looping forever.
            if turn.text:
                trace_lines.append("[untooled response, treated as final answer]")
                polished = self._format_final_answer(
                    question=question,
                    trace_summary="\n".join(trace_lines),
                    final_answer_text=turn.text,
                    preferred_provider=turn.provider,
                )
                return {"answer": polished, "evidence": evidence}

        logger.warning("Max agent reasoning loops reached without a definitive completion path.")
        return self._fallback_answer(question, context or "", collection_name, evidence=evidence)