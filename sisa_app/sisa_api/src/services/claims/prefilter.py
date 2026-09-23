"""Cheap, LLM-free first pass over finished transcript segments.

It only drops what is obviously not a claim (short fragments, greetings,
courtroom procedure, pure questions). Anything uncertain is KEPT: missing a
claim is worse than one extra batched LLM call.

Every list below is editable. Matching is case-insensitive on whole words.
An entry ending in `*` matches as a prefix, which covers Tagalog affixes and
linkers (e.g. `milyon*` -> "milyong", `pinaka*` -> "pinakamalaki").
"""

import re

MIN_WORDS = 5

WORD_LISTS: dict[str, list[str]] = {
    # --- drop lists: a segment made up only of these (plus filler) is dropped ---
    "greetings": [
        "magandang umaga", "magandang hapon", "magandang gabi", "magandang araw",
        "good morning", "good afternoon", "good evening", "good day",
        "hello", "hi", "kumusta", "mabuhay", "salamat po", "salamat", "maraming salamat",
        "thank you", "thanks", "welcome", "tuloy po kayo",
    ],
    "procedural": [
        "your honor", "objection", "sustained", "overruled", "noted", "proceed",
        "you may proceed", "please proceed", "move to strike", "so ordered",
        "no further questions", "no more questions", "the witness may step down",
        "let the record show", "for the record", "order in the court", "recess",
        "the floor is yours", "mister chair", "madam chair", "mr. chair", "madam chairperson",
        "point of order", "point of information", "go ahead", "sige po", "opo", "okay po",
    ],
    # words that carry no content on their own once greetings/procedure are removed
    "filler": [
        "po", "ho", "opo", "oo", "sir", "ma'am", "maam", "mam", "your", "the", "a", "and",
        "at", "ang", "mga", "sa", "na", "ng", "ok", "okay", "yes", "no", "uh", "um", "ah",
        "eh", "so", "well", "lahat", "everyone", "everybody", "sa inyong", "inyong", "sa inyo",
        "ninyo", "kayo", "you", "all", "ladies", "gentlemen", "and gentlemen", "honor",
        "chair", "chairman", "madam", "mister", "senator", "congressman", "secretary",
    ],
    "question_starts": [
        "ano", "anong", "bakit", "paano", "sino", "sinong", "saan", "kailan", "ilan",
        "magkano", "alin", "nasaan", "what", "why", "how", "who", "where", "when",
        "which", "is it", "are you", "did you", "do you", "does", "can you", "could you",
        "would you", "will you", "totoo ba", "hindi ba", "meron ba",
    ],
    # --- keep signals: any match marks the segment as a likely claim ---
    "number_words": [
        "million*", "billion*", "trillion*", "thousand*", "hundred*", "half", "dozen*",
        "twice", "double*", "triple*", "percent*",
        "dalawa*", "tatlo*", "apat*", "lima*", "anim*", "pito*", "walo*", "siyam*",
        "sampu*", "labing*", "daan*", "raan*", "libo*", "libu*", "milyon*", "bilyon*",
        "trilyon*", "kalahati*", "doble*", "porsyento*", "porsiyento*", "bahagdan*",
    ],
    "money": ["peso*", "piso*", "php", "dollar*", "usd", "badyet*", "budget*", "pondo*", "fund*"],
    "dates": [
        "january", "february", "march", "april", "may", "june", "july", "august",
        "september", "october", "november", "december",
        "enero", "pebrero", "marso", "abril", "mayo", "hunyo", "hulyo", "agosto",
        "setyembre", "oktubre", "nobyembre", "disyembre",
        "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
        "lunes", "martes", "miyerkules", "huwebes", "biyernes", "sabado", "linggo",
        "year*", "taon*", "buwan*", "araw", "week*", "month*", "day*", "kahapon",
        "noong", "nakaraan*", "since", "simula", "dekada*", "decade*", "quarter*",
        "yesterday", "today", "ngayong taon",
    ],
    "legal": [
        "konstitusyon*", "constitution*", "saligang batas", "batas*", "law*", "article*",
        "artikulo*", "section*", "seksyon*", "rule*", "korte*", "court*", "republic act",
        "executive order", "ordinance*", "ordinansa*", "impeach*", "trial*", "paglilitis",
        "kaso*", "case*", "resolution*", "resolusyon*", "bill*", "panukala*", "statute*",
        "desisyon*", "decision*", "ruling*", "illegal*", "ilegal*", "unconstitutional",
        "labag", "kontrata*", "contract*", "subpoena*", "testimony", "affidavit*",
    ],
    "institutions": [
        "coa", "dbm", "deped", "ovp", "dpwh", "doh", "dof", "dilg", "bir", "bsp", "psa",
        "neda", "depdev", "comelec", "ombudsman", "senado", "senate", "kamara", "congress*",
        "kongreso*", "house of representatives", "malacañang", "malacanang", "palasyo",
        "pnp", "afp", "sandiganbayan", "supreme court", "philhealth", "sss", "gsis", "lgu*",
        "doj", "dswd", "ched", "tesda", "dotr", "dict", "dti", "da", "denr", "nbi", "pcg",
        "commission on audit", "department of*", "kagawaran*", "office of the*",
        "world bank", "imf", "adb", "unicef",
    ],
    "absolutes": [
        "never", "always", "all", "none", "nobody", "every*", "only", "lahat*", "wala*",
        "kailanman", "palagi", "lagi", "pinaka*", "most", "least", "highest", "lowest",
        "biggest", "largest", "smallest", "record*", "doubled", "tripled", "halved",
        "increase*", "decrease*", "tumaas*", "bumaba*", "dumoble*", "mas", "more than",
        "less than", "higher", "lower", "first", "tanging", "zero", "wala ni isa",
    ],
    "assertion_verbs": [
        "ginastos*", "gumastos*", "gastos*", "inilabas*", "naglabas*", "pumirma*",
        "pinirmahan*", "nilagdaan*", "sinabi*", "sabi*", "ayon", "released", "spent",
        "signed", "said", "says", "reported", "allocated", "inilaan*", "naubos*", "ubos",
        "approved", "inaprubahan*", "aprubado", "disallowed", "disallowance*", "awarded",
        "received", "tinanggap*", "natanggap*", "nakatanggap*", "binili*", "bumili*",
        "bought", "paid", "binayaran*", "nagbayad*", "built", "itinayo*", "launched",
        "passed", "ipinasa*", "voted", "bumoto*", "confirmed", "kinumpirma*", "denied",
        "itinanggi*", "found", "natuklasan*", "audited", "inaudit", "nakita*", "admitted",
        "inamin*", "promised", "nangako*", "ipinangako*", "will build", "itatayo*",
    ],
}

