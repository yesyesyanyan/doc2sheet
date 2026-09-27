"""Publish the web demo to a Hugging Face Space.

    pip install huggingface_hub
    python scripts/deploy_space.py --space <your-hf-username>/doc2sheet --inference-token hf_xxx

Authentication: set HF_TOKEN to a token with *write* access (or run `hf auth login`).
--inference-token is stored as the Space secret HF_TOKEN; it is what the Space uses
to call models, so give it only the "Make calls to Inference Providers" permission.
"""

from __future__ import annotations

import argparse
import os
import shutil
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILES = ["app.py", "requirements.txt", "LICENSE"]
DIRS = ["doc2sheet", "samples"]


def stage(target: Path) -> None:
    for name in FILES:
        shutil.copy2(ROOT / name, target / name)
    for name in DIRS:
        shutil.copytree(ROOT / name, target / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    # The Space needs its own README with the YAML config block at the top.
    shutil.copy2(ROOT / "space" / "README.md", target / "README.md")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--space", required=True, help="Space id, e.g. yourname/doc2sheet")
    parser.add_argument("--private", action="store_true", help="create the Space as private")
    parser.add_argument("--inference-token", help="token the Space uses to call models (saved as secret HF_TOKEN)")
    parser.add_argument("--github-url", help="link shown in the demo header (saved as a Space variable)")
    args = parser.parse_args()

    from huggingface_hub import HfApi

    api = HfApi(token=os.getenv("HF_TOKEN") or None)
    api.create_repo(args.space, repo_type="space", space_sdk="gradio", private=args.private, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        stage(Path(tmp))
        api.upload_folder(
            folder_path=tmp,
            repo_id=args.space,
            repo_type="space",
            commit_message="Deploy Doc2Sheet demo",
        )

    if args.inference_token:
        api.add_space_secret(args.space, "HF_TOKEN", args.inference_token)
    if args.github_url:
        api.add_space_variable(args.space, "DOC2SHEET_GITHUB_URL", args.github_url)

    print(f"Deployed: https://huggingface.co/spaces/{args.space}")


if __name__ == "__main__":
    main()
