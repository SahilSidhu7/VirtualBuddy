"""Turn one phrase into many, using templates. No LLM, no tokens.
Builder and critic use DIFFERENT prefix sets so the critic tests unseen wording.
"""

BUILD_PREFIXES = ["", "please ", "can you ", "could you ", "i want to ", "hey buddy ", "buddy "]
BUILD_SUFFIXES = ["", " now", " please", " for me"]

# held-out wording the builder never trains on -> a fair test for the critic
TEST_PREFIXES = ["", "would you ", "mind if you ", "go ahead and ", "i need you to ", "quickly "]
TEST_SUFFIXES = ["", " right now", " thanks", " asap"]

def expand(phrase, prefixes, suffixes):
    out = set()
    for p in prefixes:
        for s in suffixes:
            out.add((p + phrase + s).strip())
    return out

def build_set(base_phrases):
    out = set()
    for ph in base_phrases:
        out |= expand(ph, BUILD_PREFIXES, BUILD_SUFFIXES)
    return list(out)

def test_set(base_phrases):
    out = set()
    for ph in base_phrases:
        out |= expand(ph, TEST_PREFIXES, TEST_SUFFIXES)
    return list(out)
