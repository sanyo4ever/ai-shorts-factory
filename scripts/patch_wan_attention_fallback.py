from __future__ import annotations

import argparse
from pathlib import Path


FALLBACK_BLOCK = """    if not FLASH_ATTN_2_AVAILABLE and not FLASH_ATTN_3_AVAILABLE:
        if q_lens is not None or k_lens is not None:
            warnings.warn(
                'Padding mask is disabled when using scaled_dot_product_attention. '
                'It can have a significant impact on performance.'
            )
        out_dtype = q.dtype
        q = q.transpose(1, 2).to(dtype)
        k = k.transpose(1, 2).to(dtype)
        v = v.transpose(1, 2).to(dtype)
        if q_scale is not None:
            q = q * q_scale
        out = torch.nn.functional.scaled_dot_product_attention(
            q, k, v, attn_mask=None, is_causal=causal, dropout_p=dropout_p
        )
        return out.transpose(1, 2).contiguous().type(out_dtype)
"""


def apply_patch(attention_path: Path) -> bool:
    text = attention_path.read_text(encoding="utf-8")
    marker = "    assert q.device.type == 'cuda' and q.size(-1) <= 256"
    if FALLBACK_BLOCK in text:
        return False
    if marker not in text:
        raise RuntimeError(f"Could not find Wan flash attention marker in {attention_path}")
    attention_path.write_text(
        text.replace(marker, f"{FALLBACK_BLOCK}{marker}", 1),
        encoding="utf-8",
    )
    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Patch Wan attention.py to use an SDPA fallback when flash-attn is unavailable."
    )
    parser.add_argument("repo_path", help="Path to the local Wan2.1 repo.")
    args = parser.parse_args()

    repo_path = Path(args.repo_path).resolve()
    attention_path = repo_path / "wan" / "modules" / "attention.py"
    if not attention_path.exists():
        raise RuntimeError(f"Wan attention.py not found: {attention_path}")

    changed = apply_patch(attention_path)
    print("patched" if changed else "already_patched")
    print(attention_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