SIGNAL_LISTS = ("number_words", "money", "dates", "legal", "institutions", "absolutes", "assertion_verbs")

# Regex signals that are not word lists.
_DIGIT_RE = re.compile(r"\d")
_MONEY_SYMBOL_RE = re.compile(r"[₱$%]|\bphp\b|\bp\d", re.IGNORECASE)
_WORD_RE = re.compile(r"[\w₱$%'’.-]+", re.UNICODE)


def _entry_pattern(entry: str) -> str:
    entry = entry.strip()
    if entry.endswith("*"):
        return r"(?<!\w)" + re.escape(entry[:-1]) + r"\w*"
    return r"(?<!\w)" + re.escape(entry) + r"(?!\w)"


def _compile(entries: list[str]) -> re.Pattern[str]:
    # Longest first, so multi-word phrases win over their parts.
    ordered = sorted(entries, key=len, reverse=True)
    return re.compile("|".join(_entry_pattern(e) for e in ordered), re.IGNORECASE)


_PATTERNS: dict[str, re.Pattern[str]] = {name: _compile(entries) for name, entries in WORD_LISTS.items()}
_QUESTION_START_RE = re.compile(
    r"^\s*(?:" + "|".join(re.escape(e.strip()) for e in WORD_LISTS["question_starts"]) + r")\b",
    re.IGNORECASE,
)


def _words(text: str) -> list[str]:
    return [w for w in _WORD_RE.findall(text) if re.search(r"\w|[₱$%]", w)]


def claim_signals(text: str) -> list[str]:
    """Names of the signal groups that match `text`, in a stable order."""
    found: list[str] = []
    if _DIGIT_RE.search(text):
        found.append("digits")
    if _MONEY_SYMBOL_RE.search(text):
        found.append("money_symbol")
    for name in SIGNAL_LISTS:
        if _PATTERNS[name].search(text):
            found.append(name)
    return found


def _only_greeting_or_procedure(text: str) -> str | None:
    """Return 'greeting'/'procedural' if nothing is left after removing those
    phrases and filler words, else None."""
    greeting = bool(_PATTERNS["greetings"].search(text))
    procedural = bool(_PATTERNS["procedural"].search(text))
    if not (greeting or procedural):
        return None
    rest = _PATTERNS["greetings"].sub(" ", text)
    rest = _PATTERNS["procedural"].sub(" ", rest)
    rest = _PATTERNS["filler"].sub(" ", rest)
    if _words(rest):
        return None
    return "procedural" if procedural else "greeting"


def _is_question(text: str) -> bool:
    stripped = text.strip()
    if stripped.endswith("?"):
        return True
    # No question mark (ASR punctuation is imperfect): a question-word start that
    # does not end like a statement.
    return bool(_QUESTION_START_RE.match(stripped)) and not stripped.endswith((".", "!"))


def prefilter(text: str) -> tuple[bool, str]:
    """Decide whether a finished segment should go to the LLM classifier.

    Returns (keep, reason). The reason is never empty.
    """
    text = (text or "").strip()
    if not text:
        return False, "empty segment"

    signals = claim_signals(text)
    words = _words(text)

    kind = _only_greeting_or_procedure(text)
    if kind:
        return False, f"{kind} phrase only, no content"

    # Short fragments are dropped, unless they carry a number or amount
    # ("Naubos ang ₱125 milyon") -- a missed claim costs more than a call.
    if len(words) < MIN_WORDS and not {"digits", "money_symbol"} & set(signals):
        return False, f"too short ({len(words)} words < {MIN_WORDS})"

    if _is_question(text) and not signals:
        return False, "question with no claim signal"

    if signals:
        return True, "claim signal: " + ", ".join(signals)
    return True, "no claim signal, kept by default"

