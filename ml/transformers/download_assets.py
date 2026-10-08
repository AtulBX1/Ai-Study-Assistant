"""Download the GPT-2 tokenizer assets needed by the tokenizer comparison lab."""

import os

os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

from huggingface_hub import HfApi

MODEL_ID = "openai-community/gpt2"
TOKENIZER_FILES = {
    "vocab.json",
    "merges.txt",
    "tokenizer.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
    "config.json",
}


def main() -> None:
    """Report the exact tokenizer asset size before asking Transformers to fetch it."""
    hf_home = os.environ.get("HF_HOME")
    if not hf_home:
        raise RuntimeError("HF_HOME must point to the configured D: model cache.")
    cache = os.environ.get("HF_HUB_CACHE", str(os.path.join(hf_home, "hub")))
    metadata = HfApi().model_info(MODEL_ID, files_metadata=True)
    selected = [item for item in metadata.siblings if item.rfilename in TOKENIZER_FILES]
    unknown = [item.rfilename for item in selected if item.size is None]
    if unknown:
        raise RuntimeError(f"Could not resolve tokenizer asset sizes: {unknown}")
    total_bytes = sum(int(item.size) for item in selected)
    print(
        f"Download plan: {len(selected)} tokenizer files, {total_bytes:,} bytes "
        f"({total_bytes / (1024**2):.2f} MiB) from {MODEL_ID}; "
        f"destination cache: {cache}",
        flush=True,
    )
    from transformers import AutoTokenizer

    AutoTokenizer.from_pretrained(MODEL_ID)
    print("GPT-2 tokenizer assets downloaded.", flush=True)


if __name__ == "__main__":
    main()
