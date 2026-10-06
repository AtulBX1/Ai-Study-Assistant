# Step 4: Text preprocessing

## What it does

The preprocessing lab turns each extracted PDF page into a cleaned copy that
can be inspected one operation at a time. The extracted `text` stays unchanged;
the normalized version is stored separately as `cleaned_text`.

The authenticated `/lab/preprocess` endpoint accepts either short text or an
owned document and optional page range. It returns the output for each selected
step. Other lab endpoints return n-gram counts, per-page TF-IDF terms, and
keyphrases from TF-IDF, YAKE, or RAKE. Lab input is limited to 100,000
characters.

## How the steps work

1. **Language detection and sentence segmentation:** the pipeline identifies
   English, Devanagari Hindi, or Gurmukhi Punjabi using Unicode character
   ranges. English uses the cached `en_core_web_sm` spaCy model when it is
   installed; otherwise a deterministic punctuation-based splitter is used.
   Hindi and Punjabi use a safe whitespace-based path.
2. **Tokenization:** the result displays a small Unicode regular-expression
   tokenizer beside spaCy's word tokenizer. Unsupported language/model cases
   use a safe fallback instead of failing.
3. **Normalization:** Unicode forms are made consistent, common English
   contractions are expanded, email addresses, URLs, and numbers are replaced
   with markers, whitespace is collapsed, and English text is lowercased.
4. **Punctuation and stop words:** punctuation-only tokens are removed while
   symbols such as emoji are preserved. English stop words are removed using
   NLTK's stop-word list when available; a small built-in list is the fallback.
5. **Stemming and lemmatization:** Porter and Snowball stemming are shown
   side-by-side. spaCy and WordNet lemmatization are also shown side-by-side.
   A missing language model or WordNet data falls back to the original token.
6. **Out-of-vocabulary (OOV) handling:** tokens absent from a vocabulary can
   be represented as `<UNK>`; character pieces provide a simple fallback so
   an unknown word is not lost entirely.
7. **Linguistic analysis:** spaCy supplies part-of-speech tags, lemmas,
   prefixes/suffixes, morphological features, and dependency links. If the
   English model is unavailable, the output labels the reduced fallback
   explicitly.
8. **N-grams:** contiguous groups of one, two, or three tokens are counted.
   Ties are sorted alphabetically so charts and results are deterministic.
9. **Bag-of-Words and TF-IDF:** scikit-learn builds count and TF-IDF
   representations and ranks the strongest terms for each page.
10. **Keyphrase extraction:** TF-IDF ranks informative words; YAKE and RAKE
    rank candidate phrases. Empty input safely returns no terms.

Example:

| Stage | Text |
| --- | --- |
| Before | `I'm reading NLP at https://example.org!` |
| Normalized | `i am reading nlp at <url> !` |
| Tokens after punctuation handling | `i`, `am`, `reading`, `nlp`, `at`, `<`, `url`, `>` |

The separate original page text retains the source exactly as extracted,
including any punctuation and casing.

## Stemming vs. lemmatization

Stemming cuts word endings using simple rules. For example, `studies` can become
`studi`; the result does not have to be a dictionary word. Lemmatization uses
language knowledge to find a base word, so `studies` becomes `study` and
`better` may become `good` when the model has the right context. Stemming is
fast; lemmatization is usually easier to read.

## Bag-of-Words vs. TF-IDF

Bag-of-Words (BoW) records how many times each term appears, without considering
word order. A page containing `NLP NLP text` has counts `nlp: 2` and `text: 1`.
TF-IDF starts from term counts, then gives less weight to terms that appear in
many pages. It helps surface terms that distinguish one page from the rest.

## Setup notes

Install the light NLP packages from the backend project dependencies. Install
only the small English spaCy model with:

```powershell
python -m spacy download en_core_web_sm
```

Download only the NLTK data used by this pipeline:

```powershell
python -c "import nltk; nltk.download('stopwords'); nltk.download('wordnet')"
```

The model loads only when an English preprocessing step first needs it. NLTK
stop words and WordNet are read lazily; if the data is not present, the pipeline
uses safe local fallbacks. Punkt and NLTK's POS tagger are not required because
sentence splitting and POS tagging use spaCy or the built-in fallback.

## Key syllabus concept

Text preprocessing converts raw text into useful, repeatable features. It
connects basic NLP text processing with tokenization, normalization,
stop-word removal, stemming, lemmatization, and TF-IDF representations.

## Viva questions

1. **Why normalize text before building text features?**  
   It makes equivalent forms more consistent, so case, extra spaces, and
   sensitive number/URL/email details do not create unnecessary variation.

2. **What is the difference between a token and a sentence?**  
   A sentence is a larger text unit; tokenization divides that unit into words
   and symbols that NLP algorithms can process.

3. **How is stemming different from lemmatization?**  
   Stemming cuts endings with rules and may create a non-word. Lemmatization
   uses language information to return a meaningful base form.

4. **What does TF-IDF add beyond Bag-of-Words?**  
   BoW counts words; TF-IDF reduces the importance of words common across many
   documents and emphasizes more distinguishing terms.

5. **Why keep the original page text after cleaning it?**  
   The original is the source evidence. Keeping it unchanged preserves an
   auditable page citation while the cleaned copy supports analysis.
