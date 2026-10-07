"""Reusable, lazy-loaded text preprocessing utilities for syllabus Unit I."""

import re
import unicodedata
from collections import Counter
from functools import lru_cache
from typing import Any

MAX_INPUT_CHARS = 100_000
_TOKEN_PATTERN = re.compile(r"\w+(?:['’]\w+)*|[^\w\s]", re.UNICODE)
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?।॥])\s+")
_EMAIL_PATTERN = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
_URL_PATTERN = re.compile(
    r"""\b(?:https?://|www\.)[^\s<>"']*[^\s<>"'.,!?;:]""",
    re.IGNORECASE,
)
_NUMBER_PATTERN = re.compile(r"(?<!\w)[+-]?\d+(?:[.,]\d+)*(?!\w)")
_CONTRACTIONS = {
    "ain't": "is not",
    "aren't": "are not",
    "can't": "cannot",
    "couldn't": "could not",
    "didn't": "did not",
    "doesn't": "does not",
    "don't": "do not",
    "hadn't": "had not",
    "hasn't": "has not",
    "haven't": "have not",
    "he'd": "he would",
    "he'll": "he will",
    "he's": "he is",
    "i'd": "i would",
    "i'll": "i will",
    "i'm": "i am",
    "i've": "i have",
    "isn't": "is not",
    "it'd": "it would",
    "it'll": "it will",
    "it's": "it is",
    "let's": "let us",
    "mightn't": "might not",
    "mustn't": "must not",
    "shan't": "shall not",
    "she'd": "she would",
    "she'll": "she will",
    "she's": "she is",
    "shouldn't": "should not",
    "that's": "that is",
    "there's": "there is",
    "they'd": "they would",
    "they'll": "they will",
    "they're": "they are",
    "they've": "they have",
    "we'd": "we would",
    "we'll": "we will",
    "we're": "we are",
    "we've": "we have",
    "weren't": "were not",
    "what's": "what is",
    "won't": "will not",
    "wouldn't": "would not",
    "you'd": "you would",
    "you'll": "you will",
    "you're": "you are",
    "you've": "you have",
}
_FALLBACK_STOP_WORDS = frozenset(
    "a an and are as at be been being but by for from had has have he her hers "
    "him his i in is it its me my of on or our ours she that the their theirs "
    "them they this to us was we were what when where which who will with you "
    "your".split()
)


def detect_language(text: str) -> str:
    """Identify English, Hindi (Devanagari), Punjabi (Gurmukhi), or unknown."""
    devanagari = sum("\u0900" <= char <= "\u097f" for char in text)
    gurmukhi = sum("\u0a00" <= char <= "\u0a7f" for char in text)
    latin = sum(char.isascii() and char.isalpha() for char in text)
    if devanagari > gurmukhi and devanagari > latin:
        return "hi"
    if gurmukhi > devanagari and gurmukhi > latin:
        return "pa"
    if latin:
        return "en"
    return "und"


@lru_cache(maxsize=1)
def _load_spacy_model() -> Any | None:
    """Load the requested small English model on first use, never during startup."""
    import spacy

    try:
        return spacy.load("en_core_web_sm")
    except OSError:
        return None


def _spacy_model() -> Any | None:
    return _load_spacy_model()


@lru_cache(maxsize=1)
def _nltk_module() -> Any:
    """Import NLTK only when a preprocessing step first needs an NLTK resource."""
    import nltk

    return nltk


@lru_cache(maxsize=1)
def _english_stop_words() -> frozenset[str]:
    nltk = _nltk_module()
    try:
        return frozenset(nltk.corpus.stopwords.words("english"))
    except LookupError:
        return _FALLBACK_STOP_WORDS


@lru_cache(maxsize=1)
def _wordnet_available() -> bool:
    nltk = _nltk_module()
    try:
        nltk.data.find("corpora/wordnet")
    except LookupError:
        return False
    return True


