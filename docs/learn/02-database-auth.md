# Step 2: Database and authentication

## What was built

The backend now has SQLAlchemy models for users, refresh-token revocation,
documents and chunks, chats and messages, quizzes and questions, attempts and
answers, flashcards, classes and assignments, memberships, and topic statistics.
Alembic creates the schema using the configured `DATABASE_URL`; local
development uses SQLite and the same models support PostgreSQL.

The API supports student registration, login, refresh-token rotation, logout,
document listing/detail, and teacher-owned class and assignment reads. Passwords
are stored as Argon2id hashes. Access and refresh JWTs are signed using the
environment-configured secret. Refresh-token IDs are stored in the database so
rotation and logout can revoke them. Request limits use an in-memory fixed-window
counter locally and Redis in production.

## Why it was built

Persistent, relational records keep study data connected and queryable, while
explicit ownership fields provide a basis for data isolation. Authentication
protects private study information; role checks restrict teacher tools to
teachers, and every document/class read includes its owning user or teacher in
the query condition.

## How it works

Alembic reads `DATABASE_URL` and SQLAlchemy metadata. The local default is
`sqlite:///./data/study_assistant.db`; use a PostgreSQL SQLAlchemy URL to migrate
the compatible schema to PostgreSQL. Registration creates a student account;
teacher/admin accounts must be provisioned by trusted administrative means,
not selected by a public registration request.

Login verifies the submitted password against its Argon2id hash and issues a
short-lived access JWT plus a longer-lived refresh JWT. Protected requests send
the access token in `Authorization: Bearer ...`. Refresh validates and revokes
the previous refresh token before returning a new pair. Logout revokes the
presented refresh token; existing access tokens remain usable until their short
expiry. `require_role("teacher")` adds a 403 check for teacher-only endpoints.
Document queries constrain both the requested document and `owner_id`, and
class/assignment queries constrain class ownership to the authenticated teacher.

Run `.\tasks.ps1 migrate`, `.\tasks.ps1 test`, and `.\tasks.ps1 lint` from
PowerShell. Do not use the example JWT value as a production secret; set a
random secret of at least 32 characters.

## Key syllabus concept

This step is a supporting NLP-system concern: document chunks and question
citations are represented as relational records so later retrieval and
answer-generation features can preserve document ownership and source-page
references.

## Viva questions

1. **Why is a password hash stored instead of the password?**  
   A one-way Argon2id hash prevents the database from exposing users' original
   passwords if its contents are disclosed.

2. **What is the difference between access and refresh tokens?**  
   An access token authorizes short-lived API requests; a refresh token can
   obtain a new token pair and is stored server-side so it can be revoked.

3. **Why constrain a document query by `owner_id`?**  
   It ensures a valid user's identifier is insufficient to read another user's
   document, even if its document ID is guessed.

4. **How does `require_role` enforce authorization?**  
   It first resolves the authenticated user, then rejects requests whose
   persisted role is not in the endpoint's allowed-role list.

5. **Why use a cache interface for rate limiting?**  
   The API can use an inexpensive in-memory counter locally and switch to a
   shared Redis counter in production without changing middleware behavior.
