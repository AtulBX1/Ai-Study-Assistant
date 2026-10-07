"""Scratch PyTorch sequence-to-sequence summarization models."""

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
for _entry in (_PROJECT_ROOT, _PROJECT_ROOT / "backend"):
    if str(_entry) not in sys.path:
        sys.path.insert(0, str(_entry))

from ml.seq2seq.models import Seq2SeqConfig, SequenceToSequence
from ml.seq2seq.vocabulary import Seq2SeqVocabulary

__all__ = ["Seq2SeqConfig", "Seq2SeqVocabulary", "SequenceToSequence"]
