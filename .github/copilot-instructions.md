# AI Study Assistant project rules

## Project scope and architecture
- Build an AI Study Assistant for PDF question answering and automatic quiz generation, aligned to the NLP syllabus Units I-VI: text processing and TF-IDF; Word2Vec/GloVe; RNN/LSTM/GRU; seq2seq and attention; Transformers/BERT/T5; LLMs, decoding, and hallucination.
- Keep the monorepo organized into `/backend`, `/frontend`, `/ml`, `/models`, `/data`, `/docs`, and `/infra`.
- Backend: Python 3.11, FastAPI, Pydantic, SQLAlchemy, and Alembic. Native development uses SQLite, FastAPI BackgroundTasks, local Qdrant storage, and local file storage. Production adapters use PostgreSQL, Celery/Redis, Qdrant server, and S3-compatible storage selected with `BACKEND=prod`.
- Frontend: Next.js App Router, strict TypeScript, Tailwind CSS, shadcn/ui, PDF.js, and Recharts/D3 as appropriate to each later step.
- ML tooling may include PyTorch, HuggingFace transformers/datasets/evaluate, sentence-transformers, gensim, spaCy, NLTK, scikit-learn, LlamaIndex, MLflow, and Langfuse.
- Use pytest and Playwright for tests, with native development tools and GitHub Actions. Dockerfiles and `docker-compose.prod.yml` are deployment artifacts only; never use Docker as the development workflow.
- Start local MLflow with `mlflow ui`; do not require containers for development.

## Engineering requirements
- Use type hints throughout Python and strict TypeScript. Format Python with Black, lint it with Ruff, and keep functions small, documented, and free of dead code.
- Add tests for every feature and run the relevant tests before declaring a step complete.
- Read configuration from environment variables. Never commit secrets; update `.env.example` whenever configuration changes.
- Select local or production adapters with `BACKEND=local|prod`. Keep adapter interfaces independent of the selected implementation.
- Where relevant, support switchable `classical` (TF-IDF, Word2Vec, LSTM, seq2seq) and `modern` (SBERT, BERT/T5, LLM RAG) modes.
- Every generated answer must cite its source document and page. If evidence is insufficient, say “not found in document”; never guess.
- At the end of every step, add `docs/learn/NN-topic.md` in simple language covering what was built, why, how it works, the key syllabus concept, and five viva questions with answers.
- Keep changes focused, commit-ready, and consistent with existing project conventions.

## Hardware and ML execution
- The default local GPU is an NVIDIA RTX 3050 with 4 GB VRAM. Do not assume shared system RAM is usable GPU memory or assume more than 4 GB VRAM.
- All training and inference code must use `torch.cuda` when available and fall back to CPU.
- Use mixed precision (fp16, or bf16 when supported); expose `batch_size`, `grad_accumulation_steps`, and `max_seq_len` as configuration values.
- Enable gradient checkpointing for transformer models and default to small models (DistilBERT, T5-small, MiniLM, or a small vocabulary for LSTM/seq2seq).
- Print peak VRAM usage per epoch, handle CUDA out-of-memory errors with a suggestion to reduce batch size or sequence length, and free GPU memory between jobs.
- Colab/Kaggle are optional backups for larger runs, not the default execution path.

## Scope discipline
- Implement only the step requested by the user. Do not start later features (such as authentication, database schema, PDF ingestion, or NLP/ML) without an explicit request.
- Development runs natively without containers; Docker is only for deployment on the hosting platform.
- Before coding each step, show a short plan and list the files to be created.
