from __future__ import annotations

import argparse
from pathlib import Path


IMPORT_MARKER = "import logging\nimport math\n\nimport torch\n"
IMPORT_PATCH = (
    "import logging\n"
    "import math\n"
    "import time\n\n"
    "import torch\n"
)

HELPER_IMPORT_MARKER = "from .tokenizers import HuggingfaceTokenizer\n"
HELPER_IMPORT_PATCH = (
    "from .tokenizers import HuggingfaceTokenizer\n"
    "from ..utils.filmstudio_profile import append_wan_profile_event\n"
)

TOKENIZER_CALL_MARKER = """    def __call__(self, texts, device):
        ids, mask = self.tokenizer(
            texts, return_mask=True, add_special_tokens=True)
        ids = ids.to(device)
        mask = mask.to(device)
        seq_lens = mask.gt(0).sum(dim=1).long()
        context = self.model(ids, mask)
        return [u[:v] for u, v in zip(context, seq_lens)]
"""

TOKENIZER_CALL_PATCH = """    def __call__(self, texts, device, profile_label=None):
        call_started = time.perf_counter()
        tokenize_started = call_started
        ids, mask = self.tokenizer(
            texts,
            return_mask=True,
            add_special_tokens=True,
            padding=False,
            truncation=True,
            max_length=self.text_len,
        )
        tokenize_sec = time.perf_counter() - tokenize_started
        seq_lens = mask.gt(0).sum(dim=1).long()
        seq_lens_list = [int(value) for value in seq_lens.tolist()]
        transfer_started = time.perf_counter()
        ids = ids.to(device)
        mask = mask.to(device)
        transfer_sec = time.perf_counter() - transfer_started
        forward_started = time.perf_counter()
        with torch.inference_mode():
            context = self.model(ids, mask)
        forward_sec = time.perf_counter() - forward_started
        total_sec = time.perf_counter() - call_started
        model_device = next(self.model.parameters()).device
        profile_device = (
            model_device
            if model_device.type == "cuda"
            else (device if device.type == "cuda" else None)
        )
        append_wan_profile_event(
            "text_encoder_call",
            pipeline_name="WanT5Encoder",
            device=profile_device,
            profile_label=profile_label,
            requested_device=str(device),
            model_device=str(model_device),
            batch_size=len(texts),
            input_char_lengths=[len(text) for text in texts],
            input_char_total=sum(len(text) for text in texts),
            text_len_limit=self.text_len,
            ids_shape=list(ids.shape),
            mask_shape=list(mask.shape),
            seq_lens=seq_lens_list,
            min_seq_len=min(seq_lens_list) if seq_lens_list else None,
            max_seq_len=max(seq_lens_list) if seq_lens_list else None,
            mean_seq_len=round(sum(seq_lens_list) / len(seq_lens_list), 3) if seq_lens_list else None,
            tokenize_sec=round(tokenize_sec, 6),
            transfer_sec=round(transfer_sec, 6),
            forward_sec=round(forward_sec, 6),
            total_sec=round(total_sec, 6),
        )
        return [u[:v] for u, v in zip(context, seq_lens)]
"""


def apply_replace(path: Path, marker: str, replacement: str) -> bool:
    text = path.read_text(encoding="utf-8")
    if replacement in text:
        return False
    if marker not in text:
        raise RuntimeError(f"Could not find T5 patch marker in {path}: {marker[:80]!r}")
    path.write_text(text.replace(marker, replacement, 1), encoding="utf-8")
    return True


def apply_patch(t5_path: Path) -> bool:
    changed = False
    changed |= apply_replace(t5_path, IMPORT_MARKER, IMPORT_PATCH)
    changed |= apply_replace(t5_path, HELPER_IMPORT_MARKER, HELPER_IMPORT_PATCH)
    changed |= apply_replace(t5_path, TOKENIZER_CALL_MARKER, TOKENIZER_CALL_PATCH)
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Patch the local Wan2.1 T5 path for dynamic padding and encode diagnostics."
    )
    parser.add_argument("repo_path", help="Path to the local Wan2.1 repo.")
    args = parser.parse_args()

    repo_path = Path(args.repo_path).resolve()
    t5_path = repo_path / "wan" / "modules" / "t5.py"
    if not t5_path.exists():
        raise RuntimeError(f"Wan t5.py not found: {t5_path}")

    changed = apply_patch(t5_path)
    print("patched" if changed else "already_patched")
    print(t5_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
