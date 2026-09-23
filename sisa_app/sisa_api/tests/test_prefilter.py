import pytest

from src.services.claims.prefilter import WORD_LISTS, claim_signals, prefilter

DROPS = [
    "Magandang hapon po.",
    "Objection, Your Honor.",
    "Noted.",
    "Salamat po.",
    "Yes, that one",  # 3-word fragment
    "Ano po ang masasabi ninyo tungkol dito?",  # pure question
    "Magandang umaga po sa inyong lahat.",
    "Sustained. You may proceed.",
    "What do you think about that?",
    "",
]

KEEPS = [
    "Ang ₱125 milyon ay naubos sa loob ng 11 araw.",
    "Ayon sa Konstitusyon, dapat agad ang trial.",
    "The COA disallowed 73 million pesos.",
    "Wala silang ginastos para sa mga estudyante.",
    "Ang mga bata ay pumapasok sa eskwela tuwing umaga.",  # no signal: kept by default
    "Magandang hapon po, ang DepEd ay gumastos ng ₱112 milyon.",  # greeting + claim
    "Hindi ba't kayo ang pumirma noong 2022?",  # rhetorical question with signals
    "Naubos ang ₱125 milyon.",  # short, but carries an amount
]


@pytest.mark.parametrize("text", DROPS)
def test_drops_with_reason(text):
    keep, reason = prefilter(text)
    assert keep is False
    assert reason.strip()


@pytest.mark.parametrize("text", KEEPS)
def test_keeps(text):
    keep, reason = prefilter(text)
    assert keep is True, reason
    assert reason.strip()


def test_ordinary_sentence_is_kept_by_default():
    keep, reason = prefilter("Ang mga bata ay pumapasok sa eskwela tuwing umaga.")
    assert keep
    assert "default" in reason


def test_drop_reasons_name_the_rule():
    assert "procedural" in prefilter("Objection, Your Honor.")[1]
    assert "greeting" in prefilter("Magandang hapon po.")[1]
    assert "short" in prefilter("Yes, that one")[1]
    assert "question" in prefilter("Ano po ang masasabi ninyo tungkol dito?")[1]


@pytest.mark.parametrize(
    "text, signal",
    [
        ("Ang ₱125 milyon ay naubos", "money_symbol"),
        ("tatlong bilyong piso ang nawala", "number_words"),
        ("noong Agosto 2023", "dates"),
        ("ayon sa Saligang Batas", "legal"),
        ("sinabi ng Senado", "institutions"),
        ("ito ang pinakamalaking budget", "absolutes"),
        ("inilabas ng opisina ang report", "assertion_verbs"),
    ],
)
def test_signals(text, signal):
    assert signal in claim_signals(text)


def test_tagalog_affixes_match_prefix_entries():
    # "milyong" (linker) and "pinakamalaki" (superlative prefix) come from `*` entries
    assert "number_words" in claim_signals("limampung milyong piso")
    assert "absolutes" in claim_signals("pinakamalaki sa kasaysayan")


def test_word_lists_are_one_editable_structure():
    for name in ("greetings", "procedural", "number_words", "legal", "institutions", "absolutes", "assertion_verbs"):
        assert WORD_LISTS[name], name
