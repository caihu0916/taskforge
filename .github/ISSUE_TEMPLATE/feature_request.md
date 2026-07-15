name: CI

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]

jobs:
  backend:
    name: Backend (Python)
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: open

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: pip

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -e ".[dev]"

      - name: Lint (ruff)
        run: ruff check src/ tests/

      - name: Format check (ruff)
        run: ruff format --check src/ tests/

      - name: Test (pytest)
        run: pytest tests/unit/ -v --noconftest -p no:cacheprovider --no-cov
        env:
          TF_SERVER__ENCRYPTION_KEY: "JHEc0WrVs7NDC7qg8EkQsfZN0UYEqm1twRQHsR5PW9E="

  frontend:
    name: Frontend (Node)
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: open/web

    steps:
      - uses: actions/checkout@v4

      - name: Set up Node
        uses: actions/setup-node@v4
        with:
          node-version: "18"
          cache: npm
          cache-dependency-path: open/web/package-lock.json

      - name: Install dependencies
        run: npm ci

      - name: Type check (tsc)
        run: npx tsc --noEmit

      - name: Build (vite)
        run: npx vite build

  security:
    name: Secrets Scan
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: TruffleHog OSS
        uses: trufflesecurity/trufflehog@main
        with:
          path: open/
          extra_args: --only-verified --exclude-paths=.gitignore
