"""Fine-tunes the replay review's vision model on lessons from coaching videos.

Runs on a machine with an NVIDIA GPU of about 16 GB or more (your PC, or a
rented cloud GPU), not inside the coach. See training/README.md.

    pip install unsloth
    python training/train_vision_lora.py --data training-data --out dota-coach-lora

--data is the folder `py -m coach export-lessons` wrote (train.jsonl,
test.jsonl, images/). The result is a LoRA adapter in --out, plus a merged
16-bit model in --out/merged for converting to Ollama.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def rows(path: Path, root: Path) -> list[dict]:
    """The export's chat rows with images opened (Unsloth's vision format)."""
    from PIL import Image

    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        for message in row["messages"]:
            for part in message["content"]:
                if part.get("type") == "image":
                    part["image"] = Image.open(root / part["image"]).convert("RGB")
        out.append({"messages": row["messages"]})
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=Path("dota-coach-lora"))
    parser.add_argument("--base", default="unsloth/Qwen2.5-VL-7B-Instruct-bnb-4bit")
    parser.add_argument("--epochs", type=float, default=2)
    parser.add_argument("--rank", type=int, default=16)
    args = parser.parse_args()

    from trl import SFTConfig, SFTTrainer
    from unsloth import FastVisionModel
    from unsloth.trainer import UnslothVisionDataCollator

    model, tokenizer = FastVisionModel.from_pretrained(args.base, load_in_4bit=True)
    model = FastVisionModel.get_peft_model(
        model,
        finetune_vision_layers=False,  # the game's look is fine; teach the judgement
        finetune_language_layers=True,
        r=args.rank,
        lora_alpha=args.rank,
        lora_dropout=0,
    )
    train = rows(args.data / "train.jsonl", args.data)
    test = rows(args.data / "test.jsonl", args.data) if (args.data / "test.jsonl").is_file() else None
    print(f"{len(train)} training examples, {len(test or [])} test examples")

    FastVisionModel.for_training(model)
    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        data_collator=UnslothVisionDataCollator(model, tokenizer),
        train_dataset=train,
        eval_dataset=test,
        args=SFTConfig(
            output_dir=str(args.out / "checkpoints"),
            per_device_train_batch_size=1,
            gradient_accumulation_steps=8,
            num_train_epochs=args.epochs,
            learning_rate=2e-4,
            warmup_ratio=0.05,
            logging_steps=10,
            eval_strategy="epoch" if test else "no",
            save_strategy="epoch",
            remove_unused_columns=False,
            dataset_text_field="",
            dataset_kwargs={"skip_prepare_dataset": True},
            max_seq_length=4096,
            report_to="none",
        ),
    )
    trainer.train()
    model.save_pretrained(str(args.out))
    tokenizer.save_pretrained(str(args.out))
    # A full 16-bit model, for llama.cpp's converter (training/README.md).
    model.save_pretrained_merged(str(args.out / "merged"), tokenizer, save_method="merged_16bit")
    print(f"Saved the adapter in {args.out} and the merged model in {args.out / 'merged'}")


if __name__ == "__main__":
    main()
