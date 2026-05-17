from pathlib import Path

ROOT = Path(__file__).resolve().parent

DEFAULT_DATA_DIR = ROOT / "dataset/energy-plan-pubcom-sample"

LLM_MODEL = "gpt-5.4-mini"
EXAMPLE_EMBEDDING_MODEL = "text-embedding-3-small"

MICROCLUSTER_THRESHOLD = 0.7
ENTITY_OPINIONS_MAX_COMMENTS = 40
PAIR_RELATIONS_SCORE_THRESHOLD = 4
PAIR_RELATIONS_MAX_COMMENTS = 30
RANDOM_SEED = 42
