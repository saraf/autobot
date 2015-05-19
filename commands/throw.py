import random

import nltk
from nltk.corpus import wordnet
nltk.download("wordnet")


def get_hyponym(query):
    """ Return a random hyponym for query.
    """

    # WordNet uses the underscore to split lemmata.
    query = query.replace(" ", "_")

    thing_lemmas = wordnet.lemmas(query, pos=wordnet.NOUN)

    # Prefer more frequent lemmata.
    thing_lemmas = sorted(
        thing_lemmas,
        key=lambda lemma: lemma.count(),
        reverse=True
    )

    thing_senses = [
        lemma.synset()
        for lemma in thing_lemmas
    ]

    if not thing_senses:
        raise ValueError("No results for query {}".format(query))

    # Commit to the most frequent sense.
    thing_synset = thing_senses[0]

    def get_hyponym(lemma):
        return lemma.hyponyms()

    hyponyms = [
        hyponym_lemma.name()
        for hyponym_synset in thing_synset.closure(get_hyponym)
        for hyponym_lemma in hyponym_synset.lemmas()
    ]

    if not hyponyms:
        raise ValueError("No hyponyms for query {}".format(query))

    # Fix up whitespace.
    hyponyms = list(map(lambda lexeme: lexeme.replace("_", " "), hyponyms))

    return random.choice(hyponyms)
