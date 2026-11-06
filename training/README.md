# Training the replay review's vision model

Replay review asks a vision model (Qwen2.5-VL 7B by default) to talk a replay
over. This folder fine-tunes that model on lessons from coaching videos, so
it judges moments the way a real coach does. It is optional: replay review
works without it.

## 1. Collect lessons (on your PC)

Put coaching videos on your PC: ones where the coach talks a game through
while it plays, and that you are allowed to use. Then:

```
py -m coach learn-video "C:\Videos\coaching"
```

It takes a file or a folder. For each moment it saves three frames and a
lesson card in the app folder's `lessons\`. Open the JSON files and delete
the cards that are wrong: the model learns whatever is left.

About 10 to 20 hours of video (500 to 1,000 lessons) is enough to change how
it judges moments. Fewer mostly changes how it sounds.

## 2. Export the training set

```
py -m coach export-lessons --out "C:\coach-training"
```

This writes `train.jsonl`, `test.jsonl` (every tenth lesson of each video,
kept out of training to check the result) and `images\`.

## 3. Train (NVIDIA GPU with 16 GB or more, or a cloud GPU)

On Linux or WSL with CUDA, or a rented GPU (an RTX 4090 or A100 on RunPod or
similar costs a few dollars for a run of 1 to 3 hours):

```
pip install unsloth
python training/train_vision_lora.py --data /path/to/coach-training --out dota-coach-lora
```

It trains a LoRA adapter on the language side (the model already reads the
game; it learns the judgement), and saves a merged model in
`dota-coach-lora/merged`.

## 4. Load it into Ollama

Convert the merged model with llama.cpp (the model and its vision part are
two files), then create an Ollama model from them:

```
python llama.cpp/convert_hf_to_gguf.py dota-coach-lora/merged --outfile dota-coach.gguf --outtype q8_0
python llama.cpp/convert_hf_to_gguf.py dota-coach-lora/merged --mmproj --outfile dota-coach-mmproj.gguf
```

`Modelfile`:

```
FROM ./dota-coach.gguf
FROM ./dota-coach-mmproj.gguf
```

```
ollama create dota-coach-vision -f Modelfile
```

Then pick it in Replay review, or run
`py -m coach replay-review --vision-model dota-coach-vision`.

This step depends on llama.cpp's and Ollama's support for Qwen2.5-VL, which
changes between versions: check it on the first run.

## 5. Check it got better

Run replay review on a few of your replays with the old and the new model,
and read the test lessons' answers. If the new one is worse, collect more
(or cleaner) lessons before training again.
