import os

# The settings object is constructed at import time, so the test environment has
# to exist before anything under `cubicle` is imported.
os.environ.setdefault("CUBICLE_SECRET_KEY", "test-secret-key-for-unit-tests-only")
os.environ.setdefault("CUBICLE_MASTER_KEY", "test-master-key-for-unit-tests-only")
os.environ.setdefault("CUBICLE_TESTING", "1")
os.environ.setdefault(
    "CUBICLE_DATABASE_URL", "postgresql+asyncpg://cubicle:cubicle@localhost:5432/cubicle_test"
)