def normalize_text(text: str) -> str:
    """Normalize Unicode and whitespace, expand common contractions, and mask data."""
    normalized = unicodedata.normalize("NFKC", text)
    normalized = normalized.replace("’", "'")
    normalized = _EMAIL_PATTERN.sub(" <EMAIL> ", normalized)
    normalized = _URL_PATTERN.sub(" <URL> ", normalized)

    def expand(match: re.Match[str]) -> str:
        contraction = match.group(0).lower()
        return _CONTRACTIONS.get(contraction, contraction)

    normalized = re.sub(
        r"\b[\w]+(?:'[\w]+)+\b",
        expand,
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = _NUMBER_PATTERN.sub(" <NUM> ", normalized)
    normalized = normalized.lower()
    return " ".join(normalized.split())


def sentence_segmentation(text: str) -> list[str]:
    """Split text into sentences, using spaCy for English when available."""
    if detect_language(text) == "en":
        model = _spacy_model()
        if model is not None:
            return [sentence.text.strip() for sentence in model(text).sents]
    return [
        sentence.strip()
        for sentence in _SENTENCE_BOUNDARY.split(text)
        if sentence.strip()
    ]


def regex_tokenize(text: str) -> list[str]:
    """Tokenize words and symbols using a small Unicode-aware regular expression."""
    return _TOKEN_PATTERN.findall(text)


def spacy_tokenize(text: str) -> list[str]:
    """Tokenize with spaCy when available; fall back safely to regex tokens."""
    if detect_language(text) != "en":
        return text.split()
    model = _spacy_model()
    if model is None:
        return regex_tokenize(text)
    return [token.text for token in model.make_doc(text)]


def tokenize(text: str) -> dict[str, Any]:
    """Return the simple regex tokenizer and the spaCy tokenizer side by side."""
    language = detect_language(text)
    regex_tokens = regex_tokenize(text)
    model = _spacy_model() if language == "en" else None
    library_tokens = (
        [token.text for token in model.make_doc(text)]
        if model is not None
        else (text.split() if language in {"hi", "pa"} else regex_tokens)
    )
    return {
        "language": language,
        "regex": regex_tokens,
        "spacy": library_tokens,
        "spacy_model_loaded": model is not None,
    }


def handle_punctuation(tokens: list[str]) -> list[str]:
    """Remove punctuation-only tokens while preserving emoji and other symbols."""
    return [
        token
        for token in tokens
        if any(
            unicodedata.category(character)[0] not in {"P", "Z"} for character in token
        )
    ]


def remove_stop_words(tokens: list[str], language: str = "en") -> list[str]:
    """Remove English stop words; leave other supported languages unchanged."""
    if language != "en":
        return tokens.copy()
    stop_words = _english_stop_words()
    return [token for token in tokens if token.casefold() not in stop_words]


def preprocess_tokens(text: str) -> list[str]:
    """Apply the shared Step 4 normalization and retrieval token filters."""
    normalized = normalize_text(text)
    tokens = handle_punctuation(regex_tokenize(normalized))
    return remove_stop_words(tokens, detect_language(normalized))


def stem_tokens(tokens: list[str]) -> dict[str, list[str]]:
    """Return Porter and Snowball stems in parallel."""
    from nltk.stem import PorterStemmer, SnowballStemmer

    porter = PorterStemmer()
    snowball = SnowballStemmer("english")
    return {
        "porter": [porter.stem(token) for token in tokens],
        "snowball": [snowball.stem(token) for token in tokens],
    }


def lemmatize_tokens(tokens: list[str]) -> dict[str, list[str]]:
    """Return spaCy and WordNet lemmas with safe fallbacks."""
    from nltk.stem import WordNetLemmatizer

    model = _spacy_model()
    spacy_lemmas = (
        [token.lemma_ for token in model(" ".join(tokens))]
        if model is not None
        else tokens.copy()
    )
    wordnet = WordNetLemmatizer()
    if _wordnet_available():
        try:
            wordnet_lemmas = [wordnet.lemmatize(token) for token in tokens]
        except LookupError:
            wordnet_lemmas = tokens.copy()
    else:
        wordnet_lemmas = tokens.copy()
    return {"spacy": spacy_lemmas, "wordnet": wordnet_lemmas}


def handle_oov(
    tokens: list[str], vocabulary: set[str] | None = None
) -> list[dict[str, Any]]:
    """Mark out-of-vocabulary tokens and provide character pieces as a fallback."""
    known_words = vocabulary or set()
    output: list[dict[str, Any]] = []
    for token in tokens:
        known = token.casefold() in known_words
        output.append(
            {
                "token": token,
                "known": known,
                "unknown_token": None if known else "<UNK>",
                "character_fallback": [] if known else list(token),
            }
        )
    return output


def linguistic_analysis(text: str) -> dict[str, Any]:
    """Return POS, morphology, and dependency information without requiring a model."""
    language = detect_language(text)
    model = _spacy_model() if language == "en" else None
    if model is not None:
        doc = model(text)
        return {
            "pos": [
                {"token": token.text, "pos": token.pos_, "tag": token.tag_}
                for token in doc
            ],
            "morphology": [
                {
                    "token": token.text,
                    "lemma": token.lemma_,
                    "prefix": token.text[: len(token.text) - len(token.lemma_)],
                    "suffix": (
                        token.text[len(token.lemma_) :]
                        if token.text.startswith(token.lemma_)
                        else ""
                    ),
                    "features": str(token.morph),
                }
                for token in doc
            ],
            "dependencies": [
                {
                    "token": token.text,
                    "head": token.head.text,
                    "dependency": token.dep_,
                }
                for token in doc
            ],
            "model_loaded": True,
        }

    tokens = text.split() if language in {"hi", "pa"} else regex_tokenize(text)
    return {
        "pos": [{"token": token, "pos": "X", "tag": "UNKNOWN"} for token in tokens],
        "morphology": [
            {
                "token": token,
                "lemma": token.casefold(),
                "prefix": "",
                "suffix": "",
                "features": {},
            }
            for token in tokens
        ],
        "dependencies": [
            {
                "token": token,
                "head": token if index == 0 else tokens[index - 1],
                "dependency": "root" if index == 0 else "dep",
            }
            for index, token in enumerate(tokens)
        ],
        "model_loaded": False,
    }


def generate_ngrams(tokens: list[str], n: int | None = None) -> dict[str, Any]:
    """Generate unigram, bigram, and trigram counts, or counts for one n."""
    sizes = [n] if n is not None else [1, 2, 3]
    if any(size < 1 or size > 3 for size in sizes):
        raise ValueError("n must be 1, 2, or 3.")
    results = {
        size: dict(
            sorted(
                Counter(
                    " ".join(tokens[index : index + size])
                    for index in range(len(tokens) - size + 1)
                ).items(),
                key=lambda item: (-item[1], item[0]),
            )
        )
        for size in sizes
    }
    return {"frequencies": results}


def vectorize_documents(documents: list[str], top_n: int = 10) -> dict[str, Any]:
    """Build sparse Bag-of-Words and TF-IDF results with ranked terms per document."""
    from sklearn.feature_extraction.text import CountVectorizer, TfidfVectorizer

    if not documents or not any(document.strip() for document in documents):
        return {"vocabulary": [], "bow": [], "tfidf": [], "top_terms": []}
    count = CountVectorizer()
    tfidf = TfidfVectorizer()
    try:
        count_matrix = count.fit_transform(documents)
        tfidf_matrix = tfidf.fit_transform(documents)
    except ValueError as error:
        if "empty vocabulary" in str(error).lower():
            return {"vocabulary": [], "bow": [], "tfidf": [], "top_terms": []}
        raise

    terms = tfidf.get_feature_names_out().tolist()
    bow_terms = count.get_feature_names_out().tolist()
    bow_matrix = count_matrix.toarray().tolist()
    tfidf_values = tfidf_matrix.toarray()
    top_terms = [
        [
            {"term": terms[index], "score": float(tfidf_values[row, index])}
            for index in sorted(
                range(len(terms)),
                key=lambda column: (-tfidf_values[row, column], terms[column]),
            )[:top_n]
            if tfidf_values[row, index] > 0
        ]
        for row in range(len(documents))
    ]
    return {
        "vocabulary": bow_terms,
        "bow": [
            {
                term: int(value)
                for term, value in zip(bow_terms, row, strict=True)
                if value
            }
            for row in bow_matrix
        ],
        "tfidf": top_terms,
        "top_terms": top_terms,
    }


def extract_keywords(
    documents: list[str], method: str = "tfidf", top_n: int = 10
) -> list[dict[str, Any]]:
    """Extract ranked terms/phrases using TF-IDF, YAKE, or RAKE."""
    if method not in {"tfidf", "yake", "rake"}:
        raise ValueError("method must be 'tfidf', 'yake', or 'rake'.")
    if method == "tfidf":
        return [
            {"document": index, **term}
            for index, terms in enumerate(
                vectorize_documents(documents, top_n)["tfidf"]
            )
            for term in terms
        ]

    output: list[dict[str, Any]] = []
    for index, document in enumerate(documents):
        if not document.strip():
            continue
        if method == "yake":
            import yake

            extractor = yake.KeywordExtractor(lan="en", n=3, top=top_n)
            phrases = extractor.extract_keywords(document)
        else:
            from rake_nltk import Rake

            extractor = Rake(
                stopwords=_english_stop_words(),
                max_length=3,
                sentence_tokenizer=sentence_segmentation,
                word_tokenizer=regex_tokenize,
            )
            extractor.extract_keywords_from_text(document)
            phrases = [
                (phrase, score)
                for score, phrase in extractor.get_ranked_phrases_with_scores()[:top_n]
            ]
        output.extend(
            {"document": index, "phrase": phrase, "score": float(score)}
            for phrase, score in phrases[:top_n]
        )
    return output


PIPELINE_STEPS = (
    "sentence_segmentation",
    "tokenization",
    "normalization",
    "punctuation",
    "stop_words",
    "stemming",
    "lemmatization",
    "oov",
    "linguistic",
    "ngrams",
    "vectorization",
    "keywords",
)


def preprocess_text(text: str, steps: list[str] | None = None) -> dict[str, Any]:
    """Run selected preprocessing steps in canonical order and return each result."""
    if len(text) > MAX_INPUT_CHARS:
        raise ValueError(f"Text exceeds the {MAX_INPUT_CHARS}-character limit.")
    selected = set(steps or PIPELINE_STEPS)
    unknown = selected.difference(PIPELINE_STEPS)
    if unknown:
        detail = ", ".join(sorted(unknown))
        raise ValueError(f"Unsupported preprocessing steps: {detail}.")

    results: dict[str, Any] = {"language": detect_language(text)}
    normalized = normalize_text(text)
    tokens = tokenize(normalized)["spacy"]
    for step in PIPELINE_STEPS:
        if step not in selected:
            continue
        if step == "sentence_segmentation":
            results[step] = sentence_segmentation(text)
        elif step == "tokenization":
            results[step] = tokenize(text)
        elif step == "normalization":
            results[step] = normalized
        elif step == "punctuation":
            tokens = handle_punctuation(tokens)
            results[step] = tokens
        elif step == "stop_words":
            tokens = remove_stop_words(tokens, results["language"])
            results[step] = tokens
        elif step == "stemming":
            results[step] = stem_tokens(tokens)
        elif step == "lemmatization":
            results[step] = lemmatize_tokens(tokens)
        elif step == "oov":
            results[step] = handle_oov(tokens)
        elif step == "linguistic":
            results[step] = linguistic_analysis(text)
        elif step == "ngrams":
            results[step] = generate_ngrams(tokens)
        elif step == "vectorization":
            results[step] = vectorize_documents([normalized])
        elif step == "keywords":
            results[step] = {
                method: extract_keywords([normalized], method)
                for method in ("tfidf", "yake", "rake")
            }
    return results
